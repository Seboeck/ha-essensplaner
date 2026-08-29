# Essensplaner – Home Assistant Add-on (Grundgerüst V1)

Dieses Grundgerüst enthält die Kernfunktionen:
- Rezeptverwaltung (API) mit Zutatenlisten
- Wochenplan-Generator (abwechslungsreich, Favoriten häufiger, keine Wiederholung/Woche)
- Anbindung an Home Assistant: Kalender (`calendar.essensplan`), To-do-Liste (Bring!-Sync)
- Aggregierte Einkaufsliste

Foto-Import (Rezepte) und Kühlschrank-Erkennung sind als Platzhalter markiert (V2).

## Installation als lokales Add-on

1. Repository/Ordner auf deinem HA-Server unter `/addons/essensplaner` ablegen
   (bei HA OS z.B. per Samba-Share oder SSH-Add-on in den `addons`-Ordner kopieren).
2. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → oben rechts „⋮" → Repositories**
   → lokalen Ordner als Repository hinzufügen (oder GitHub-Repo, falls du es dort hostest).
3. Das Add-on „Essensplaner" erscheint in der Liste → Installieren → Starten.
4. Über die Sidebar (Ingress) öffnet sich die Weboberfläche direkt in Home Assistant.

## Vorbereitung in Home Assistant

Bevor das Add-on vollständig nutzbar ist, folgende Helfer/Entitäten einmalig anlegen:

1. **Local Calendar Integration** hinzufügen → Entity-ID `calendar.essensplan`
   (Einstellungen → Geräte & Dienste → Integration hinzufügen → „Local Calendar")
2. **Bring!-Integration** hinzufügen (siehe home-assistant.io/integrations/bring) →
   liefert die To-do-Entity, z.B. `todo.einkaufen` (Namen ggf. in der Add-on-Konfiguration anpassen)
3. Optional für schnelles Tauschen im Dashboard: `input_select`-Helper pro Wochentag anlegen

## Nächste Schritte (Entwicklung)

- [ ] Vision-Import für Rezeptfotos implementieren (`/api/recipes/import-photo`),
      inkl. Review-Schritt für handschriftliche Rezepte
- [ ] Einfaches Web-UI für Rezeptverwaltung, Wochenplan-Ansicht und Foto-Upload
- [ ] Lovelace-Dashboard-Card (Kalender-Card oder Markdown-Tabelle) einrichten
- [ ] V2: Kühlschrank-Fotoerkennung mit Rezeptvorschlägen

## Lokale Entwicklung/Test ohne HA

```bash
cd app
pip install -r ../requirements.txt
export DB_PATH=./test.db
export HA_URL=http://localhost  # Dummy, HA-Calls schlagen lokal fehl, das ist ok zum Testen der Rezept-API
uvicorn main:app --reload --port 8099
```
