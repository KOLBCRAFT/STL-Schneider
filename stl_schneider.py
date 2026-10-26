#!/usr/bin/env python3
"""STL-Schneider: zerteilt ein STL so, dass jedes Teil auf die Druckplatte passt.

Schnittpositionen werden in mm ab der Unterkante des Modells angegeben (x=0 ist die linke Kante).

Beispiele:
  python stl_schneider.py modell.stl                          # automatisch, H2D eine Düse
  python stl_schneider.py modell.stl --drucker "H2D beide Düsen"
  python stl_schneider.py modell.stl --bauraum 256 256 256    # eigener Bauraum
  python stl_schneider.py modell.stl --schnitt z=50 --schnitt x=120   # manuell
  python stl_schneider.py modell.stl --3mf                    # zusätzlich alle Teile als 3MF
"""
import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import trimesh

ACHSEN = {"x": 0, "y": 1, "z": 2}

# Bauraum in mm (X, Y, Z)
DRUCKER = {
    "H2D eine Düse": (325, 320, 325),
    "H2D beide Düsen": (300, 320, 325),
    "X1 / P1 / P2S": (256, 256, 256),
    "A1": (256, 256, 256),
    "A1 mini": (180, 180, 180),
}
STANDARD_DRUCKER = "H2D eine Düse"


def lade(pfad):
    return trimesh.load_mesh(pfad, force="mesh")


@dataclass
class Duebel:
    """Einstellungen für Dübel-Verzapfung an jeder Schnittfläche."""
    anzahl: int = 2          # Dübel pro Schnittfläche
    durchmesser: float = 6.0
    tiefe: float = 10.0      # Lochtiefe pro Seite
    spiel: float = 0.2       # Loch ist um so viel größer (Durchmesser)
    randabstand: float = 3.0 # Mindestwand zwischen Loch und Außenkante
    drucken: bool = True     # Dübel als eigene Teile mit ausgeben


def duebel_positionen(flaeche, d: Duebel):
    """Verteilt d.anzahl Punkte möglichst weit auseinander in einer Schnittfläche (shapely-Polygon)."""
    # Etwas weiter nach innen als nötig, damit die Dübel nicht direkt an der Außenwand sitzen
    einzug = d.durchmesser / 2 + d.spiel + d.randabstand + 0.1 * math.sqrt(flaeche.area)
    innen = flaeche.buffer(-einzug)
    if innen.is_empty:
        return []
    from shapely.geometry import Point
    from shapely.ops import polylabel

    groesstes = max(getattr(innen, "geoms", [innen]), key=lambda g: g.area)
    punkte = [np.array(polylabel(groesstes, tolerance=0.5).coords[0])]
    if d.anzahl > 1:
        x0, y0, x1, y1 = innen.bounds
        schritt = max(min(x1 - x0, y1 - y0) / 30, 0.5)
        gx, gy = np.meshgrid(np.arange(x0, x1 + schritt, schritt), np.arange(y0, y1 + schritt, schritt))
        raster = [np.array(p) for p in zip(gx.ravel(), gy.ravel()) if innen.contains(Point(p))]
        mindest = d.durchmesser + 2 * d.spiel + d.randabstand
        while len(punkte) < d.anzahl and raster:
            abst = [min(np.linalg.norm(p - q) for q in punkte) for p in raster]
            i = int(np.argmax(abst))
            if abst[i] < mindest:
                break
            punkte.append(raster[i])
    return punkte


def schneide(mesh, achse, pos, duebel: Duebel = None, log=None):
    """Schneidet das Mesh an einer Ebene und gibt beide Hälften geschlossen zurück.

    Mit duebel werden Löcher in beide Schnittflächen gebohrt. Rückgabe: (hälften, anzahl_dübel).
    """
    normal = np.zeros(3)
    normal[achse] = 1.0
    origin = np.zeros(3)
    origin[achse] = pos

    loecher = []
    if duebel and duebel.anzahl > 0:
        eben = schnitt_2d(mesh, achse, [pos])[0]
        if eben is not None:
            nach_3d = eben.metadata["to_3D"]
            for flaeche in eben.polygons_full:
                punkte = duebel_positionen(flaeche, duebel)
                if not punkte and log:
                    log(f"  Schnittfläche zu klein für Dübel ({flaeche.area:.0f} mm²)")
                for p in punkte:
                    mitte = trimesh.transform_points([[p[0], p[1], 0.0]], nach_3d)[0]
                    zyl = trimesh.creation.cylinder(
                        radius=(duebel.durchmesser + duebel.spiel) / 2,
                        height=2 * (duebel.tiefe + 0.5),
                        sections=32,
                    )
                    zyl.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], normal))
                    zyl.apply_translation(mitte)
                    loecher.append(zyl)

    teile = []
    for n in (-normal, normal):
        t = mesh.slice_plane(origin, n, cap=True)
        if t is not None and len(t.faces):
            if loecher:
                t = trimesh.boolean.difference([t] + loecher, engine="manifold")
            teile.append(t)
    return teile, len(loecher)


