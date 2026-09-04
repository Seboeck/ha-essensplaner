# Angebote (Kaufland/Edeka) — Design

## Ziel

Aktuelle Angebote von Kaufland und Edeka (lokale Filiale, per PLZ ermittelt)
übersichtlich im Add-on anzeigen, mit besonderer Hervorhebung von Artikeln,
die regelmäßig benötigt werden. Passende Angebote fließen zusätzlich mit
einem Gewichtsbonus in die automatische Wochenplanung ein (wie in der
ursprünglichen V2-Spec für Kaufland skizziert, hier erweitert um Edeka und
einen zweiten Datenkanal).

Dies ist eine Erweiterung des bestehenden Grundgerüsts
(`essensplaner/CLAUDE.md`, Abschnitt "Funktionsumfang V2 — Kaufland-Angebote"),
nicht dessen Ersatz.

## Nicht-Ziele

- Keine Preisvergleichs- oder Kaufhistorien-Funktion.
- Keine automatische Bestellung/Reservierung — nur Anzeige + Planungs-Bonus.
- Keine Unterstützung weiterer Händler in diesem Schritt (Architektur soll
  es aber nicht erschweren, später einen weiteren Connector zu ergänzen).

## Datenmodell (neue Tabellen in `app/models.py`)

### `Offer`
| Feld | Typ | Bedeutung |
|---|---|---|
| id | Integer PK | |
| retailer | String | `kaufland` \| `edeka` |
| source | String | `kaufland_scraper` \| `edeka_scraper` \| `marktguru` |
| product_name | String | wie vom Connector geliefert |
| description | String, nullable | optionaler Zusatztext |
| price | Float, nullable | Angebotspreis, falls vorhanden |
| discount_text | String, nullable | z.B. "-30%", falls kein fester Preis |
| valid_from | Date | |
| valid_until | Date | |
| notified_at | DateTime, nullable | gesetzt, sobald einmal per HA-Notification gemeldet |
| scraped_at | DateTime | Zeitpunkt des Connector-Laufs |

### `WatchlistItem`
| Feld | Typ | Bedeutung |
|---|---|---|
| id | Integer PK | |
| name | String, unique | Artikelname |
| unit | String, nullable | optional |

Eigenständige Liste für Artikel, die häufig gekauft werden, aber nicht
dauerhaft im Kühlschrank sind (z.B. Mehl, Waschmittel). Ergänzt die
bestehende `FridgeStaple`-Tabelle; beide zusammen bilden die Menge der
"regelmäßig benötigten Artikel" für die Hervorhebung.

### `OfferSourceConfig`
| Feld | Typ | Bedeutung |
|---|---|---|
| id | Integer PK | |
| source | String, unique | `kaufland_scraper` \| `edeka_scraper` \| `marktguru` |
| enabled | Boolean, default True | |
| schedule_weekday | Integer, nullable | 0=Montag..6=Sonntag |
| schedule_hour | Integer, nullable | 0–23 |
| last_run_at | DateTime, nullable | |
| last_status | String, nullable | `ok` \| Fehlertext |

### `Settings` (Erweiterung bestehender Tabelle)
Neue Felder: `plz` (String), `kaufland_store_url` (String, nullable, Fallback),
`edeka_store_url` (String, nullable, Fallback).

## Connectors

Neues Package `app/offers/` mit gemeinsamem Interface:

```python
def fetch_offers(plz: str, store_url: str | None = None) -> list[OfferData]:
    ...
```

- `app/offers/kaufland_scraper.py` — scraped die öffentliche
  Kaufland-Angebotsseite der über PLZ ermittelten Filiale; nutzt
  `kaufland_store_url` als Fallback, falls die PLZ-Zuordnung nicht
  funktioniert.
- `app/offers/edeka_scraper.py` — analog für die (dezentrale) Edeka-Region;
  Fallback-URL hier voraussichtlich wichtiger als bei Kaufland.
- `app/offers/marktguru_connector.py` — fragt die inoffizielle
  Marktguru-API nach PLZ ab, gefiltert auf Kaufland und Edeka als Händler.

Alle drei laufen parallel und unabhängig; jeder schreibt seine Treffer mit
eigenem `source`-Tag in dieselbe `Offer`-Tabelle. Ziel: über mehrere Wochen
vergleichen, welche Quelle vollständiger/zuverlässiger ist, ohne dass sich
die Ansätze gegenseitig ausschließen. Ein Connector-Lauf ersetzt alle
`Offer`-Zeilen seines eigenen `source`-Werts (kein Merge nötig, da Angebote
wöchentlich neu sind).

Scraper sind laut ursprünglicher Spec fragiler als eine echte API — jeder
Lauf schreibt Erfolg/Fehler in `OfferSourceConfig.last_status`, sichtbar in
der UI.

## Scheduling

