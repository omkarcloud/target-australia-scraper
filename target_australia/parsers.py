"""Raw HTML / JSON -> clean dicts for every /target-australia/* endpoint.
Pure functions, no I/O.

Sources (research 2026-10-28):
  * Constructor.io JSON (ac.cnstrc.com): search / category / brand /
    collection listings, the autocomplete, the category tree. One result
    = one base product with its size/colour `variations` (SKU level).
  * Next.js page data (<script id="__NEXT_DATA__">): the product page
    (props.pageProps.product + productMetaData) and the brand page header.
  * Bazaarvoice JSON (api.bazaarvoice.com/data/reviews.json): reviews +
    the product's review statistics.
  * api.target.com.au JSON: stock status, delivery region, postcode lookup.
  * Hybris HTML: the store finder (table rows + the embedded
    store-json-data blob with coordinates) and the store page (schema.org
    microdata + two weeks of trading hours).
  * XML sitemaps.

Value conventions (shared with the other scraper packages):
  * money   numeric amount + "currency": "AUD"
  * dates   ISO: epoch seconds -> "YYYY-MM-DD" (UTC), Bazaarvoice
            timestamps kept as full ISO-8601 (they carry the offset)
  * HTML    descriptions / features arrive as HTML fragments and come back
            as plain text (lists as arrays of items); the site's stray
            "607," line-number artefacts inside them are dropped
  * keys    snake_case; `link` not `url`; booleans as questions
  * null    for anything the site leaves empty ("", 0-rating with no
            reviews, "N/A")

Fixtures captured 2026-10-28 (target_australia/fixtures/): three product
pages (a SKU with a price, a W base with a price range, a sparse P base
with no reviews and one variant), a colour-variant page as full HTML, the
/404 page, a brand page + the "Hmm" error page, Constructor search /
browse / tree / autocomplete payloads (including an unknown group), a
reviews page + an empty one, stock / delivery-region / location JSON, two
store-finder pages, a store page, the /brands page and every sitemap (the
product and category sitemaps truncated to their first entries).
"""
import html as html_lib
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

from bs4 import BeautifulSoup

from target_australia import refs
from target_australia.refs import SITE, absolute

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
_BREAK_RE = re.compile(r"<\s*(?:br\s*/?|/p|/li|/h[1-6]|/div|/tr)\s*>", re.I)
_ARTEFACT_LINE_RE = re.compile(r"^\d{1,5},?$")
_IMAGE_QUERY_RE = re.compile(r"\?io=.*$")
_WS_RE = re.compile(r"\s+")

CURRENCY = "AUD"


# ---- small helpers ----------------------------------------------------------------

def _num(value):
    """int / float / numeric string -> number; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("$", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _int(value):
    number = _num(value)
    return int(number) if isinstance(number, (int, float)) else None


def _str(value):
    """Non-empty stripped string or None."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
    return None


def _date_from_epoch(value):
    number = _num(value)
    if not number:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


def _text(fragment):
    """HTML fragment -> plain text with newlines at block boundaries; the
    site's stray "607," line numbers inside descriptions are dropped."""
    if not fragment or not isinstance(fragment, str):
        return None
    raw = _BREAK_RE.sub("\n", fragment)
    raw = _TAG_RE.sub("", raw)
    raw = html_lib.unescape(raw)
    lines = []
    for line in raw.replace("\r", "").split("\n"):
        line = _WS_RE.sub(" ", line).strip()
        if not line or _ARTEFACT_LINE_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines) or None


def _items(fragment):
    """HTML <li> items (or newline-separated text) -> list of plain strings."""
    if not fragment:
        return []
    if isinstance(fragment, list):
        out = []
        for part in fragment:
            out.extend(_items(part))
        return out
    if not isinstance(fragment, str):
        return []
    items = [_text(m) for m in _LI_RE.findall(fragment)]
    if not items:
        text = _text(fragment)
        items = text.split("\n") if text else []
    return [i for i in items if i]


def _split(value, sep):
    if not isinstance(value, str) or not value.strip():
        return []
    return [part.strip() for part in value.split(sep) if part.strip()]


def _image_list(value):
    """'a|b|c' full-image field -> absolute links without the ?io= transform."""
    return [absolute(_IMAGE_QUERY_RE.sub("", link)) for link in _split(value, "|")]


def _clean_image(value):
    value = _str(value)
    return absolute(_IMAGE_QUERY_RE.sub("", value)) if value else None


def _rating(average, count):
    count = _int(count) or 0
    average = _num(average)
    return {
        "average": round(float(average), 2) if average and count else None,
        "count": count,
    }


# ---- Next.js page data --------------------------------------------------------------

