"""Bambu Studio finden und Dateien darin öffnen.

Gesucht wird in dieser Reihenfolge: selbst gewählter Pfad, Windows-Registry (Installationseintrag),
übliche Installationsordner, PATH. Wird nichts gefunden, liefert finde() None.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXE = "bambu-studio.exe"


def _aus_registry():
    try:
        import winreg
    except ImportError:
        return []
    treffer = []
    schluessel = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for wurzel in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for ansicht in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                haupt = winreg.OpenKey(wurzel, schluessel, 0, winreg.KEY_READ | ansicht)
            except OSError:
                continue
            with haupt:
                for i in range(winreg.QueryInfoKey(haupt)[0]):
                    try:
                        with winreg.OpenKey(haupt, winreg.EnumKey(haupt, i)) as eintrag:
                            name = winreg.QueryValueEx(eintrag, "DisplayName")[0]
                            if not str(name).lower().startswith("bambu studio"):
                                continue
                            for wert in ("DisplayIcon", "InstallLocation"):
                                try:
                                    text = str(winreg.QueryValueEx(eintrag, wert)[0]).split(",")[0].strip('"')
                                except OSError:
                                    continue
                                p = Path(text)
                                treffer.append(p if p.suffix.lower() == ".exe" else p / EXE)
                    except OSError:
                        continue
    return treffer


def kandidaten(eigener=None):
    liste = []
    if eigener:
        liste.append(Path(eigener))
    if os.name == "nt":
        liste += _aus_registry()
        for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
            if os.environ.get(var):
                liste.append(Path(os.environ[var]) / "Bambu Studio" / EXE)
        if os.environ.get("LOCALAPPDATA"):
            liste.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Bambu Studio" / EXE)
    elif sys.platform == "darwin":
        liste.append(Path("/Applications/BambuStudio.app"))
    for name in ("bambu-studio", "BambuStudio"):
        gefunden = shutil.which(name)
        if gefunden:
            liste.append(Path(gefunden))
    return liste


def finde(eigener=None):
    for p in kandidaten(eigener):
        if p.exists():
            return p
    return None


def oeffne(dateien, programm=None):
    """Öffnet die Dateien in Bambu Studio. Ohne gefundenes Programm wird die Datei-Verknüpfung
    von Windows benutzt. Liefert True, wenn etwas gestartet wurde."""
    dateien = [str(d) for d in dateien]
    if programm:
        programm = Path(programm)
        if programm.suffix == ".app":
            subprocess.Popen(["open", "-a", str(programm), *dateien])
        else:
            subprocess.Popen([str(programm), *dateien], cwd=str(programm.parent))
        return True
    if hasattr(os, "startfile") and dateien:
        os.startfile(dateien[0])
        return True
    return False
