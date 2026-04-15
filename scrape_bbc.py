#!/usr/bin/env python3
"""
Scrape BBC Good Food and merge new recipes into recipes.json.

Uses the BBC Good Food search API (no browser / JS engine needed) to discover
free (non-premium) recipe URLs, then fetches each page's JSON-LD for structured
recipe data.

Usage:
    python scrape_bbc.py                  # add up to 150 new recipes (default)
    python scrape_bbc.py --limit 50       # add fewer
    python scrape_bbc.py --dry-run        # print JSON without saving

The script uses polite random delays and skips recipes already in recipes.json.
"""

import argparse
import json
import re
import time
import random
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL = "https://www.bbcgoodfood.com"
SEARCH_API = f"{BASE_URL}/api/search-frontend/search"

# (cuisine_slug, display_name) — slug goes to the API, display_name stored in recipe.
# Ordered roughly by number of BBC Good Food recipes available per cuisine.
CUISINES_TO_SCRAPE = [
    ("british",       "British"),
    ("italian",       "Italian"),
    ("french",        "French"),
    ("indian",        "Indian"),
    ("american",      "American"),
    ("mediterranean", "Mediterranean"),
    ("asian",         "Asian"),
    ("mexican",       "Mexican"),
    ("chinese",       "Chinese"),
    ("middle-eastern","Middle Eastern"),
    ("spanish",       "Mediterranean"),
    ("thai",          "Thai"),
    ("moroccan",      "Middle Eastern"),
    ("greek",         "Greek"),
    ("japanese",      "Japanese"),
    ("caribbean",     "Other"),
    ("korean",        "Asian"),
    ("turkish",       "Middle Eastern"),
    ("vietnamese",    "Asian"),
]

# Pages to fetch per cuisine. 24 results/page; many will be premium so
# non-premium yield is ~8-18 per page.
PAGES_PER_CUISINE = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

RECIPES_FILE = Path(__file__).parent / "recipes.json"

# ── HTTP helper ───────────────────────────────────────────────────────────────

def get(url: str, params: dict | None = None, retries: int = 3) -> requests.Response | None:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            wait = 2 ** attempt
            print(f"  Attempt {attempt + 1} failed ({exc}) — retrying in {wait}s")
            time.sleep(wait)
    return None


# ── Search API ────────────────────────────────────────────────────────────────

def search_recipe_urls(cuisine_slug: str, max_pages: int = PAGES_PER_CUISINE) -> list[str]:
    """
    Return free (non-premium) recipe URLs for a given BBC cuisine slug.
    Paginates up to max_pages times.
    """
    results: list[str] = []
    next_url: str | None = SEARCH_API
    params: dict | None = {"query": "", "tab": "recipe", "limit": 24, "cuisine": cuisine_slug}
    page = 0

    while next_url and page < max_pages:
        resp = get(next_url, params=params)
        params = None  # nextUrl already has all params encoded
        if not resp:
            break
        try:
            data = resp.json()
        except ValueError:
            break

        sr = data.get("searchResults", {})
        items = sr.get("items", [])
        for item in items:
            url = item.get("url", "")
            if not item.get("isPremium", False) and "/recipes/" in url:
                results.append(url)

        raw_next = sr.get("nextUrl")
        if raw_next:
            next_url = raw_next if raw_next.startswith("http") else BASE_URL + raw_next
        else:
            next_url = None
        page += 1
        if next_url:
            time.sleep(random.uniform(0.2, 0.5))

    return results


# ── JSON-LD extraction ────────────────────────────────────────────────────────

