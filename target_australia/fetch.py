"""Target Australia transport: plain curl_cffi with browser-impersonated
TLS. No browser, no cookies, no login. Egress: the pod's own IP
(config.target_australia_proxy(), knob TARGET_AUSTRALIA_EXIT = direct),
with an Australian residential exit for TARGET_AUSTRALIA_BLOCK_COOLDOWN
seconds after a block (pod probe 2026-10-28: the pod's own Google Cloud
IP is 200 on every surface; Akamai refuses www.target.com.au per IP on
1 of 2 datacenter exits; AU residential 2/2 — table in config.py). A
retryable failure drops the thread's session, so the retry rides a fresh
exit.

Five upstream hosts, all open to curl_cffi (research 2026-10-28):

  * www.target.com.au     Next.js pages (product /p/<code>, brand /b/<slug>)
    whose data sits in <script id="__NEXT_DATA__">; two legacy Hybris pages
    (store finder, store page, server-rendered HTML); the XML sitemaps.
    Unknown product / collection / store -> real HTTP 404; unknown category
    / brand -> HTTP 500 with the site's "Hmm... That's not supposed to
    happen" page (mapped to NotFound here); a brand slug the site has
    re-pointed (/b/lego -> the /lego shop) 301s off /b/ (NotFound too).
  * ac.cnstrc.com         Constructor.io, the site's own search engine, with
    the public key the page ships (config.TARGET_AUSTRALIA_CONSTRUCTOR_KEY):
    /search/<term>, /browse/<facet>/<value>, /autocomplete/<term>. Pure
    JSON, 1-200 results a page, facets, sort options, the category tree.
  * api.bazaarvoice.com   reviews (/data/reviews.json) with the page's
    public passkey (config.TARGET_AUSTRALIA_BAZAARVOICE_PASSKEY), keyed on
    the BASE product code (W1521109).
  * api.target.com.au     stock status (/lz3inventory/stockStatus/<skus>),
    delivery region (/lz3inventory/delivery/<postcode>) and the postcode /
    suburb lookup (/location/search). No auth.

NOT used: the site's /uir-bff/graphql (Kasada-gated: 429 challenge on
every tier and TLS profile), the legacy /ws-api (Akamai 403), /_next/data
(404). Everything they serve is on the surfaces above except the delivery
date estimates.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  TargetUpstreamError  transport failure / 5xx            — retryable
  TargetBlocked        403 / 429 / challenge page          — retryable
  TargetBadRequest     upstream 400                        — never retried
  TargetNotFound       404 / unknown id                    — never retried
"""
import json
import os
import re
import sys
import threading
import time
from urllib.parse import quote, urlsplit

# Allow direct execution (python target_australia/fetch.py): flat imports
# resolve like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from target_australia.refs import SITE

IMPERSONATE = "chrome"
PAGE_TIMEOUT = 40      # listing pages are ~1 MB
JSON_TIMEOUT = 25
SITEMAP_TIMEOUT = 60   # the product sitemap is 4.4 MB

CONSTRUCTOR_HOST = "https://ac.cnstrc.com"
BAZAARVOICE_HOST = "https://api.bazaarvoice.com"
SERVICES_HOST = "https://api.target.com.au"

PAGE_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": SITE,
    "referer": SITE + "/",
}
XML_HEADERS = {"accept": "application/xml,text/xml;q=0.9,*/*;q=0.8"}

_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.I)
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_BLOCK_MARKERS = ("access denied", "kpsdk", "ips.js", "just a moment", "captcha", "unusual traffic")
_SITE_ERROR_TITLE = "not supposed to happen"


class TargetUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class TargetBlocked(TargetUpstreamError, Blocked):
    """403 / 429 or a challenge page where a page or JSON was expected — retryable."""


class TargetBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class TargetNotFound(NotFound):
    """Product / category / brand / collection / store does not exist — never retried."""


# ---- sessions ----------------------------------------------------------------
# One session per cheroot worker thread: a curl handle must not be shared
# across threads; these GETs are stateless so thread-lifetime sessions with
# keep-alive are enough.
_local = threading.local()
# Process-wide: after a block on the direct tier every new session rides the
# fallback exit (config.target_australia_fallback_proxy()) until this instant.
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy():
    """The exit for a new session: config.target_australia_proxy() (direct
    by default), or the AU residential fallback while a block cooldown runs."""
    proxy = config.target_australia_proxy()
    if proxy is None and time.time() < _fallback_until:
        proxy = config.target_australia_fallback_proxy()
    return proxy


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        proxy = _proxy()
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
    return sess


