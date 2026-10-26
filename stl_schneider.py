#!/usr/bin/env python3
"""STL-Schneider: zerteilt ein STL so, dass jedes Teil auf die Druckplatte passt.

Beispiele:
  python stl_schneider.py modell.stl                       # Bambu-Standard 256x256x256 mm
  python stl_schneider.py modell.stl --bauraum 180 180 180 # z.B. A1 mini
  python stl_schneider.py modell.stl --schnitt z=50 --schnitt x=0   # eigene Schnitte
  python stl_schneider.py modell.stl --3mf                 # zusätzlich alle Teile als 3MF
"""
import argparse
import math
from pathlib import Path

import numpy as np
import trimesh

ACHSEN = {"x": 0, "y": 1, "z": 2}


def schneide(mesh, achse, pos):
    """Schneidet das Mesh an einer Ebene und gibt (unten, oben) geschlossen zurück."""
    normal = np.zeros(3)
    normal[achse] = 1.0
    origin = np.zeros(3)
    origin[achse] = pos
    teile = []
    for n in (-normal, normal):
        t = mesh.slice_plane(origin, n, cap=True)
        if t is not None and len(t.faces):
            teile.append(t)
        else:
            teile.append(None)
    return teile


def auto_schnitte(mesh, bauraum, rand):
    """Gleichmäßige Schnitte, damit jedes Teil in den Bauraum (minus Rand) passt."""
    lo, hi = mesh.bounds
    schnitte = []
    for a in range(3):
        nutzbar = bauraum[a] - 2 * rand
        anzahl = max(1, math.ceil((hi[a] - lo[a]) / nutzbar))
        schritt = (hi[a] - lo[a]) / anzahl
        schnitte += [(a, lo[a] + i * schritt) for i in range(1, anzahl)]
    return schnitte


def zerteile(mesh, schnitte):
    teile = [mesh]
    for achse, pos in schnitte:
        neu = []
        for t in teile:
            if t.bounds[0][achse] < pos < t.bounds[1][achse]:
                neu += [x for x in schneide(t, achse, pos) if x is not None]
            else:
                neu.append(t)
        teile = neu
    # Lose Inseln trennen (z.B. wenn ein Schnitt zwei getrennte Stücke erzeugt)
    ergebnis = []
    for t in teile:
        ergebnis += [s for s in t.split(only_watertight=False) if len(s.faces) > 3]
    return ergebnis


def auf_platte_legen(teil):
    """Größte Schnittfläche nach unten drehen und auf z=0 setzen."""
    kandidaten = teil.facets_area if len(teil.facets) else []
    if len(kandidaten):
        i = int(np.argmax(kandidaten))
        normal = teil.facets_normal[i]
        rot = trimesh.geometry.align_vectors(normal, [0, 0, -1])
        teil = teil.copy()
        teil.apply_transform(rot)
    teil.apply_translation(-teil.bounds[0])
    return teil


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stl")
    p.add_argument("--bauraum", nargs=3, type=float, default=[256, 256, 256], metavar=("X", "Y", "Z"))
    p.add_argument("--rand", type=float, default=3.0, help="Sicherheitsabstand zum Plattenrand in mm")
    p.add_argument("--schnitt", action="append", default=[], help="Eigener Schnitt, z.B. z=50")
    p.add_argument("--nicht-drehen", action="store_true", help="Teile nicht auf die Schnittfläche legen")
    p.add_argument("--3mf", dest="dreimf", action="store_true", help="Zusätzlich alle Teile in einer 3MF")
    p.add_argument("--aus", default=None, help="Ausgabeordner")
    a = p.parse_args()

    pfad = Path(a.stl)
    mesh = trimesh.load_mesh(pfad, force="mesh")
    print(f"Geladen: {pfad.name}  Größe {np.round(mesh.extents, 1)} mm  wasserdicht={mesh.is_watertight}")

    if a.schnitt:
        schnitte = [(ACHSEN[s.split("=")[0].lower()], float(s.split("=")[1])) for s in a.schnitt]
    else:
        schnitte = auto_schnitte(mesh, a.bauraum, a.rand)

    teile = zerteile(mesh, schnitte)
    aus = Path(a.aus) if a.aus else pfad.with_name(pfad.stem + "_teile")
    aus.mkdir(parents=True, exist_ok=True)

    szene = trimesh.Scene()
    for i, t in enumerate(teile, 1):
        if not a.nicht_drehen:
            t = auf_platte_legen(t)
        passt = all(t.extents[k] <= a.bauraum[k] for k in range(3))
        datei = aus / f"{pfad.stem}_teil{i:02d}.stl"
        t.export(datei)
        szene.add_geometry(t, node_name=f"teil{i:02d}")
        print(f"  Teil {i:02d}: {np.round(t.extents, 1)} mm  {'ok' if passt else 'PASST NICHT'}  -> {datei.name}")

    if a.dreimf:
        datei = aus / f"{pfad.stem}_teile.3mf"
        szene.export(datei)
        print(f"  3MF: {datei.name}")
    print(f"{len(teile)} Teile in {aus}")


if __name__ == "__main__":
    main()