def duebel_teile(anzahl, d: Duebel):
    """Stehende Dübel mit 0,5 mm Fase oben und unten, etwas kürzer als beide Löcher zusammen."""
    laenge = 2 * d.tiefe - 0.6
    r, f = d.durchmesser / 2, 0.5
    profil = [[0, 0], [r - f, 0], [r, f], [r, laenge - f], [r - f, laenge], [0, laenge]]
    teile = []
    for i in range(anzahl):
        t = trimesh.creation.revolve(profil, sections=48)
        t.apply_translation([i * (d.durchmesser + 4), 0, 0])
        teile.append(t)
    return teile


def auto_schnitte(mesh, bauraum, rand=3.0):
    """Gleichmäßige Schnitte als Gitter, damit jedes Teil in den Bauraum (minus Rand) passt.

    Gibt Schnitte als (achse, position ab Modell-Unterkante) zurück.
    """
    schnitte = []
    for a in range(3):
        nutzbar = bauraum[a] - 2 * rand
        laenge = mesh.extents[a]
        anzahl = max(1, math.ceil(laenge / nutzbar))
        schritt = laenge / anzahl
        schnitte += [(a, i * schritt) for i in range(1, anzahl)]
    return schnitte


def schnitt_2d(mesh, achse, positionen):
    """Querschnitte (Path2D oder None) an mehreren Positionen entlang einer Achse.

    section_multiplane ist hier zuverlässiger als mesh.section, das bei manchen Ebenen None liefert.
    """
    normal = np.zeros(3)
    normal[achse] = 1.0
    return mesh.section_multiplane(np.zeros(3), normal, list(positionen))


def passt_irgendwie(teil, bauraum, rand=0.0):
    """Passt das Teil in einer der sechs 90°-Lagen in den Bauraum?"""
    return all(a <= b - 2 * rand for a, b in zip(sorted(teil.extents), sorted(bauraum)))


def auto_zerteile(mesh, bauraum, rand=3.0, duebel=None, proben=40, log=None):
    """Schneidet nur Teile, die nicht passen, und legt jeden Schnitt an die dünnste Stelle.

    Das gibt meist weniger und schönere Teile als ein starres Gitter, weil Schnitte
    z.B. durch schmale Äste statt durch dicke Stellen gehen.
    """
    offen, fertig = [mesh], []
    zaehler = 0
    while offen:
        t = offen.pop()
        if passt_irgendwie(t, bauraum, rand):
            fertig.append(t)
            continue
        # Teil-Achsen der Größe nach den Bauraum-Achsen zuordnen (Teile dürfen gedreht werden)
        # und die Achse schneiden, die am weitesten übersteht
        reihenfolge = np.argsort(t.extents)
        platz = np.array(sorted(bauraum), dtype=float) - 2 * rand
        k = int(np.argmax(t.extents[reihenfolge] / platz))
        achse, nutzbar = int(reihenfolge[k]), platz[k]
        lo, hi = t.bounds[0][achse], t.bounds[1][achse]
        laenge = hi - lo
        if laenge <= 2 * nutzbar:
            # Beide Hälften sollen entlang der Achse passen
            a, b = hi - nutzbar, lo + nutzbar
        else:
            # Ein passendes Stück abschneiden
            a, b = lo + 0.5 * nutzbar, lo + nutzbar
        a, b = max(a, lo + 0.05 * laenge), min(b, hi - 0.05 * laenge)
        kandidaten = np.linspace(a, b, proben)
        flaechen = [s.area if s is not None else 0.0 for s in schnitt_2d(t, achse, kandidaten)]
        # Leicht zur Mitte hin bevorzugen, damit bei gleicher Fläche ausgewogene Teile entstehen
        mitte = (a + b) / 2
        kosten = [f * (1 + 0.1 * abs(p - mitte) / max(b - a, 1e-6)) for f, p in zip(flaechen, kandidaten)]
        pos = kandidaten[int(np.argmin(kosten))]
        if log:
            log(f"Schnitt {'XYZ'[achse]} bei {pos - mesh.bounds[0][achse]:.1f} mm (Fläche {min(flaechen):.0f} mm²)")
        haelften, n = schneide(t, achse, pos, duebel, log)
        zaehler += n
        for h in haelften:
            offen += [s for s in h.split(only_watertight=False) if len(s.faces) > 3]
    return fertig, zaehler


