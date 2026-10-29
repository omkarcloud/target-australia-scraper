"""Configuration for the Target Australia Scraper. Everything can be set
with an environment variable; the defaults work out of the box.

    PORT                    port the API listens on (default 8000)
    TARGET_AUSTRALIA_PROXY  proxy URL for every request, e.g.
                            http://user:pass@host:port (default: none —
                            direct). Search, listings, autocomplete, reviews,
                            stock and the postcode lookup come from Target's
                            search engine and data services, which answer any
                            connection. Target's own pages (product details,
                            brand pages, stores, sitemaps) sit behind Akamai,
                            which refuses some datacenter IPs; if you get 403s
                            on a cloud server, set an Australian residential
                            proxy.
    TARGET_AUSTRALIA_FALLBACK_PROXY
                            proxy used for TARGET_AUSTRALIA_BLOCK_COOLDOWN
                            seconds after a block while TARGET_AUSTRALIA_PROXY
                            is unset (default: none — stays direct).

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# Public keys every target.com.au page ships to the browser: the site's
# search engine (Constructor.io) and its review widget (Bazaarvoice).
TARGET_AUSTRALIA_CONSTRUCTOR_KEY = "key_kWcXakjuyHSxpu75"
TARGET_AUSTRALIA_BAZAARVOICE_PASSKEY = "caUB5upavpWffhjzleyYJtC1IDay5OH1ibdymrHEjmrmE"

TARGET_AUSTRALIA_BLOCK_COOLDOWN = 600   # seconds the fallback proxy is used after a block
TARGET_AUSTRALIA_WORKERS = 4            # parallel product fetches inside /products/bulk

TARGET_AUSTRALIA_PROXY = os.environ.get("TARGET_AUSTRALIA_PROXY") or None


def target_australia_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("TARGET_AUSTRALIA_PROXY") or None


def target_australia_fallback_proxy():
    """The proxy new sessions use for TARGET_AUSTRALIA_BLOCK_COOLDOWN seconds
    after a block (None = stay direct)."""
    return os.environ.get("TARGET_AUSTRALIA_FALLBACK_PROXY") or None
