# Essensplaner – Projektspezifikation

## Ziel
Home-Assistant-OS-Add-on zur Digitalisierung eigener Rezepte, automatischer
Wochenplanung und Einkaufslisten-Erstellung, mit Anbindung an bestehende
Home-Assistant-Funktionen.

## Architektur
- Läuft als eigenes **HA-Add-on** (Docker-Container, Ingress-UI direkt in HA
  eingebettet, siehe `config.yaml`)
- Eigene **SQLite-Datenbank** im Add-on für Rezepte, Zutaten, Wochenplan
  (nicht in HA's eigener Storage – siehe Begründung unten)
- Backend: Python/FastAPI
- Home Assistant wird nur für **Anzeige & bestehende Integrationen** genutzt,
  nicht als primärer Datenspeicher für Rezepte

### Warum Rezepte nicht in HA selbst gespeichert werden
HA hat keine native Datenstruktur für verschachtelte Objekte (Rezept mit
Zutatenliste + Bild + Anleitung). Eine eigene Speicherung wäre technisch
möglich, aber unnötig aufwändig. Stattdessen: eigene DB im Add-on, dafür aber
komplett innerhalb von HA installiert/verwaltet (Add-on-Store), fühlt sich
also "wie ein Teil von HA" an.

## Bereits vorhandenes Grundgerüst
Ein lauffähiges Grundgerüst existiert bereits (siehe `essensplaner-addon.zip`
im Repo-Root nach dem Auspacken):
- `config.yaml`, `Dockerfile`, `run.sh` – Add-on-Setup
- `app/models.py` – SQLAlchemy-Modelle: `Recipe`, `Ingredient`, `PlanEntry`
- `app/database.py` – DB-Init
- `app/ha_client.py` – Kalender-Events, Bring!-To-do, `input_select`-Update
- `app/planner.py` – Wochenplan-Algorithmus
- `app/main.py` – FastAPI-Endpunkte (CRUD Rezepte, Plan generieren/tauschen,
  Einkaufsliste pushen)
- `README.md` – Setup-Anleitung

**Wichtig:** Dieses Grundgerüst bitte als Ausgangsbasis nehmen und erweitern,
nicht neu schreiben.

## Home-Assistant-Voraussetzungen (beim Nutzer bereits geplant)
- **Local Calendar Integration** → Entity `calendar.essensplan`
- **Bring!-Integration** → To-do-Entity (Name konfigurierbar, Default
  `todo.einkaufen`), synct automatisch mit der Bring!-App
- Optional: `input_select`-Helper pro Wochentag für schnelles Tauschen im
  Dashboard

## Funktionsumfang V1 (Kernfunktionen – zuerst umsetzen)
1. **Rezeptverwaltung**
   - Anlegen/Bearbeiten/Löschen (API vorhanden, Web-UI fehlt noch)
   - Foto-Import: ca. 100 Rezepte zu digitalisieren, gemischt aus gedruckten
     HelloFresh-Rezeptkarten und komplett handschriftlichen Rezepten
   - Nutzung von Claude Vision (Anthropic API) zur Erkennung
   - **Review-Schritt vor dem Speichern ist Pflicht**, besonders bei
     handschriftlichen Rezepten (Fehlerquote höher)
   - Start: größerer Batch-Import, danach einzelne Rezepte nach und nach
2. **Wochenplanung**
   - Ein Hauptgericht pro Tag, 7 Tage
   - Portionsgröße: fix für 2 Erwachsene + 2 Kinder (6 und 4 Jahre)
   - Algorithmus: gewichteter Zufall – Favoriten häufiger, aber **keine
     Wiederholung eines Rezepts innerhalb derselben Woche**
   - Plan muss editierbar sein (einzelne Tage austauschbar)
3. **Anzeige**
   - Wochenplan wird als Events in `calendar.essensplan` geschrieben
   - Dashboard-Anzeige über HA-Kalender-Card oder Markdown-Tabelle
   - Schnelles Tauschen direkt im Dashboard via `input_select`-Helper pro Tag
4. **Einkaufsliste**
   - Automatische Aggregation aller Zutaten der Wochenplan-Rezepte
     (gleiche Zutat+Einheit wird summiert)
   - Übertragung in HA-To-do-Liste → synct automatisch mit Bring!

## Funktionsumfang V2 (nach V1, iterativ)
1. **Kühlschrank-Fotoerkennung**
   - Foto vom Kühlschrankinhalt → Vision-Modell erkennt sichtbare Produkte
   - Erkennung als Vorschlag mit Korrekturmöglichkeit (nie blind übernehmen)
   - Darauf basierend: Rezeptvorschläge, die zum vorhandenen Inhalt passen
2. **Kaufland-Angebote**
   - Keine offizielle öffentliche API vorhanden → eigener Scraper für die
     öffentliche Kaufland-Angebotsseite (wöchentlicher Cron-Job)
   - Neue Tabelle `offers` (Produktname, Rabatt, Gültigkeitszeitraum)
   - Fuzzy-Matching zwischen Angeboten und Rezept-Zutaten
   - Rezepte mit passenden Angebots-Zutaten bekommen zusätzlichen
     Gewichtsbonus im Planungsalgorithmus
   - Hinweis: Scraper ist fragiler als eine echte API – Wartungsaufwand bei
     Seitenänderungen einplanen

## Offene Punkte für die Umsetzung mit Claude Code
- Web-UI für Rezeptverwaltung, Foto-Upload, Wochenplan-Ansicht fehlt noch
  komplett (aktuell nur REST-API)
- Vision-Import-Endpunkt (`/api/recipes/import-photo`) ist nur Platzhalter
- Lovelace-Dashboard-Card muss noch konkret gebaut werden
- Gegen echte HA-Instanz des Nutzers testen (Claude Code hat dafür lokalen
  Zugriff, im Gegensatz zur Sandbox-Umgebung des vorherigen Chats)
