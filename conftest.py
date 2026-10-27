"""Sorgt dafür, dass ein einfaches `pytest` im Programmordner die Module findet und
die Oberflächen-Tests ohne Bildschirm übersprungen statt abgestürzt werden."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Unter Linux ohne Bildschirm (z.B. Server) kann VTK kein Fenster öffnen
KEIN_BILDSCHIRM = sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def pytest_ignore_collect(collection_path, config):
    if KEIN_BILDSCHIRM and collection_path.name == "test_gui.py":
        print("\ntests/test_gui.py übersprungen: kein Bildschirm (unter Linux mit xvfb-run starten)")
        return True
    return None
