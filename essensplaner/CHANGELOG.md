# Changelog

Alle nennenswerten Änderungen an diesem Add-on werden hier dokumentiert.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

## [0.2.1] - 2026-08-29

### Geändert

- DB-Speicherort von `/data/essensplaner.db` auf `/share/essensplaner/essensplaner.db`
  verschoben. `/data` wird vom Supervisor beim Deinstallieren des Add-ons gelöscht,
  `/share` (bereits über `map: share:rw` gemountet) übersteht das. Damit gehen
  Rezepte/Wochenplan nicht mehr verloren, wenn das Add-on für ein Update
  deinstalliert und neu installiert werden muss.

## [0.2.0] - 2026-08-29

### Hinzugefügt

- Einstellungsseite (`/`, statisches HTML unter `app/static/`): Kalender- und
  To-do-Entity werden per Dropdown aus den tatsächlich in Home Assistant
  vorhandenen Entities ausgewählt (`GET/POST /api/settings`), statt nur über
  die Add-on-Optionen (die einen Neustart erfordern) fest hinterlegt zu sein.
  Neue `settings`-Tabelle in der DB als Ablage; Fallback auf die bisherigen
  `CALENDAR_ENTITY`/`TODO_ENTITY`-Add-on-Optionen, falls noch nichts gespeichert ist.

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