def next_data(html):
    """The page's __NEXT_DATA__ JSON (None when the page has none)."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def _page_props(data):
    return ((data or {}).get("props") or {}).get("pageProps") or {}


# ---- product page -------------------------------------------------------------------

def _money(block):
    """A Price block ({value, currencyIso, ...}) -> numeric amount or None."""
    if not isinstance(block, dict):
        return None
    return _num(block.get("value"))


def _money_range(block):
    if not isinstance(block, dict):
        return None
    low, high = _money(block.get("minPrice")), _money(block.get("maxPrice"))
    if low is None and high is None:
        return None
    return {"min": low, "max": high}


def _colour_variant(entry):
    if not isinstance(entry, dict):
        return None
    return {
        "code": _str(entry.get("productCode")),
        "label": _str(entry.get("label")),
        "link": absolute(entry.get("url")),
        "image": absolute(entry.get("imageUrl")),
        "swatch_image": absolute(entry.get("swatchUrl")),
    }


def _size_variant(entry):
    if not isinstance(entry, dict):
        return None
    return {
        "code": _str(entry.get("productCode")),
        "label": _str(entry.get("label")),
        "link": absolute(entry.get("url")),
        "is_display_only": bool(entry.get("displayOnly")),
    }


def _delivery_mode(block):
    if not isinstance(block, dict):
        return None
    return _bool(block.get("available"))


def parse_product(data, code):
    """props.pageProps of a /p/<code> page -> the product record."""
    props = _page_props(data)
    product = props.get("product") or {}
    if not product or not product.get("code"):
        return None
    meta = props.get("productMetaData") or {}
    rating = meta.get("rating") or {}
    labels = meta.get("labels") or {}
    delivery = product.get("deliveryModes") or {}
    rrp = _money(product.get("recommendedRetailPrice"))
    images = []
    seen = set()
    for image in product.get("images") or []:
        if not isinstance(image, dict):
            continue
        link = absolute(image.get("url"))
        if not link or link in seen:
            continue
        seen.add(link)
        images.append({
            "link": link,
            "type": _str(image.get("imageType")),
            "format": _str(image.get("format")),
            "alt": _str(image.get("altText")),
        })
    gallery = [absolute(g.get("src")) for g in product.get("galleryImages") or []
               if isinstance(g, dict) and g.get("src")]
    breadcrumbs = [{
        "name": _str(b.get("label")),
        "category_id": _str(b.get("categoryCode")),
        "link": absolute(b.get("href")),
    } for b in product.get("breadcrumbs") or [] if isinstance(b, dict)]
    colour_variants = [v for v in map(_colour_variant, product.get("colourVariants") or []) if v]
    size_variants = [v for v in map(_size_variant, product.get("sizeVariants") or []) if v]
    sizes_by_colour = meta.get("colourToSizeCodeMapping")
    manuals = [{
        "name": _str(m.get("name") or m.get("title")),
        "link": absolute(m.get("url") or m.get("href")),
    } for m in (props.get("pageContent") or {}).get("productManual") or [] if isinstance(m, dict)]
    return {
        "id": _str(product.get("code")) or code,
        "base_id": _str(product.get("baseProduct")),
        "parent_base_id": _str(product.get("parentBaseProduct")),
        "name": _str(product.get("name")),
        "link": absolute(product.get("url")) or refs.product_link(code),
        "manufacturer": _str(product.get("manufacturer")),   # supplier of record (NINTENDO AUST P/L), not the brand
        "description": _text(product.get("description")),
        "extra_info": _text(product.get("extraInfo")),
        "features": _items(product.get("productFeatures")),
        "materials": [m for m in map(_text, product.get("materials") or []) if m],
        "care_instructions": [c for c in map(_text, product.get("careInstructions") or []) if c],
        "price": {
            "amount": _money(product.get("price")),
            "range": _money_range(product.get("priceRange")),
            "was": _money(product.get("wasPrice")),
            "was_range": _money_range(product.get("wasPriceRange")),
            "rrp": rrp or None,
            "onepass": _money(product.get("onePassPrice")),
            "onepass_range": _money_range(product.get("onePassPriceRange")),
            "currency": CURRENCY,
        },
        "deal_description": _text(product.get("dealDescription")),
        "promotions": product.get("potentialPromotions") or [],
        "availability": _str(product.get("productAvailability")),
        "is_coming_soon": bool(product.get("comingSoon")),
        "is_online_only": bool(product.get("onlineOnly")),
        "delivery": {
            "home_delivery": _delivery_mode(delivery.get("homeDelivery")),
            "click_and_collect": _delivery_mode(delivery.get("clickAndCollect")),
            "express_delivery": _delivery_mode(delivery.get("expressDelivery")),
            "is_big_and_bulky": bool(product.get("bigAndBulky")),
            "is_click_and_collect_in_store_allowed": bool(product.get("cncIstAllowed")),
            "is_eligible_for_onepass_free_delivery": bool(product.get("eligibleForAdvFreeDelivery")
                                                          or meta.get("eligibleForFreeDelivery")),
        },
        "rating": _rating(rating.get("averageRating") or product.get("averageRating"),
                          rating.get("numberOfReviews")),
        "labels": {
            "is_new": bool(labels.get("new")),
            "is_popular": bool(labels.get("popular")),
            "is_clearance": bool(labels.get("clearance")),
            "is_online_only": bool(labels.get("onlineOnly")),
            "is_online_only_price": bool(labels.get("onlineOnlyPrice")),
            "is_only_at_target": bool(labels.get("onlyAtTarget")),
        },
        "onepass": {
            "badge_text": _str(product.get("onePassBadgeText")),
            "is_promo_available": bool(product.get("onePassPromoAvailable")),
            "is_exclusive": bool(product.get("onePassExclusive")),
            "exclusive_badge_text": _str(product.get("onePassExclusiveBadgeText")),
            "exclusive_start_date": _str(product.get("onePassExclusiveStartDate")),
            "exclusive_end_date": _str(product.get("onePassExclusiveEndDate")),
        },
        "product_type": _str(product.get("productTypeCode")),
        "gift_card": product.get("giftCard"),
        "images": images,
        "gallery_images": gallery,
        "breadcrumbs": breadcrumbs,
        "colour_variants": colour_variants,
        "selected_colour": _colour_variant(product.get("selectedColourVariant")),
        "size_variants": size_variants,
        "selected_size": _size_variant(product.get("selectedSizeVariant")),
        "purchasable_variant_codes": [_str(c) for c in product.get("purchasableVariantCodes") or [] if _str(c)],
        "sizes_by_colour": sizes_by_colour if isinstance(sizes_by_colour, dict) else None,
        "has_size_chart": bool(product.get("sizeChartPageId")),
        "manuals": manuals,
        "meta": {
            "title": _str(product.get("metaName")),
            "description": _str(product.get("metaDescription")),
        },
    }


# ---- Constructor.io listings -----------------------------------------------------------

def _flags(data):
    return {
        "is_on_sale": bool(_num(data.get("wasprice")) and _num(data.get("price"))
                           and _num(data.get("wasprice")) > _num(data.get("price"))),
        "is_clearance": bool(data.get("clearance")),
        "is_new_arrival": bool(data.get("newarrived")),
        "is_online_exclusive": bool(data.get("onlineexclusive")),
        "is_online_only_price": bool(data.get("onlineonlyprice")),
        "is_target_exclusive": bool(data.get("targetexclusive")),
        "is_onepass_exclusive": bool(data.get("onepassexclusive")),
        "is_onepass_early_access": bool(data.get("onepassearlyaccess")),
        "is_eligible_for_onepass_free_delivery": bool(data.get("eligibleforadvfreedelivery")),
        "is_assorted": bool(data.get("assorted")),
        "is_gift_card": bool(data.get("giftcard")),
        "is_bulky": bool(data.get("bulkyproductflag")),
        "is_display_only": bool(data.get("displayonly")),
        "is_essential": bool(data.get("essential")),
        "is_preview": bool(data.get("preview") or data.get("previewflag")),
    }


def _price(data):
    return {
        "amount": _num(data.get("price")),
        "was": _num(data.get("wasprice")),
        "currency": CURRENCY,
    }


def _variation(entry):
    data = (entry or {}).get("data") or {}
    if not data:
        return None
    return {
        "id": _str(data.get("variation_id") or data.get("sizevariantcode")),
        "name": _str(entry.get("value")),
        "link": absolute(data.get("url")),
        "colour": _str(data.get("swatchcolour")),
        "colour_variant_code": _str(data.get("colourvariantcode")),
        "colour_variant_link": absolute(data.get("colourvarianturl")),
        "price": _price(data),
        "is_in_stock": _bool(data.get("instock")),
        "availability": _str(data.get("productavailability")),
        "display_type": _str(data.get("productdisplaytype")),
        "online_quantity": _int(data.get("availableonlineqty")),
        "store_quantity": _int(data.get("availablestoreqty")),
        "rating": _rating(data.get("reviewavgrating"), data.get("numberofreviews")),
        "image": _clean_image(data.get("image_url")),
        "images": _image_list(data.get("fullimage")),
        "online_date": _date_from_epoch(data.get("onlinedate")),
        "labels": _flags(data),
    }


def parse_result(item):
    """One Constructor result -> a product card (base product + its
    size/colour variations)."""
    data = (item or {}).get("data") or {}
    if not data:
        return None
    variations = [v for v in map(_variation, item.get("variations") or []) if v]
    return {
        "id": _str(data.get("id")),
        "name": _str(item.get("value")),
        "link": absolute(data.get("url")),
        "base_link": absolute(data.get("baseproducturl")),
        "brand": _str(data.get("brand")),
        "description": _text(data.get("description")),
        "features": _items(data.get("features")),
        "care_instructions": _items(data.get("careinstructions")),
        "price": _price(data),
        "is_in_stock": _bool(data.get("instock")),
        "availability": _str(data.get("productavailability")),
        "display_type": _str(data.get("productdisplaytype")),
        "stock": {
            "online_quantity": _int(data.get("availableonlineqty")),
            "store_quantity": _int(data.get("availablestoreqty")),
            "delivery_stock_locations": _split(data.get("delstockpot"), "|"),
            "in_store_stock_locations": _split(data.get("instorestockpot"), "|"),
        },
        "rating": _rating(data.get("reviewavgrating"), data.get("numberofreviews")),
        "popularity": _int(data.get("totalinterest")),
        "colour": _str(data.get("swatchcolour")),
        "colour_variant_code": _str(data.get("colourvariantcode")),
        "size_variant_code": _str(data.get("sizevariantcode")),
        "variation_id": _str(data.get("variation_id")),
        "labels": _flags(data),
        "product_type": _str(data.get("ptypecode")),
        "top_level_category": _str(data.get("toplevelcategory")),
        "google_taxonomy": _str(data.get("googletaxanomy")),
        "category_ids": [c for c in data.get("group_ids") or [] if isinstance(c, str)],
        "online_date": _date_from_epoch(data.get("onlinedate")),
        "image": _clean_image(data.get("image_url")),
        "images": _image_list(data.get("fullimage")),
        "variations": variations,
        "variations_count": len(variations),
        "matched_terms": [t for t in item.get("matched_terms") or [] if isinstance(t, str)],
    }


def _facet_option(option):
    value = option.get("value")
    return {
        "value": _str(value) if not isinstance(value, (int, float)) else value,
        "display_name": _str(option.get("display_name")),
        "count": _int(option.get("count")),
        "range": option.get("range") if isinstance(option.get("range"), list) else None,
        "is_selected": option.get("status") == "selected",
    }


def _facets(payload_response):
    facets = []
    for facet in payload_response.get("facets") or []:
        if not isinstance(facet, dict) or facet.get("hidden"):
            continue
        facets.append({
            "name": _str(facet.get("name")),
            "display_name": _str(facet.get("display_name")),
            "type": _str(facet.get("type")),
            "options": [_facet_option(o) for o in facet.get("options") or [] if isinstance(o, dict)],
        })
    return facets


_SORT_NAMES = {v: k for k, v in refs.SORTS.items()}


def _sort_options(payload_response):
    out = []
    for option in payload_response.get("sort_options") or []:
        if not isinstance(option, dict) or option.get("hidden"):
            continue
        key = (option.get("sort_by"), option.get("sort_order"))
        out.append({
            "value": _SORT_NAMES.get(key) or option.get("sort_by"),
            "display_name": _str(option.get("display_name")),
            "is_selected": option.get("status") == "selected",
        })
    return out


def _group_node(group, links=None, depth=0, max_depth=None):
    if not isinstance(group, dict):
        return None
    group_id = _str(group.get("group_id"))
    node = {
        "id": group_id,
        "name": _str(group.get("display_name")),
        "product_count": _int(group.get("count")),
        "link": (links or {}).get(group_id) or (refs.category_link(group_id) if group_id and group_id != "AP01" else None),
    }
    if max_depth is None or depth < max_depth:
        node["children"] = [c for c in (_group_node(child, links, depth + 1, max_depth)
                                        for child in group.get("children") or []) if c]
    return node


def _category_counts(payload_response):
    """The browse group's children with their result counts (one level)."""
    groups = payload_response.get("groups") or []
    if not groups or not isinstance(groups[0], dict):
        return []
    root = groups[0]
    return [_group_node(child, max_depth=0) for child in root.get("children") or [] if isinstance(child, dict)]


