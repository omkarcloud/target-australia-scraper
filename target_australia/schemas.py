"""Marshmallow request schemas for every /target-australia/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    product     a product code (SKU 63681024, colour variant 1521109_white,
                base W1521109 / P73493297) OR any target.com.au product link
    products    a comma list of the same (bulk / stock)
    category    a W-code (W1852625), a category path or link; AP01 = all
    brand       a brand slug (bluey) OR a /b/<slug> link
    collection  a collection slug (womens-sale) OR a /collection/<slug> link
    store       a store number (5123) OR a /store/<state>/<suburb>/<number> link
    location    a 4-digit postcode or a suburb / city name

Listing filters (search / category / brand / collection products) are the
site's own facets (target_australia/refs.py, captured 2026-10-28): sort,
brand, colour, price range, age, minimum rating, delivery mode and the
new-arrivals / on-sale / online-only / OnePass switches.
"""
from functools import partial

from marshmallow import ValidationError, fields, validate

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, LimitField, PageField,
                           PageSizeField, QueryField, RefField, StrippedString)
from target_australia import refs

LISTING_PAGE_SIZE = 48      # the site's own listing page size
MAX_LISTING_PAGE_SIZE = 200  # Constructor's num_results_per_page ceiling
MAX_LISTING_PAGE = 500
MAX_BULK_PRODUCTS = 10
MAX_STOCK_PRODUCTS = 20
MAX_STOCK_STORES = 10
REVIEWS_PAGE_SIZE = 20
MAX_REVIEWS_PAGE_SIZE = 100  # Bazaarvoice's Limit ceiling
MAX_TREE_DEPTH = 6


class ProductRefField(RefField):
    resolver = staticmethod(refs.resolve_product)


class ProductsRefField(RefField):
    """Comma-separated product codes / links -> list of codes."""

    def __init__(self, max_items, **kwargs):
        super().__init__(resolver=partial(refs.resolve_products, max_items=max_items), **kwargs)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class BrandRefField(RefField):
    resolver = staticmethod(refs.resolve_brand)


class CollectionRefField(RefField):
    resolver = staticmethod(refs.resolve_collection)


class StoreRefField(RefField):
    resolver = staticmethod(refs.resolve_store)


class StoresRefField(RefField):
    """Comma-separated store numbers / links -> list of numbers (optional)."""

    def __init__(self, max_items, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(resolver=partial(refs.resolve_stores, max_items=max_items), **kwargs)


class PriceRangeField(StrippedString):
    """'10-20', '10-' or '-20' (AUD) -> the same string, normalised."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        try:
            low, high = refs.resolve_price_range(value)
        except ValueError as e:
            raise ValidationError(str(e))
        fmt = lambda n: ("" if n is None else (str(int(n)) if float(n).is_integer() else str(n)))
        return f"{fmt(low)}-{fmt(high)}"


class PostcodeField(StrippedString):
    """4-digit Australian postcode (optional)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        if not refs.POSTCODE_RE.match(value):
            raise ValidationError("Must be a 4-digit Australian postcode (e.g. 3000).")
        return value


class ListingSchema(BaseSchema):
    """The filters every product listing shares."""
    page = PageField(max_page=MAX_LISTING_PAGE, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=LISTING_PAGE_SIZE, max_size=MAX_LISTING_PAGE_SIZE, metadata={
        "description": f"products per page, 1-{MAX_LISTING_PAGE_SIZE} (the site shows {LISTING_PAGE_SIZE})"})
    sort = ChoiceField(list(refs.SORTS), load_default="relevance", metadata={
        "description": "relevance (default), latest, rating, price_asc, price_desc or brand"})
    brand = CommaListField(upper=False, max_items=20, metadata={
        "description": "brand name(s) as the site spells them, comma-separated (LEGO, Anko)"})
    colour = CommaListField(upper=False, max_items=20, metadata={
        "description": "colour(s), comma-separated (Multi, White, Blue)"})
    price = PriceRangeField(metadata={"description": "AUD price range: 10-20, 50- or -20"})
    age = CommaListField(upper=False, max_items=10, metadata={
        "description": "age band(s) as the toys facet spells them (1-2, 3-4, 5-7, 8-11)"})
    min_rating = fields.Integer(strict=False, load_default=None, validate=validate.Range(min=1, max=5), metadata={
        "description": "only products rated at least this many stars (1-5)"})
    delivery = ChoiceField(list(refs.DELIVERY_MODES), metadata={
        "description": "home_delivery or click_and_collect"})
    new_arrivals = Flag(metadata={"description": "true: only new arrivals"})
    on_sale = Flag(metadata={"description": "true: only products with a was-price"})
    online_only = Flag(metadata={"description": "true: only online-exclusive products"})
    onepass = Flag(metadata={"description": "true: only products eligible for OnePass free delivery"})


class SearchSchema(ListingSchema):
    query = QueryField(metadata={"description": "search term (lego duplo, sheet set)"})
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "restrict to a category: W-code (W138532), category path or link"})


