"""Use the scraper straight from Python — no server needed.

    python main.py

Every call is validated by the same schema the API uses and returns the same
records; results are written to output/*.json.
"""
import json
import os

from schema_fields import load_query
from target_australia import api, schemas

os.makedirs("output", exist_ok=True)


def run(schema_cls, fn, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return fn(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a SKU, colour-variant or base code, or any target.com.au product link
    save("product_71566665.json", run(schemas.ProductSchema, api.product_details, product="71566665"))

    # 48 products per page, with facets and sort options
    save("search_nintendo_switch.json", run(schemas.SearchSchema, api.products_search, query="nintendo switch"))

    # 20 reviews per page, most helpful first
    save("reviews_P60494832.json", run(schemas.ReviewsSchema, api.product_reviews,
                                       product="P60494832", sort="helpful"))