def _current_group(payload_response):
    groups = payload_response.get("groups") or []
    if not groups or not isinstance(groups[0], dict):
        return None
    root = groups[0]
    parents = [{"id": _str(p.get("group_id")), "name": _str(p.get("display_name")),
                "link": refs.category_link(p.get("group_id")) if p.get("group_id") and p.get("group_id") != "AP01" else None}
               for p in root.get("parents") or [] if isinstance(p, dict)]
    return {
        "id": _str(root.get("group_id")),
        "name": _str(root.get("display_name")),
        "product_count": _int(root.get("count")),
        "link": refs.category_link(root.get("group_id")) if root.get("group_id") and root.get("group_id") != "AP01" else None,
        "parents": parents,
    }


def _collection(payload_response):
    block = payload_response.get("collection")
    if not isinstance(block, dict):
        return None
    data = block.get("data") or {}
    return {
        "id": _str(block.get("id")),
        "name": _str(block.get("display_name")),
        "link": refs.collection_link(block.get("id")) if block.get("id") else None,
        "meta_title": _str(data.get("meta_title")),
        "meta_description": _str(data.get("meta_description")),
        "description": _text(data.get("seo_above_copy")),
        "description_below": _text(data.get("seo_below_copy")),
        "breadcrumbs": [{"name": _str(b.get("name")), "link": absolute(b.get("url")), "level": _int(b.get("level"))}
                        for b in data.get("breadcrumbs") or [] if isinstance(b, dict)],
        "start_time": _str(block.get("start_time")),
        "end_time": _str(block.get("end_time")),
    }


