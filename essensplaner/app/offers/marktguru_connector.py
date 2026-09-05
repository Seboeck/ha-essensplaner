"""Fragt die inoffizielle Marktguru-API nach Angeboten für eine PLZ ab,
gefiltert auf die Händler Kaufland und Edeka. Inoffiziell/undokumentiert —
bewusst redundant zu den eigenen Scrapern (kaufland_scraper.py,
edeka_scraper.py), damit über mehrere Wochen verglichen werden kann,
welche Quelle zuverlässiger ist (siehe Spec).

Live-Verifikation am 2026-09-04 (Task 8, Step 5) gegen die echte API. Die
im Brief angenommene Struktur war in mehreren Punkten falsch:

- Der angenommene Endpoint `api/v3/offers/search` existiert NICHT
  (`400 UnsupportedApiVersion`). Die tatsächlich aktive Version ist
  `api/v1/offers/search` (v2 existiert ebenfalls, liefert aber wie v1 nur
  `401 Invalid or missing api key` ohne Auth-Header).
- Die API verlangt Auth über die Header `x-apikey` / `x-clientkey`. Es
  handelt sich dabei NICHT um ein persönliches, geheimes API-Secret,
  sondern um öffentliche Client-Keys, die die marktguru.de-Website selbst
  bei jedem Seitenaufruf im HTML einbettet (`<script
  type="application/json">` mit `config.apiKey` / `config.clientKey`) und
  die jeder Browser-Client automatisch mitschickt. Es ist daher KEIN
  zusätzliches `Settings`-Feld für einen Nutzer-API-Key nötig (anders als
  im Brief antizipiert) — `_get_api_keys()` holt sich die Keys stattdessen
  live von der Startseite. Bekanntes Risiko: ändert Marktguru diesen
  Mechanismus (z.B. serverseitiges Rendering ohne den Config-Block), bricht
  die Auth; das wird nie verschluckt (Fehler propagieren wie bei den
  anderen Connectors).
- Wichtigster struktureller Unterschied: `offers/search` ist eine
  **Produktsuche**, kein "gib mir alle aktuellen Angebote für PLZ X"-
  Endpoint. Der Parameter `q` ist PFLICHT — ein leerer oder fehlender `q`
  liefert immer `{"totalResults": 0, "results": null}`, unabhängig von der
  PLZ. Es gibt keinen Wildcard-Wert, der "alle Angebote" liefert (getestet:
  leerer String, "*", Leerzeichen, `allowedRetailers` ohne `q` — alle ohne
  Treffer). Um die Kaufland-/Edeka-Angebote einer PLZ näherungsweise
  vollständig abzudecken, iteriert `fetch_offers` daher über eine feste
  Liste breiter Lebensmittel-Suchbegriffe (`_SEARCH_TERMS`) und dedupliziert
  die Treffer über die Angebots-`id`. Das ist eine bewusste Näherung, KEINE
  vollständige Angebotsliste wie bei den eigenen Kaufland-/Edeka-Scrapern —
  Angebote zu Begriffen außerhalb der Liste werden nicht gefunden. Für den
  Zweck dieses Connectors (redundante Vergleichsquelle, siehe Spec) ist das
  akzeptabel, sollte aber bei Abweichungen zu den anderen Quellen als
  Ursache in Betracht gezogen werden.
- Response-Shape: Angebote stehen unter `results` (nicht `offers`), Preise
  sind bereits JSON-Zahlen (kein Komma-String), der Händlername steht
  nicht als flaches `retailer`-Feld, sondern als Liste `advertisers`
  (`{"uniqueName": "kaufland", "name": "Kaufland", ...}` — `uniqueName`
  ist der stabile, kleingeschriebene Bezeichner). `edeka` und `kaufland`
  sind live bestätigt als exakte `uniqueName`-Werte (z.B. PLZ 80331/50667
  für Edeka, praktisch jede getestete PLZ für Kaufland — Edeka scheint
  nicht in jeder Region auf Marktguru vertreten zu sein, z.B. PLZ 10115
  Berlin-Mitte lieferte in keinem Test einen Edeka-Treffer).
  Es gibt kein fertiges `discount`-Textfeld wie im Brief angenommen —
  stattdessen `price` (Float) und optional `oldPrice` (Float | null);
  `_compute_discount_text` berechnet daraus einen Prozent-Text analog zum
  Format der eigenen Scraper. Der Produktname steht in `product.name`
  (Fallback: `description`, z.B. bei fehlendem `product`-Objekt).
  Gültigkeitszeiträume stehen unter `validityDates` (Liste, i.d.R. ein
  Eintrag) als ISO-Datumszeit mit Uhrzeit/Zeitzone (z.B.
  "2026-09-09T22:00:00Z") statt reinem Datum — nur der Datumsteil wird
  übernommen.
"""
import json
import re
from datetime import date

import httpx

from offers.base import OfferData

