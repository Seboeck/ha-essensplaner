"""Scraper für die öffentliche Edeka-Angebotsseite der per PLZ ermittelten
(regionalen) Filiale. Edeka ist dezentral organisiert — `store_url` als
Fallback ist hier wichtiger als bei Kaufland. Gleiche Fehlerbehandlungs-
Philosophie wie kaufland_scraper.py: Fehler werden nie verschluckt.

Die Selektoren unten wurden am 2026-09-04 gegen die echte Seite
(https://www.edeka.de/angebote, https://www.edeka.de/maerkte/<id>/angebote)
verifiziert (Task 7, Step 5). Wichtige Erkenntnisse aus der Live-Prüfung:
- Der im Task-Brief angenommene URL-Parameter `?plz=` existiert NICHT
  (`edeka.de/angebote/index.jsp?plz=...` liefert 404). Eine PLZ lässt sich
  nur über die zweistufige Marktsuche auflösen:
  1. GET `https://www.edeka.de/maerkte/suche/?suchbegriff=<plz>` (liefert
     serverseitig gerenderte Trefferliste, keine PLZ-spezifische
     Angebotsseite),
  2. daraus den ersten Filiale-Link `/maerkte/<id>/angebote` INNERHALB des
     Trefferlisten-Containers (`#results-wrapper`) extrahieren und diesen
     abrufen. Das ist genau das im Spec befürchtete Risiko: ohne diesen
     Zwischenschritt (oder einen expliziten `store_url`) bekommt man nur
     die bundesweite Teaser-Seite ohne filialspezifische Angebote/Preise.
     Der Link wird bewusst NICHT per Regex über die komplette Roh-Seite
     gesucht (siehe `_resolve_store_offers_url`) - das würde bei einem
     zufällig früher im HTML stehenden, unabhängigen `/maerkte/<id>/
     angebote`-Link (z.B. ein "Mein Markt"-Schnellzugriff im Header) still
     eine völlig unabhängige Filiale zurückgeben, die nichts mit der
     gesuchten PLZ zu tun hat.
- Die Seite ist serverseitig gerendert (Phoenix LiveView SSR) — ein
  Headless-Browser ist NICHT nötig, ein einfacher `httpx.get()` liefert
  bereits das vollständige HTML mit allen Angeboten.
- Es gibt KEINE stabilen, semantischen CSS-Klassen wie im Brief angenommen
  (`.product-grid__item` o.ä.) — alle Klassen sind generierte Tailwind-
  Utility-Klassen (z.B. `bg-red-700`, `mb-2`), die bei einem Redesign
  wahrscheinlich wechseln. Es wird daher auf strukturelle Selektoren
  (`article:has(a[data-dialog-action="open"])`) und auf Text-Regexes für
  Datumsangaben ausgewichen — robuster gegenüber Styling-Änderungen, aber
  weiterhin anfällig für strukturelle Layout-Änderungen.
- Gültigkeitszeiträume stehen als Fließtext "Gültig vom DD.MM.YYYY bis zum
  DD.MM.YYYY." einmal pro Seite (inkl. Jahr, anders als bei Kaufland -
  keine Jahresauflösung nötig). Einzelne Kacheln können das mit
  "Gültig ab DD.MM.YYYY" überschreiben (späterer Start innerhalb der
  Woche, Wochenende der Angebotsseite bleibt als Enddatum bestehen).
- Produktkarten enthalten oft zwei Preis-Einträge (App-Preis zuerst,
  regulärer/rabattierter Preis danach) - es wird bewusst der letzte
  Preis-Eintrag verwendet, um den App-exklusiven Preis nicht als
  regulären Angebotspreis zu übernehmen.
"""
import re
from datetime import date

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

from offers.base import OfferData

SOURCE = "edeka_scraper"

_STORE_SEARCH_URL = "https://www.edeka.de/maerkte/suche/?suchbegriff={plz}"
_STORE_OFFERS_URL = "https://www.edeka.de/maerkte/{store_id}/angebote"
_STORE_OFFERS_URL_RE = re.compile(r"/maerkte/(\d+)/angebote")
# Am 2026-09-04 live verifiziert (PLZ 10115): die Marktsuche-Ergebnisliste
# steckt serverseitig gerendert in genau diesem Container
# (`<section id="results-wrapper" aria-labelledby="search-results-headline">`),
# eindeutig auf der Seite. Header/Nav (z.B. ein "Mein Markt"-Schnellzugriff-
# Link) liegt VOR diesem Container im HTML und wird durch das Scoping auf
# diese ID ausgeschlossen.
_STORE_SEARCH_RESULTS_SELECTOR = "#results-wrapper"

_WEEK_RANGE_RE = re.compile(
    r"G[uü]ltig vom\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*bis zum\s*(\d{1,2})\.(\d{1,2})\.(\d{4})",
    re.IGNORECASE,
)
_VALID_FROM_OVERRIDE_RE = re.compile(r"G[uü]ltig ab\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", re.IGNORECASE)


