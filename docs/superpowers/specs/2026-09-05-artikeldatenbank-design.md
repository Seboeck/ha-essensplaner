# Artikeldatenbank (Bilder, Preis-Historie, Dublettenprüfung) — Design

## Ziel

Rezept-Zutaten, Standard-Kühlschrankartikel, Merklisten-Artikel und der
aktuelle Kühlschrank-Bestand verweisen künftig auf eine gemeinsame,
kanonische **Artikeldatenbank** statt auf Freitext-Namen. Jeder Artikel
trägt ein Bild (automatisch aus einem passenden Angebot übernommen) und
eine Preis-Historie (wann zu welchem Preis/Rabatt im Angebot). Gleiche
Artikel unter leicht unterschiedlichem Namen (z. B. andere Marke) werden
nicht automatisch zusammengeführt, sondern nur bei ausreichender
Ähnlichkeit zur Bestätigung vorgeschlagen — so bleibt die Datenbank auf
tatsächlich genutzte Artikel begrenzt (keine Angebots-Flut) und wächst
nicht unkontrolliert durch stille Fehl-Zusammenlegungen.

Dies baut auf der bestehenden Angebote-Funktion (Kaufland/Edeka/
Marktguru-Connectors, Fuzzy-Matching in `app/offers/matching.py`) auf und
erweitert sie um eine persistente Artikel-Ebene.

## Nicht-Ziele

- Keine automatische Zusammenführung bei nur ähnlichem (nicht exaktem)
  Namen — immer Bestätigung nötig, außer bei der einmaligen
  Migrations-Regel (siehe unten).
- `FridgeItem`-Mengenerfassung bleibt funktional wie bisher (Menge/Einheit
  frei editierbar) — nur der Namensteil wird durch die Artikel-Auswahl
  ersetzt.
- Keine Bildbearbeitung/-zuschnitt — das vom Händler gelieferte Bild wird
  unverändert übernommen.

## Datenmodell (neue/geänderte Tabellen in `app/models.py`)

### `Artikel` (neu)
| Feld | Typ | Bedeutung |
|---|---|---|
| id | Integer PK | |
| name | String, nullable=False | kanonischer Anzeigename |
| image_path | String, nullable | lokaler Pfad, analog `Recipe.image_path` |
| created_at | String (ISO), nullable=False | |

### `ArtikelPriceHistory` (neu)
| Feld | Typ | Bedeutung |
|---|---|---|
| id | Integer PK | |
| artikel_id | Integer, FK → `Artikel.id`, nullable=False | |
| price | Float, nullable | |
| discount_text | String, nullable | |
| retailer | String, nullable=False | `kaufland` \| `edeka` |
| source | String, nullable=False | `kaufland_scraper` \| `edeka_scraper` \| `marktguru` |
| valid_from | Date, nullable=False | |
| valid_until | Date, nullable=False | |
| recorded_at | String (ISO), nullable=False | Zeitpunkt der Verknüpfung |

### `PendingArtikelMatch` (neu)
| Feld | Typ | Bedeutung |
|---|---|---|
| id | Integer PK | |
| offer_id | Integer, FK → `Offer.id`, nullable=False | |
| artikel_id | Integer, FK → `Artikel.id`, nullable=False | Kandidat |
| score | Float, nullable=False | Match-Score (Mittel-Band, 60–79) |
| status | String, nullable=False, default `"open"` | `open` \| `confirmed` \| `rejected` |
| created_at | String (ISO), nullable=False | |

### Geänderte Tabellen
- **`Ingredient`**: `name` (String) entfernt, ersetzt durch `artikel_id`
  (Integer, FK → `Artikel.id`, nullable=False)
- **`FridgeStaple`**: `name` entfernt, ersetzt durch `artikel_id`
  (nullable=False, unique bleibt sinngemäß erhalten: ein Artikel ist
  höchstens einmal Standardartikel)
- **`WatchlistItem`**: `name` entfernt, ersetzt durch `artikel_id`
  (nullable=False, unique)
- **`FridgeItem`**: `name` entfernt, ersetzt durch `artikel_id`
  (nullable=False); `amount`/`unit` bleiben wie bisher frei editierbar

Da SQLite (siehe `database.py`) keine nachträgliche Änderung von
`NOT NULL`-Constraints auf bestehenden Spalten unterstützt, erfolgt die
Umstellung dieser vier Tabellen über eine einmalige **Migrationsroutine**
(Neuaufbau der Tabellen mit Datenübernahme), nicht über
`_migrate_add_missing_columns()`-artige `ALTER TABLE ADD COLUMN`-Schritte.

## Matching: `resolve_artikel`

Neue zentrale Funktion in `app/offers/matching.py` (oder ausgelagert nach
`app/artikel_matching.py`, falls die Datei sonst zu groß würde),
aufbauend auf der bestehenden `match_score`-Logik (token_set_ratio +
längenbegrenzter Substring-Fallback):

```python
def resolve_artikel(name: str, db: Session) -> ArtikelMatchResult:
    ...
```

