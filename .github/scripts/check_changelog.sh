#!/usr/bin/env bash
# Erzwingt: wer app/-Code oder config.yaml ändert, muss auch CHANGELOG.md
# aktualisieren und die 'version' in config.yaml erhöhen.
set -euo pipefail

ZERO_SHA="0000000000000000000000000000000000000000"

if [ -z "${BASE_SHA:-}" ] || [ "$BASE_SHA" = "$ZERO_SHA" ]; then
  echo "Kein Vergleichs-Commit verfügbar (z.B. neuer Branch) – Changelog-Check übersprungen."
  exit 0
fi

CHANGED=$(git diff --name-only "$BASE_SHA" "$HEAD_SHA")
echo "Geänderte Dateien:"
echo "$CHANGED"

CODE_CHANGED=$(echo "$CHANGED" | grep -E '^essensplaner/(app/|config\.yaml)' || true)

if [ -z "$CODE_CHANGED" ]; then
  echo "Keine relevanten Code-/Config-Änderungen – Changelog-Check übersprungen."
  exit 0
fi

if ! echo "$CHANGED" | grep -qx "essensplaner/CHANGELOG.md"; then
  echo "FEHLER: app/-Code oder config.yaml wurden geändert, aber essensplaner/CHANGELOG.md nicht aktualisiert."
  exit 1
fi

OLD_VERSION=$(git show "$BASE_SHA:essensplaner/config.yaml" | grep '^version:' | head -1)
NEW_VERSION=$(git show "$HEAD_SHA:essensplaner/config.yaml" | grep '^version:' | head -1)

if [ "$OLD_VERSION" = "$NEW_VERSION" ]; then
  echo "FEHLER: Code wurde geändert, aber die 'version' in config.yaml wurde nicht erhöht."
  exit 1
fi

echo "Changelog-Check OK: $OLD_VERSION -> $NEW_VERSION"
