"""Scraper für die öffentliche Edeka-Angebotsseite der per PLZ ermittelten
(regionalen) Filiale. Edeka ist dezentral organisiert — `store_url` als
Fallback ist hier wichtiger als bei Kaufland. Gleiche Fehlerbehandlungs-
Philosophie wie kaufland_scraper.py: Fehler werden nie verschluckt.
"""
from datetime import date

import httpx
from bs4 import BeautifulSoup

from offers.base import OfferData

SOURCE = "edeka_scraper"
_PLZ_LOOKUP_URL = "https://www.edeka.de/angebote/index.jsp?plz={plz}"


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace("€", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_offers_html(html: str) -> list[OfferData]:
    soup = BeautifulSoup(html, "html.parser")
    offers: list[OfferData] = []
    for item in soup.select(".product-grid__item"):
        title_el = item.select_one(".product-grid__title")
        if not title_el:
            continue
        valid_from = item.get("data-from")
        valid_until = item.get("data-to")
        if not valid_from or not valid_until:
            continue
        price_el = item.select_one(".product-grid__price")
        discount_el = item.select_one(".product-grid__discount")
        subtitle_el = item.select_one(".product-grid__subtitle")
        offers.append(OfferData(
            retailer="edeka",
            product_name=title_el.get_text(strip=True),
            description=subtitle_el.get_text(strip=True) if subtitle_el else None,
            price=_parse_price(price_el.get_text() if price_el else None),
            discount_text=discount_el.get_text(strip=True) if discount_el else None,
            valid_from=date.fromisoformat(valid_from),
            valid_until=date.fromisoformat(valid_until),
        ))
    return offers


def fetch_offers(plz: str, store_url: str | None = None) -> list[OfferData]:
    url = store_url or _PLZ_LOOKUP_URL.format(plz=plz)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return _parse_offers_html(response.text)