Ergebnis unterscheidet drei Fälle:
- **Hoch** (Score ≥ 80 oder Substring-Treffer, Mindestlänge 4 Zeichen wie
  bisher) → eindeutiger bestehender Artikel, automatische Verknüpfung
- **Mittel** (Score 60–79) → ein oder mehrere Kandidaten, Bestätigung
  nötig (Autocomplete-Vorschlag bzw. `PendingArtikelMatch` bei Angeboten)
- **Niedrig** (< 60) → kein Treffer; im Erfassungskontext wird ein neuer
  Artikel angelegt, im Angebots-Kontext wird das Angebot ignoriert
  (wie bisher, keine Verhaltensänderung gegenüber der bestehenden
  Watchlist-/Rezept-Matching-Funktion)

`find_matching_recipe_ids` und `is_watchlist_match` (bestehend) werden
intern auf `resolve_artikel`/dieselbe Score-Funktion umgestellt, damit nur
eine Matching-Implementierung gepflegt wird.

## Migration bestehender Daten

Einmalige Migrationsroutine (läuft beim ersten Start nach dem Update,
ähnlich `_migrate_add_missing_columns()`, aber als eigener Schritt wegen
der Tabellen-Neuanlage):

1. Für jeden bestehenden, normalisierten (getrimmt, lowercased) Namen aus
   `Ingredient`, `FridgeStaple`, `WatchlistItem`, `FridgeItem` gemeinsam:
   ein `Artikel` mit dem zuerst gesehenen Original-Namen anlegen.
2. Alle vier Tabellen werden neu aufgebaut (`artikel_id` statt `name`),
   Zeilen mit demselben normalisierten Namen erhalten dieselbe
   `artikel_id`.