def _parse_price(text: str | None) -> float | None:
    if not text:
        return None
    cleaned = text.replace("€", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_week_validity(page_text: str) -> tuple[date, date] | None:
    """Sucht den seitenweiten Gültigkeitszeitraum ("Gültig vom ... bis zum ...")."""
    match = _WEEK_RANGE_RE.search(page_text)
    if not match:
        return None
    from_day, from_month, from_year, until_day, until_month, until_year = (int(g) for g in match.groups())
    try:
        return date(from_year, from_month, from_day), date(until_year, until_month, until_day)
    except ValueError:
        return None


def _parse_valid_from_override(item_text: str) -> date | None:
    """Sucht eine kachel-spezifische Überschreibung ("Gültig ab ..."), z.B. für
    Angebote, die erst später in der Woche starten."""
    match = _VALID_FROM_OVERRIDE_RE.search(item_text)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_price(li: Tag) -> tuple[float | None, str | None]:
    price_div = li.select_one('div[aria-hidden="true"]')
    if not price_div:
        return None, None
    spans = price_div.find_all("span", recursive=False)
    if not spans:
        return None, None
    price = _parse_price(spans[0].get_text())
    discount_text = None
    if len(spans) > 1:
        text = spans[1].get_text(strip=True)
        if text.startswith("-"):
            discount_text = text
    return price, discount_text


def _parse_offers_html(html: str) -> list[OfferData]:
    soup = BeautifulSoup(html, "html.parser")
    week_validity = _parse_week_validity(soup.get_text(" "))

    offers: list[OfferData] = []
    for item in soup.select('article:has(a[data-dialog-action="open"])'):
        heading = item.select_one('a[data-dialog-action="open"]')
        if not heading:
            continue
        sr_only = heading.select_one(".sr-only")
        if sr_only:
            sr_only.extract()
        product_name = heading.get_text(strip=True)
        if not product_name:
            continue

        if week_validity is None:
            continue
        valid_from, valid_until = week_validity
        override = _parse_valid_from_override(item.get_text(" "))
        if override:
            valid_from = override

        description_el = item.select_one("p")
        price_lis = item.select("ul li")
        price, discount_text = _extract_price(price_lis[-1]) if price_lis else (None, None)

        offers.append(OfferData(
            retailer="edeka",
            product_name=product_name,
            description=description_el.get_text(strip=True) if description_el else None,
            price=price,
            discount_text=discount_text,
            valid_from=valid_from,
            valid_until=valid_until,
        ))
    return offers


def _resolve_store_offers_url(plz: str) -> str:
    """Löst eine PLZ über die Marktsuche auf die Angebotsseite der ersten
    gefundenen Filiale auf (Marktsuche sortiert nach Entfernung). Wirft, wenn
    keine Filiale gefunden wurde - Fehler werden nicht verschluckt.

    Der Filiale-Link wird NICHT per Regex über den kompletten Seiten-Text
    gesucht, sondern gezielt innerhalb des Trefferlisten-Containers
    (`#results-wrapper`, siehe Modul-Docstring). Ein früherer Ansatz, der
    `/maerkte/(\\d+)/angebote` über response.text gesucht hat, hätte den
    ERSTEN Treffer irgendwo auf der Seite genommen - z.B. einen "Mein
    Markt"-Schnellzugriff-Link im Header, der mit der eigentlichen
    PLZ-Suche nichts zu tun hat, und damit still eine völlig falsche
    Filiale zurückgeben können (nicht nur "nicht garantiert die nächste",
    sondern potenziell eine völlig unabhängige Filiale ohne jeden Bezug
    zur gesuchten PLZ). Fehlt der Container (Seitenstruktur geändert),
    wird das als Fehler behandelt statt stillschweigend auf die komplette
    Seite zurückzufallen."""
    response = httpx.get(_STORE_SEARCH_URL.format(plz=plz), timeout=15, follow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    results_container = soup.select_one(_STORE_SEARCH_RESULTS_SELECTOR)
    if results_container is None:
        raise ValueError(
            f"Trefferlisten-Container '{_STORE_SEARCH_RESULTS_SELECTOR}' der "
            f"Marktsuche für PLZ {plz} nicht gefunden - Seitenstruktur hat "
            f"sich vermutlich geändert (kein automatischer Fallback auf die "
            f"gesamte Seite, um keine falsche Filiale zu riskieren)."
        )
    link = results_container.find("a", href=_STORE_OFFERS_URL_RE)
    if link is None:
        raise ValueError(f"Keine Edeka-Filiale für PLZ {plz} gefunden (Marktsuche lieferte keinen Treffer)")
    match = _STORE_OFFERS_URL_RE.search(link["href"])
    return _STORE_OFFERS_URL.format(store_id=match.group(1))


def fetch_offers(plz: str, store_url: str | None = None) -> list[OfferData]:
    url = store_url or _resolve_store_offers_url(plz)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    return _parse_offers_html(response.text)