def parse_listing(payload, page, page_size):
    """A Constructor search / browse payload -> results + facets + sort
    options + the category breakdown + a pagination block."""
    response = (payload or {}).get("response") or {}
    results = [r for r in map(parse_result, response.get("results") or []) if r]
    total = _int(response.get("total_num_results")) or 0
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "results": results,
        "facets": _facets(response),
        "sort_options": _sort_options(response),
        "category": _current_group(response),
        "category_counts": _category_counts(response),
        "collection": _collection(response),
        "related_searches": [s for s in (_str(s.get("query") if isinstance(s, dict) else s)
                                         for s in response.get("related_searches") or []) if s],
        "related_browse_pages": response.get("related_browse_pages") or [],
        "pagination": {
            "page": page,
            "items_per_page": page_size,
            "total_pages": total_pages,
            "total_count": total,
        },
    }


def card_for_code(payload, code):
    """The Constructor result that IS the product `code` (a search for a
    code answers exactly that base product; an unknown code answers fuzzy
    matches): the parsed card when the base id, a colour variant code or a
    SKU of the first result equals `code`, else None."""
    response = (payload or {}).get("response") or {}
    results = response.get("results") or []
    if not results:
        return None
    card = parse_result(results[0])
    if not card:
        return None
    wanted = (code or "").upper()
    codes = {(card["id"] or "").upper(), (card["colour_variant_code"] or "").upper(),
             (card["size_variant_code"] or "").upper(), (card["variation_id"] or "").upper()}
    for variation in card["variations"]:
        codes.update({(variation["id"] or "").upper(), (variation["colour_variant_code"] or "").upper()})
    return card if wanted in codes else None


def listing_is_empty_group(payload):
    """True when a browse answered with no results AND no group at all
    (an unknown category / brand / collection)."""
    response = (payload or {}).get("response") or {}
    if _int(response.get("total_num_results")):
        return False
    groups = response.get("groups") or []
    return not groups and not response.get("collection")


def parse_tree(payload, links=None, max_depth=None):
    """A browse payload asked with fmt_options[groups_max_depth] -> the
    category tree rooted at the browsed group. `links` maps W-code -> the
    canonical /c/<path>/<W-code> link (from the category sitemap)."""
    response = (payload or {}).get("response") or {}
    groups = response.get("groups") or []
    if not groups:
        return None
    return _group_node(groups[0], links, 0, max_depth)