3. **Nur exakte (normalisierte) Übereinstimmung wird zusammengeführt.**
   Ähnliche, aber nicht identische Namen (z. B. "Gouda" vs. "Gouda
   gerieben") werden zu zwei getrennten Artikeln — spätere echte
   Doppelverwendung wird über das reguläre Mittel-Konfidenz-Matching
   (siehe oben) erkannt und kann dann manuell zusammengeführt werden
   (Merge-Funktion, siehe UI-Abschnitt).
4. Migration läuft in einer Transaktion; schlägt sie fehl, bleibt die
   alte Struktur unverändert (kein Teil-Zustand).

## Erfassung (Autocomplete, Import, Foto-Import)

- **Rezept-Zutaten & Kühlschrank-Erfassung (UI)**: Textfeld mit
  Autocomplete. `GET /api/artikel/suggest?q=` liefert Hoch- und
  Mittel-Konfidenz-Kandidaten als Dropdown-Liste, plus immer eine
  "Neuen Artikel '…' anlegen"-Option am Ende. Speichern ist nur mit
  ausgewähltem (bestehendem oder neu angelegtem) Artikel möglich —
  reiner Freitext wird nicht mehr akzeptiert.
- **JSON-Import** (`POST /api/recipes/import/apply` u. ä., bestehend):
  jeder importierte Zutatenname wird beim Import durch `resolve_artikel`
  aufgelöst. Hoch → automatisch verknüpft. Niedrig → automatisch neuer
  Artikel. Mittel → zusätzlicher Eintrag in der bestehenden
  Konflikt-Ansicht des Imports (dort existiert bereits die UI-Struktur
  für "mehrere offene Entscheidungen vor dem Abschluss").
- **Foto-Import**: gleiche Auflösung, direkt im bestehenden
  Review-Schritt vor dem Speichern (Nutzer sieht ohnehin schon jede
  Zutat zur Kontrolle).

## Angebots-Verknüpfung (Preis-Historie, Bild)

- `OfferData` (`app/offers/base.py`) bekommt ein neues Feld
  `image_url: Optional[str] = None`. Alle drei Connectors
  (`kaufland_scraper.py`, `edeka_scraper.py`, `marktguru_connector.py`)
  werden erweitert, um das Bild-Element aus der jeweiligen
  Angebots-Kachel/dem API-Feld zu extrahieren (die reale Struktur wurde
  bei der Live-Verifikation der bestehenden Angebote-Funktion bereits
  eingesehen).
- Nach jedem Connector-Lauf (`run_source` in `app/offers/runner.py`)
  wird zusätzlich zur bestehenden Watchlist-Prüfung für jedes neue
  `Offer` `resolve_artikel(offer.product_name, db)` aufgerufen:
  - **Hoch** → `ArtikelPriceHistory`-Zeile wird angelegt. Ist
    `Artikel.image_path` noch leer, wird `offer.image_url` per `httpx`
    heruntergeladen und unter `ARTIKEL_IMAGES_DIR` gespeichert (Muster
    wie `IMAGES_DIR` für Rezeptbilder in `main.py`); Download-Fehler
    werden wie Scraper-Fehler behandelt (geloggt, brechen den Lauf
    nicht ab).
  - **Mittel** → `PendingArtikelMatch`-Zeile (status `open`) wird
    angelegt statt automatisch verknüpft.
- Neuer Abschnitt **"Unsichere Zuordnungen"** im bestehenden
  Angebote-Tab zeigt offene `PendingArtikelMatch`-Einträge
  ("Angebot X könnte zu Artikel Y gehören") mit
  Bestätigen-/Ablehnen-Buttons. Bestätigen erzeugt nachträglich den
  `ArtikelPriceHistory`-Eintrag (+ ggf. Bild) und setzt `status =
  confirmed`. Ablehnen setzt `status = rejected` — dasselbe
  Angebot/Artikel-Paar wird nicht erneut vorgeschlagen.

## Artikel-Übersicht (UI)

Der bestehende Tab "Zutatenliste" (`app/static/index.html`, aktuell
Platzhalter-Tabelle mit Hinweis "Preisübersicht folgt, sobald Preise
erfasst werden können") wird zur echten Artikel-Übersicht ausgebaut:
Bild, Name, letzter bekannter Preis/Rabatt. Klick auf einen Artikel zeigt
die volle Preis-Historie (`ArtikelPriceHistory`, absteigend nach
`recorded_at`). Von hier aus ist auch die manuelle Merge-Funktion
erreichbar (zwei Artikel zusammenführen: `Ingredient`/`FridgeStaple`/
`WatchlistItem`/`FridgeItem`-Zeilen des einen werden auf den anderen
umgehängt, der überflüssige `Artikel` wird gelöscht).

## API-Endpunkte (neu, `app/main.py`)

- `GET /api/artikel` — Liste mit Bild, letztem bekannten Preis
- `GET /api/artikel/{id}` — Detail
- `GET /api/artikel/{id}/history` — `ArtikelPriceHistory`-Liste
- `GET /api/artikel/suggest?q=` — Autocomplete (Hoch + Mittel)
- `POST /api/artikel` — neuen Artikel manuell anlegen
- `POST /api/artikel/{id}/merge/{other_id}` — zwei Artikel zusammenführen
- `GET /api/artikel/pending-matches` — offene `PendingArtikelMatch`-Fälle
- `POST /api/artikel/pending-matches/{id}/confirm` — Bestätigen
- `POST /api/artikel/pending-matches/{id}/reject` — Ablehnen

Bestehende Endpunkte, die von der Umstellung betroffen sind (Signaturen
ändern sich, da `Ingredient`/`FridgeStaple`/`WatchlistItem`/`FridgeItem`
jetzt `artikel_id` statt `name` tragen):
- Rezept-CRUD (`POST/PUT /api/recipes`, `RecipeIn`/`RecipeOut`/
  `IngredientIn`) — Zutaten werden über `artikel_id` statt `name`
  referenziert
- `/api/fridge/*`, `/api/watchlist/*` — analog
- Einkaufslisten-Aggregation (`planner.aggregate_shopping_list`) — nutzt
  künftig `Ingredient.artikel.name` statt `Ingredient.name`
- Angebots-Matching (`find_matching_recipe_ids`, `is_watchlist_match`) —
  intern auf `resolve_artikel` umgestellt

## Testing

- Migration: Unit-Test mit vorbereiteter Alt-Datenbank (mehrere Rezepte
  mit teils identischen, teils ähnlichen Zutatennamen), prüft korrekte
  Zusammenführung nur bei exaktem normalisierten Namen
- `resolve_artikel`: Unit-Tests für alle drei Konfidenz-Bänder
  (Grenzfälle bei 60/80 explizit)
- Autocomplete-Endpunkt: Tests für Hoch-/Mittel-/Niedrig-Fälle
- Angebots-Verknüpfung: Tests mit gemocktem Connector-Ergebnis, prüfen
  `ArtikelPriceHistory`-Erzeugung bei Hoch, `PendingArtikelMatch` bei
  Mittel, Bild-Download (gemockt) bei erstem Treffer
- Merge-Endpunkt: Test, dass alle vier verweisenden Tabellen korrekt
  umgehängt werden und der alte Artikel gelöscht wird
- Regressionstests für Rezept-CRUD, Einkaufsliste, JSON-Import,
  Foto-Import mit der neuen `artikel_id`-Struktur

## Offene Risiken

- **Migrations-Umfang**: Vier Tabellen werden gleichzeitig umgebaut: bei
  ~100 bereits digitalisierten Rezepten ist das ein einmaliger, aber
  nicht trivialer Schritt — sorgfältiges Testen gegen eine Kopie der
  echten Datenbank vor dem Live-Einsatz empfohlen.
- **Bild-Verfügbarkeit**: Nicht jedes Angebot liefert zwangsläufig ein
  brauchbares Bild (z. B. bei Marktguru je nach Kategorie-Suchbegriff);
  manche Artikel bleiben ggf. dauerhaft ohne Bild, bis ein passendes
  Angebot mit Bild auftaucht.
- **Blast Radius im Code**: Die Umstellung auf Pflicht-`artikel_id`
  berührt Rezept-CRUD, JSON-Import, Foto-Import, Kühlschrank- und
  Merklisten-Endpunkte sowie die Einkaufslisten-Aggregation — deutlich
  größerer Umfang als die vorherige Angebote-Funktion, entsprechend wird
  der Implementierungsplan mehr Tasks umfassen.