def extract_json_ld(html: str) -> dict | None:
    """Pull the Recipe JSON-LD object from a page, handling @graph wrappers."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or ""
            data = json.loads(raw)
            if isinstance(data, list):
                data = data[0]
            if isinstance(data, dict) and "@graph" in data:
                for item in data["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "Recipe":
                        return item
            if isinstance(data, dict) and data.get("@type") == "Recipe":
                return data
        except (json.JSONDecodeError, AttributeError):
            continue
    return None


def parse_servings(yield_val) -> int:
    if isinstance(yield_val, int):
        return max(1, yield_val)
    if isinstance(yield_val, list):
        yield_val = yield_val[0] if yield_val else "2"
    nums = re.findall(r"\d+", str(yield_val))
    return int(nums[0]) if nums else 2


def parse_method(instructions) -> str:
    if not instructions:
        return ""
    if isinstance(instructions, str):
        return instructions.strip()
    steps = []
    for idx, step in enumerate(instructions, 1):
        text = step.get("text", "") if isinstance(step, dict) else str(step)
        text = BeautifulSoup(text, "html.parser").get_text().strip()
        if text:
            steps.append(f"{idx}. {text}")
    return "\n".join(steps)


_QUANTITY_RE = re.compile(
    r"^(a\s+|an\s+)?"
    r"[\d¼½¾⅓⅔⅛⅜⅝⅞\s./×x]+-?"
    r"(tsp|tbsp|teaspoon|tablespoon|ml|g|kg|oz|lb|cup|cups|litre|litres|pint|pints"
    r"|large|small|medium|handful|bunch|pinch|splash|drop|glug|sprig|sprigs"
    r"|slice|slices|rasher|rashers|piece|pieces|can|cans|tin|tins|pack|packs"
    r"|clove|cloves|head|heads|stalk|stalks|sheet|sheets|sachet|sachets"
    r"|bag|bags|block|blocks|knob|knobs|jar|jars|bottle|bottles)s?\.?\s+",
    re.IGNORECASE,
)
# Strip bare leading number / fraction when no unit follows: "2 eggs" → "eggs"
_BARE_NUM_RE = re.compile(r"^[\d¼½¾⅓⅔⅛⅜⅝⅞]+\s+")


def clean_ingredient(raw: str) -> str:
    """Strip quantities/measures and HTML; return lowercase ingredient name."""
    text = BeautifulSoup(raw, "html.parser").get_text().strip()
    text = _QUANTITY_RE.sub("", text)
    text = _BARE_NUM_RE.sub("", text)
    text = text.split(",")[0].strip()
    # Remove trailing prep notes after common separators
    for sep in (" – ", " - ", " or ", " ("):
        text = text.split(sep)[0].strip()
    return text.lower()


# Schema.org diet URI → human label
_DIET_MAP = {
    "vegetariandiet":  "Vegetarian",
    "vegandiet":       "Vegan",
    "glutenfreediet":  "Gluten-free",
    "lowcaloriediet":  "Low calorie",
    "diabeticdiet":    "Diabetic",
    "lowlactosediet":  "Dairy-free",
    "halaldiet":       "Halal",
    "kosherdiet":      "Kosher",
}

# recipeCategory values worth keeping (lowercase for comparison)
_CATEGORY_ALLOW = {
    "breakfast", "brunch", "lunch", "dinner", "dessert", "snack",
    "starter", "side dish", "buffet", "afternoon tea", "canapes",
    "main course", "soup", "salad", "bread", "cake", "biscuits",
    "pastry", "sauce", "condiment", "drink", "cocktail",
}


def parse_tags(ld: dict) -> list[str]:
    """Extract standardised tag list from JSON-LD recipeCategory and suitableForDiet."""
    tags: set[str] = set()

    # recipeCategory (may be string or list)
    cat = ld.get("recipeCategory", "")
    cats = cat if isinstance(cat, list) else [c.strip() for c in str(cat).split(",") if c.strip()]
    for c in cats:
        if c.strip().lower() in _CATEGORY_ALLOW:
            tags.add(c.strip().title())

    # suitableForDiet (may be string or list of schema.org URIs)
    diet = ld.get("suitableForDiet", "")
    diets = diet if isinstance(diet, list) else ([diet] if diet else [])
    for d in diets:
        key = str(d).split("/")[-1].lower()
        label = _DIET_MAP.get(key)
        if label:
            tags.add(label)

    return sorted(tags)


def build_recipe(ld: dict, fallback_cuisine: str) -> dict | None:
    """Assemble a recipe dict from JSON-LD. Returns None if unusable."""
    name = str(ld.get("name", "")).strip()
    if not name:
        return None

    ingredients = [
        ci for raw in ld.get("recipeIngredient", [])
        if (ci := clean_ingredient(raw))
    ]
    if not ingredients:
        return None

    method = parse_method(ld.get("recipeInstructions", []))
    servings = parse_servings(ld.get("recipeYield", 2))

    cuisine = ld.get("recipeCuisine") or fallback_cuisine
    if isinstance(cuisine, list):
        cuisine = cuisine[0] if cuisine else ""
    cuisine = str(cuisine).strip()

    return {
        "name": name,
        "cuisine": cuisine,
        "tags": parse_tags(ld),
        "ingredients": ingredients,
        "method": method,
        "servings": servings,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=150,
        help="Maximum number of new recipes to add (default: 150)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print scraped recipes as JSON without saving",
    )
    args = parser.parse_args()

    existing: list[dict] = []
    if RECIPES_FILE.exists():
        existing = json.loads(RECIPES_FILE.read_text())
    existing_names = {r["name"].lower() for r in existing}
    print(f"Loaded {len(existing)} existing recipes from {RECIPES_FILE.name}")

    new_recipes: list[dict] = []
    seen_urls: set[str] = set()

    for cuisine_slug, display_cuisine in CUISINES_TO_SCRAPE:
        if len(new_recipes) >= args.limit:
            break

        print(f"\nCuisine: {display_cuisine} ({cuisine_slug})")
        recipe_urls = search_recipe_urls(cuisine_slug)
        new_from_this_cuisine = 0
        print(f"  → {len(recipe_urls)} free recipe URLs found")

        for recipe_url in recipe_urls:
            if len(new_recipes) >= args.limit:
                break
            if recipe_url in seen_urls:
                continue
            seen_urls.add(recipe_url)

            time.sleep(random.uniform(0.6, 1.4))

            resp = get(recipe_url)
            if not resp:
                continue

            ld = extract_json_ld(resp.text)
            if not ld:
                print(f"    (no JSON-LD) {recipe_url}")
                continue

            recipe = build_recipe(ld, display_cuisine)
            if not recipe:
                continue

            if recipe["name"].lower() in existing_names:
                print(f"    skip (duplicate): {recipe['name']}")
                continue

            existing_names.add(recipe["name"].lower())
            new_recipes.append(recipe)
            new_from_this_cuisine += 1
            print(
                f"    ✓ [{len(new_recipes)}/{args.limit}] "
                f"{recipe['name']} ({recipe.get('cuisine', '—')})"
            )

        print(f"  Added {new_from_this_cuisine} new recipes from {display_cuisine}.")

    print(f"\nScraped {len(new_recipes)} new recipes.")

    if args.dry_run:
        print(json.dumps(new_recipes, indent=2))
    else:
        merged = existing + new_recipes
        RECIPES_FILE.write_text(json.dumps(merged, indent=2))
        print(f"Saved {len(merged)} total recipes → {RECIPES_FILE}")


if __name__ == "__main__":
    main()
