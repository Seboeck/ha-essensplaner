"""Prüft essensplaner/config.yaml auf gültiges YAML und HA-Add-on-Pflichtfelder."""
import sys

import yaml

REQUIRED_KEYS = [
    "name",
    "version",
    "slug",
    "description",
    "arch",
    "ingress",
    "ingress_port",
    "options",
    "schema",
]


def main() -> int:
    with open("essensplaner/config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        print("FEHLER: config.yaml enthält kein gültiges YAML-Mapping")
        return 1

    missing = [key for key in REQUIRED_KEYS if key not in config]
    if missing:
        print(f"FEHLER: Pflichtfelder fehlen in config.yaml: {', '.join(missing)}")
        return 1

    if not isinstance(config["arch"], list) or not config["arch"]:
        print("FEHLER: 'arch' muss eine nicht-leere Liste sein")
        return 1

    if not isinstance(config["ingress_port"], int):
        print("FEHLER: 'ingress_port' muss eine Zahl sein")
        return 1

    print(f"config.yaml OK: {config['name']} v{config['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
