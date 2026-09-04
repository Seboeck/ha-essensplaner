"""Scraper für die öffentliche Kaufland-Angebotsseite der per PLZ ermittelten
Filiale. Fällt auf `store_url` zurück, falls die PLZ-Zuordnung fehlschlägt.
Bekanntes Risiko: Layout-Änderungen der Seite brechen die Selektoren unten
(siehe Spec, Abschnitt "Offene Risiken") — Fehler werden nie verschluckt,
sondern nach oben gereicht, damit der Runner (Task 9) sie in
OfferSourceConfig.last_status festhält."""
from datetime import date

import httpx
from bs4 import BeautifulSoup

from offers.base import OfferData

SOURCE = "kaufland_scraper"
_PLZ_LOOKUP_URL = "https://filiale.kaufland.de/angebote.html?plz={plz}"


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
    for tile in soup.select(".offer-tile"):
        title_el = tile.select_one(".offer-tile__title")
        if not title_el:
            continue
        valid_from = tile.get("data-valid-from")
        valid_until = tile.get("data-valid-until")
        if not valid_from or not valid_until:
            continue
        price_el = tile.select_one(".offer-tile__price")
        discount_el = tile.select_one(".offer-tile__discount")
        description_el = tile.select_one(".offer-tile__description")
        offers.append(OfferData(
            retailer="kaufland",
            product_name=title_el.get_text(strip=True),
            description=description_el.get_text(strip=True) if description_el else None,
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