def parse_autocomplete(payload):
    sections = (payload or {}).get("sections") or {}
    totals = (payload or {}).get("total_num_results_per_section") or {}
    suggestions = []
    for entry in sections.get("Search Suggestions") or []:
        data = entry.get("data") or {}
        suggestions.append({
            "term": _str(entry.get("value")),
            "link": f"{SITE}/search?text={quote(entry.get('value') or '', safe='')}" if entry.get("value") else None,
            "categories": [{
                "id": _str(g.get("group_id")),
                "name": _str(g.get("display_name")),
                "path": [_str(p.get("display_name")) for p in g.get("path_list") or [] if isinstance(p, dict)],
                "link": refs.category_link(g.get("group_id")) if g.get("group_id") else None,
            } for g in data.get("groups") or [] if isinstance(g, dict)],
            "matched_terms": [t for t in entry.get("matched_terms") or [] if isinstance(t, str)],
        })
    products = []
    for entry in sections.get("Products") or []:
        data = entry.get("data") or {}
        products.append({
            "id": _str(data.get("id")),
            "name": _str(entry.get("value")),
            "link": absolute(data.get("url")),
            "brand": _str(data.get("brand")),
            "price": _price(data),
            "is_in_stock": _bool(data.get("instock")),
            "rating": _rating(data.get("reviewavgrating"), data.get("numberofreviews")),
            "image": _clean_image(data.get("image_url")),
            "labels": _flags(data),
        })
    simple = {}
    for section in ("Brands", "Categories"):
        simple[section.lower()] = [{
            "id": _str((entry.get("data") or {}).get("id")),
            "name": _str(entry.get("value")),
        } for entry in sections.get(section) or [] if isinstance(entry, dict)]
    return {
        "suggestions": suggestions,
        "products": products,
        "brands": simple["brands"],
        "categories": simple["categories"],
        "totals": {
            "suggestions": _int(totals.get("Search Suggestions")),
            "products": _int(totals.get("Products")),
            "brands": _int(totals.get("Brands")),
            "categories": _int(totals.get("Categories")),
        },
    }


# ---- brand page -----------------------------------------------------------------------

def parse_brand_page(data, slug):
    """props.pageProps of a /b/<slug> page -> the brand header (name,
    titles, banners); None when the page is not a brand page."""
    props = _page_props(data)
    name = _str(props.get("brandName"))
    if not name:
        return None
    hero = props.get("smartHeroBanner") or {}
    carousel = props.get("bannerCarousel") or {}
    metadata = props.get("metadata") or {}
    return {
        "slug": _str(props.get("brandCode")) or slug,
        "name": name,
        "link": refs.brand_link(slug),
        "title": _str(props.get("brandPageTitle")) or _str(props.get("title")),
        "meta_title": _str(props.get("metaPageTitle")),
        "meta_description": _str(props.get("metaDescription")),
        "product_count": _int(metadata.get("totalNumProducts")),
        "hero_banner": {
            "alt": _str(hero.get("altText")),
            "image": absolute(hero.get("imageUrl")),
            "mobile_image": absolute(hero.get("mobileImageUrl")),
            "link": absolute(hero.get("linkUrl")),
        } if hero else None,
        "banners": [{
            "text": _str(b.get("linkText")),
            "link": absolute(b.get("href")),
            "image": absolute(b.get("imageUrl")),
        } for b in carousel.get("banners") or [] if isinstance(b, dict)],
        "contextual_links": _links_in(props.get("contextualLinks")),
    }


_ANCHOR_RE = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S | re.I)
_TITLE_ATTR_RE = re.compile(r'title="([^"]*)"', re.I)


def _links_in(fragment):
    """Anchors of an HTML fragment -> [{name, link}] (deduped by link)."""
    out, seen = [], set()
    for href, inner in _ANCHOR_RE.findall(fragment or ""):
        link = absolute(html_lib.unescape(href))
        name = _text(inner)
        if not link or link in seen:
            continue
        seen.add(link)
        out.append({"name": name, "link": link})
    return out


def parse_brands_page(html):
    """/brands -> {slug: {name, image}} for every /b/<slug> link it shows."""
    found = {}
    for match in re.finditer(r'<a\s[^>]*href="/b/([^"/?#]+)[^"]*"([^>]*)>(.*?)</a>', html or "", re.S | re.I):
        slug, attrs, inner = match.group(1).lower(), match.group(2), match.group(3)
        title = _TITLE_ATTR_RE.search(attrs)
        name = html_lib.unescape(title.group(1)).strip() if title else None
        image = re.search(r'<img[^>]+src="([^"]+)"', inner, re.I)
        if not name:
            img_title = re.search(r'<img[^>]+title="([^"]+)"', inner, re.I)
            name = html_lib.unescape(img_title.group(1)).strip() if img_title else (_text(inner) or None)
        if name and name.lower().startswith("shop "):
            name = name[5:].strip()
        entry = found.setdefault(slug, {"name": None, "image": None})
        if name and not entry["name"]:
            entry["name"] = name
        if image and not entry["image"]:
            entry["image"] = absolute(html_lib.unescape(image.group(1)))
    return found


# ---- reviews --------------------------------------------------------------------------

