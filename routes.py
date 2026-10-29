"""The 18 Target Australia endpoints. Every path is served with and without
the `/target-australia` prefix, so code generated against the hosted API on
RapidAPI (paths like /products/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in target_australia/schemas.py
(ONE param per input: `product` takes a SKU, colour-variant or base code or a
target.com.au product link, `category` a W-code, category path or link,
`brand` / `collection` a slug or link, `store` a store number or link);
unknown params are rejected."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, NotFound
from target_australia import api, schemas


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so getunicode is mandatory)."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, host = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{host}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, params):
    """Lift the `pagination` block into the flat shape the hosted API
    returns: count / per_page / current_page / total_pages / next / previous.
    `count` is the total, so the per-page count the module adds is dropped."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(params.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, params, page + 1 if page < total_pages else None),
        "previous": _page_link(path, params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(label, schema_cls, impl, paginated=False):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    transport / blocks -> 500."""
    raw = query_dict()
    data, error = load_query(schema_cls, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"target australia rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"target australia {label} failed: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/products/details", schemas.ProductSchema, api.product_details, False),
    ("/products/autocomplete", schemas.AutocompleteSchema, api.products_autocomplete, False),
    ("/products/search", schemas.SearchSchema, api.products_search, True),
    ("/products/reviews", schemas.ReviewsSchema, api.product_reviews, True),
    ("/products/stock", schemas.StockSchema, api.products_stock, False),
    ("/products/bulk", schemas.ProductsBulkSchema, api.products_bulk, False),
    ("/categories", schemas.CategoriesSchema, api.categories, False),
    ("/categories/products", schemas.CategoryProductsSchema, api.category_products, True),
    ("/brands", schemas.BrandsSchema, api.brands, True),
    ("/brands/products", schemas.BrandProductsSchema, api.brand_products, True),
    ("/collections", schemas.CollectionsSchema, api.collections, True),
    ("/collections/products", schemas.CollectionProductsSchema, api.collection_products, True),
    ("/stores/search", schemas.StoresSearchSchema, api.stores_search, False),
    ("/stores/details", schemas.StoreSchema, api.store_details, False),
    ("/stores", schemas.StoresSchema, api.stores, True),
    ("/locations/suggestions", schemas.LocationsSchema, api.locations_suggestions, False),
    ("/sitemap/products", schemas.SitemapProductsSchema, api.sitemap_products, True),
    ("/sitemap/links", schemas.SitemapLinksSchema, api.sitemap_links, True),
]


def mount(path, schema_cls, impl, paginated):
    """Serve a handler at /path and /target-australia/path."""
    label = path.strip("/")

    def handler():
        return call(label, schema_cls, impl, paginated)

    handler.__name__ = "target_australia_" + label.replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/target-australia" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
