# Changelog

Alle nennenswerten Änderungen an diesem Add-on werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

## [0.1.1] - 2026-08-29

### Behoben

- `calendar/create_event`-Aufruf schlug fehl, weil `end_date` gleich `start_date`
  gesetzt wurde (HA verlangt ein exklusives Enddatum nach dem Startdatum) –
  Wochenplan-Generierung schrieb dadurch keine Kalender-Events.

## [0.1.0] - 2026-08-29

### Hinzugefügt

- Erstes Grundgerüst: Rezeptverwaltung (API), Wochenplan-Generator
  (Favoriten häufiger, keine Wiederholung pro Woche), Home-Assistant-Anbindung
  (Kalender, Bring!-To-do), aggregierte Einkaufsliste
