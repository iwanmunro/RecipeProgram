import json
import os
import base64
import difflib
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
import streamlit as st

try:
    import anthropic as _anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

# ── Constants ────────────────────────────────────────────────────────────────
RECIPES_FILE = Path(__file__).parent / "recipes.json"

CARD_COLOURS = [
    ("#6B5CE7", "#FFFFFF"), ("#00B894", "#FFFFFF"), ("#E17055", "#FFFFFF"),
    ("#0984E3", "#FFFFFF"), ("#FDCB6E", "#4A3000"), ("#FD79A8", "#FFFFFF"),
    ("#00CEC9", "#FFFFFF"), ("#A29BFE", "#FFFFFF"), ("#55EFC4", "#1A4A3A"),
    ("#FF7675", "#FFFFFF"),
]

CUISINES = [
    "American", "Asian", "British", "Chinese", "French", "Greek",
    "Indian", "Italian", "Japanese", "Mediterranean", "Mexican",
    "Middle Eastern", "Thai", "Other",
]

PREDEFINED_TAGS = [
    "Breakfast", "Brunch", "Lunch", "Dinner", "Dessert", "Snack",
    "Starter", "Side dish", "Soup", "Salad", "Bread", "Cake",
    "Vegetarian", "Vegan", "Gluten-free", "Dairy-free",
    "Low calorie", "Healthy", "Quick", "Make ahead",
]

# Cuisine → (accent-colour, card-tint) for Browse All cards
CUISINE_COLOURS: dict[str, tuple[str, str]] = {
    "American":       ("#E17055", "#FFF6F4"),
    "Asian":          ("#E84393", "#FFF1F7"),
    "British":        ("#2980B9", "#F0F7FF"),
    "Chinese":        ("#C0392B", "#FFF3F2"),
    "French":         ("#8B7FF0", "#F5F3FF"),
    "Greek":          ("#27AE60", "#F1FBF5"),
    "Indian":         ("#E67E22", "#FFFBF5"),
    "Italian":        ("#C0392B", "#FFF5F4"),
    "Japanese":       ("#E84393", "#FFF2F7"),
    "Mediterranean":  ("#0984E3", "#F0F8FF"),
    "Mexican":        ("#27AE60", "#F0FBF4"),
    "Middle Eastern": ("#F39C12", "#FFFCF0"),
    "Thai":           ("#16A085", "#F0FBFA"),
    "Other":          ("#7F8C8D", "#F8F8F8"),
}

# Tag → CSS class for colour-coded pills
_TAG_CLASS: dict[str, str] = {
    "Vegetarian": "tag-green", "Vegan": "tag-green",
    "Gluten-free": "tag-green", "Dairy-free": "tag-green",
    "Low calorie": "tag-green", "Healthy": "tag-green",
    "Breakfast": "tag-amber", "Brunch": "tag-amber",
    "Lunch": "tag-amber", "Dinner": "tag-amber", "Snack": "tag-amber",
    "Dessert": "tag-pink", "Cake": "tag-pink", "Starter": "tag-pink",
    "Side dish": "tag-pink", "Bread": "tag-pink",
    "Soup": "tag-teal", "Salad": "tag-teal",
    "Quick": "tag-teal", "Make ahead": "tag-teal",
}


# ── Data helpers ─────────────────────────────────────────────────────────────

def load_recipes() -> list[dict]:
    if RECIPES_FILE.exists():
        with open(RECIPES_FILE, "r") as f:
            return json.load(f)
    return []


def save_recipes(recipes: list[dict]) -> None:
    with open(RECIPES_FILE, "w") as f:
        json.dump(recipes, f, indent=2)


def normalise(text: str) -> str:
    return text.strip().lower()


def ingredients_match(have: list[str], need: list[str]) -> tuple[list[str], list[str]]:
    have_norm = [normalise(h) for h in have]
    matched, missing = [], []
    for ingredient in need:
        ing_norm = normalise(ingredient)
        if any(ing_norm in h or h in ing_norm for h in have_norm):
            matched.append(ingredient)
        else:
            missing.append(ingredient)
    return matched, missing


def match_score(have: list[str], need: list[str]) -> float:
    """Fraction of recipe ingredients covered by fridge contents. Returns [0, 1]."""
    if not need:
        return 0.0
    matched, _ = ingredients_match(have, need)
    return len(matched) / len(need)


@st.cache_data
def _score_all(recipes: list[dict], fridge: list[str]) -> list[tuple]:
    """Score every recipe against the fridge. Cached so it only runs when inputs change."""
    scored = []
    for recipe in recipes:
        matched, missing = ingredients_match(fridge, recipe["ingredients"])
        n = len(recipe["ingredients"])
        score = len(matched) / n if n else 0.0
        scored.append((recipe, matched, missing, score, round(score * 100)))
    return scored


