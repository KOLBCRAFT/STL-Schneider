"""Speichert eigene Drucker-Profile und Einstellungen in einer JSON-Datei im Benutzerordner.

Windows: %APPDATA%\\STL-Schneider\\einstellungen.json, sonst ~/.config/stl-schneider/einstellungen.json.
Die Datei liegt außerhalb des Programmordners, damit sie beim Aktualisieren erhalten bleibt.
"""
import json
import os
from pathlib import Path


def pfad():
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "STL-Schneider" / "einstellungen.json"
    return Path.home() / ".config" / "stl-schneider" / "einstellungen.json"


def lade():
    daten = {}
    try:
        daten = json.loads(pfad().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    daten.setdefault("profile", {})
    return daten


def speichere(daten):
    try:
        p = pfad()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