def ausrichten(mesh):
    """Dreht das Modell so, dass seine kleinste umgebende Box achsparallel liegt."""
    m = mesh.copy()
    m.apply_transform(np.linalg.inv(m.bounding_box_oriented.primitive.transform))
    return m


def automatisch(mesh, bauraum, rand=3.0, duebel=None, log=print):
    """Probiert das Modell in Originallage und ausgerichtet, nimmt die Variante mit weniger Teilen.

    Rückgabe: (teile, anzahl_dübel)
    """
    log("Automatisch: Originallage ...")
    beste = auto_zerteile(mesh, bauraum, rand, duebel, log=log)
    log(f"  {len(beste[0])} Teile")
    if not passt_irgendwie(mesh, bauraum, rand):
        log("Automatisch: ausgerichtet ...")
        andere = auto_zerteile(ausrichten(mesh), bauraum, rand, duebel, log=log)
        log(f"  {len(andere[0])} Teile")
        if len(andere[0]) < len(beste[0]):
            beste = andere
    return beste


def lies_schnitte(texte):
    """Wandelt z.B. ["z=50", "x=120"] in [(2, 50.0), (0, 120.0)] um."""
    schnitte = []
    for s in texte:
        achse, pos = s.split("=")
        schnitte.append((ACHSEN[achse.strip().lower()], float(pos.replace(",", "."))))
    return schnitte


def zerteile(mesh, schnitte, duebel=None, log=None):
    """Manuelle Schnitte als (achse, position ab Modell-Unterkante). Rückgabe: (teile, anzahl_dübel)"""
    lo = mesh.bounds[0]
    teile, zaehler = [mesh], 0
    for achse, rel in schnitte:
        pos = lo[achse] + rel
        neu = []
        for t in teile:
            if t.bounds[0][achse] < pos < t.bounds[1][achse]:
                haelften, n = schneide(t, achse, pos, duebel, log)
                neu += haelften
                zaehler += n
            else:
                neu.append(t)
        teile = neu
    # Lose Inseln trennen (z.B. wenn ein Schnitt zwei getrennte Stücke erzeugt)
    ergebnis = []
    for t in teile:
        ergebnis += [s for s in t.split(only_watertight=False) if len(s.faces) > 3]
    return ergebnis, zaehler


def auf_platte_legen(teil, bauraum=None):
    """Legt das Teil auf die Platte.

    Bevorzugt die größte ebene Fläche (meist die Schnittfläche) nach unten. Passt das Teil so
    nicht in den Bauraum, wird die nächstkleinere ebene Fläche bzw. eine 90°-Lage genommen.
    """
    lagen = []
    if len(teil.facets):
        for i in np.argsort(teil.facets_area)[::-1][:5]:
            lagen.append(trimesh.geometry.align_vectors(teil.facets_normal[i], [0, 0, -1]))
    for v in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]):
        lagen.append(trimesh.geometry.align_vectors(v, [0, 0, -1]))
    erstes = None
    for rot in lagen:
        t = teil.copy()
        t.apply_transform(rot)
        t.apply_translation(-t.bounds[0])
        if erstes is None:
            erstes = t
        if bauraum is None:
            return t
        if passt(t, bauraum):
            x, y, _ = t.extents
            if x > bauraum[0] or y > bauraum[1]:
                t.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]))
                t.apply_translation(-t.bounds[0])
            return t
    return erstes


def passt(teil, bauraum):
    """Passt das Teil, notfalls um 90° um Z gedreht?"""
    x, y, z = teil.extents
    bx, by, bz = bauraum
    return z <= bz and ((x <= bx and y <= by) or (y <= bx and x <= by))


