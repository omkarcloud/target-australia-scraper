"""Reference resolvers + the public <-> upstream value tables for
/target-australia/*.

ONE param per input (tripadvisor QueryOrIdField convention): every id
param also accepts the www.target.com.au link for the same record, and the
resolver hands back the bare id. Resolvers raise ValueError with a
user-facing message (schema_fields.RefField turns it into a 400).

Identifier shapes on target.com.au (research 2026-10-28):
  * product   a SKU (size level, 8 digits: 63681024), a colour variant
              (<base>_<colour>: 1521109_white, 5000322001FL_amber), or a
              base product (W1521109 / P73493297). Every form is served by
              /p/<code> (the slug is optional; the site redirects to the
              canonical /p/<slug>/<code>).
  * category  a W-code (W1852625) at the end of /c/<slug path>/<W-code>;
              AP01 is the "All Products" root of the Constructor tree.
  * brand     the slug of /b/<slug> (bluey, crownandrews) — the brand's
              display name ("Crown & Andrews") is what the search engine
              keys on, read from the brand page (parsers.parse_brand_page).
  * collection the slug of /collection/<slug> (womens-sale), also used by
              /search?collection_id=<slug>.
  * store     a 4-digit store number (5123) inside
              /store/<state>/<slug>/<number>; /store/<number> alone resolves.
"""
import re
from urllib.parse import parse_qs, urlparse

SITE = "https://www.target.com.au"
ASSETS = "https://assets.target.com.au"
ALL_PRODUCTS = "AP01"   # the root group of the search engine's category tree

PRODUCT_CODE_RE = re.compile(r"^[WP]?\d{5,12}[A-Z]{0,3}(?:_[A-Za-z0-9-]{1,40})?$", re.I)
CATEGORY_CODE_RE = re.compile(r"^(?:W\d{4,12}|AP01)$", re.I)
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
STORE_NUMBER_RE = re.compile(r"^\d{3,6}$")
POSTCODE_RE = re.compile(r"^\d{4}$")

_PRODUCT_LINK_RE = re.compile(r"/p/(?:[^/?#]+/)?([^/?#]+)")
_CATEGORY_LINK_RE = re.compile(r"/c/(?:[^?#]*/)?(W\d{4,12})(?:[/?#]|$)", re.I)
_BRAND_LINK_RE = re.compile(r"/b/([^/?#]+)")
_COLLECTION_LINK_RE = re.compile(r"/collection/([^/?#]+)")
_STORE_LINK_RE = re.compile(r"/store/(?:[^/?#]+/)*?(\d{3,6})(?:[/?#]|$)")


def _is_link(value):
    return value.startswith(("http://", "https://", "//", "www.target.com.au", "target.com.au"))


def _as_url(value):
    if value.startswith("//"):
        return "https:" + value
    if value.startswith(("www.", "target.com.au")):
        return "https://" + value
    return value


def _check_host(url):
    host = (urlparse(url).hostname or "").lower()
    if not (host == "target.com.au" or host.endswith(".target.com.au")):
        raise ValueError("Must be a target.com.au link.")
    return url


def resolve_product(value):
    """Bare product code (SKU, colour variant or W/P base) or a target.com.au
    product link -> the code."""
    value = (value or "").strip()
    if _is_link(value):
        url = _check_host(_as_url(value))
        match = _PRODUCT_LINK_RE.search(urlparse(url).path)
        if match and PRODUCT_CODE_RE.match(match.group(1)):
            return _canonical_product_code(match.group(1))
        raise ValueError("Must be a target.com.au product link "
                         "(https://www.target.com.au/p/<slug>/<code>).")
    if PRODUCT_CODE_RE.match(value):
        return _canonical_product_code(value)
    raise ValueError("Must be a product code (63681024, 1521109_white, W1521109) "
                     "or a target.com.au product link.")


def _canonical_product_code(code):
    """W/P prefix upper-cased, the colour suffix kept as the site spells it."""
    head, sep, colour = code.partition("_")
    return head.upper() + sep + colour