def _review(entry, photo_sizes=("normal", "large", "thumbnail")):
    badges = entry.get("Badges") or {}
    photos = []
    for photo in entry.get("Photos") or []:
        sizes = (photo or {}).get("Sizes") or {}
        link = None
        for size in photo_sizes:
            link = (sizes.get(size) or {}).get("Url")
            if link:
                break
        if link:
            photos.append({"link": link, "caption": _str(photo.get("Caption"))})
    context = {}
    for key, value in (entry.get("ContextDataValues") or {}).items():
        if isinstance(value, dict):
            context[key] = _str(value.get("ValueLabel") or value.get("Value"))
    secondary = {}
    for key, value in (entry.get("SecondaryRatings") or {}).items():
        if isinstance(value, dict):
            secondary[key] = {
                "label": _str(value.get("Label")),
                "value": _num(value.get("Value")),
                "value_label": _str(value.get("ValueLabel")),
                "range": _num(value.get("ValueRange")),
            }
    tags = {}
    for key, value in (entry.get("TagDimensions") or {}).items():
        if isinstance(value, dict):
            tags[key] = value.get("Values") or []
    responses = [{
        "department": _str(r.get("Department")),
        "name": _str(r.get("Name")),
        "text": _str(r.get("Response")),
        "date": _str(r.get("Date")),
    } for r in entry.get("ClientResponses") or [] if isinstance(r, dict)]
    return {
        "id": _str(entry.get("Id")),
        "product_id": _str(entry.get("ProductId")),
        "product_name": _str(entry.get("OriginalProductName")),
        "rating": _num(entry.get("Rating")),
        "rating_range": _num(entry.get("RatingRange")),
        "title": _str(entry.get("Title")),
        "text": _str(entry.get("ReviewText")),
        "pros": _str(entry.get("Pros")),
        "cons": _str(entry.get("Cons")),
        "is_recommended": _bool(entry.get("IsRecommended")),
        "is_ratings_only": bool(entry.get("IsRatingsOnly")),
        "is_featured": bool(entry.get("IsFeatured")),
        "is_syndicated": bool(entry.get("IsSyndicated")),
        "is_verified_purchaser": "verifiedPurchaser" in badges,
        "badges": sorted(badges.keys()),
        "author": {
            "id": _str(entry.get("AuthorId")),
            "nickname": _str(entry.get("UserNickname")),
            "location": _str(entry.get("UserLocation")),
        },
        "submitted_at": _str(entry.get("SubmissionTime")),
        "last_modified_at": _str(entry.get("LastModificationTime")),
        "locale": _str(entry.get("ContentLocale")),
        "helpfulness": {
            "score": _num(entry.get("Helpfulness")),
            "positive_votes": _int(entry.get("TotalPositiveFeedbackCount")) or 0,
            "negative_votes": _int(entry.get("TotalNegativeFeedbackCount")) or 0,
            "total_votes": _int(entry.get("TotalFeedbackCount")) or 0,
        },
        "comments_count": _int(entry.get("TotalCommentCount")) or 0,
        "photos": photos,
        "videos": [{"link": v.get("VideoUrl"), "thumbnail": v.get("VideoThumbnailUrl"), "caption": _str(v.get("Caption"))}
                   for v in entry.get("Videos") or [] if isinstance(v, dict) and v.get("VideoUrl")],
        "context": context,
        "secondary_ratings": secondary,
        "tags": tags,
        "client_responses": responses,
    }


def _review_stats(stats):
    if not isinstance(stats, dict) or not stats:
        return None
    distribution = {}
    for row in stats.get("RatingDistribution") or []:
        if isinstance(row, dict) and row.get("RatingValue") is not None:
            distribution[str(row["RatingValue"])] = _int(row.get("Count")) or 0
    for star in "12345":
        distribution.setdefault(star, 0)
    context = {}
    for key, block in (stats.get("ContextDataDistribution") or {}).items():
        if isinstance(block, dict):
            context[key] = {
                "label": _str(block.get("Label")),
                "values": [{"value": _str(v.get("ValueLabel") or v.get("Value")), "count": _int(v.get("Count"))}
                           for v in block.get("Values") or [] if isinstance(v, dict)],
            }
    secondary = {}
    for key, block in (stats.get("SecondaryRatingsAverages") or {}).items():
        if isinstance(block, dict):
            secondary[key] = {"label": _str(block.get("Label")), "average": _num(block.get("AverageRating")),
                              "range": _num(block.get("ValueRange"))}
    average = _num(stats.get("AverageOverallRating"))
    return {
        "average": round(float(average), 2) if average else None,
        "count": _int(stats.get("TotalReviewCount")) or 0,
        "ratings_only_count": _int(stats.get("RatingsOnlyReviewCount")) or 0,
        "recommended_count": _int(stats.get("RecommendedCount")),
        "not_recommended_count": _int(stats.get("NotRecommendedCount")),
        "helpful_votes": _int(stats.get("HelpfulVoteCount")),
        "not_helpful_votes": _int(stats.get("NotHelpfulVoteCount")),
        "photos_count": _int(stats.get("TotalPhotoCount")) or 0,
        "videos_count": _int(stats.get("TotalVideoCount")) or 0,
        "distribution": {k: distribution[k] for k in sorted(distribution, reverse=True)},
        "first_submitted_at": _str(stats.get("FirstSubmissionTime")),
        "last_submitted_at": _str(stats.get("LastSubmissionTime")),
        "secondary_ratings": secondary,
        "context": context,
    }


def parse_reviews(payload, product_id, page, page_size):
    """A Bazaarvoice reviews.json payload -> reviews + the product's stats."""
    payload = payload or {}
    results = [_review(r) for r in payload.get("Results") or [] if isinstance(r, dict)]
    products = ((payload.get("Includes") or {}).get("Products") or {})
    product = products.get(product_id) or (next(iter(products.values())) if products else {}) or {}
    stats = _review_stats(product.get("ReviewStatistics"))
    total = _int(payload.get("TotalResults")) or 0
    brand = product.get("Brand") or {}
    return {
        "product": {
            "id": _str(product.get("Id")) or product_id,
            "name": _str(product.get("Name")),
            "link": _str(product.get("ProductPageUrl")) or refs.product_link(product_id),
            "brand": _str(brand.get("Name")) if isinstance(brand, dict) else None,
            "image": _str(product.get("ImageUrl")),
            "category_id": _str(product.get("CategoryId")),
            "description": _text(product.get("Description")),
            "is_active": _bool(product.get("Active")),
        } if product else {"id": product_id, "name": None, "link": refs.product_link(product_id),
                           "brand": None, "image": None, "category_id": None, "description": None,
                           "is_active": None},
        "statistics": stats,
        "reviews": results,
        "pagination": {
            "page": page,
            "items_per_page": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size else 0,
            "total_count": total,
        },
    }


# ---- stock / delivery / locations ----------------------------------------------------

_STOCK_STATUS = {"instock": "in_stock", "lowstock": "low_stock", "outofstock": "out_of_stock"}


