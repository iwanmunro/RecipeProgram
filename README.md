# Recipe Finder

A web app for searching recipes based on what you have in your fridge. It shows recipes you can make right now and highlights recipes where you're only missing one or two ingredients, along with a shopping list.

## Features

- **Fridge search** — add your ingredients in the sidebar and instantly see matching recipes
- **Missing-ingredient slider** — choose how many missing ingredients to allow (0–5)
- **Shopping list** — for near-match recipes, shows exactly what you still need to buy
- **Ingredient badges** — green for what you have, red for what you need
- **Browse all** — filter the full recipe list by name or ingredient
- **Add recipes** — save your own recipes with name, servings, ingredients and method
- **Persistent storage** — recipes are saved to `recipes.json`

## Running with Docker (recommended)

```bash
# Build and start
docker compose up --build

# Open in your browser
open http://localhost:8501
```

Recipes are stored in `recipes.json` which is mounted as a volume, so they persist between container restarts.

To stop:

```bash
docker compose down
```

## Running locally (without Docker)

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Project structure

```
RecipeProgram/
├── app.py              # Streamlit app
├── recipes.json        # Recipe data (pre-loaded with 10 example recipes)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## Recipe format

Recipes are stored in `recipes.json`. Each entry looks like:

```json
{
  "name": "Tomato Pasta",
  "ingredients": ["pasta", "tinned tomatoes", "garlic", "olive oil"],
  "method": "1. Cook pasta...",
  "servings": 2
}
```