def _drop_session(blocked=False):
    """Close the thread's session so the retry rides a fresh exit; a block on
    the direct tier also starts the residential fallback cooldown."""
    global _fallback_until
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass
    if blocked and config.target_australia_proxy() is None:
        with _fallback_lock:
            _fallback_until = max(_fallback_until, time.time() + config.TARGET_AUSTRALIA_BLOCK_COOLDOWN)


def _retrying(fn):
    """Run fn() under the shared retry policy (TargetUpstreamError only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except TargetUpstreamError as e:
            last = e
            _drop_session(blocked=isinstance(e, TargetBlocked))
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _page_title(text):
    match = _TITLE_RE.search(text or "")
    return match.group(1).strip() if match else ""


def _looks_blocked(text):
    head = (text or "")[:6000].lower()
    return any(marker in head for marker in _BLOCK_MARKERS)


def _classify(resp, label):
    """Map an HTTP response to the taxonomy; return the body text."""
    if resp.status_code in (404, 410):
        raise TargetNotFound(f"{label} not found")
    if resp.status_code == 400:
        raise TargetBadRequest(resp.text[:200])
    if resp.status_code in (401, 403, 429):
        raise TargetBlocked(f"HTTP {resp.status_code} for {label}")
    if resp.status_code != 200:
        if _SITE_ERROR_TITLE in _page_title(resp.text).lower():
            # the site's own "Hmm... That's not supposed to happen" page: what
            # an unknown category / brand answers (HTTP 500 from the edge)
            raise TargetNotFound(f"{label} not found")
        raise TargetUpstreamError(f"HTTP {resp.status_code} for {label}")
    # challenge markers are only meaningful on an HTML body: a JSON payload
    # carries user text (review bodies, descriptions) that can contain them
    if "json" not in (resp.headers.get("content-type") or "").lower() and _looks_blocked(resp.text):
        raise TargetBlocked(f"challenge page for {label}")
    return resp.text


def _get_once(url, label, headers, timeout, params=None):
    try:
        resp = _session().get(url, headers=headers, params=params, timeout=timeout)
    except Exception as e:
        raise TargetUpstreamError(f"request failed: {type(e).__name__}: {e}")
    return _classify(resp, label), resp


def _get(url, label, headers, timeout, params=None):
    return _retrying(lambda: _get_once(url, label, headers, timeout, params))


def _json_of(resp, text, label):
    try:
        return resp.json()
    except Exception:
        raise TargetBlocked(f"non-JSON response for {label}: {text[:120]}")


# ---- www.target.com.au ---------------------------------------------------------

def fetch_page(path, label):
    """GET a www.target.com.au page -> HTML text."""
    text, _ = _get(SITE + path, label, PAGE_HEADERS, PAGE_TIMEOUT)
    return text


def next_data(html, label):
    """The page's <script id="__NEXT_DATA__"> JSON; a page without one is
    not the app page we asked for (edge challenge, maintenance) -> retryable."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        raise TargetBlocked(f"no page data in {label}")
    try:
        data = json.loads(match.group(1))
    except ValueError:
        raise TargetUpstreamError(f"unreadable page data in {label}")
    if data.get("page") == "/404":
        raise TargetNotFound(f"{label} not found")
    return data


def fetch_next_data(path, label, stay_under=None):
    """GET a Next.js page -> its __NEXT_DATA__ dict (one retry ladder for
    the transport and for a page that came back without its data). With
    stay_under, a redirect off that path prefix means there is no such page
    (/b/lego 301s to the /lego shop, /b/apple to the home page) -> NotFound,
    not a block."""
    def once():
        text, resp = _get_once(SITE + path, label, PAGE_HEADERS, PAGE_TIMEOUT)
        if stay_under and not urlsplit(str(resp.url)).path.startswith(stay_under):
            raise TargetNotFound(f"{label} not found")
        return next_data(text, label)
    return _retrying(once)


def fetch_product_page(code):
    return fetch_next_data(f"/p/{quote(code, safe='_')}", f"product {code}")


def fetch_brand_page(slug):
    return fetch_next_data(f"/b/{quote(slug)}", f"brand {slug}", stay_under="/b/")