In-Process-Scheduler (APScheduler) beim Add-on-Start, ein Job pro Eintrag
in `OfferSourceConfig` mit `enabled=True`, ausgeführt zu
`schedule_weekday`/`schedule_hour`. Jede Quelle einzeln konfigurierbar
(an/aus, Zeitpunkt) — kein gemeinsamer fester Cron für alle drei.

Zusätzlich: manueller Trigger-Endpoint `POST /api/offers/refresh/{source}`
für Tests und Ad-hoc-Läufe.

## Fuzzy-Matching

Neues Modul `app/offers/matching.py`, nutzt `rapidfuzz` (neue Dependency in
`requirements.txt`). Matcht `Offer.product_name` gegen:

1. alle `Ingredient.name` aktiver Rezepte → Ergebnis: Liste passender
   Rezept-IDs (für Planer-Bonus)
2. `FridgeStaple.name` ∪ `WatchlistItem.name` → Ergebnis: Boolean
   `matched_watchlist` (für UI-Hervorhebung und Benachrichtigung)

Score-Schwelle konfigurierbar, Startwert 80 (rapidfuzz `token_sort_ratio`).
Matching läuft on-demand beim Abruf der Angebotsliste bzw. direkt nach
einem Connector-Lauf (Ergebnis wird nicht persistiert, da Rezeptbestand
sich ändern kann — Neuberechnung ist bei der erwarteten Datenmenge
günstig genug).

## Planer-Integration

`app/planner.py`: neue Konstante `OFFER_WEIGHT_BONUS` (additiv, nicht
exklusiv zum Favoriten-Bonus). Für jedes Rezept wird geprüft, ob mindestens
eine Zutat zu einem aktuell gültigen Angebot passt (via Matching-Modul);
falls ja, wird der Gewichtswert um `OFFER_WEIGHT_BONUS` erhöht. Ein
favorisiertes Rezept mit passender Angebots-Zutat hat damit das höchste
Gewicht.

## Benachrichtigung

`app/ha_client.py`: neue Funktion `notify(message: str)`, ruft den in
`config.yaml`/Settings konfigurierten Notify-Service (`notify.notify` oder
`persistent_notification.create`) über die bestehende `_post`-Hilfsfunktion
auf.

Nach jedem Connector-Lauf: alle neuen Angebote mit `matched_watchlist=True`
und `notified_at IS NULL` werden zu **einer** Sammel-Benachrichtigung pro
Lauf zusammengefasst (keine Einzel-Notification pro Artikel). Anschließend
wird `notified_at` gesetzt, damit dasselbe Angebot nicht erneut meldet.

## UI

Neuer Tab "Angebote" in `app/static/index.html`, analog zum bestehenden
Kühlschrank-Tab:

- Liste gruppiert nach Händler (Kaufland / Edeka)
- Sortierung: Treffer auf Standard-/Merklisten-Artikel zuerst (visuell
  hervorgehoben), danach chronologisch nach `valid_until`
- Filter-Dropdown nach `source`, um die drei Kanäle einzeln zu betrachten
  (Vergleichszeitraum)
- Verwaltungsbereich für `WatchlistItem` (hinzufügen/entfernen), analog zum
  bestehenden `FridgeStaple`-UI
- Einstellungsbereich: PLZ, Fallback-Store-URLs, pro Quelle An/Aus +
  Zeitplan, Anzeige von `last_run_at`/`last_status`

## API-Endpunkte (neu, `app/main.py`)

- `GET /api/offers` — Liste, Filterparameter `retailer`, `source`
- `POST /api/offers/refresh/{source}` — manueller Connector-Lauf
- `GET/POST/DELETE /api/watchlist` — CRUD für `WatchlistItem`
- `GET/PUT /api/offers/sources` — `OfferSourceConfig` lesen/ändern
- `PUT /api/settings` — Erweiterung um `plz`, `kaufland_store_url`,
  `edeka_store_url` (bestehender Endpoint, nur neue Felder)

## Testing

- Connectors: Unit-Tests mit gespeicherten Beispiel-HTML/JSON-Fixtures
  (kein Live-Scraping in Tests)
- Matching: Unit-Tests mit bekannten Ingredient-/Angebots-Paaren
  (True/False-Positive-Fälle)
- Planer-Bonus: bestehende Tests in `planner.py`-Umfeld erweitern
- Manuelle Prüfung gegen echte HA-Instanz: Notification kommt an,
  Scheduler-Läufe erscheinen korrekt in `OfferSourceConfig`

## Offene Risiken

- Scraper-Fragilität bei Layout-Änderungen (bekanntes Risiko, in Spec
  bereits vermerkt) — `last_status` macht Ausfälle sichtbar
- Marktguru-API ist inoffiziell/undokumentiert — Verhalten kann sich
  ändern; deshalb bewusst redundant zu den eigenen Scrapern
- Edeka-PLZ-Zuordnung unsicher (dezentrale Struktur) — Fallback-URL als
  Sicherheitsnetz vorgesehen