@st.cache_data
def get_ingredient_vocab(recipes: list[dict]) -> list[str]:
    """Deduplicated list of all ingredient names across stored recipes."""
    seen: set[str] = set()
    vocab: list[str] = []
    for r in recipes:
        for ing in r.get("ingredients", []):
            n = normalise(ing)
            if n not in seen:
                seen.add(n)
                vocab.append(n)
    return vocab


def suggest_ingredient(text: str, recipes: list[dict]) -> str | None:
    """Return a corrected spelling if a close match exists in the known ingredient vocab."""
    norm = normalise(text)
    vocab = get_ingredient_vocab(recipes)
    matches = difflib.get_close_matches(norm, vocab, n=1, cutoff=0.75)
    if matches and matches[0] != norm:
        return matches[0]
    return None


def _safe_key(prefix: str, name: str) -> str:
    """Consistent safe CSS key from a prefix + recipe name."""
    return (
        f"{prefix}_{name}"
        .replace(" ", "-").replace("'", "").replace(",", "")
        .replace("(", "").replace(")", "")
    )


def _coloured_tags(tags: list[str]) -> str:
    """HTML spans for each tag, colour-classed by category."""
    return "".join(
        f'<span class="recipe-tag {_TAG_CLASS.get(t, "")}">{t}</span>'
        for t in tags
    )


def send_shopping_list_email(to_addr: str, items: list[dict], smtp_cfg: dict) -> None:
    """Send the shopping list as a plain-text email via SMTP."""
    to_buy  = [i for i in items if not i["checked"]]
    in_cart = [i for i in items if i["checked"]]
    lines = ["Shopping List", "=" * 30, ""]
    if to_buy:
        lines.append("TO BUY:")
        for i in to_buy:
            src = f"  ({i['source']})" if i.get("source") else ""
            lines.append(f"  \u2022 {i['item']}{src}")
        lines.append("")
    if in_cart:
        lines.append("ALREADY TICKED:")
        for i in in_cart:
            src = f"  ({i['source']})" if i.get("source") else ""
            lines.append(f"  \u2713 {i['item']}{src}")
    msg = MIMEMultipart()
    msg["From"]    = smtp_cfg["user"]
    msg["To"]      = to_addr
    msg["Subject"] = "\U0001f6d2 My Shopping List"
    msg.attach(MIMEText("\n".join(lines), "plain"))
    with smtplib.SMTP(smtp_cfg["host"], smtp_cfg["port"]) as s:
        s.starttls()
        s.login(smtp_cfg["user"], smtp_cfg["password"])
        s.send_message(msg)


def extract_recipe_from_image(image_bytes: bytes, media_type: str, api_key: str) -> dict:
    """Send an image to Claude and return a parsed recipe dict."""
    client = _anthropic.Anthropic(api_key=api_key)
    b64 = base64.standard_b64encode(image_bytes).decode()
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                },
                {
                    "type": "text",
                    "text": (
                        "Extract the recipe from this image. "
                        "Return ONLY valid JSON with exactly these keys:\n"
                        '{"name": "...", "cuisine": "...", "servings": 2, '
                        '"tags": ["..."], '
                        '"ingredients": ["...", "..."], "method": "..."}\n'
                        "For 'tags', choose only from this list (include all that apply): "
                        "Breakfast, Brunch, Lunch, Dinner, Dessert, Snack, Starter, Side dish, Soup, Salad, "
                        "Bread, Cake, Vegetarian, Vegan, Gluten-free, Dairy-free, Low calorie, Healthy, Quick, Make ahead.\n"
                        "List each ingredient as its own array item, lowercase, without quantities. "
                        "Write the method as a single string with numbered steps separated by \\n. "
                        "If a field cannot be determined use an empty string (or 2 for servings, [] for tags)."
                    ),
                },
            ],
        }],
    )
    text = response.content[0].text
    found = re.search(r"\{.*\}", text, re.DOTALL)
    if found:
        return json.loads(found.group())
    return {}


# ── Modal (must be module-level for @st.dialog to work) ──────────────────────

