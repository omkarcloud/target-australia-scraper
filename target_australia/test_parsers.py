"""Offline tests for the Target Australia parsers, reference resolvers and
the api layer's slicing / merging (no network).

    python -m pytest target_australia/test_parsers.py -q

Fixtures are real captures from 2026-10-28 (target_australia/fixtures/):
three product pages (SKU with a price, W base with a price range, sparse P
base with one variant and no reviews), a colour-variant page as full HTML,
the /404 page, a brand page + the site's "Hmm" error page, Constructor
search / browse / tree / autocomplete payloads (incl. an unknown group),
Bazaarvoice reviews (+ an empty page), stock / delivery / location JSON,
two store-finder pages, a store page, the /brands page and the sitemaps.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from target_australia import api, parsers as P, refs  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


# ---- refs ---------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("63681024", "63681024"),
    ("1521109_white", "1521109_white"),
    ("w1521109", "W1521109"),
    ("P73493297", "P73493297"),
    ("5000322001FL_amber", "5000322001FL_amber"),
    ("https://www.target.com.au/p/arlo-stonewash-sheet-set/1521109_white", "1521109_white"),
    ("https://www.target.com.au/p/63681024?x=1", "63681024"),
    ("www.target.com.au/p/some-slug/W1521109", "W1521109"),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "sheet set", "https://example.com/p/63681024",
                                   "https://www.target.com.au/c/toys/W138532", "abc"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


def test_resolve_products_list():
    assert refs.resolve_products("63681024, W1521109,63681024", 10) == ["63681024", "W1521109"]
    with pytest.raises(ValueError):
        refs.resolve_products("63681024,73493297", 1)
    with pytest.raises(ValueError):
        refs.resolve_products(" , ", 5)


@pytest.mark.parametrize("value,expected", [
    ("W1852625", "W1852625"),
    ("w1852625", "W1852625"),
    ("AP01", "AP01"),
    ("toys/trading-card-games/W1852625", "W1852625"),
    ("/c/toys/W138532", "W138532"),
    ("https://www.target.com.au/c/toys/board-games-puzzles/trading-card-games/W1852625?page=2", "W1852625"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value", ["", "toys", "https://www.target.com.au/b/bluey", "12345"])
def test_resolve_category_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_category(value)


def test_resolve_brand_collection_store():
    assert refs.resolve_brand("Bluey") == "bluey"
    assert refs.resolve_brand("https://www.target.com.au/b/bluey?group_id=W138532") == "bluey"
    assert refs.resolve_collection("womens-sale") == "womens-sale"
    assert refs.resolve_collection("https://www.target.com.au/collection/womens-sale") == "womens-sale"
    assert refs.resolve_collection("https://www.target.com.au/search?collection_id=womens-sale") == "womens-sale"
    assert refs.resolve_store("5123") == "5123"
    assert refs.resolve_store("https://www.target.com.au/store/act/belconnen/5123") == "5123"
    assert refs.resolve_stores("5123, 5121", 10) == ["5123", "5121"]
    for fn, bad in ((refs.resolve_brand, "a/b"), (refs.resolve_brand, "https://www.target.com.au/c/W1"),
                    (refs.resolve_collection, ""), (refs.resolve_store, "belconnen"),
                    (refs.resolve_store, "https://www.target.com.au/p/63681024")):
        with pytest.raises(ValueError):
            fn(bad)


@pytest.mark.parametrize("value,expected", [
    ("10-20", (10.0, 20.0)), ("$10 - $20", (10.0, 20.0)), ("50-", (50.0, None)), ("-20", (None, 20.0)),
    ("15", (15.0, None)),
])
def test_resolve_price_range(value, expected):
    assert refs.resolve_price_range(value) == expected


@pytest.mark.parametrize("value", ["", "-", "abc", "20-10", "-5-"])
def test_resolve_price_range_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_price_range(value)


def test_absolute_links():
    assert refs.absolute("/p/x/1") == "https://www.target.com.au/p/x/1"
    assert refs.absolute("/dam/grid/x") == "https://assets.target.com.au/dam/grid/x"
    assert refs.absolute("https://a/b") == "https://a/b"
    assert refs.absolute("") is None and refs.absolute(None) is None


# ---- product page --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sku_page():
    return P.parse_product(fixture("product_sku_63681024.next.json"), "63681024")


def test_parse_product_sku(sku_page):
    p = sku_page
    assert p["id"] == "63681024" and p["base_id"] == "1521109_white" and p["parent_base_id"] == "W1521109"
    assert p["name"] == "Arlo Stonewash Sheet Set - White"
    assert p["link"] == "https://www.target.com.au/p/arlo-stonewash-sheet-set/63681024"
    assert p["price"] == {"amount": 80, "range": {"min": 70, "max": 100}, "was": None, "was_range": None,
                          "rrp": None, "onepass": None, "onepass_range": None, "currency": "AUD"}
    assert p["description"].startswith("Luxuriously comfortable")
    assert "<" not in p["description"]
    assert p["extra_info"].startswith("Single bed includes:\n1 x flat sheet")
    assert p["features"][1] == "Made from 100% pre-washed cotton"
    assert p["materials"] == ["100% Pre-washed Cotton"]
    assert p["care_instructions"][0] == "Cold gentle machine wash separately before use"
    assert len(p["care_instructions"]) == 7
    assert p["delivery"] == {"home_delivery": True, "click_and_collect": True, "express_delivery": True,
                             "is_big_and_bulky": False, "is_click_and_collect_in_store_allowed": False,
                             "is_eligible_for_onepass_free_delivery": True}
    assert p["rating"] == {"average": 4.46, "count": 1467}
    assert p["labels"]["is_new"] is False and p["labels"]["is_only_at_target"] is False
    assert p["availability"] == "NORMAL" and p["is_coming_soon"] is False
    assert [c["code"] for c in p["colour_variants"]] == ["1521109_charcoal", "1521109_white", "P1521109_seafoam"]
    assert p["selected_colour"]["label"] == "White"
    assert p["selected_size"] == {"code": "63681024", "label": "Queen Bed",
                                  "link": "https://www.target.com.au/p/arlo-stonewash-sheet-set/63681024",
                                  "is_display_only": False}
    assert sorted(s["label"] for s in p["size_variants"]) == ["Double Bed", "King Bed", "Queen Bed", "Super King Bed"]
    assert len(p["purchasable_variant_codes"]) == 10
    assert p["sizes_by_colour"]["1521109_white"] == ["63681024", "63681215", "64924281", "63681208"]
    assert p["breadcrumbs"][0] == {"name": "Home", "category_id": "W99700",
                                   "link": "https://www.target.com.au/c/home/W99700"}
    assert p["images"][0]["type"] == "PRIMARY" and p["images"][0]["link"].startswith("https://assets.target.com.au/")
    assert len(p["gallery_images"]) == 2
    assert p["has_size_chart"] is True and p["manuals"] == []
    assert p["manufacturer"] is None and "brand" not in p   # brand: details merges it from the search engine
    assert p["meta"] == {"title": None, "description": None}


def test_parse_product_base_with_range():
    p = P.parse_product(fixture("product_base_W1521109.next.json"), "W1521109")
    assert p["id"] == "1521109_charcoal" and p["base_id"] == "W1521109"
    assert p["price"]["amount"] is None and p["price"]["range"] == {"min": 70, "max": 100}
    assert p["selected_size"] is None


def test_parse_product_sparse():
    p = P.parse_product(fixture("product_base_P73493297.next.json"), "P73493297")
    assert p["id"] == "73493297" and p["base_id"] == "P73493297"
    assert p["price"]["amount"] == 11 and p["price"]["range"] is None
    assert p["rating"] == {"average": None, "count": 0}
    assert p["size_variants"] == [] and p["selected_size"] is None
    assert p["purchasable_variant_codes"] == ["73493297"]
    assert p["features"][0] == "Suitable for ages: 6+ years"
    assert p["onepass"]["badge_text"] is None and p["deal_description"] is None
    assert p["manufacturer"] == "BANTER TOYS - TRADING CARDS (FIS)"


def test_parse_product_from_html_and_not_found():
    data = P.next_data(fixture("product_colour_variant_1521109_white.html"))
    p = P.parse_product(data, "1521109_white")
    assert p["id"] == "1521109_white" and p["selected_colour"]["code"] == "1521109_white"
    assert P.next_data(fixture("product_not_found.html"))["page"] == "/404"
    assert P.parse_product(P.next_data(fixture("product_not_found.html")), "00000000") is None
    assert P.next_data(fixture("brand_not_found.html")) is None
    assert P.next_data("<html></html>") is None
    assert P.parse_product({}, "x") is None


# ---- Constructor listings ---------------------------------------------------------------------

@pytest.fixture(scope="module")
def search():
    return P.parse_listing(fixture("constructor_search_lego_duplo.json"), 1, 5)


def test_parse_listing_search(search):
    assert search["pagination"] == {"page": 1, "items_per_page": 5, "total_pages": 20, "total_count": 99}
    assert len(search["results"]) == 5
    card = search["results"][0]
    assert card["id"] == "P73001331" and card["brand"] == "LEGO"
    assert card["name"] == "LEGO® DUPLO Classic Colourful Creative Box 10479"
    assert card["link"].endswith("/73001331") and card["base_link"].endswith("/P73001331")
    assert card["price"] == {"amount": 20.8, "was": 26, "currency": "AUD"}
    assert card["labels"]["is_on_sale"] is True and card["labels"]["is_clearance"] is False
    assert card["is_in_stock"] is True and card["availability"] == "NORMAL"
    assert card["stock"]["online_quantity"] == 37 and card["stock"]["store_quantity"] == 234
    assert "VIC-Chadstone" in card["stock"]["delivery_stock_locations"]
    assert len(card["stock"]["in_store_stock_locations"]) == 90
    assert card["rating"] == {"average": 4.8, "count": 5}
    assert card["features"][0] == "Suitable for ages: 18+ months years"
    assert not any(f.strip(",").isdigit() for f in card["features"])      # "607," artefacts dropped
    assert "<" not in card["description"]
    assert card["top_level_category"] == "Toys" and sorted(card["category_ids"]) == ["W152984", "W1583242", "W418124"]
    assert card["google_taxonomy"].startswith("Toys & Games")
    assert card["online_date"] == "2026-06-02"   # epoch 1780358400, UTC
    assert card["image"].startswith("https://assets.target.com.au/transform/") and "?io=" not in card["image"]
    assert len(card["images"]) == 11 and len(set(card["images"])) == 11
    assert card["variations_count"] == 1
    var = card["variations"][0]
    assert var["id"] == "73001331" and var["price"]["amount"] == 20.8 and var["is_in_stock"] is True
    assert var["online_quantity"] == 37 and var["colour"] == "Multi"
    assert card["matched_terms"] == ["duplo", "lego"]


def test_parse_listing_facets_sorts_groups(search):
    names = [f["name"] for f in search["facets"]]
    assert names[:4] == ["newarrivals", "colour", "price", "brand"]
    price = next(f for f in search["facets"] if f["name"] == "price")
    assert price["options"][1] == {"value": '"10"-"20"', "display_name": "$10 - $20", "count": 25,
                                   "range": [10, 20], "is_selected": False}
    assert [s["value"] for s in search["sort_options"]] == \
        ["relevance", "latest", "rating", "price_desc", "price_asc", "brand"]
    assert search["sort_options"][0]["is_selected"] is True
    assert search["category"] == {"id": "AP01", "name": "All Products", "product_count": 99, "link": None, "parents": []}
    assert search["category_counts"][0] == {"id": "W93741", "name": "Baby", "product_count": 2,
                                            "link": "https://www.target.com.au/c/W93741"}
    assert search["related_searches"][:2] == ["lego marvel", "lego technic"]
    assert search["collection"] is None


def test_parse_listing_filtered_and_sorted():
    result = P.parse_listing(fixture("constructor_search_sheet_set_filtered.json"), 1, 3)
    assert result["sort_options"][0]["value"] == "relevance" and result["sort_options"][0]["is_selected"] is False
    assert next(s for s in result["sort_options"] if s["value"] == "price_asc")["is_selected"] is True
    price = next(f for f in result["facets"] if f["name"] == "price")
    assert any(o["is_selected"] for o in price["options"])
    prices = [r["price"]["amount"] for r in result["results"]]
    assert prices == sorted(prices) and all(20 <= p <= 100 for p in prices)
    first = result["results"][0]
    assert first["variations_count"] > 1
    assert all(v["colour_variant_code"] for v in first["variations"])


def test_parse_listing_category_brand_collection():
    cat = P.parse_listing(fixture("constructor_browse_category_W1852625.json"), 1, 5)
    assert cat["category"]["id"] == "W1852625" and cat["category"]["name"] == "Trading Card Games"
    assert cat["category"]["parents"][-1]["id"] == "W138532"
    assert cat["pagination"]["total_count"] == 48
    assert cat["results"][0]["labels"]["is_assorted"] is True
    brand = P.parse_listing(fixture("constructor_browse_brand_bluey.json"), 1, 3)
    assert brand["pagination"]["total_count"] == 198 and all(r["brand"] == "Bluey" for r in brand["results"])
    coll = P.parse_listing(fixture("constructor_browse_collection_womens_sale.json"), 1, 3)
    assert coll["collection"]["id"] == "womens-sale" and coll["collection"]["name"] == "Womens Sale"
    assert coll["collection"]["link"] == "https://www.target.com.au/collection/womens-sale"
    assert coll["collection"]["breadcrumbs"][0]["name"] == "Women"
    assert "<" not in coll["collection"]["description"]


def test_parse_listing_unknown_group_and_empty():
    unknown = fixture("constructor_browse_unknown.json")
    assert P.listing_is_empty_group(unknown) is True
    assert P.listing_is_empty_group(fixture("constructor_browse_category_W1852625.json")) is False
    assert P.listing_is_empty_group(fixture("constructor_browse_collection_womens_sale.json")) is False
    result = P.parse_listing(unknown, 1, 2)
    assert result["results"] == [] and result["pagination"]["total_count"] == 0
    assert P.parse_listing({}, 3, 10)["pagination"] == {"page": 3, "items_per_page": 10, "total_pages": 0,
                                                        "total_count": 0}
    assert P.parse_result({}) is None and P.parse_result({"data": {}}) is None


def test_card_for_code():
    payload = fixture("constructor_search_lego_duplo.json")
    assert P.card_for_code(payload, "P73001331")["id"] == "P73001331"
    assert P.card_for_code(payload, "73001331")["id"] == "P73001331"   # SKU of the base
    assert P.card_for_code(payload, "p73001331")["id"] == "P73001331"
    assert P.card_for_code(payload, "00000000") is None
    assert P.card_for_code({}, "P73001331") is None


def test_parse_tree():
    tree = P.parse_tree(fixture("constructor_tree_W1852625.json"))
    assert tree["id"] == "W1852625" and tree["product_count"] == 48
    assert [c["name"] for c in tree["children"]] == ["Pokemon Cards", "Sports Trading Cards"]
    assert tree["children"][0]["children"] == []
    full = P.parse_tree(fixture("constructor_tree_AP01_depth3.json"), links={"W93741": "https://x/baby"}, max_depth=1)
    assert full["id"] == "AP01" and full["link"] is None and full["product_count"] == 24907
    assert full["children"][0]["name"] == "Baby" and full["children"][0]["link"] == "https://x/baby"
    assert "children" not in full["children"][0]
    assert P.parse_tree(fixture("constructor_browse_unknown.json")) is None


def test_parse_autocomplete():
    out = P.parse_autocomplete(fixture("constructor_autocomplete_bl.json"))
    assert [s["term"] for s in out["suggestions"]][:2] == ["bluey", "bluey pyjamas"]
    first = out["suggestions"][0]
    assert first["link"] == "https://www.target.com.au/search?text=bluey"
    assert first["categories"][0]["id"] == "W1552602" and first["categories"][0]["path"][0] == "All Products"
    assert out["products"][0]["id"] == "P73172994" and out["products"][0]["brand"] == "Bluey"
    assert out["products"][0]["price"]["amount"] == 20 and out["products"][0]["image"].startswith("https://")
    assert out["brands"] == [] and out["categories"] == []
    assert out["totals"] == {"suggestions": 500, "products": 282, "brands": 0, "categories": 0}
    assert out["suggestions"][1]["link"] == "https://www.target.com.au/search?text=bluey%20pyjamas"   # URL-encoded
    assert P.parse_autocomplete({"sections": {"Search Suggestions": [{"value": "crown & andrews"}]}})[
        "suggestions"][0]["link"] == "https://www.target.com.au/search?text=crown%20%26%20andrews"
    assert P.parse_autocomplete({})["suggestions"] == []


# ---- brand pages ----------------------------------------------------------------------------

def test_parse_brand_page():
    brand = P.parse_brand_page(fixture("brand_bluey.next.json"), "bluey")
    assert brand["slug"] == "bluey" and brand["name"] == "Bluey"
    assert brand["link"] == "https://www.target.com.au/b/bluey"
    assert brand["title"] == "Bluey Toys, Pyjamas & Books | Shop Online | Target Australia"
    assert brand["meta_description"].startswith("Explore Target's great range")
    assert brand["product_count"] == 198
    assert brand["hero_banner"]["alt"] == "Welcome to the Bluey Shop!"
    assert brand["hero_banner"]["image"].startswith("https://www.target.com.au/medias/")
    assert brand["banners"][0]["text"] == "Toys"
    assert brand["contextual_links"] == []       # this capture's SEO block carries prose, no anchors
    assert P.parse_brand_page({"props": {"pageProps": {"brandName": "X", "contextualLinks":
                                                       '<p>see <a href="/c/toys/W138532">toys</a></p>'}}}, "x")[
        "contextual_links"] == [{"name": "toys", "link": "https://www.target.com.au/c/toys/W138532"}]
    assert P.parse_brand_page({}, "x") is None


def test_parse_brands_page():
    found = P.parse_brands_page(fixture("brands_page.html"))
    assert len(found) > 80
    assert found["bluey"]["name"] == "Bluey" and found["bluey"]["image"].endswith(".png")
    assert found["russellhobbs"]["name"] == "Russell Hobbs"     # "Shop Russell Hobbs" alt trimmed
    assert P.parse_brands_page("") == {}


# ---- reviews ----------------------------------------------------------------------------------

def test_parse_reviews():
    out = P.parse_reviews(fixture("reviews_W1521109.json"), "W1521109", 1, 5)
    assert out["product"]["id"] == "W1521109" and out["product"]["brand"] == "Arlo"
    assert out["product"]["link"] == "https://www.target.com.au/p/arlo-stonewash-sheet-set/W1521109"
    stats = out["statistics"]
    assert stats["average"] == 4.46 and stats["count"] == 1467 and stats["ratings_only_count"] == 992
    assert stats["distribution"] == {"5": 1088, "4": 190, "3": 60, "2": 37, "1": 92}
    assert stats["recommended_count"] == 296 and stats["photos_count"] == 38
    assert stats["secondary_ratings"]["Value"]["label"] == "Value For Money"
    assert stats["context"]["Gender"]["values"][1] == {"value": "Female", "count": 289}
    assert stats["first_submitted_at"] == "2020-08-09T00:20:27.000+00:00"
    assert out["pagination"] == {"page": 1, "items_per_page": 5, "total_pages": 294, "total_count": 1467}
    assert len(out["reviews"]) == 5
    first = out["reviews"][0]
    assert first["id"] == "280838114" and first["rating"] == 5 and first["is_ratings_only"] is True
    assert first["is_verified_purchaser"] is True and first["badges"] == ["verifiedPurchaser"]
    assert first["title"] is None and first["text"] is None and first["author"]["nickname"] is None
    assert first["submitted_at"] == "2026-10-15T20:19:05.000+00:00"
    assert first["helpfulness"] == {"score": None, "positive_votes": 0, "negative_votes": 0, "total_votes": 0}
    written = [r for r in out["reviews"] if r["text"]]
    assert written and written[0]["author"]["nickname"]


def test_parse_reviews_empty():
    out = P.parse_reviews(fixture("reviews_none_P73493297.json"), "P73493297", 1, 5)
    assert out["reviews"] == [] and out["statistics"] is None
    assert out["product"] == {"id": "P73493297", "name": None, "link": "https://www.target.com.au/p/P73493297",
                              "brand": None, "image": None, "category_id": None, "description": None,
                              "is_active": None}
    assert out["pagination"]["total_count"] == 0 and out["pagination"]["total_pages"] == 0
    assert P.parse_reviews({}, "X", 2, 10)["pagination"]["page"] == 2


# ---- stock / delivery / locations -------------------------------------------------------------

def test_parse_stock():
    rows = P.parse_stock(fixture("stock_63681024_39808608.json"), ["5121", "5123", "9999"])
    by_sku = {r["sku"]: r for r in rows}
    assert by_sku["39808608"]["stores"] == {"5121": "out_of_stock", "5123": "low_stock", "9999": None}
    assert by_sku["63681024"]["overall"] == "in_stock" and by_sku["63681024"]["home_delivery"] == "in_stock"
    assert by_sku["63681024"]["click_and_collect"] == "in_stock" and by_sku["63681024"]["all_stores"] == "in_stock"
    assert by_sku["00000000"]["overall"] == "out_of_stock"      # the API answers unknown SKUs as out of stock
    assert P.parse_stock({}) == [] and P.parse_stock(None) == []


def test_parse_delivery_region_and_locations():
    assert P.parse_delivery_region(fixture("delivery_region_3000.json")) == {
        "location_group": "VIC-Northland", "is_home_delivery_available": True, "region_id": "103072"}
    assert P.parse_delivery_region({}) is None
    rows = P.parse_locations(fixture("locations_bondi.json"))
    assert rows[0] == {"postcode": "2026", "suburb": "North Bondi", "state": "NSW"}
    assert len(rows) == 5
    assert P.parse_locations({}) == [] and P.parse_locations({"results": [{"postalCode": 800}]})[0]["postcode"] == "0800"


# ---- stores ------------------------------------------------------------------------------------

def test_parse_store_finder():
    out = P.parse_store_finder(fixture("store_finder_3000.html"))
    assert out["center"] == {"latitude": -37.8152065, "longitude": 144.963937}
    assert len(out["stores"]) == 5
    first = out["stores"][0]
    assert first == {"number": "5121", "name": "Northland",
                     "link": "https://www.target.com.au/store/vic/northland/5121", "distance_km": 10.1,
                     "address": {"venue": "Northland Shopping Centre", "street": "2 Murray Road",
                                 "suburb": "Preston", "state": "VIC", "postcode": "3072"},
                     "phone": "03 9474 6800", "latitude": -37.741026, "longitude": 145.030861}
    assert [s["distance_km"] for s in out["stores"]] == sorted(s["distance_km"] for s in out["stores"])
    bondi = P.parse_store_finder(fixture("store_finder_bondi.html"))
    assert bondi["stores"][0]["name"] == "Broadway" and bondi["stores"][0]["latitude"] == -33.883677
    assert P.parse_store_finder("<html></html>") == {"center": None, "stores": []}


def test_parse_store_page():
    store = P.parse_store_page(fixture("store_belconnen_5123.html"), "5123")
    assert store["number"] == "5123" and store["name"] == "Belconnen" and store["state"] == "ACT"
    assert store["link"] == "https://www.target.com.au/store/act/belconnen/5123"
    assert store["address"] == {"venue": None, "street": "18 Benjamin Way", "suburb": "Belconnen",
                                "state": "ACT", "postcode": "2617"}
    assert store["phone"] == "02 6256 4000"
    assert store["latitude"] == -35.237592 and store["longitude"] == 149.063815
    assert len(store["trading_hours"]) == 2
    week = store["trading_hours"][0]
    assert week["week"] == "Mon, 26 Oct - Sun, 1 Nov"
    assert week["days"][0] == {"day": "Monday", "hours": "8:30 AM - 7:00 PM", "opens": "8:30 AM",
                               "closes": "7:00 PM", "is_closed": False}
    assert week["days"][4]["closes"] == "9:00 PM"
    assert P.parse_store_page("<html><body>nothing</body></html>", "1") is None


# ---- sitemaps ------------------------------------------------------------------------------------

def test_parse_sitemaps():
    index = P.parse_sitemap_index(fixture("sitemap_index.xml"))
    assert [i["link"].rsplit("/", 1)[-1] for i in index] == \
        ["content-sitemap.xml", "category-sitemap.xml", "brand-sitemap.xml", "collection-sitemap.xml",
         "stores-sitemap.xml", "sitemap.xml"]
    products = P.sitemap_products(P.parse_sitemap(fixture("sitemap_products_head.xml")))
    assert products[0] == {"id": "12393473", "slug": "lindt-lindor-assorted-chocolate-gift-box-235g",
                           "link": "https://www.target.com.au/p/lindt-lindor-assorted-chocolate-gift-box-235g/12393473",
                           "last_modified": None}
    assert products[1]["id"] == "1521109_leafgreen"
    categories = P.sitemap_categories(P.parse_sitemap(fixture("sitemap_categories_head.xml")))
    assert categories[1] == {"id": "W1852625", "path": "toys/trading-card-games", "name": "Trading Card Games",
                             "link": "https://www.target.com.au/c/toys/trading-card-games/W1852625",
                             "last_modified": None}
    brands = P.sitemap_slugs(P.parse_sitemap(fixture("sitemap_brands.xml")), "/b/")
    assert len(brands) == 489 and brands[0]["slug"] == "sherrin"
    collections = P.sitemap_slugs(P.parse_sitemap(fixture("sitemap_collections.xml")), "/collection/")
    assert collections[0]["slug"] == "xbox-wireless-controllers"
    stores = P.sitemap_stores(P.parse_sitemap(fixture("sitemap_stores.xml")))
    assert len(stores) == 123 and stores[0] == {"number": "5123", "state": "ACT", "slug": "belconnen",
                                                "name": "Belconnen",
                                                "link": "https://www.target.com.au/store/act/belconnen/5123",
                                                "last_modified": None}
    content = P.parse_sitemap(fixture("sitemap_content.xml"))
    assert content[0] == {"link": "https://www.target.com.au/", "last_modified": None,
                          "change_frequency": "weekly", "priority": 1}
    assert P.parse_sitemap("") == [] and P.parse_sitemap_index("") == []


# ---- api layer (no network) -------------------------------------------------------------------

def test_listing_params():
    data = {"page": 2, "page_size": 48, "sort": "price_asc", "brand": ["LEGO", "Anko"], "colour": None,
            "price": "10-", "age": ["3-4"], "min_rating": 4, "delivery": "click_and_collect",
            "new_arrivals": True, "on_sale": None, "online_only": True, "onepass": False, "category": "W138532"}
    params = api._listing_params(data)
    assert params[:4] == [("num_results_per_page", 48), ("page", 2), ("sort_by", "price"), ("sort_order", "ascending")]
    assert params.count(("filters[brand]", "LEGO")) == 1 and ("filters[brand]", "Anko") in params
    assert ("filters[price]", "10-inf") in params
    assert ("filters[reviewavgrating]", "4-inf") in params
    assert ("filters[deliverymodes]", "Click & Collect") in params
    assert ("filters[newarrivals]", "True") in params and not any(p[0] == "filters[sale]" for p in params)
    assert ("filters[promotionstatus]", "Online Exclusive") in params
    assert ("filters[eligibleforadvfreedelivery]", "False") in params
    assert ("filters[group_id]", "W138532") in params
    assert api._has_filters(data) is True
    assert api._has_filters({"page": 1, "page_size": 48, "sort": "relevance", "category": "AP01"}) is False
    assert api._listing_params({"page": 1, "page_size": 10, "price": "-20"})[-1] == ("filters[price]", "-inf-20")


def test_merge_details_page_and_card():
    page = P.parse_product(fixture("product_sku_63681024.next.json"), "63681024")
    card = P.parse_result(fixture("constructor_search_sheet_set_filtered.json")["response"]["results"][0])
    assert card["id"] == "W5000299513"
    merged = api._merge_details(page, card)
    assert list(merged)[:5] == ["id", "base_id", "parent_base_id", "name", "link"]
    assert merged["brand"] == card["brand"] == "Target" and merged["is_in_stock"] is True
    assert merged["stock"]["online_quantity"] == card["stock"]["online_quantity"]
    assert merged["variations"] and merged["variations"][0]["price"]["amount"]
    assert merged["labels"]["is_target_exclusive"] is False and merged["labels"]["is_only_at_target"] is False
    assert merged["online_date"] and merged["category_ids"]
    bare = api._merge_details(page, None)
    assert bare["brand"] is None and bare["stock"] is None and bare["variations"] == []
    # the supplier of record never stands in for the brand
    sparse = P.parse_product(fixture("product_base_P73493297.next.json"), "P73493297")
    assert api._merge_details(sparse, {"brand": "Pokemon"})["brand"] == "Pokemon"
    merged = api._merge_details(sparse, None)
    assert merged["brand"] is None and merged["manufacturer"] == "BANTER TOYS - TRADING CARDS (FIS)"


def test_paged():
    out = api._paged(list(range(10)), 2, 4)
    assert out["results"] == [4, 5, 6, 7]
    assert out["pagination"] == {"page": 2, "items_per_page": 4, "total_pages": 3, "total_count": 10}
    assert api._paged(list(range(10)), 9, 4)["results"] == []


def test_one_of_bulk_reports_every_failure_per_row(monkeypatch):
    from target_australia import fetch
    for exc in (fetch.TargetNotFound("gone"), fetch.TargetBadRequest("bad"), fetch.TargetBlocked("403")):
        monkeypatch.setattr(api, "product_details", lambda code, exc=exc: (_ for _ in ()).throw(exc))
        row = api._one_of_bulk("63681024")
        assert row["id"] == "63681024" and row["error"]


def test_classify_ignores_markers_inside_json(monkeypatch):
    from target_australia import fetch

    class Resp:
        status_code = 200
        headers = {"content-type": "application/json;charset=utf-8"}
        text = '{"Results": [{"ReviewText": "Just a moment after unboxing the captcha puzzle..."}]}'

    assert fetch._classify(Resp(), "reviews") == Resp.text
    Resp.headers = {"content-type": "text/html"}
    Resp.text = "<html><title>Access Denied</title></html>"
    with pytest.raises(fetch.TargetBlocked):
        fetch._classify(Resp(), "page")


def test_brand_page_redirected_off_b_is_not_found(monkeypatch):
    from target_australia import fetch

    class Resp:
        status_code = 200
        headers = {"content-type": "text/html"}
        text = "<html><title>LEGO Shop | Target Australia</title></html>"
        url = "https://www.target.com.au/lego"

    class Session:
        def get(self, url, **kwargs):
            return Resp()

    monkeypatch.setattr(fetch, "_session", Session)
    monkeypatch.setattr(fetch, "_fallback_until", 0.0)
    with pytest.raises(fetch.TargetNotFound):
        fetch.fetch_brand_page("lego")
    assert fetch._fallback_until == 0.0     # not a block: no residential cooldown


def test_brand_slug_of():
    assert refs.brand_slug_of("Crown & Andrews") == "crownandrews"
    assert refs.brand_slug_of("Russell Hobbs") == "russellhobbs"
    assert refs.brand_slug_of("3C4G") == "3c4g"
    assert refs.brand_slug_of(None) == ""