def _stock_status(value):
    text = _str(value)
    if not text:
        return None
    return _STOCK_STATUS.get(text.lower(), text)


def parse_stock(payload, requested_stores=None):
    """/lz3inventory/stockStatus JSON -> one row per SKU."""
    rows = []
    for entry in (payload or {}).get("stock") or []:
        if not isinstance(entry, dict):
            continue
        stores = {}
        for number, status in (entry.get("storeSoh") or {}).items():
            stores[str(number)] = _stock_status(status)
        for number in requested_stores or []:
            stores.setdefault(str(number), None)
        rows.append({
            "sku": _str(entry.get("sku")),
            "overall": _stock_status(entry.get("ats")),
            "home_delivery": _stock_status(entry.get("hd")),
            "click_and_collect": _stock_status(entry.get("cc")),
            "all_stores": _stock_status(entry.get("consolidated_stores_soh")),
            "stores": stores,
        })
    return rows


def parse_delivery_region(payload):
    payload = payload or {}
    if not payload:
        return None
    return {
        "location_group": _str(payload.get("locationGroup")),
        "is_home_delivery_available": _bool(payload.get("available")),
        "region_id": _str(payload.get("regionId")),
    }


def parse_locations(payload):
    """/location/search JSON -> [{postcode, suburb, state}] (encGeo, the
    site's opaque geo token, is dropped)."""
    out = []
    for entry in (payload or {}).get("results") or []:
        if not isinstance(entry, dict):
            continue
        postcode = entry.get("postalCode")
        state = _str(entry.get("state"))
        out.append({
            "postcode": f"{int(postcode):04d}" if _int(postcode) is not None else _str(postcode),
            "suburb": _str(entry.get("suburb")),
            "state": state.upper() if state else None,
        })
    return out


# ---- stores (Hybris HTML) --------------------------------------------------------------

_STORE_LINK_RE = re.compile(r"/store/([a-z]+)/([^/]+)/(\d+)")
_STORE_JSON_RE = re.compile(r'id="store-json-data"[^>]*>\s*(\{.*?\})\s*</script>', re.S)
_DISTANCE_RE = re.compile(r"([\d.]+)\s*km", re.I)
_PHONE_RE = re.compile(r"(?:\(0\d\)\s*\d{4}\s*\d{4}|0\d[\d\s]{8,10}\d|1[38]00[\d\s]{6,9})")


def _soup(html):
    return BeautifulSoup(html or "", "lxml")


def _store_from_link(href):
    match = _STORE_LINK_RE.search(href or "")
    if not match:
        return None, None, None
    return match.group(3), match.group(1).upper(), match.group(2)


def _address_block(node):
    """A node with schema.org address spans -> {street, suburb, state, postcode, venue}."""
    street_node = node.find(attrs={"itemprop": "streetAddress"})
    venue = None
    street = None
    if street_node:
        strong = street_node.find("strong")
        venue = strong.get_text(" ", strip=True) if strong else None
        lines = [t.strip() for t in street_node.get_text("\n").split("\n") if t.strip()]
        if venue and venue in lines:
            lines.remove(venue)
        street = ", ".join(lines) or None

    def prop(name):
        found = node.find(attrs={"itemprop": name})
        return found.get_text(" ", strip=True) if found else None

    return {
        "venue": venue,
        "street": street,
        "suburb": prop("addressLocality"),
        "state": prop("addressRegion"),
        "postcode": prop("postalCode"),
    }


def _coordinates(html):
    """{name: (lat, lng)} from the store-finder's embedded JSON blob."""
    match = _STORE_JSON_RE.search(html or "")
    if not match:
        return {}, {}
    try:
        blob = json.loads(match.group(1))
    except ValueError:
        return {}, {}
    out = {}
    for loc in blob.get("locations") or []:
        if isinstance(loc, dict) and loc.get("name"):
            content = loc.get("content") or ""
            number = _STORE_LINK_RE.search(content)
            key = number.group(3) if number else loc["name"]
            out[key] = (_num(loc.get("lat")), _num(loc.get("lng")))
    return out, (blob.get("center") or {})


def parse_store_finder(html):
    """/store-finder?q=.. -> {"center": {lat, lng}, "stores": [...]} ordered
    by distance like the page."""
    soup = _soup(html)
    by_number, center = _coordinates(html)
    stores = []
    table = soup.find("table", class_="store-locator")
    for row in (table.find_all("tr") if table else []):
        name_cell = row.find("td", class_="storefinder-name")
        if not name_cell:
            continue
        link = name_cell.find("a")
        href = link.get("href") if link else None
        number, state, slug = _store_from_link(href)
        distance_cell = row.find("td", class_="store-distance")
        distance = None
        if distance_cell:
            match = _DISTANCE_RE.search(distance_cell.get_text(" ", strip=True))
            distance = _num(match.group(1)) if match else None
        address_cell = row.find("td", attrs={"headers": "store-address"})
        address = _address_block(address_cell) if address_cell else {
            "venue": None, "street": None, "suburb": None, "state": None, "postcode": None}
        phone = None
        if address_cell:
            tail = address_cell.get_text(" ", strip=True)
            match = _PHONE_RE.search(tail.rsplit(address["postcode"] or "", 1)[-1] if address["postcode"] else tail)
            phone = match.group(0).strip() if match else None
        lat, lng = by_number.get(number) or by_number.get(link.get_text(strip=True) if link else "") or (None, None)
        stores.append({
            "number": number,
            "name": link.get_text(" ", strip=True) if link else None,
            "link": absolute(href),
            "distance_km": distance,
            "address": address,
            "phone": phone,
            "latitude": lat,
            "longitude": lng,
        })
    return {
        "center": {"latitude": _num(center.get("lat")), "longitude": _num(center.get("lng"))} if center else None,
        "stores": stores,
    }