@st.dialog("\U0001f4e7 Email shopping list", width="small")
def email_list() -> None:
    try:
        smtp_cfg = {
            "host":     st.secrets.get("SMTP_HOST", ""),
            "port":     int(st.secrets.get("SMTP_PORT", 587)),
            "user":     st.secrets.get("SMTP_USER", ""),
            "password": st.secrets.get("SMTP_PASSWORD", ""),
        }
        default_email = st.secrets.get("DEFAULT_EMAIL", "")
    except Exception:
        smtp_cfg = {"host": "", "port": 587, "user": "", "password": ""}
        default_email = ""
    if not smtp_cfg["host"] or not smtp_cfg["user"]:
        st.warning(
            "Add SMTP settings to `.streamlit/secrets.toml` to enable email:\n\n"
            "```toml\n"
            "SMTP_HOST     = \"smtp.gmail.com\"\n"
            "SMTP_PORT     = 587\n"
            "SMTP_USER     = \"you@gmail.com\"\n"
            "SMTP_PASSWORD = \"your-app-password\"\n"
            "DEFAULT_EMAIL = \"you@gmail.com\"\n"
            "```"
        )
        return
    to_addr = st.text_input(
        "Send to",
        value=default_email,
        placeholder="email@example.com",
        key="email_to_addr",
    )
    to_buy_count = sum(1 for i in st.session_state.shopping_list if not i["checked"])
    st.markdown(
        f"<p style='color:#888;font-size:0.82rem;margin:0.1rem 0 0.7rem;'>"
        f"{to_buy_count} item(s) to buy on the list.</p>",
        unsafe_allow_html=True,
    )
    if st.button(
        "Send \U0001f4e8",
        key="email_send_btn",
        use_container_width=True,
        disabled=not to_addr.strip(),
    ):
        with st.spinner("Sending\u2026"):
            try:
                send_shopping_list_email(
                    to_addr.strip(), st.session_state.shopping_list, smtp_cfg
                )
                st.success(f"\u2705 Sent to {to_addr}!")
            except Exception as exc:
                st.error(f"Failed: {exc}")


