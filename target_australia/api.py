"""The /target-australia/* endpoint functions (route_glue's route_table
calls them with the schema's loaded kwargs).

Every endpoint caches its own response through cache.cached_call. The
product endpoints also share two cached upstream parses:

  * _page(code)  the /p/<code> Next.js page (descriptions, variants,
                 delivery modes) — target_australia.product_page
  * _card(code)  the Constructor record for the code (a search for a
                 product code answers exactly that base product: brand,
                 online / store quantities, every SKU with price and stock)
                 — target_australia.product_card

so details (page + card), reviews (card for the base id) and stock (card
for the SKU list) on one product cost at most one page fetch and one
search call between them.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import config
from cache import cached_call
from scraper_errors import BadRequest, NotFound, UpstreamError
from target_australia import cache_config as ttl
from target_australia import parsers, refs
from target_australia.fetch import (TargetNotFound, fetch_brand_page, fetch_brands_page, fetch_constructor,
                                    fetch_delivery_region, fetch_locations, fetch_product_page, fetch_reviews,
                                    fetch_sitemap, fetch_stock, fetch_store_finder, fetch_store_page)

NS = "target_australia"
_BASE_CODE_RE = re.compile(r"^[WP](?=[A-Z0-9]*\d)[A-Z0-9]+$")   # W1521109, P73493297, W220MILAHRFL1
_SKU_RE = re.compile(r"^\d+$")
MAX_STOCK_SKUS = 60   # one stockStatus call; a base product has up to ~45 SKUs


def _paged(items, page, page_size):
    """Slice a full list into one page + the pagination block."""
    total = len(items)
    start = (page - 1) * page_size
    return {
        "results": items[start:start + page_size],
        "pagination": {
            "page": page,
            "items_per_page": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 0,
            "total_count": total,
        },
    }


# ---- Constructor listings ------------------------------------------------------

def _listing_params(data):
    """The validated listing filters -> Constructor query pairs."""
    page, page_size = data["page"], data["page_size"]
    sort_by, sort_order = refs.SORTS[data.get("sort") or "relevance"]
    params = [("num_results_per_page", page_size), ("page", page),
              ("sort_by", sort_by), ("sort_order", sort_order)]
    for brand in data.get("brand") or []:
        params.append(("filters[brand]", brand))
    for colour in data.get("colour") or []:
        params.append(("filters[colour]", colour))
    for age in data.get("age") or []:
        params.append(("filters[age]", age))
    if data.get("price"):
        low, _, high = data["price"].partition("-")
        params.append(("filters[price]", f"{low or '-inf'}-{high or 'inf'}"))
    if data.get("min_rating"):
        params.append(("filters[reviewavgrating]", f"{data['min_rating']}-inf"))
    if data.get("delivery"):
        params.append(("filters[deliverymodes]", refs.DELIVERY_MODES[data["delivery"]]))
    if data.get("new_arrivals") is not None:
        params.append(("filters[newarrivals]", "True" if data["new_arrivals"] else "False"))
    if data.get("on_sale") is not None:
        params.append(("filters[sale]", "True" if data["on_sale"] else "False"))
    if data.get("online_only"):
        params.append(("filters[promotionstatus]", "Online Exclusive"))
    if data.get("onepass") is not None:
        params.append(("filters[eligibleforadvfreedelivery]", "True" if data["onepass"] else "False"))
    if data.get("category") and data["category"] != refs.ALL_PRODUCTS:
        params.append(("filters[group_id]", data["category"]))
    return params


def _has_filters(data):
    return any(data.get(k) not in (None, [], False) for k in
               ("brand", "colour", "age", "price", "min_rating", "delivery", "new_arrivals",
                "on_sale", "online_only", "onepass")) or (data.get("category") not in (None, refs.ALL_PRODUCTS))


def _listing(path, data, extra_params=()):
    payload = fetch_constructor(path, list(extra_params) + _listing_params(data))
    return parsers.parse_listing(payload, data["page"], data["page_size"]), payload


# ---- products/search -------------------------------------------------------------

def _search(**data):
    result, _ = _listing(f"/search/{quote(data['query'], safe='')}", data)
    return {"query": data["query"], **result}


def products_search(**data):
    return cached_call(f"{NS}.search", data, _search, ttl.LISTING_CACHE)


# ---- products/autocomplete ---------------------------------------------------------

def _autocomplete(query, limit):
    payload = fetch_constructor(f"/autocomplete/{quote(query, safe='')}", [
        ("num_results_Products", limit), ("num_results_Search Suggestions", limit),
        ("num_results_Brands", limit), ("num_results_Categories", limit)])
    return {"query": query, **parsers.parse_autocomplete(payload)}


def products_autocomplete(**data):
    return cached_call(f"{NS}.autocomplete", data, _autocomplete, ttl.AUTOCOMPLETE_CACHE)


# ---- the shared product record ---------------------------------------------------

def _fetch_page(product):
    record = parsers.parse_product(fetch_product_page(product), product)
    if record is None:
        raise TargetNotFound(f"product {product} not found")
    return record


def _page(product):
    return cached_call(f"{NS}.product_page", {"product": product}, _fetch_page, ttl.PRODUCT_PAGE_CACHE)


def _fetch_card(product):
    payload = fetch_constructor(f"/search/{quote(product, safe='')}", [("num_results_per_page", 1)])
    return parsers.card_for_code(payload, product)


def _card(product):
    """The Constructor record for a code, or None when the engine has no
    product under it (cached either way)."""
    return cached_call(f"{NS}.product_card", {"product": product}, _fetch_card, ttl.PRODUCT_CARD_CACHE)


def _base_id(product):
    """The base product code (W1521109 / P73493297) reviews are keyed on."""
    if _BASE_CODE_RE.match(product):
        return product
    card = _card(product)
    if card and card["id"]:
        return card["id"]
    page = _page(product)
    for key in ("parent_base_id", "base_id"):
        if page.get(key) and _BASE_CODE_RE.match(page[key]):
            return page[key]
    raise TargetNotFound(f"product {product} not found")


# ---- products/details --------------------------------------------------------------

def _merge_details(page, card):
    """The page record first, then what only the search engine knows (brand,
    quantities, store lists, SKU-level variations, taxonomy). The page's
    manufacturer is the supplier of record, never a stand-in for the brand."""
    card = card or {}
    labels = {**(card.get("labels") or {}), **page["labels"]}
    out = {
        "id": page["id"],
        "base_id": page["base_id"],
        "parent_base_id": page["parent_base_id"] or card.get("id"),
        "name": page["name"],
        "link": page["link"],
        "base_link": card.get("base_link"),
        "brand": card.get("brand"),
        "manufacturer": page["manufacturer"],
        "description": page["description"],
        "extra_info": page["extra_info"],
        "features": page["features"] or card.get("features") or [],
        "materials": page["materials"],
        "care_instructions": page["care_instructions"] or card.get("care_instructions") or [],
        "price": page["price"],
        "deal_description": page["deal_description"],
        "promotions": page["promotions"],
        "availability": page["availability"],
        "is_in_stock": card.get("is_in_stock"),
        "is_coming_soon": page["is_coming_soon"],
        "is_online_only": page["is_online_only"],
        "stock": card.get("stock"),
        "delivery": page["delivery"],
        "rating": page["rating"],
        "popularity": card.get("popularity"),
        "labels": labels,
        "onepass": page["onepass"],
        "product_type": page["product_type"] or card.get("product_type"),
        "gift_card": page["gift_card"],
        "top_level_category": card.get("top_level_category"),
        "google_taxonomy": card.get("google_taxonomy"),
        "category_ids": card.get("category_ids") or [],
        "breadcrumbs": page["breadcrumbs"],
        "online_date": card.get("online_date"),
        "images": page["images"],
        "gallery_images": page["gallery_images"],
        "colour_variants": page["colour_variants"],
        "selected_colour": page["selected_colour"],
        "size_variants": page["size_variants"],
        "selected_size": page["selected_size"],
        "purchasable_variant_codes": page["purchasable_variant_codes"],
        "sizes_by_colour": page["sizes_by_colour"],
        "variations": card.get("variations") or [],
        "has_size_chart": page["has_size_chart"],
        "manuals": page["manuals"],
        "meta": page["meta"],
    }
    return out


def product_details(product):
    """Everything on the product page plus the search engine's record of
    the product (brand, quantities, SKU-level prices and stock)."""
    page = _page(product)
    card = _card(product)
    return _merge_details(page, card)


# ---- products/bulk ---------------------------------------------------------------------

def _one_of_bulk(code):
    try:
        return product_details(code)
    except NotFound as e:
        return {"id": code, "error": str(e) or "not found"}
    except BadRequest as e:
        return {"id": code, "error": f"rejected upstream: {e}"}
    except UpstreamError as e:
        return {"id": code, "error": f"upstream failure: {e}"}


def products_bulk(products):
    with ThreadPoolExecutor(max_workers=min(config.TARGET_AUSTRALIA_WORKERS, len(products))) as pool:
        records = list(pool.map(_one_of_bulk, products))
    return {
        "count": len(records),
        "found_count": sum(1 for r in records if "error" not in r),
        "products": records,
    }


# ---- products/reviews -------------------------------------------------------------------

def _reviews(product, page, page_size, sort):
    base = _base_id(product)
    payload = fetch_reviews(base, refs.REVIEW_SORTS[sort], page_size, (page - 1) * page_size)
    return {"product_code": product, **parsers.parse_reviews(payload, base, page, page_size)}


def product_reviews(**data):
    return cached_call(f"{NS}.reviews", data, _reviews, ttl.REVIEWS_CACHE)


# ---- products/stock ----------------------------------------------------------------------

def _skus_for(code):
    """A code -> the SKUs under it (a SKU is itself; a colour variant its
    sizes; a base product every SKU)."""
    if _SKU_RE.match(code):
        return [code]
    card = _card(code)
    if not card:
        raise TargetNotFound(f"product {code} not found")
    variations = card["variations"]
    if code.upper() != (card["id"] or "").upper():
        narrowed = [v for v in variations if (v["colour_variant_code"] or "").upper() == code.upper()]
        variations = narrowed or variations
    return [v["id"] for v in variations if v["id"]] or ([card["variation_id"]] if card["variation_id"] else [])


def _stock(products, stores, postcode):
    skus, owner = [], {}
    for code in products:
        for sku in _skus_for(code):
            if sku not in owner:
                owner[sku] = code
                skus.append(sku)
    if not skus:
        raise TargetNotFound("no SKUs found for the requested products")
    skus = skus[:MAX_STOCK_SKUS]
    rows = [{"product": owner.get(row["sku"]), **row}
            for row in parsers.parse_stock(fetch_stock(skus, stores, postcode), stores)]
    delivery = None
    if postcode:
        try:
            delivery = parsers.parse_delivery_region(fetch_delivery_region(postcode))
        except NotFound:
            delivery = None
    return {
        "products": products,
        "stores": stores or [],
        "postcode": postcode,
        "delivery_region": delivery,
        "count": len(rows),
        "results": rows,
    }


def products_stock(**data):
    return cached_call(f"{NS}.stock", data, _stock, ttl.STOCK_CACHE)


# ---- categories --------------------------------------------------------------------------

def _category_links():
    entries = parsers.sitemap_categories(parsers.parse_sitemap(fetch_sitemap(refs.SITEMAPS["categories"])))
    return {e["id"]: e["link"] for e in entries}


def _links():
    return cached_call(f"{NS}.category_links", {}, _category_links, ttl.CATEGORY_LINKS_CACHE)


def _count_nodes(node):
    return 1 + sum(_count_nodes(c) for c in node.get("children") or [])


def _categories(category, depth):
    payload = fetch_constructor(f"/browse/group_id/{quote(category)}",
                                [("num_results_per_page", 1), ("fmt_options[groups_max_depth]", depth)])
    tree = parsers.parse_tree(payload, _links(), max_depth=depth)
    if tree is None:
        raise TargetNotFound(f"category {category} not found")
    return {"depth": depth, "categories_count": _count_nodes(tree), "category": tree}


def categories(**data):
    # an empty `category=` loads as None (optional RefField): the whole catalogue
    data["category"] = data.get("category") or refs.ALL_PRODUCTS
    return cached_call(f"{NS}.categories", data, _categories, ttl.CATEGORY_TREE_CACHE)


# ---- categories/products ------------------------------------------------------------------

def _category_products(**data):
    category = data.pop("category")
    result, payload = _listing(f"/browse/group_id/{quote(category)}", data)
    if parsers.listing_is_empty_group(payload) and not _has_filters(data):
        raise TargetNotFound(f"category {category} not found")
    links = _links() if result["category"] else {}
    if result["category"] and links.get(category):
        result["category"]["link"] = links[category]
    for child in result["category_counts"]:
        if links.get(child["id"]):
            child["link"] = links[child["id"]]
    return result


def category_products(**data):
    return cached_call(f"{NS}.category_products", data, _category_products, ttl.LISTING_CACHE)


# ---- brands --------------------------------------------------------------------------------

def _brand_facet():
    """{slug: (display name, product count)} from the search engine's brand
    facet over the whole catalogue (a brand's /b/ slug is its name with
    everything but letters and digits dropped: "Crown & Andrews" ->
    crownandrews)."""
    payload = fetch_constructor(f"/browse/group_id/{refs.ALL_PRODUCTS}", [("num_results_per_page", 1)])
    out = {}
    for facet in ((payload or {}).get("response") or {}).get("facets") or []:
        if facet.get("name") != "brand":
            continue
        for option in facet.get("options") or []:
            name = option.get("value")
            if isinstance(name, str) and name.strip():
                out[refs.brand_slug_of(name)] = (name.strip(), option.get("count"))
    return out


def _brand_directory():
    """Every brand the site lists: the brand sitemap (slugs + links), the
    /brands page (featured names + logos) and the search engine's brand
    facet (names + product counts)."""
    sitemap = parsers.sitemap_slugs(parsers.parse_sitemap(fetch_sitemap(refs.SITEMAPS["brands"])), "/b/")
    featured = parsers.parse_brands_page(fetch_brands_page())
    facet = _brand_facet()
    rows, seen = [], set()

    def row(slug, link):
        info = featured.get(slug) or {}
        name, count = facet.get(slug) or (None, None)
        return {"slug": slug, "name": info.get("name") or name, "link": link, "image": info.get("image"),
                "product_count": count, "is_featured": slug in featured}

    for entry in sitemap:
        slug = entry["slug"].lower()
        if slug not in seen:
            seen.add(slug)
            rows.append(row(slug, entry["link"]))
    for slug in list(featured) + list(facet):
        if slug not in seen:
            seen.add(slug)
            rows.append(row(slug, refs.brand_link(slug)))
    rows.sort(key=lambda r: r["slug"])
    return rows


def _brands(page, page_size):
    rows = cached_call(f"{NS}.brand_directory", {}, _brand_directory, ttl.DIRECTORY_CACHE)
    return _paged(rows, page, page_size)


def brands(**data):
    return cached_call(f"{NS}.brands", data, _brands, ttl.DIRECTORY_CACHE)


def _brand_header(brand):
    """The /b/<slug> page header; a brand the search engine knows but that
    has no landing page gets a minimal header from the directory."""
    try:
        header = parsers.parse_brand_page(fetch_brand_page(brand), brand)
    except NotFound:
        header = None
    if header is None:
        known = next((r for r in cached_call(f"{NS}.brand_directory", {}, _brand_directory, ttl.DIRECTORY_CACHE)
                      if r["slug"] == brand and r["name"]), None)
        if not known:
            raise TargetNotFound(f"brand {brand} not found")
        header = {"slug": brand, "name": known["name"], "link": known["link"], "title": None, "meta_title": None,
                  "meta_description": None, "product_count": known["product_count"], "hero_banner": None,
                  "banners": [], "contextual_links": []}
    return header


def _brand(brand):
    return cached_call(f"{NS}.brand_page", {"brand": brand}, _brand_header, ttl.BRAND_PAGE_CACHE)


def _brand_products(**data):
    slug = data.pop("brand")
    header = _brand(slug)
    result, _ = _listing(f"/browse/brand/{quote(header['name'], safe='')}", data)
    return {"brand": header, **result}


def brand_products(**data):
    return cached_call(f"{NS}.brand_products", data, _brand_products, ttl.LISTING_CACHE)


# ---- collections ---------------------------------------------------------------------------

def _collection_directory():
    rows = parsers.sitemap_slugs(parsers.parse_sitemap(fetch_sitemap(refs.SITEMAPS["collections"])), "/collection/")
    out, seen = [], set()
    for entry in rows:
        slug = entry["slug"].lower()
        if slug in seen:
            continue
        seen.add(slug)
        out.append({"slug": slug, "name": parsers._title_from_slug(slug), "link": entry["link"]})
    return out


def _collections(page, page_size):
    rows = cached_call(f"{NS}.collection_directory", {}, _collection_directory, ttl.DIRECTORY_CACHE)
    return _paged(rows, page, page_size)


def collections(**data):
    return cached_call(f"{NS}.collections", data, _collections, ttl.DIRECTORY_CACHE)


def _collection_products(**data):
    slug = data.pop("collection")
    try:
        result, payload = _listing(f"/browse/collection_id/{quote(slug)}", data)
    except NotFound:   # the engine answers an unknown collection with HTTP 404
        raise TargetNotFound(f"collection {slug} not found")
    if result["collection"] is None and parsers.listing_is_empty_group(payload):
        raise TargetNotFound(f"collection {slug} not found")
    return result


def collection_products(**data):
    return cached_call(f"{NS}.collection_products", data, _collection_products, ttl.LISTING_CACHE)


# ---- stores ----------------------------------------------------------------------------------

def _store_directory():
    return parsers.sitemap_stores(parsers.parse_sitemap(fetch_sitemap(refs.SITEMAPS["stores"])))


def _stores(state, page, page_size):
    rows = cached_call(f"{NS}.store_directory", {}, _store_directory, ttl.DIRECTORY_CACHE)
    if state:
        rows = [r for r in rows if (r["state"] or "").lower() == state.lower()]
    return {"state": state.upper() if state else None, **_paged(rows, page, page_size)}


def stores(**data):
    return cached_call(f"{NS}.stores", data, _stores, ttl.DIRECTORY_CACHE)


def _stores_search(location):
    found = parsers.parse_store_finder(fetch_store_finder(location))
    return {"location": location, "center": found["center"], "count": len(found["stores"]),
            "results": found["stores"]}


def stores_search(**data):
    return cached_call(f"{NS}.stores_search", data, _stores_search, ttl.STORES_CACHE)


def _store_details(store):
    record = parsers.parse_store_page(fetch_store_page(store), store)
    if record is None:
        raise TargetNotFound(f"store {store} not found")
    return record


def store_details(**data):
    return cached_call(f"{NS}.store", data, _store_details, ttl.STORES_CACHE)


# ---- locations/suggestions ------------------------------------------------------------------

def _locations(query):
    try:
        rows = parsers.parse_locations(fetch_locations(query))
    except NotFound:   # the API answers an unmatched term with HTTP 404
        rows = []
    return {"query": query, "count": len(rows), "results": rows}


def locations_suggestions(**data):
    return cached_call(f"{NS}.locations", data, _locations, ttl.LOCATIONS_CACHE)


# ---- sitemaps --------------------------------------------------------------------------------

def _sitemap_entries(type):
    entries = parsers.parse_sitemap(fetch_sitemap(refs.SITEMAPS[type]))
    for entry in entries:
        entry["type"] = type
    return entries


def _entries(kind):
    return cached_call(f"{NS}.sitemap_raw", {"type": kind}, _sitemap_entries, ttl.SITEMAP_CACHE)


def _sitemap_products(page, page_size):
    rows = parsers.sitemap_products(_entries("products"))
    return _paged(rows, page, page_size)


def sitemap_products(**data):
    return cached_call(f"{NS}.sitemap_products", data, _sitemap_products, ttl.SITEMAP_CACHE)


def _sitemap_links(type, page, page_size):
    kinds = list(refs.SITEMAPS) if type == "all" else [type]
    rows = []
    for kind in kinds:
        rows.extend(_entries(kind))
    return {"type": type, **_paged(rows, page, page_size)}


def sitemap_links(**data):
    return cached_call(f"{NS}.sitemap_links", data, _sitemap_links, ttl.SITEMAP_CACHE)