class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100, metadata={"description": "the partial search term (bl, lego)"})
    limit = LimitField(default=10, max_size=20, metadata={
        "description": "suggestions and products to return, 1-20"})


class ProductSchema(BaseSchema):
    product = ProductRefField(metadata={
        "description": "product code (SKU 63681024, 1521109_white, W1521109) or a target.com.au product link"})


class ProductsBulkSchema(BaseSchema):
    products = ProductsRefField(MAX_BULK_PRODUCTS, metadata={
        "description": f"up to {MAX_BULK_PRODUCTS} product codes or links, comma-separated"})


class ReviewsSchema(BaseSchema):
    product = ProductRefField(metadata={
        "description": "product code (any form) or a target.com.au product link; reviews are kept per base product"})
    page = PageField(max_page=1000, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=REVIEWS_PAGE_SIZE, max_size=MAX_REVIEWS_PAGE_SIZE, metadata={
        "description": f"reviews per page, 1-{MAX_REVIEWS_PAGE_SIZE}"})
    sort = ChoiceField(list(refs.REVIEW_SORTS), load_default="newest", metadata={
        "description": "newest (default), oldest, rating_high, rating_low or helpful"})


class StockSchema(BaseSchema):
    products = ProductsRefField(MAX_STOCK_PRODUCTS, metadata={
        "description": f"up to {MAX_STOCK_PRODUCTS} product codes or links, comma-separated; a base or "
                       "colour code expands to every SKU under it"})
    stores = StoresRefField(MAX_STOCK_STORES, metadata={
        "description": f"up to {MAX_STOCK_STORES} store numbers or store links for per-store stock"})
    postcode = PostcodeField(metadata={
        "description": "4-digit postcode: home-delivery availability for that region"})


class CategoriesSchema(BaseSchema):
    category = CategoryRefField(required=False, load_default=refs.ALL_PRODUCTS, metadata={
        "description": "subtree root: W-code, category path or link (default: the whole catalogue)"})
    depth = fields.Integer(strict=False, load_default=2, validate=validate.Range(min=1, max=MAX_TREE_DEPTH),
                           metadata={"description": f"levels below the root to return, 1-{MAX_TREE_DEPTH}"})


class CategoryProductsSchema(ListingSchema):
    category = CategoryRefField(metadata={
        "description": "W-code (W1852625), category path (toys/trading-card-games/W1852625) or link"})


class BrandsSchema(BaseSchema):
    page = PageField(max_page=100, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=100, max_size=500, metadata={"description": "brands per page, 1-500"})


class BrandProductsSchema(ListingSchema):
    brand = BrandRefField(metadata={"description": "brand slug (bluey, lego) or a /b/<slug> link"})
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "restrict to a category: W-code, category path or link"})


class CollectionsSchema(BaseSchema):
    page = PageField(max_page=100, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=100, max_size=500, metadata={"description": "collections per page, 1-500"})


class CollectionProductsSchema(ListingSchema):
    collection = CollectionRefField(metadata={
        "description": "collection slug (womens-sale) or a /collection/<slug> link"})
    category = CategoryRefField(required=False, load_default=None, metadata={
        "description": "restrict to a category: W-code, category path or link"})


class StoresSchema(BaseSchema):
    state = ChoiceField(["ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"], metadata={
        "description": "only stores in this state (ACT, NSW, NT, QLD, SA, TAS, VIC, WA)"})
    page = PageField(max_page=20, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=50, max_size=200, metadata={"description": "stores per page, 1-200"})


class StoresSearchSchema(BaseSchema):
    location = QueryField(max_length=80, metadata={
        "description": "a 4-digit postcode (3000) or a suburb / city (Bondi, Melbourne)"})


class StoreSchema(BaseSchema):
    store = StoreRefField(metadata={"description": "store number (5123) or a target.com.au store link"})


class LocationsSchema(BaseSchema):
    query = QueryField(max_length=60, metadata={
        "description": "the start of a postcode or suburb name (Bondi, 30)"})


class SitemapProductsSchema(BaseSchema):
    page = PageField(max_page=1000, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=1000, max_size=5000, metadata={"description": "links per page, 1-5000"})


class SitemapLinksSchema(BaseSchema):
    type = ChoiceField(["all", *refs.SITEMAPS], load_default="all", metadata={
        "description": "all (default), products, categories, brands, collections, stores or content"})
    page = PageField(max_page=1000, metadata={"description": "1-based page"})
    page_size = PageSizeField(default=1000, max_size=5000, metadata={"description": "links per page, 1-5000"})