def resolve_products(value, max_items):
    """Comma-separated product codes / links -> deduped list of codes."""
    items = []
    for raw in str(value or "").replace("\n", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        code = resolve_product(raw)
        if code not in items:
            items.append(code)
    if not items:
        raise ValueError("Pass at least one product code (e.g. 63681024,73493297).")
    if len(items) > max_items:
        raise ValueError(f"At most {max_items} products per request.")
    return items


def resolve_category(value):
    """W-code, a /c/<slug path>/<W-code> path or link -> the W-code (upper)."""
    value = (value or "").strip()
    if CATEGORY_CODE_RE.match(value):
        return value.upper()
    if _is_link(value):
        url = _check_host(_as_url(value))
        match = _CATEGORY_LINK_RE.search(urlparse(url).path)
        if match:
            return match.group(1).upper()
        raise ValueError("Must be a target.com.au category link "
                         "(https://www.target.com.au/c/<path>/<W-code>).")
    match = _CATEGORY_LINK_RE.search("/c/" + value.strip("/"))
    if match:
        return match.group(1).upper()
    raise ValueError("Must be a category code (W1852625), a category path "
                     "(toys/trading-card-games/W1852625) or a target.com.au category link.")


def resolve_brand(value):
    """Brand slug or a /b/<slug> link -> the slug (lower-case)."""
    value = (value or "").strip()
    if _is_link(value):
        url = _check_host(_as_url(value))
        match = _BRAND_LINK_RE.search(urlparse(url).path)
        if match:
            return match.group(1).lower()
        raise ValueError("Must be a target.com.au brand link (https://www.target.com.au/b/<slug>).")
    if SLUG_RE.match(value) and "/" not in value:
        return value.lower()
    raise ValueError("Must be a brand slug (bluey, lego) or a target.com.au brand link.")


def resolve_collection(value):
    """Collection slug, a /collection/<slug> link or a
    /search?collection_id=<slug> link -> the slug."""
    value = (value or "").strip()
    if _is_link(value):
        url = _check_host(_as_url(value))
        parsed = urlparse(url)
        match = _COLLECTION_LINK_RE.search(parsed.path)
        if match:
            return match.group(1).lower()
        ids = parse_qs(parsed.query).get("collection_id")
        if ids and SLUG_RE.match(ids[0]):
            return ids[0].lower()
        raise ValueError("Must be a target.com.au collection link "
                         "(https://www.target.com.au/collection/<slug>).")
    if SLUG_RE.match(value):
        return value.lower()
    raise ValueError("Must be a collection slug (womens-sale) or a target.com.au collection link.")


def resolve_store(value):
    """Store number or a /store/<state>/<slug>/<number> link -> the number."""
    value = (value or "").strip()
    if STORE_NUMBER_RE.match(value):
        return value
    if _is_link(value):
        url = _check_host(_as_url(value))
        match = _STORE_LINK_RE.search(urlparse(url).path)
        if match:
            return match.group(1)
        raise ValueError("Must be a target.com.au store link "
                         "(https://www.target.com.au/store/<state>/<suburb>/<number>).")
    raise ValueError("Must be a store number (5123) or a target.com.au store link.")


def resolve_stores(value, max_items):
    """Comma-separated store numbers / links -> deduped list of numbers."""
    items = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        number = resolve_store(raw)
        if number not in items:
            items.append(number)
    if len(items) > max_items:
        raise ValueError(f"At most {max_items} stores per request.")
    return items


def resolve_price_range(value):
    """'10-20', '10-', '-20' -> (min, max) floats with None for an open side."""
    value = (value or "").strip().replace("$", "")
    low, sep, high = value.partition("-")
    if not sep and low:
        low, high = low, ""
    try:
        lo = float(low) if low.strip() else None
        hi = float(high) if high.strip() else None
    except ValueError:
        raise ValueError("Must be a price range like 10-20, 50- or -20.")
    if lo is None and hi is None:
        raise ValueError("Must be a price range like 10-20, 50- or -20.")
    if lo is not None and hi is not None and lo > hi:
        raise ValueError("The price range's lower bound must not exceed the upper bound.")
    if (lo is not None and lo < 0) or (hi is not None and hi < 0):
        raise ValueError("Prices must not be negative.")
    return lo, hi


# ---- public <-> upstream value tables -------------------------------------------

# `sort` -> (sort_by, sort_order): the site's own six orderings
# (Constructor sort_options, identical on search / category / brand /
# collection listings).
SORTS = {
    "relevance": ("relevance", "descending"),
    "latest": ("onlinedate", "descending"),
    "rating": ("weightedreview", "descending"),
    "price_asc": ("price", "ascending"),
    "price_desc": ("price", "descending"),
    "brand": ("brand", "ascending"),
}

# `delivery` -> the deliverymodes facet value.
DELIVERY_MODES = {
    "home_delivery": "Home Delivery",
    "click_and_collect": "Click & Collect",
}

# Review `sort` -> Bazaarvoice Sort.
REVIEW_SORTS = {
    "newest": "SubmissionTime:desc",
    "oldest": "SubmissionTime:asc",
    "rating_high": "Rating:desc",
    "rating_low": "Rating:asc",
    "helpful": "TotalPositiveFeedbackCount:desc",
}

# Sitemap `type` -> the child sitemap of /sitemap-index.xml.
SITEMAPS = {
    "products": "/medias/feeds/sitemap/sitemap.xml",
    "categories": "/medias/feeds/sitemap/category-sitemap.xml",
    "brands": "/medias/feeds/sitemap/brand-sitemap.xml",
    "collections": "/medias/feeds/sitemap/collection-sitemap.xml",
    "stores": "/stores-sitemap.xml",
    "content": "/content-sitemap.xml",
}


# ---- links ------------------------------------------------------------------------

def absolute(link):
    """A site-relative href (/p/.., /medias/.., /dam/..) -> absolute https link."""
    if not link or not isinstance(link, str):
        return None
    link = link.strip()
    if not link:
        return None
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("http://") or link.startswith("https://"):
        return link
    if link.startswith("/dam/"):
        return ASSETS + link
    return SITE + (link if link.startswith("/") else "/" + link)


def product_link(code):
    return f"{SITE}/p/{code}"


def category_link(code):
    return f"{SITE}/c/{code}"


def brand_link(slug):
    return f"{SITE}/b/{slug}"


def brand_slug_of(name):
    """A brand's /b/ slug is its display name with everything but letters
    and digits dropped ("Crown & Andrews" -> crownandrews, "3C4G" -> 3c4g)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def collection_link(slug):
    return f"{SITE}/collection/{slug}"


def store_link(number):
    return f"{SITE}/store/{number}"
