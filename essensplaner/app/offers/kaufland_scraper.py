"""Scraper für die öffentliche Kaufland-Angebotsseite der per PLZ ermittelten
Filiale. Fällt auf `store_url` zurück, falls die PLZ-Zuordnung fehlschlägt.
Bekanntes Risiko: Layout-Änderungen der Seite brechen die Selektoren unten
(siehe Spec, Abschnitt "Offene Risiken") — Fehler werden nie verschluckt,
sondern nach oben gereicht, damit der Runner (Task 9) sie in
OfferSourceConfig.last_status festhält.

Die Selektoren unten wurden am 2026-09-04 gegen die echte Seite
(https://filiale.kaufland.de/angebote/uebersicht.html) verifiziert (Task 6,
Step 6). Wichtige Erkenntnisse aus der Live-Prüfung:
- Die Seite ist serverseitig gerendert (Vue-SSR) — die Angebotsdaten stehen
  bereits im initialen HTML, ein Headless-Browser (Playwright) ist NICHT
  nötig.
- Gültigkeitszeiträume stehen nicht pro Kachel, sondern pro Kategorie-
  Abschnitt (`.k-product-section`) als deutscher Text ohne Jahr, z.B.
  "Gültig vom 03.09. bis 09.09." oder "Gültig am 04.09.".
- Der Produktname ist auf Marke (`.k-product-tile__title`) und Beschreibung
  (`.k-product-tile__subtitle`) aufgeteilt; beide werden zu `product_name`
  zusammengeführt (bessere Trefferquote beim Fuzzy-Matching in matching.py).
- Preise nutzen bereits einen Punkt als Dezimaltrennzeichen und kein "€"-
  Zeichen (z.B. "0.39"), `_parse_price` bleibt trotzdem tolerant gegenüber
  dem Komma-Format, falls sich das wieder ändert.
"""
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup

from offers.base import OfferData

SOURCE = "kaufland_scraper"
_PLZ_LOOKUP_URL = "https://filiale.kaufland.de/angebote.html?plz={plz}"

_DATE_RANGE_RE = re.compile(r"vom\s*(\d{1,2})\.(\d{1,2})\.\s*bis\s*(\d{1,2})\.(\d{1,2})\.", re.IGNORECASE)
_DATE_SINGLE_RE = re.compile(r"am\s*(\d{1,2})\.(\d{1,2})\.", re.IGNORECASE)


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace("€", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _resolve_year(month: int, day: int, today: date) -> int:
    """Die Kaufland-Seite nennt Gültigkeitsdaten ohne Jahr (z.B. "03.09.").
    Nimmt das aktuelle Jahr an — außer das Datum läge damit weit (>200 Tage)
    in der Vergangenheit; dann handelt es sich vermutlich um einen
    Jahreswechsel und das Folgejahr wird angenommen."""
    year = today.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return year
    if (today - candidate).days > 200:
        year += 1
    return year


def _parse_validity(text: str | None, today: date | None = None) -> tuple[date, date] | None:
    if not text:
        return None
    today = today or date.today()

    match = _DATE_RANGE_RE.search(text)
    if match:
        # Deutsches Format: TT.MM. bis TT.MM. (kein Jahr)
        from_day, from_month, until_day, until_month = (int(g) for g in match.groups())
        from_year = _resolve_year(from_month, from_day, today)
        until_year = _resolve_year(until_month, until_day, today)
        try:
            return date(from_year, from_month, from_day), date(until_year, until_month, until_day)
        except ValueError:
            return None

    match = _DATE_SINGLE_RE.search(text)
    if match:
        # Deutsches Format: TT.MM. (kein Jahr)
        day, month = (int(g) for g in match.groups())
        year = _resolve_year(month, day, today)
        try:
            single_day = date(year, month, day)
        except ValueError:
            return None
        return single_day, single_day

    return None


def _parse_offers_html(html: str, today: date | None = None) -> list[OfferData]:
    soup = BeautifulSoup(html, "html.parser")
    offers: list[OfferData] = []
    for section in soup.select(".k-product-section"):
        subheadline_el = section.select_one(".k-product-section__subheadline")
        validity = _parse_validity(subheadline_el.get_text(strip=True) if subheadline_el else None, today)
        if not validity:
            continue
        valid_from, valid_until = validity

        for tile in section.select(".k-product-tile"):
            title_el = tile.select_one(".k-product-tile__title")
            if not title_el:
                continue
            subtitle_el = tile.select_one(".k-product-tile__subtitle")
            title = title_el.get_text(strip=True)
            subtitle = subtitle_el.get_text(strip=True) if subtitle_el else ""
            product_name = f"{title} {subtitle}".strip()

            price_el = tile.select_one(".k-price-tag__price")
            discount_el = tile.select_one(".k-price-tag__discount")
            offers.append(OfferData(
                retailer="kaufland",
                product_name=product_name,
                description=None,
                price=_parse_price(price_el.get_text() if price_el else None),
                discount_text=discount_el.get_text(strip=True) if discount_el else None,
                valid_from=valid_from,
                valid_until=valid_until,
            ))
    return offers


def fetch_offers(plz: str, store_url: str | None = None) -> list[OfferData]:
    url = store_url or _PLZ_LOOKUP_URL.format(plz=plz)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return _parse_offers_html(response.text)