SOURCE = "marktguru"
_HOMEPAGE_URL = "https://marktguru.de"
_SEARCH_URL = "https://api.marktguru.de/api/v1/offers/search"
_CONFIG_SCRIPT_RE = re.compile(
    r'<script\s+type="application/json">(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_RELEVANT_RETAILERS = {"kaufland": "kaufland", "edeka": "edeka"}

# offers/search verlangt zwingend einen nicht-leeren Suchbegriff `q` (siehe
# Modul-Docstring) - es gibt keinen "alle Angebote"-Modus. Diese Liste
# breiter Lebensmittel-Kategorien deckt die Kaufland-/Edeka-Angebote einer
# PLZ näherungsweise ab, ohne den Anspruch auf Vollständigkeit.
_SEARCH_TERMS = [
    "milch", "butter", "käse", "joghurt", "kaffee", "fleisch", "wurst",
    "brot", "obst", "gemüse", "getränke", "wasser", "waschmittel",
    "schokolade", "nudeln", "reis", "tiefkühl",
]


def _get_api_keys() -> tuple[str, str]:
    """Holt `apiKey`/`clientKey` live aus dem im HTML der Marktguru-
    Startseite eingebetteten Config-Block (öffentliche Client-Keys, siehe
    Modul-Docstring). Wirft, wenn der Block nicht gefunden/geparst werden
    kann - kein stiller Fallback."""
    response = httpx.get(_HOMEPAGE_URL, timeout=15, follow_redirects=True)
    response.raise_for_status()
    for match in _CONFIG_SCRIPT_RE.finditer(response.text):
        try:
            block = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        config = block.get("config") if isinstance(block, dict) else None
        if isinstance(config, dict) and "apiKey" in config and "clientKey" in config:
            return config["apiKey"], config["clientKey"]
    raise ValueError(
        "Marktguru-Config-Block (config.apiKey/config.clientKey) nicht auf "
        "der Startseite gefunden - Seitenstruktur hat sich vermutlich "
        "geändert."
    )


def _compute_discount_text(price: float | None, old_price: float | None) -> str | None:
    if price is None or not old_price:
        return None
    if old_price <= 0 or price >= old_price:
        return None
    percent = round((old_price - price) / old_price * 100)
    return f"-{percent}%"


def _parse_validity(validity_dates: list | None) -> tuple[date, date] | None:
    if not validity_dates:
        return None
    entry = validity_dates[0]
    from_raw, to_raw = entry.get("from"), entry.get("to")
    if not from_raw or not to_raw:
        return None
    try:
        return date.fromisoformat(from_raw[:10]), date.fromisoformat(to_raw[:10])
    except ValueError:
        return None


def _parse_response(payload: dict) -> list[OfferData]:
    offers: list[OfferData] = []
    for raw in payload.get("results") or []:
        advertisers = raw.get("advertisers") or []
        retailer = None
        for advertiser in advertisers:
            retailer = _RELEVANT_RETAILERS.get((advertiser.get("uniqueName") or "").strip().lower())
            if retailer:
                break
        if retailer is None:
            continue

        validity = _parse_validity(raw.get("validityDates"))
        if not validity:
            continue
        valid_from, valid_until = validity

        product = raw.get("product") or {}
        product_name = (product.get("name") or raw.get("description") or "").strip()

        offers.append(OfferData(
            retailer=retailer,
            product_name=product_name,
            price=raw.get("price"),
            discount_text=_compute_discount_text(raw.get("price"), raw.get("oldPrice")),
            valid_from=valid_from,
            valid_until=valid_until,
        ))
    return offers


def fetch_offers(plz: str, store_url: str | None = None) -> list[OfferData]:
    api_key, client_key = _get_api_keys()
    headers = {"x-apikey": api_key, "x-clientkey": client_key}

    # `q` ist Pflicht (siehe Modul-Docstring) - über mehrere breite Begriffe
    # iterieren und über die Angebots-`id` deduplizieren, um eine
    # Näherung an "alle Kaufland-/Edeka-Angebote der PLZ" zu bekommen.
    #
    # Läuft unbeaufsichtigt als wöchentlicher Cron-Job: Ein einzelner
    # flakiger Suchbegriff (Timeout, transientes 5xx) soll nicht den
    # gesamten Lauf und damit alle bereits erfolgreich abgefragten
    # Begriffe verwerfen. Fehler pro Begriff werden daher abgefangen und
    # der Lauf wird mit den verbleibenden Begriffen fortgesetzt
    # (graceful degradation). Nur wenn AUSNAHMSLOS jeder Begriff
    # fehlschlägt, ist das ein echter Totalausfall und muss wie bei den
    # anderen Connectors propagiert werden (nie still `[]` zurückgeben -
    # das wäre nicht von "diese Woche keine Angebote" unterscheidbar).
    merged_by_id: dict[object, dict] = {}
    failed_terms: list[tuple[str, Exception]] = []
    for term in _SEARCH_TERMS:
        try:
            response = httpx.get(
                _SEARCH_URL,
                headers=headers,
                params={"as": "web", "q": term, "limit": 50, "offset": 0, "zipCode": plz},
                timeout=15,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
        except httpx.HTTPError as exc:
            failed_terms.append((term, exc))
            continue
        for raw in results:
            merged_by_id[raw.get("id")] = raw

    if failed_terms and len(failed_terms) == len(_SEARCH_TERMS):
        last_term, last_exc = failed_terms[-1]
        raise RuntimeError(
            f"Marktguru-Abfrage komplett fehlgeschlagen: alle "
            f"{len(_SEARCH_TERMS)} von {len(_SEARCH_TERMS)} Suchbegriffen "
            f"schlugen fehl (zuletzt '{last_term}': {last_exc})."
        ) from last_exc

    if failed_terms:
        print(
            f"[marktguru_connector] {len(failed_terms)} von "
            f"{len(_SEARCH_TERMS)} Suchbegriffen fehlgeschlagen "
            f"({', '.join(term for term, _ in failed_terms)}); fahre mit "
            f"den übrigen {len(_SEARCH_TERMS) - len(failed_terms)} Treffern fort."
        )

    return _parse_response({"results": list(merged_by_id.values())})
