# 🎯 Target Australia Scraper

Target Australia Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Target Australia data for free.

## ✨ What Can I Get?

- 🛍️ **Full details on 24K+ products** — price, was-price, stock counts, delivery options, variants, materials & images
- 🔍 **Search & browse every aisle** — keyword search, every category, 500+ brands & 300+ collections, fully filterable
- ⭐ **Every customer review** — full text, star rating, author location, helpful votes & star breakdown
- 📍 **All 120+ stores** — live stock per store, addresses, phones, GPS & two weeks of trading hours

## 💍 Example: A Full Target Australia Product

```json
{
  "id": "71566665",
  "name": "Waterproof 3 Pack Pendant Necklace Set - Gold",
  "link": "https://www.target.com.au/p/waterproof-3-pack-pendant-necklace-set/71566665",
  "brand": "Target Woman",
  "description": "Transform your accessories collection with this stylish Waterproof 3 Pack Pendant Necklace Set. These necklaces, made from stainless steel with real gold plating and bright cubic zirconia accents, offer a beautiful way to enhance any look.",
  "features": ["Womens necklace set", "3 pack set", "Necklace lengths: 41cm, 45cm and 50cm"],
  "materials": ["90% Stainless Steel/10% Cubic Zirconia", "Real Gold Plated"],
  "price": { "amount": 35, "range": { "min": 10, "max": 35 }, "was": null, "currency": "AUD" },
  "is_in_stock": true,
  "stock": { "online_quantity": 124, "store_quantity": 599, "in_store_stock_locations": ["NSW-Broadway", "VIC-Chadstone"] },
  "delivery": { "home_delivery": true, "click_and_collect": true, "express_delivery": true, "is_eligible_for_onepass_free_delivery": true },
  "breadcrumbs": [
    { "name": "Women", "category_id": "W93743", "link": "https://www.target.com.au/c/women/W93743" },
    { "name": "Necklaces", "category_id": "W385149", "link": "https://www.target.com.au/c/women/accessories/jewellery/necklaces/W385149" }
  ],
  "images": [
    { "link": "https://assets.target.com.au/m/e39c3b3c6cd8bb3/webimage-160_71566665_1-160T7156.png", "type": "PRIMARY" }
  ],
  "variations": [
    { "id": "71566665", "colour": "Gold", "price": { "amount": 35, "was": null, "currency": "AUD" }, "online_quantity": 124, "store_quantity": 599 },
    { "id": "72356937", "colour": "Silver", "price": { "amount": 10, "was": 15, "currency": "AUD" }, "online_quantity": 51, "store_quantity": 531 }
  ],
  "online_date": "2025-08-29"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Target Australia Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/target-australia-scraper
cd target-australia-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=71566665"
```

```json
{
  "id": "71566665",
  "name": "Waterproof 3 Pack Pendant Necklace Set - Gold",
  "link": "https://www.target.com.au/p/waterproof-3-pack-pendant-necklace-set/71566665",
  "brand": "Target Woman",
  "materials": ["90% Stainless Steel/10% Cubic Zirconia", "Real Gold Plated"],
  "price": { "amount": 35, "range": { "min": 10, "max": 35 }, "was": null, "currency": "AUD" },
  "availability": "NORMAL",
  "is_in_stock": true,
  "stock": { "online_quantity": 124, "store_quantity": 599 },
  "delivery": { "home_delivery": true, "click_and_collect": true, "express_delivery": true },
  "top_level_category": "Women",
  "colour_variants": [
    { "code": "71566665", "label": "Gold", "link": "https://www.target.com.au/p/waterproof-3-pack-pendant-necklace-set/71566665" },
    { "code": "72356937", "label": "Silver", "link": "https://www.target.com.au/p/waterproof-3-pack-pendant-necklace-set/72356937" }
  ],
  "online_date": "2025-08-29"
}
```

All 18 endpoints are now live at `http://localhost:8000`.

Running it on a cloud server? Akamai refuses some datacenter IPs on Target's own pages (product details, stores, sitemaps). If they start answering 403, set `TARGET_AUSTRALIA_PROXY` to an Australian residential proxy (`http://user:pass@host:port`). Everything else needs nothing.

## 📚 Endpoints

18 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Autocomplete | `/products/autocomplete` | Suggested searches plus matching products as you type |
| Search Products | `/products/search` | 48 products per page; filter by brand, colour, price, age, rating |
| Product Reviews | `/products/reviews` | Full review text, star rating, author location and star breakdown |
| Product Stock | `/products/stock` | Live stock online, for click & collect and per store |
| Bulk Product Details | `/products/bulk` | Up to 10 full product records in one call |
| Categories | `/categories` | The full category tree with product counts and links |
| Category Products | `/categories/products` | Any category, 48 per page, fully filterable |
| Brands | `/brands` | Every brand Target Australia sells, with product counts |
| Brand Products | `/brands/products` | A brand's full Target Australia range, 48 per page |
| Collections | `/collections` | Every curated collection: sales, seasonal edits, gift guides |
| Collection Products | `/collections/products` | Any collection's products, 48 per page, fully filterable |
| Search Stores | `/stores/search` | Nearest stores to a postcode, suburb or city, with distance |
| Store Details | `/stores/details` | Address, phone, GPS and two weeks of trading hours |
| List Stores | `/stores` | Every Target store in Australia, filterable by state |
| Location Suggestions | `/locations/suggestions` | Postcode and suburb autocomplete with state |
| Sitemap Products | `/sitemap/products` | Every product code and link, up to 5,000 per page |
| Sitemap Links | `/sitemap/links` | Every product, category, brand, collection and store URL |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-target-australia-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-target-australia-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-target-australia-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/search",
    params={"query": "nintendo switch", "sort": "price_asc"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Target Australia Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Target%20Australia%20Scraper%20API.)

[![Ask Us by Email about Target Australia Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Target%20Australia%20Scraper%20API&body=I%20need%20help%20using%20the%20Target%20Australia%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/target-australia-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/target-australia-scraper)