def _hours_week(block):
    title = block.find("h5")
    days = []
    for dt in block.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        text = dd.get_text(" ", strip=True) if dd else None
        text = html_lib.unescape(text).replace("\u2013", "-") if text else None
        if text and "-" in text:
            opens, _, closes = [p.strip() for p in text.partition("-")]
        else:
            opens, closes = None, None
        days.append({
            "day": dt.get_text(" ", strip=True),
            "hours": text or None,
            "opens": opens or None,
            "closes": closes or None,
            "is_closed": bool(text) and "closed" in text.lower(),
        })
    return {
        "week": title.get_text(" ", strip=True).replace("\u2013", "-") if title else None,
        "days": days,
    }


def parse_store_page(html, number):
    """/store/<state>/<slug>/<number> -> the store record; None when the
    page carries no store card (the 404 page)."""
    soup = _soup(html)
    card = soup.find("div", class_="store-contact-card")
    if not card:
        return None
    heading = card.find(class_="store-heading")
    name = heading.get_text(" ", strip=True) if heading else None
    if name and "\u2013" in name:
        name = name.split("\u2013", 1)[1].strip()
    elif name and " - " in name:
        name = name.split(" - ", 1)[1].strip()
    phone_node = card.find(attrs={"itemprop": "telephone"})
    canonical = soup.find("link", attrs={"rel": "canonical"})
    link = canonical.get("href") if canonical else None
    if not link:
        anchor = soup.find("a", href=_STORE_LINK_RE)
        link = anchor.get("href") if anchor else None
    _, state, slug = _store_from_link(link)
    map_node = soup.find(class_="store-map")
    hours = [_hours_week(b) for b in soup.select("div.store-hours div.hours-week")]
    return {
        "number": number,
        "name": name,
        "slug": slug,
        "link": absolute(link) if link else refs.store_link(number),
        "address": _address_block(card),
        "phone": phone_node.get_text(" ", strip=True) if phone_node else None,
        "latitude": _num(map_node.get("data-lat")) if map_node else None,
        "longitude": _num(map_node.get("data-lng")) if map_node else None,
        "trading_hours": hours,
        "state": state or (_address_block(card).get("state")),
    }


# ---- sitemaps -------------------------------------------------------------------------

_URL_BLOCK_RE = re.compile(r"<url>(.*?)</url>", re.S)
_SITEMAP_BLOCK_RE = re.compile(r"<sitemap>(.*?)</sitemap>", re.S)
_LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)
_LASTMOD_RE = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.S)
_CHANGEFREQ_RE = re.compile(r"<changefreq>\s*(.*?)\s*</changefreq>", re.S)
_PRIORITY_RE = re.compile(r"<priority>\s*(.*?)\s*</priority>", re.S)
_PRODUCT_PATH_RE = re.compile(r"/p/(?:([^/?#]+)/)?([^/?#]+)$")
_CATEGORY_PATH_RE = re.compile(r"/c/(.+?)/(W\d+)$")
_STORE_PATH_RE = re.compile(r"/store/([a-z]+)/([^/]+)/(\d+)$")


def _first(regex, block):
    match = regex.search(block)
    return html_lib.unescape(match.group(1)).strip() if match else None


def parse_sitemap_index(xml):
    out = []
    for block in _SITEMAP_BLOCK_RE.findall(xml or ""):
        loc = _first(_LOC_RE, block)
        if loc:
            out.append({"link": loc, "last_modified": _first(_LASTMOD_RE, block)})
    return out


def parse_sitemap(xml):
    """A urlset sitemap -> [{link, last_modified, change_frequency, priority}]."""
    out = []
    for block in _URL_BLOCK_RE.findall(xml or ""):
        loc = _first(_LOC_RE, block)
        if not loc:
            continue
        out.append({
            "link": loc,
            "last_modified": _first(_LASTMOD_RE, block),
            "change_frequency": _first(_CHANGEFREQ_RE, block),
            "priority": _num(_first(_PRIORITY_RE, block)),
        })
    return out


def sitemap_products(entries):
    out = []
    for entry in entries:
        match = _PRODUCT_PATH_RE.search(entry["link"])
        if not match:
            continue
        out.append({"id": match.group(2), "slug": match.group(1), "link": entry["link"],
                    "last_modified": entry.get("last_modified")})
    return out


def sitemap_categories(entries):
    out = []
    for entry in entries:
        match = _CATEGORY_PATH_RE.search(entry["link"])
        if not match:
            continue
        path = match.group(1)
        out.append({"id": match.group(2), "path": path, "name": _title_from_slug(path.rsplit("/", 1)[-1]),
                    "link": entry["link"], "last_modified": entry.get("last_modified")})
    return out


def sitemap_slugs(entries, marker):
    """Entries of /b/<slug> or /collection/<slug> -> [{slug, link}]."""
    out = []
    for entry in entries:
        link = entry["link"]
        if marker not in link:
            continue
        slug = link.split(marker, 1)[1].strip("/").split("/")[0].split("?")[0]
        if slug:
            out.append({"slug": slug, "link": link, "last_modified": entry.get("last_modified")})
    return out


def sitemap_stores(entries):
    out = []
    for entry in entries:
        match = _STORE_PATH_RE.search(entry["link"])
        if not match:
            continue
        out.append({"number": match.group(3), "state": match.group(1).upper(), "slug": match.group(2),
                    "name": _title_from_slug(match.group(2)), "link": entry["link"],
                    "last_modified": entry.get("last_modified")})
    return out


def _title_from_slug(slug):
    if not slug:
        return None
    return " ".join(w.capitalize() if w not in ("and", "of", "the") else w for w in slug.replace("-", " ").split()) or None
