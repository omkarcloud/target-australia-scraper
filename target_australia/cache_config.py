"""Cache TTL per /target-australia/* endpoint (cache.py, keyed on the
validated params). Target's catalogue moves on a retail cadence: prices
and stock change through the day, descriptions and the category tree
weekly, stores and sitemaps rarely. The product endpoints share two cached
upstream parses (api._page: the product page; api._card: the Constructor
record), so details + reviews + stock on one product cost at most one page
fetch and one search call.
"""
from datetime import timedelta

# Search / category / brand / collection listings: prices, "was" prices
# and stock counts move during the day (flash toy sales).
LISTING_CACHE = timedelta(hours=1)
# Autocomplete suggestions are near static.
AUTOCOMPLETE_CACHE = timedelta(hours=6)
# The product page parse (descriptions, variants, delivery modes).
PRODUCT_PAGE_CACHE = timedelta(hours=2)
# The product's Constructor record (brand, online/store quantities).
PRODUCT_CARD_CACHE = timedelta(hours=1)
# Reviews accrue slowly; the page is keyed on sort + page.
REVIEWS_CACHE = timedelta(hours=12)
# Store-level stock status is the freshest thing the site publishes.
STOCK_CACHE = timedelta(minutes=10)
# Category tree + counts: merchandising moves weekly.
CATEGORY_TREE_CACHE = timedelta(hours=24)
# The category sitemap (W-code -> canonical link) backs the tree's links.
CATEGORY_LINKS_CACHE = timedelta(hours=24)
# A brand's header (name, banners): the display name is what the search
# engine keys on and it never changes.
BRAND_PAGE_CACHE = timedelta(days=7)
# Brand / collection / store directories from the sitemaps.
DIRECTORY_CACHE = timedelta(hours=24)
# Store finder results and store pages (trading hours are published
# two weeks ahead).
STORES_CACHE = timedelta(hours=24)
# Postcode / suburb lookup: Australia Post data.
LOCATIONS_CACHE = timedelta(days=7)
# Raw sitemap listings (27 k product links).
SITEMAP_CACHE = timedelta(hours=12)