def exportiere(teile, name, ordner, bauraum, drehen=True, dreimf=False, duebel=None, anzahl_duebel=0, log=print):
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    szene = trimesh.Scene()
    for i, t in enumerate(teile, 1):
        if drehen:
            t = auf_platte_legen(t, bauraum)
        datei = ordner / f"{name}_teil{i:02d}.stl"
        t.export(datei)
        szene.add_geometry(t, node_name=f"teil{i:02d}")
        status = "ok" if passt(t, bauraum) else "PASST NICHT"
        log(f"Teil {i:02d}: {' x '.join(f'{v:.1f}' for v in t.extents)} mm  {status}  -> {datei.name}")
    if duebel and duebel.drucken and anzahl_duebel:
        stifte = trimesh.util.concatenate(duebel_teile(anzahl_duebel, duebel))
        datei = ordner / f"{name}_duebel_{anzahl_duebel}x.stl"
        stifte.export(datei)
        szene.add_geometry(stifte, node_name="duebel")
        log(f"{anzahl_duebel} Dübel {duebel.durchmesser:g} x {2 * duebel.tiefe - 0.6:g} mm -> {datei.name}")
    elif anzahl_duebel:
        log(f"{anzahl_duebel} Dübellöcher für {duebel.durchmesser:g} mm Dübel, {duebel.tiefe:g} mm tief pro Seite")
    if dreimf:
        datei = ordner / f"{name}_teile.3mf"
        szene.export(datei)
        log(f"3MF: {datei.name}")
    log(f"{len(teile)} Teile gespeichert in {ordner}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stl")
    p.add_argument("--drucker", choices=list(DRUCKER), default=STANDARD_DRUCKER)
    p.add_argument("--bauraum", nargs=3, type=float, metavar=("X", "Y", "Z"), help="Überschreibt --drucker")
    p.add_argument("--rand", type=float, default=3.0, help="Sicherheitsabstand zum Plattenrand in mm")
    p.add_argument("--schnitt", action="append", default=[], help="Manueller Schnitt, z.B. z=50")
    p.add_argument("--gitter", action="store_true", help="Automatisch als starres Gitter statt an dünnen Stellen")
    p.add_argument("--duebel", type=int, default=2, help="Dübel pro Schnittfläche (0 = keine)")
    p.add_argument("--duebel-durchmesser", type=float, default=6.0)
    p.add_argument("--duebel-tiefe", type=float, default=10.0, help="Lochtiefe pro Seite in mm")
    p.add_argument("--duebel-spiel", type=float, default=0.2, help="Loch so viel größer als der Dübel")
    p.add_argument("--keine-duebel-teile", action="store_true", help="Nur Löcher, z.B. für gekaufte Holzdübel")
    p.add_argument("--nicht-drehen", action="store_true", help="Teile nicht auf die Schnittfläche legen")
    p.add_argument("--3mf", dest="dreimf", action="store_true", help="Zusätzlich alle Teile in einer 3MF")
    p.add_argument("--aus", default=None, help="Ausgabeordner")
    a = p.parse_args()

    bauraum = a.bauraum or DRUCKER[a.drucker]
    pfad = Path(a.stl)
    mesh = lade(pfad)
    print(f"Geladen: {pfad.name}  Größe {np.round(mesh.extents, 1)} mm  wasserdicht={mesh.is_watertight}")

    duebel = None
    if a.duebel > 0:
        duebel = Duebel(a.duebel, a.duebel_durchmesser, a.duebel_tiefe, a.duebel_spiel, drucken=not a.keine_duebel_teile)

    if a.schnitt:
        teile, n = zerteile(mesh, lies_schnitte(a.schnitt), duebel, log=print)
    elif a.gitter:
        teile, n = zerteile(mesh, auto_schnitte(mesh, bauraum, a.rand), duebel, log=print)
    else:
        teile, n = automatisch(mesh, bauraum, a.rand, duebel)
    aus = a.aus or pfad.with_name(pfad.stem + "_teile")
    exportiere(teile, pfad.stem, aus, bauraum, drehen=not a.nicht_drehen, dreimf=a.dreimf,
               duebel=duebel, anzahl_duebel=n)


if __name__ == "__main__":
    main()
