"""Offline tests for the /target-australia/* request schemas.

    python -m pytest target_australia/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from target_australia import schemas  # noqa: E402


def load(schema, data):
    return schema().load(data)


def rejects(schema, data, field, fragment=None):
    with pytest.raises(ValidationError) as info:
        schema().load(data)
    messages = info.value.normalized_messages()
    assert field in messages, messages
    if fragment:
        assert fragment in " ".join(messages[field]), messages[field]


# ---- product refs ----------------------------------------------------------------------------

def test_product_schema_accepts_codes_and_links():
    assert load(schemas.ProductSchema, {"product": " 63681024 "}) == {"product": "63681024"}
    assert load(schemas.ProductSchema, {"product": "w1521109"}) == {"product": "W1521109"}
    assert load(schemas.ProductSchema, {"product": "1521109_white"}) == {"product": "1521109_white"}
    assert load(schemas.ProductSchema,
                {"product": "https://www.target.com.au/p/arlo-stonewash-sheet-set/1521109_white?x=1"}) == \
        {"product": "1521109_white"}


@pytest.mark.parametrize("value,fragment", [
    ("", "Must not be empty"),
    ("sheet set", "product code"),
    ("https://example.com/p/63681024", "target.com.au"),
    ("https://www.target.com.au/c/toys/W138532", "product link"),
])
def test_product_schema_rejects(value, fragment):
    rejects(schemas.ProductSchema, {"product": value}, "product", fragment)


def test_product_schema_rejects_sibling_and_unknown_params():
    rejects(schemas.ProductSchema, {"product": "63681024", "url": "x"}, "url")
    rejects(schemas.ProductSchema, {}, "product")


def test_bulk_schema():
    assert load(schemas.ProductsBulkSchema, {"products": "63681024, W1521109,63681024"}) == \
        {"products": ["63681024", "W1521109"]}
    rejects(schemas.ProductsBulkSchema, {"products": ",".join(str(10000000 + i) for i in range(11))},
            "products", "At most 10")
    rejects(schemas.ProductsBulkSchema, {"products": "63681024,abc"}, "products")


def test_reviews_schema():
    assert load(schemas.ReviewsSchema, {"product": "W1521109"}) == \
        {"product": "W1521109", "page": 1, "page_size": 20, "sort": "newest"}
    assert load(schemas.ReviewsSchema, {"product": "63681024", "page": "3", "page_size": "100", "sort": "Helpful"})["sort"] == "helpful"
    rejects(schemas.ReviewsSchema, {"product": "63681024", "page_size": "101"}, "page_size")
    rejects(schemas.ReviewsSchema, {"product": "63681024", "sort": "best"}, "sort", "Must be one of")


def test_stock_schema():
    assert load(schemas.StockSchema, {"products": "63681024"}) == \
        {"products": ["63681024"], "stores": None, "postcode": None}
    loaded = load(schemas.StockSchema, {"products": "63681024,W1521109", "stores": "5123, https://www.target.com.au/store/vic/northland/5121",
                                        "postcode": "3000"})
    assert loaded == {"products": ["63681024", "W1521109"], "stores": ["5123", "5121"], "postcode": "3000"}
    rejects(schemas.StockSchema, {"products": "63681024", "postcode": "30000"}, "postcode", "4-digit")
    rejects(schemas.StockSchema, {"products": "63681024", "stores": "belconnen"}, "stores")
    rejects(schemas.StockSchema, {"products": "63681024", "stores": ",".join(str(5000 + i) for i in range(11))},
            "stores", "At most 10")


# ---- listings ------------------------------------------------------------------------------------

def test_search_schema_defaults_and_filters():
    loaded = load(schemas.SearchSchema, {"query": "lego duplo"})
    assert loaded == {"query": "lego duplo", "page": 1, "page_size": 48, "sort": "relevance", "brand": None,
                      "colour": None, "price": None, "age": None, "min_rating": None, "delivery": None,
                      "new_arrivals": None, "on_sale": None, "online_only": None, "onepass": None,
                      "category": None}
    loaded = load(schemas.SearchSchema, {
        "query": "lego", "page": "2", "page_size": "200", "sort": "PRICE_ASC", "brand": "LEGO, Anko,LEGO",
        "colour": "Multi", "price": "$10 - $20", "age": "3-4,5-7", "min_rating": "4", "delivery": "Click_And_Collect",
        "new_arrivals": "yes", "on_sale": "0", "online_only": "true", "onepass": "false",
        "category": "https://www.target.com.au/c/toys/W138532"})
    assert loaded["page"] == 2 and loaded["page_size"] == 200 and loaded["sort"] == "price_asc"
    assert loaded["brand"] == ["LEGO", "Anko"] and loaded["colour"] == ["Multi"]
    assert loaded["price"] == "10-20" and loaded["age"] == ["3-4", "5-7"] and loaded["min_rating"] == 4
    assert loaded["delivery"] == "click_and_collect"
    assert loaded["new_arrivals"] is True and loaded["on_sale"] is False
    assert loaded["online_only"] is True and loaded["onepass"] is False
    assert loaded["category"] == "W138532"
    assert load(schemas.SearchSchema, {"query": "x", "price": "50-"})["price"] == "50-"
    assert load(schemas.SearchSchema, {"query": "x", "price": "-19.5"})["price"] == "-19.5"


@pytest.mark.parametrize("data,field,fragment", [
    ({}, "query", "Missing"),
    ({"query": "lego", "page": "0"}, "page", None),
    ({"query": "lego", "page": "501"}, "page", None),
    ({"query": "lego", "page_size": "201"}, "page_size", None),
    ({"query": "lego", "sort": "cheapest"}, "sort", "Must be one of"),
    ({"query": "lego", "price": "20-10"}, "price", "lower bound"),
    ({"query": "lego", "price": "abc"}, "price", "price range"),
    ({"query": "lego", "min_rating": "6"}, "min_rating", None),
    ({"query": "lego", "delivery": "drone"}, "delivery", "Must be one of"),
    ({"query": "lego", "on_sale": "maybe"}, "on_sale", "true or false"),
    ({"query": "lego", "category": "toys"}, "category", "category code"),
    ({"query": "lego", "limit": "5"}, "limit", "Unknown"),
])
def test_search_schema_rejects(data, field, fragment):
    rejects(schemas.SearchSchema, data, field, fragment)


def test_category_products_schema():
    assert load(schemas.CategoryProductsSchema, {"category": "toys/trading-card-games/W1852625"})["category"] == "W1852625"
    assert load(schemas.CategoryProductsSchema, {"category": "ap01"})["category"] == "AP01"
    rejects(schemas.CategoryProductsSchema, {}, "category")
    rejects(schemas.CategoryProductsSchema, {"category": "https://www.target.com.au/b/bluey"}, "category", "category link")


def test_brand_and_collection_products_schemas():
    assert load(schemas.BrandProductsSchema, {"brand": "Bluey"})["brand"] == "bluey"
    assert load(schemas.BrandProductsSchema, {"brand": "https://www.target.com.au/b/bluey?group_id=W138532",
                                              "category": "W138532"})["category"] == "W138532"
    rejects(schemas.BrandProductsSchema, {"brand": "https://www.target.com.au/c/toys/W138532"}, "brand", "brand link")
    rejects(schemas.BrandProductsSchema, {"brand": "a b/c"}, "brand", "brand slug")
    assert load(schemas.CollectionProductsSchema, {"collection": "Womens-Sale"})["collection"] == "womens-sale"
    assert load(schemas.CollectionProductsSchema,
                {"collection": "https://www.target.com.au/search?collection_id=womens-sale"})["collection"] == "womens-sale"
    rejects(schemas.CollectionProductsSchema, {"collection": ""}, "collection")


def test_autocomplete_schema():
    assert load(schemas.AutocompleteSchema, {"query": "bl"}) == {"query": "bl", "limit": 10}
    rejects(schemas.AutocompleteSchema, {"query": "bl", "limit": "21"}, "limit")
    rejects(schemas.AutocompleteSchema, {"query": "x" * 101}, "query")


# ---- categories / directories ----------------------------------------------------------------------

def test_categories_schema():
    assert load(schemas.CategoriesSchema, {}) == {"category": "AP01", "depth": 2}
    assert load(schemas.CategoriesSchema, {"category": "W138532", "depth": "6"}) == {"category": "W138532", "depth": 6}
    rejects(schemas.CategoriesSchema, {"depth": "7"}, "depth")
    rejects(schemas.CategoriesSchema, {"depth": "0"}, "depth")


def test_directory_schemas():
    assert load(schemas.BrandsSchema, {}) == {"page": 1, "page_size": 100}
    rejects(schemas.BrandsSchema, {"page_size": "501"}, "page_size")
    assert load(schemas.CollectionsSchema, {"page": "2"}) == {"page": 2, "page_size": 100}
    assert load(schemas.StoresSchema, {"state": "vic"}) == {"state": "vic", "page": 1, "page_size": 50}
    rejects(schemas.StoresSchema, {"state": "XX"}, "state", "Must be one of")


# ---- stores / locations ----------------------------------------------------------------------------

def test_store_schemas():
    assert load(schemas.StoreSchema, {"store": "5123"}) == {"store": "5123"}
    assert load(schemas.StoreSchema, {"store": "https://www.target.com.au/store/act/belconnen/5123"}) == {"store": "5123"}
    rejects(schemas.StoreSchema, {"store": "belconnen"}, "store", "store number")
    rejects(schemas.StoreSchema, {"store": "https://www.target.com.au/p/63681024"}, "store", "store link")
    assert load(schemas.StoresSearchSchema, {"location": " 3000 "}) == {"location": "3000"}
    assert load(schemas.StoresSearchSchema, {"location": "Bondi"}) == {"location": "Bondi"}
    rejects(schemas.StoresSearchSchema, {"location": ""}, "location", "Must not be empty")
    rejects(schemas.StoresSearchSchema, {}, "location")
    assert load(schemas.LocationsSchema, {"query": "Bon"}) == {"query": "Bon"}
    rejects(schemas.LocationsSchema, {"query": ""}, "query")


# ---- sitemaps --------------------------------------------------------------------------------------

def test_sitemap_schemas():
    assert load(schemas.SitemapProductsSchema, {}) == {"page": 1, "page_size": 1000}
    rejects(schemas.SitemapProductsSchema, {"page_size": "5001"}, "page_size")
    assert load(schemas.SitemapLinksSchema, {}) == {"type": "all", "page": 1, "page_size": 1000}
    assert load(schemas.SitemapLinksSchema, {"type": "Stores"})["type"] == "stores"
    rejects(schemas.SitemapLinksSchema, {"type": "images"}, "type", "Must be one of")