@st.dialog("Recipe", width="large")
def show_recipe(recipe: dict, matched: list, missing: list) -> None:
    pct = round(match_score(st.session_state.get("fridge", []), recipe["ingredients"]) * 100)
    cuisine = recipe.get("cuisine", "")
    cuisine_html = f'<span class="cuisine-tag">{cuisine}</span>&nbsp;' if cuisine else ""
    tags = recipe.get("tags", [])
    tags_html = _coloured_tags(tags)
    st.markdown(
        f'<div class="modal-title">{recipe["name"]}</div>'
        f'<div class="modal-meta">'
        f'{cuisine_html}{tags_html}'
        f'</div>'
        f'<div class="modal-meta" style="margin-top:0.35rem;">'
        f'{recipe.get("servings","?")} servings &nbsp;·&nbsp; '
        f'{len(recipe["ingredients"])} ingredients &nbsp;·&nbsp; '
        f'<span class="modal-score">{pct}% match</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")
    ing_html = " ".join(
        [f'<span class="badge-have">{i}</span>' for i in matched]
        + [f'<span class="badge-missing">{i}</span>' for i in missing]
    )
    st.markdown(ing_html, unsafe_allow_html=True)
    if missing:
        items = "".join(f'<div class="shopping-item">&bull; {i}</div>' for i in missing)
        st.markdown(
            f'<div class="shopping-list" style="margin-top:0.75rem;">'
            f'<div class="shopping-list-title">🛔 Still need</div>{items}</div>',
            unsafe_allow_html=True,
        )
        # Scoped style for the add-to-list button
        safe_modal_key = (
            f"modal_shop_{recipe['name']}"
            .replace(" ", "-").replace("'", "").replace(",", "").replace("(", "").replace(")", "")
        )
        st.markdown(
            f"""
            <style>
            .st-key-{safe_modal_key} button {{
                background: linear-gradient(135deg, #00B894, #00CEC9) !important;
                color: #FFFFFF !important;
                border: none !important;
                border-radius: 12px !important;
                padding: 0.65rem 1.25rem !important;
                font-weight: 700 !important;
                font-size: 0.9rem !important;
                letter-spacing: 0.02em !important;
                box-shadow: 0 4px 14px rgba(0,184,148,0.35) !important;
                transition: box-shadow 0.15s ease, transform 0.1s ease !important;
                margin-top: 0.5rem !important;
            }}
            .st-key-{safe_modal_key} button:hover {{
                box-shadow: 0 6px 20px rgba(0,184,148,0.5) !important;
                transform: translateY(-2px) !important;
            }}
            .st-key-{safe_modal_key} button:active {{
                transform: translateY(0) !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        if st.button(
            f"🛒\u2002Add {len(missing)} missing item{'s' if len(missing) != 1 else ''} to shopping list",
            key=safe_modal_key,
            use_container_width=True,
        ):
            existing = {i["item"].lower() for i in st.session_state.shopping_list}
            for m in missing:
                if m.lower() not in existing:
                    st.session_state.shopping_list.append({"item": m, "checked": False, "source": recipe["name"]})
            st.rerun()
    st.markdown(
        f'<div class="method-block">{recipe.get("method","No method provided.")}</div>',
        unsafe_allow_html=True,
    )


@st.dialog("🛒 Add ingredients to list", width="large")
def pick_ingredients(recipe: dict) -> None:
    """Modal: all ingredients pre-selected as checkboxes; user deselects what they have."""
    st.markdown(
        f'<div class="modal-title" style="font-size:1.25rem;">{recipe["name"]}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#888;font-size:0.83rem;margin:0.15rem 0 0.9rem;'>"
        "Tick the ingredients you <b>don’t</b> already have, then hit Add."
        "</p>",
        unsafe_allow_html=True,
    )

    ingredients = recipe["ingredients"]
    # Build checkbox state: default True (selected) for every ingredient
    selections: dict[str, bool] = {}
    cols = st.columns(2)
    for idx, ing in enumerate(ingredients):
        ck_key = f"pick_ing_{recipe['name']}_{idx}"
        # Initialise to True on first render
        if ck_key not in st.session_state:
            st.session_state[ck_key] = True
        with cols[idx % 2]:
            selections[ing] = st.checkbox(ing, key=ck_key)

    chosen = [ing for ing, sel in selections.items() if sel]
    safe_confirm_key = (
        f"pick_confirm_{recipe['name']}"
        .replace(" ", "-").replace("'", "").replace(",", "").replace("(", "").replace(")", "")
    )
    st.markdown(
        f"""
        <style>
        .st-key-{safe_confirm_key} button {{
            background: linear-gradient(135deg, #00B894, #00CEC9) !important;
            color: #FFFFFF !important;
            border: none !important;
            border-radius: 12px !important;
            font-weight: 700 !important;
            font-size: 0.9rem !important;
            box-shadow: 0 4px 14px rgba(0,184,148,0.35) !important;
            transition: box-shadow 0.15s ease, transform 0.1s ease !important;
        }}
        .st-key-{safe_confirm_key} button:hover {{
            box-shadow: 0 6px 20px rgba(0,184,148,0.5) !important;
            transform: translateY(-2px) !important;
        }}
        .st-key-{safe_confirm_key} button:disabled {{
            opacity: 0.45 !important;
            transform: none !important;
            box-shadow: none !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")
    col_btn, col_info = st.columns([3, 2])
    with col_info:
        st.markdown(
            f"<p style='color:#888;font-size:0.82rem;margin-top:0.6rem;'>"
            f"{len(chosen)} of {len(ingredients)} selected</p>",
            unsafe_allow_html=True,
        )
    with col_btn:
        if st.button(
            f"🛒\u2002Add {len(chosen)} item{'s' if len(chosen) != 1 else ''} to shopping list",
            key=safe_confirm_key,
            disabled=len(chosen) == 0,
            use_container_width=True,
        ):
            existing = {i["item"].lower() for i in st.session_state.shopping_list}
            for ing in chosen:
                if ing.lower() not in existing:
                    st.session_state.shopping_list.append(
                        {"item": ing, "checked": False, "source": recipe["name"]}
                    )
            # Clear checkbox state so next open starts fresh
            for idx in range(len(ingredients)):
                ck_key = f"pick_ing_{recipe['name']}_{idx}"
                if ck_key in st.session_state:
                    del st.session_state[ck_key]
            st.rerun()


def recipe_card(recipe: dict, matched: list, missing: list, pct: int, key_prefix: str, inject_css: bool = True) -> None:
    bar_colour = "#00B894" if not missing else "#E17055"
    n_ing = len(recipe["ingredients"])
    servings = recipe.get("servings", "?")

    safe_key = (
        f"{key_prefix}_{recipe['name']}"
        .replace(" ", "-").replace("'", "").replace(",", "").replace("(", "").replace(")", "")
    )
    if inject_css:
        st.markdown(
            f"""
            <style>
            .st-key-{safe_key} button {{
                background: linear-gradient(to right, {bar_colour}28 {pct}%, #FFFFFF {pct}%) !important;
                border: 1.5px solid #EAE5F0 !important;
                border-radius: 14px !important;
                padding: 0.85rem 1.25rem !important;
                text-align: left !important;
                height: auto !important;
                white-space: pre-wrap !important;
                color: #1A1A1A !important;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                font-size: 0.95rem !important;
                font-weight: 700 !important;
                line-height: 1.55 !important;
                transition: box-shadow 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
            }}
            .st-key-{safe_key} button:hover {{
                box-shadow: 0 5px 18px rgba(107,92,231,0.14) !important;
                border-color: #C8B8F0 !important;
                transform: translateY(-2px);
            }}
            .st-key-{safe_key} button:active {{
                transform: translateY(0);
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    cuisine = recipe.get("cuisine", "")
    cuisine_str = f"{cuisine}  ·  " if cuisine else ""
    match_str = f"{pct}% match  ·  " if pct > 0 else ""
    label = f"{recipe['name']}\n{cuisine_str}{match_str}{servings} servings  ·  {n_ing} ingredients"
    if st.button(label, key=safe_key, use_container_width=True):
        show_recipe(recipe, matched, missing)


# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Recipe Finder",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

def load_css(path: Path) -> None:
    st.markdown(f"<style>{path.read_text()}</style>", unsafe_allow_html=True)

load_css(Path(__file__).parent / "style.css")


# ── State ────────────────────────────────────────────────────────────────────

if "recipes" not in st.session_state:
    st.session_state.recipes = load_recipes()

if "fridge" not in st.session_state:
    st.session_state.fridge = []

if "pending_ingredient" not in st.session_state:
    # Holds (original_text, suggestion) while awaiting user confirmation
    st.session_state.pending_ingredient = None

if "shopping_list" not in st.session_state:
    # Each entry: {"item": str, "checked": bool}
    st.session_state.shopping_list = []


# ── App header ───────────────────────────────────────────────────────────────

st.markdown("""
<div class="app-header">
    <h1>🍽️ Recipe Finder</h1>
    <p>Tell us what's in your fridge and we'll find what you can cook.</p>
</div>
""", unsafe_allow_html=True)

tab_search, tab_browse, tab_add, tab_shop = st.tabs(["Find Recipes", "Browse All", "Add Recipe", "🛒 Shopping List"])


# ── Tab 1: Search ─────────────────────────────────────────────────────────────

with tab_search:

    # ── Fridge panel ─────────────────────────────────────────────────────────
    st.markdown('<div class="fridge-panel">', unsafe_allow_html=True)
    st.markdown('<h3>🧊 What\'s in your fridge?</h3>', unsafe_allow_html=True)

    with st.form("fridge_form", clear_on_submit=True):
        col_input, col_btn = st.columns([8, 1])
        with col_input:
            new_ing = st.text_input(
                "ingredient_input",
                label_visibility="collapsed",
                placeholder="Type an ingredient and press Enter or Add…",
            )
        with col_btn:
            add_clicked = st.form_submit_button("Add", use_container_width=True)

    if add_clicked:
        item = normalise(new_ing)
        if item and item not in [normalise(i) for i in st.session_state.fridge]:
            suggestion = suggest_ingredient(item, st.session_state.recipes)
            if suggestion:
                st.session_state.pending_ingredient = (item, suggestion)
            else:
                st.session_state.fridge.append(item)
            st.rerun()

    # ── Fuzzy suggestion banner ───────────────────────────────────────────────
    if st.session_state.pending_ingredient:
        original, suggestion = st.session_state.pending_ingredient
        st.markdown(
            f'<div class="suggestion-banner">'  
            f'🤔 Did you mean <strong>{suggestion}</strong> instead of <em>{original}</em>?'
            f'</div>',
            unsafe_allow_html=True,
        )
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button(f'✓ Use "{suggestion}"', key="sug_yes", use_container_width=True):
                st.session_state.fridge.append(suggestion)
                st.session_state.pending_ingredient = None
                st.rerun()
        with col_no:
            if st.button(f'Keep "{original}"', key="sug_no", use_container_width=True):
                st.session_state.fridge.append(original)
                st.session_state.pending_ingredient = None
                st.rerun()

    # Ingredient cards — each is a real button so clicking removes it
    if st.session_state.fridge:
        st.markdown('<p class="remove-hint">Click an ingredient to remove it</p>',
                    unsafe_allow_html=True)
        cols = st.columns(len(st.session_state.fridge))
        to_remove = None
        for idx, ing in enumerate(st.session_state.fridge):
            bg, fg = CARD_COLOURS[idx % len(CARD_COLOURS)]
            with cols[idx]:
                st.markdown(
                    f'<style>'
                    f'div[data-testid="stButton"] button[kind="secondary"]#ing_btn_{idx} {{'
                    f'  background:{bg}; color:{fg}; border:none;'
                    f'  border-radius:12px; font-weight:600; font-size:0.85rem;'
                    f'  box-shadow:0 2px 8px rgba(0,0,0,0.15);'
                    f'}}'
                    f'</style>',
                    unsafe_allow_html=True,
                )
                if st.button(f"✓ {ing}", key=f"ing_btn_{idx}", use_container_width=True):
                    to_remove = ing
        if to_remove:
            st.session_state.fridge.remove(to_remove)
            st.rerun()

        if st.button("Clear all", key="clear_btn"):
            st.session_state.fridge = []
            st.rerun()
    else:
        st.markdown('<p class="chip-empty">No ingredients added yet.</p>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    # ── Results ───────────────────────────────────────────────────────────────
    if not st.session_state.fridge:
        st.markdown('<div class="empty-state">Add ingredients above to see matching recipes.</div>',
                    unsafe_allow_html=True)
    elif not st.session_state.recipes:
        st.markdown('<div class="empty-state">No recipes yet — add some in the <b>Add Recipe</b> tab.</div>',
                    unsafe_allow_html=True)
    else:
        # Score every recipe — cached, only recomputes when fridge or recipes change
        scored = _score_all(st.session_state.recipes, st.session_state.fridge)

        can_make = [(r, m, ms, s, p) for r, m, ms, s, p in scored if len(ms) == 0]
        nearly   = [(r, m, ms, s, p) for r, m, ms, s, p in scored if len(m) != 0 and len(ms) != 0]

        can_make.sort(key=lambda x: x[3], reverse=True)
        nearly.sort(key=lambda x: x[3], reverse=True)

        # ── Side-by-side columns ──────────────────────────────────────────────
        col_left, col_right = st.columns(2, gap="large")

        with col_left:
            st.markdown(
                f'<div class="section-heading">✅ Ready to cook'
                f' <span class="count">{len(can_make)}</span></div>',
                unsafe_allow_html=True,
            )
            if not can_make:
                st.markdown(
                    '<div class="empty-state" style="padding:1rem 0;">No exact matches yet — '
                    'try adding more ingredients.</div>',
                    unsafe_allow_html=True,
                )
            else:
                for recipe, matched, missing, score, pct in can_make:
                    recipe_card(recipe, matched, missing, pct, "can")

        with col_right:
            st.markdown(
                f'<div class="section-heading nearly">🛒 Nearly there'
                f' <span class="count">{len(nearly)}</span></div>',
                unsafe_allow_html=True,
            )
            if not nearly:
                st.markdown(
                    '<div class="empty-state" style="padding:1rem 0;">No near-matches found.</div>',
                    unsafe_allow_html=True,
                )
            else:
                for recipe, matched, missing, score, pct in nearly:
                    recipe_card(recipe, matched, missing, pct, "near")
                    if st.button(
                        "🛒 Add missing to list",
                        key=f"shop_near_{recipe['name']}",
                        use_container_width=True,
                    ):
                        existing = {i["item"].lower() for i in st.session_state.shopping_list}
                        for m in missing:
                            if m.lower() not in existing:
                                st.session_state.shopping_list.append({"item": m, "checked": False, "source": recipe["name"]})
                        st.rerun()


# ── Tab 2: Browse ─────────────────────────────────────────────────────────────

with tab_browse:
    recipes = st.session_state.recipes
    if not recipes:
        st.markdown(
            '<div class="empty-state">No recipes yet — add some in the <b>Add Recipe</b> tab.</div>',
            unsafe_allow_html=True,
        )
    else:
        # ── Filters ──────────────────────────────────────────────────────────
        col_search, col_cuisine = st.columns([3, 2])
        with col_search:
            search_term = st.text_input(
                "search_browse",
                label_visibility="collapsed",
                placeholder="🔍  Filter by name or ingredient…",
                key="browse_search",
            )
        with col_cuisine:
            available_cuisines = sorted(
                {r.get("cuisine", "Other") for r in recipes if r.get("cuisine")}
            )
            selected_cuisines = st.multiselect(
                "Cuisines",
                options=available_cuisines,
                placeholder="🌍  Filter by cuisine…",
                label_visibility="collapsed",
                key="browse_cuisines",
            )
        available_tags = sorted(
            {t for r in recipes for t in r.get("tags", [])}
        )
        if available_tags:
            selected_tags = st.multiselect(
                "Tags",
                options=available_tags,
                placeholder="🏷️  Filter by tag (Dessert, Vegan, Breakfast…)",
                label_visibility="collapsed",
                key="browse_tags",
            )
        else:
            selected_tags = []
        # ── Apply filters ─────────────────────────────────────────────────────
        filtered = recipes
        if search_term:
            term = normalise(search_term)
            filtered = [
                r for r in filtered
                if term in normalise(r["name"])
                or any(term in normalise(i) for i in r["ingredients"])
            ]
        if selected_cuisines:
            filtered = [r for r in filtered if r.get("cuisine") in selected_cuisines]
        if selected_tags:
            filtered = [r for r in filtered if any(t in r.get("tags", []) for t in selected_tags)]

        st.markdown(
            f"<p style='color:#999;font-size:0.82rem;margin:0.25rem 0 1rem;'>"
            f"Showing {len(filtered)} of {len(recipes)} recipes</p>",
            unsafe_allow_html=True,
        )

        if not filtered:
            st.markdown(
                '<div class="empty-state">No recipes match your filters.</div>',
                unsafe_allow_html=True,
            )
        else:
            # Inject ONE combined CSS block for all visible cards (cuisine tint + accent)
            browse_css_parts: list[str] = []
            for r in filtered:
                acc, tint = CUISINE_COLOURS.get(r.get("cuisine", ""), ("#A29BFE", "#F8F7FF"))
                sk = _safe_key("browse", r["name"])
                browse_css_parts.append(
                    f".st-key-{sk} button {{"
                    f"background:{tint}!important;"
                    f"border-left:4px solid {acc}!important;"
                    f"}}"
                    f".st-key-{sk} button:hover {{"
                    f"border-color:{acc}!important;"
                    f"box-shadow:0 5px 18px {acc}30!important;"
                    f"}}"
                )
            st.markdown(f"<style>{''.join(browse_css_parts)}</style>", unsafe_allow_html=True)

            col_left, col_right = st.columns(2, gap="large")
            for idx, recipe in enumerate(filtered):
                col = col_left if idx % 2 == 0 else col_right
                with col:
                    recipe_card(recipe, recipe["ingredients"], [], 0, "browse", inject_css=False)
                    btn_col, del_col = st.columns([3, 1])
                    with btn_col:
                        if st.button(
                            "🛒 Add ingredients to list",
                            key=f"addlist_{recipe['name']}",
                            use_container_width=True,
                        ):
                            pick_ingredients(recipe)
                    with del_col:
                        if st.button("🗑 Delete", key=f"del_{recipe['name']}",
                                     use_container_width=True):
                            st.session_state.recipes = [
                                r for r in st.session_state.recipes
                                if r["name"] != recipe["name"]
                            ]
                            save_recipes(st.session_state.recipes)
                            st.rerun()


# ── Tab 3: Add recipe ─────────────────────────────────────────────────────────

with tab_add:
    st.markdown('<div style="max-width:680px;margin:0 auto;">', unsafe_allow_html=True)
    st.markdown("### Add a new recipe")

    # ── Photo extraction ────────────────────────────────────────────────────
    with st.expander("📷 Extract from a photo", expanded=False):
        if not _ANTHROPIC_AVAILABLE:
            st.info("`anthropic` package not installed — run `pip install anthropic`.")
        else:
            _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not _api_key:
                try:
                    _api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
                except Exception:
                    _api_key = ""
            if not _api_key:
                st.warning(
                    "Set `ANTHROPIC_API_KEY` in `.streamlit/secrets.toml` or as an "
                    "environment variable to enable photo extraction."
                )
            else:
                uploaded_file = st.file_uploader(
                    "Upload a photo of a handwritten or printed recipe",
                    type=["jpg", "jpeg", "png"],
                    key="recipe_image_upload",
                    label_visibility="collapsed",
                )
                if uploaded_file:
                    st.image(uploaded_file, use_container_width=True)
                    if st.button("✨ Extract recipe details", key="extract_btn",
                                 use_container_width=True):
                        with st.spinner("Reading recipe with Claude…"):
                            try:
                                data = extract_recipe_from_image(
                                    uploaded_file.read(), uploaded_file.type, _api_key
                                )
                                if data:
                                    st.session_state["ar_name"] = data.get("name", "")
                                    st.session_state["ar_ingredients"] = "\n".join(
                                        data.get("ingredients", [])
                                    )
                                    st.session_state["ar_method"] = data.get("method", "")
                                    try:
                                        st.session_state["ar_servings"] = int(
                                            data.get("servings", 2)
                                        )
                                    except (ValueError, TypeError):
                                        st.session_state["ar_servings"] = 2
                                    cuisine_val = data.get("cuisine", "")
                                    st.session_state["ar_cuisine"] = (
                                        cuisine_val if cuisine_val in CUISINES else "Other"
                                    )
                                    extracted_tags = [
                                        t for t in data.get("tags", [])
                                        if t in PREDEFINED_TAGS
                                    ]
                                    st.session_state["ar_tags"] = extracted_tags
                                    st.success(
                                        "✅ Recipe extracted — review the fields below then save."
                                    )
                                    st.rerun()
                                else:
                                    st.error(
                                        "Couldn't parse a recipe from that image. "
                                        "Try a clearer or better-lit photo."
                                    )
                            except Exception as exc:
                                st.error(f"Extraction failed: {exc}")

    # ── Recipe form ─────────────────────────────────────────────────────────
    with st.form("add_recipe_form", clear_on_submit=True):
        name = st.text_input(
            "Recipe name", placeholder="e.g. Chicken Tikka Masala", key="ar_name"
        )
        col_a, col_b = st.columns(2)
        with col_a:
            servings = st.number_input(
                "Servings", min_value=1, max_value=20, value=2, key="ar_servings"
            )
        with col_b:
            cuisine = st.selectbox("Cuisine", options=CUISINES, key="ar_cuisine")
        tags_selected = st.multiselect(
            "Tags",
            options=PREDEFINED_TAGS,
            placeholder="e.g. Dinner, Vegetarian, Dessert…",
            key="ar_tags",
        )
        ingredients_raw = st.text_area(
            "Ingredients",
            placeholder="One per line:\nchicken breast\ngarlic\ntinned tomatoes",
            height=180,
            key="ar_ingredients",
        )
        method = st.text_area(
            "Method",
            placeholder="Step-by-step instructions…",
            height=200,
            key="ar_method",
        )
        submitted = st.form_submit_button("Save recipe", use_container_width=True)

    st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        if not name.strip():
            st.error("Please enter a recipe name.")
        elif not ingredients_raw.strip():
            st.error("Please enter at least one ingredient.")
        else:
            existing_names = [normalise(r["name"]) for r in st.session_state.recipes]
            if normalise(name) in existing_names:
                st.error(f"A recipe called '{name}' already exists.")
            else:
                ingredients_list = [
                    line.strip() for line in ingredients_raw.splitlines() if line.strip()
                ]
                new_recipe = {
                    "name": name.strip(),
                    "cuisine": cuisine,
                    "tags": tags_selected,
                    "ingredients": ingredients_list,
                    "method": method.strip(),
                    "servings": int(servings),
                }
                st.session_state.recipes.append(new_recipe)
                save_recipes(st.session_state.recipes)
                st.success(f"✅ '{name}' saved!")
                st.rerun()


# ── Tab 4: Shopping List ─────────────────────────────────────────────────────

with tab_shop:
    st.markdown('<div style="max-width:600px;margin:0 auto;">', unsafe_allow_html=True)

    # ── Manual add ───────────────────────────────────────────────────────────
    with st.form("shop_add_form", clear_on_submit=True):
        col_si, col_sb = st.columns([8, 1])
        with col_si:
            new_shop_item = st.text_input(
                "shop_input",
                label_visibility="collapsed",
                placeholder="Add an item…",
            )
        with col_sb:
            shop_add = st.form_submit_button("Add", use_container_width=True)

    if shop_add and new_shop_item.strip():
        existing_items = {i["item"].lower() for i in st.session_state.shopping_list}
        if new_shop_item.strip().lower() not in existing_items:
            st.session_state.shopping_list.append({"item": new_shop_item.strip(), "checked": False})
        st.rerun()

    # ── The list ──────────────────────────────────────────────────────────────
    sl = st.session_state.shopping_list
    if not sl:
        st.markdown(
            '<div class="empty-state">Your shopping list is empty.<br>'
            'Open a recipe and hit <b>🛒 Add missing to shopping list</b> to get started.</div>',
            unsafe_allow_html=True,
        )
    else:
        to_buy  = [i for i in sl if not i["checked"]]
        in_cart = [i for i in sl if i["checked"]]

        # Action bar
        col_rm, col_em, col_cl = st.columns(3)
        with col_rm:
            if in_cart and st.button(
                f"Remove ticked ({len(in_cart)})",
                key="shop_rm_checked",
                use_container_width=True,
            ):
                st.session_state.shopping_list = to_buy
                st.rerun()
        with col_em:
            if st.button("\U0001f4e7 Email list", key="shop_email_btn", use_container_width=True):
                email_list()
        with col_cl:
            if st.button("Clear all", key="shop_clear_all", use_container_width=True):
                st.session_state.shopping_list = []
                st.rerun()

        # Rows helper
        def _shop_rows(items: list[dict]) -> None:
            for item_obj in items:
                col_chk, col_del = st.columns([11, 1])
                with col_chk:
                    source = item_obj.get("source", "")
                    label = f"{item_obj['item']}  ({source})" if source else item_obj["item"]
                    ticked = st.checkbox(
                        label,
                        value=item_obj["checked"],
                        key=f"shop_chk_{item_obj['item']}",
                    )
                    if ticked != item_obj["checked"]:
                        item_obj["checked"] = ticked
                        st.rerun()
                with col_del:
                    if st.button("✕", key=f"shop_del_{item_obj['item']}", help="Remove"):
                        st.session_state.shopping_list.remove(item_obj)
                        st.rerun()

        if to_buy:
            st.markdown(
                f'<div class="shop-section-label">To buy &nbsp;<span class="count">{len(to_buy)}</span></div>',
                unsafe_allow_html=True,
            )
            _shop_rows(to_buy)

        if in_cart:
            st.markdown(
                f'<div class="shop-section-label done">In trolley &nbsp;<span class="count">{len(in_cart)}</span></div>',
                unsafe_allow_html=True,
            )
            _shop_rows(in_cart)

    st.markdown('</div>', unsafe_allow_html=True)