def fetch_store_page(number):
    return fetch_page(f"/store/{number}", f"store {number}")


def fetch_store_finder(query):
    return fetch_page(f"/store-finder?q={quote(query)}", f"stores near {query}")


def fetch_brands_page():
    return fetch_page("/brands", "brands page")


def fetch_sitemap(path):
    """GET one sitemap XML (index or child) -> text."""
    text, _ = _get(SITE + path, f"sitemap {path}", XML_HEADERS, SITEMAP_TIMEOUT)
    return text


# ---- ac.cnstrc.com (Constructor.io) -------------------------------------------

def fetch_constructor(path, params):
    """GET /search/<term> | /browse/<facet>/<value> | /autocomplete/<term>
    -> the JSON dict. `params` is a list of (name, value) pairs so repeated
    filters[brand] keys survive."""
    query = [("key", config.TARGET_AUSTRALIA_CONSTRUCTOR_KEY)] + list(params)
    text, resp = _get(CONSTRUCTOR_HOST + path, f"search {path}", JSON_HEADERS, JSON_TIMEOUT, params=query)
    payload = _json_of(resp, text, path)
    if not isinstance(payload, dict):
        raise TargetUpstreamError(f"unexpected search payload for {path}")
    return payload


# ---- api.bazaarvoice.com -------------------------------------------------------

def fetch_reviews(product_id, sort, limit, offset):
    """GET /data/reviews.json for one BASE product code -> the JSON dict."""
    params = [
        ("apiversion", "5.4"),
        ("passkey", config.TARGET_AUSTRALIA_BAZAARVOICE_PASSKEY),
        ("Filter", f"ProductId:{product_id}"),
        ("Sort", sort),
        ("Limit", str(limit)),
        ("Offset", str(offset)),
        ("Include", "Products"),
        ("Stats", "Reviews"),
    ]
    label = f"reviews of {product_id}"
    text, resp = _get(BAZAARVOICE_HOST + "/data/reviews.json", label,
                      {"accept": "application/json"}, JSON_TIMEOUT, params=params)
    payload = _json_of(resp, text, label)
    if not isinstance(payload, dict):
        raise TargetUpstreamError(f"unexpected reviews payload for {product_id}")
    if payload.get("HasErrors"):
        errors = payload.get("Errors") or []
        message = "; ".join(str(e.get("Message") or e.get("Code") or e) for e in errors if isinstance(e, dict))
        raise TargetBadRequest(message or "reviews request rejected")
    return payload


# ---- api.target.com.au ---------------------------------------------------------

def fetch_stock(skus, stores=None, postcode=None):
    """GET /lz3inventory/stockStatus/<sku,sku> -> {"stock": [...]}."""
    modes = ["HD", "CC", "CONSOLIDATED_STORES_SOH"]
    params = [("modes", ",".join(modes))]
    if postcode:
        params.append(("postcode", postcode))
    if stores:
        joined = ",".join(stores)
        params += [("storeNumber", joined), ("locationRefs", joined)]
    label = f"stock of {','.join(skus)}"
    text, resp = _get(f"{SERVICES_HOST}/lz3inventory/stockStatus/{','.join(skus)}", label,
                      JSON_HEADERS, JSON_TIMEOUT, params=params)
    payload = _json_of(resp, text, label)
    if not isinstance(payload, dict):
        raise TargetUpstreamError(f"unexpected stock payload: {text[:120]}")
    return payload


def fetch_delivery_region(postcode):
    """GET /lz3inventory/delivery/<postcode>?mode=HD -> {locationGroup, available, regionId}."""
    label = f"delivery region {postcode}"
    text, resp = _get(f"{SERVICES_HOST}/lz3inventory/delivery/{postcode}", label,
                      JSON_HEADERS, JSON_TIMEOUT, params=[("mode", "HD")])
    payload = _json_of(resp, text, label)
    return payload if isinstance(payload, dict) else {}


def fetch_locations(term):
    """GET /location/search?searchTerm=<postcode or suburb> -> {"results": [...]}."""
    label = f"locations {term}"
    text, resp = _get(f"{SERVICES_HOST}/location/search", label, JSON_HEADERS, JSON_TIMEOUT,
                      params=[("searchTerm", term)])
    payload = _json_of(resp, text, label)
    if not isinstance(payload, dict):
        raise TargetUpstreamError(f"unexpected locations payload: {text[:120]}")
    return payload
