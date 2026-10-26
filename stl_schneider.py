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


VERBINDER_ARTEN = {"duebel": "Dübel", "zapfen": "Zapfen", "magnet": "Magnete"}


@dataclass
class Duebel:
    """Einstellungen für die Verbinder an jeder Schnittfläche.

    art "duebel": Löcher in beiden Hälften, Dübel als eigenes Teil. tiefe = Lochtiefe je Seite.
    art "zapfen": Zapfen an einer Hälfte angeformt, Loch in der anderen. tiefe = Zapfenlänge.
    art "magnet": Löcher in beiden Hälften für Scheibenmagnete. tiefe = Magnethöhe.
    """
    anzahl: int = 2          # Verbinder pro Schnittfläche
    durchmesser: float = 6.0
    tiefe: float = 10.0
    spiel: float = 0.2       # Loch ist um so viel größer (Durchmesser)
    randabstand: float = 3.0 # Mindestwand zwischen Loch und Außenkante
    drucken: bool = True     # Dübel als eigene Teile mit ausgeben
    art: str = "duebel"


Verbinder = Duebel


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


def ebene_achse(achse, pos):
    """Ebene senkrecht zu einer Achse (0=X, 1=Y, 2=Z) bei absoluter Position pos."""
    normal = np.zeros(3)
    normal[achse] = 1.0
    return normal * pos, normal


@dataclass
class Fenster:
    """Begrenzt einen Schnitt auf ein Rechteck in der Schnittebene.

    Nur Schnittflächen (Inseln im Querschnitt), die das Rechteck berühren, werden geschnitten,
    alle anderen Stellen bleiben verbunden. So lässt sich z.B. ein einzelner Ast abtrennen.
    """
    mitte: np.ndarray   # Mittelpunkt in der Ebene
    u: np.ndarray       # Richtung der Breite (Einheitsvektor in der Ebene)
    v: np.ndarray       # Richtung der Höhe
    breite: float
    hoehe: float

    def enthaelt(self, punkte_3d):
        """Polygon (3D-Punkte in der Ebene) berührt das Fenster?"""
        from shapely.geometry import Polygon, box
        d = np.asarray(punkte_3d) - self.mitte
        poly = Polygon(np.column_stack([d @ self.u, d @ self.v]))
        rechteck = box(-self.breite / 2, -self.hoehe / 2, self.breite / 2, self.hoehe / 2)
        return poly.buffer(0).intersects(rechteck)


def ebenen_achsen(normal):
    """Zwei Richtungen in der Ebene, passend zur Normalen (für Fenster und Anzeige)."""
    n = np.asarray(normal, float) / np.linalg.norm(normal)
    hilfe = np.array([0.0, 0.0, 1.0]) if abs(n[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(hilfe, n)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def schneide(mesh, ebene, duebel: Duebel = None, log=None, fenster: Fenster = None):
    """Schneidet das Mesh an einer beliebigen Ebene (punkt, normale) und schließt die Schnittflächen.

    Mit duebel werden Löcher in beide Schnittflächen gebohrt, mit fenster wird nur innerhalb des
    Fensters geschnitten. Rückgabe: (teile, anzahl_dübel).
    """
    origin, normal = np.asarray(ebene[0], float), np.asarray(ebene[1], float)
    normal = normal / np.linalg.norm(normal)

    # Inseln des Querschnitts: (polygon_2d, 3D-Randpunkte, 3D-Innenpunkt, wird_geschnitten)
    inseln = []
    eben = schnitt_2d(mesh, origin, normal, [0.0])[0]
    if eben is None:
        return [mesh], 0
    nach_3d = eben.metadata["to_3D"]

    def zu_3d(xy):
        xy = np.asarray(xy, float)
        return trimesh.transform_points(np.column_stack([xy, np.zeros(len(xy))]), nach_3d)

    for flaeche in eben.polygons_full:
        rand = zu_3d(np.asarray(flaeche.exterior.coords))
        innen = zu_3d([flaeche.representative_point().coords[0]])[0]
        gewaehlt = fenster is None or fenster.enthaelt(rand)
        inseln.append((flaeche, innen, gewaehlt))
    if not any(i[2] for i in inseln):
        return [mesh], 0

    mitten = []
    if duebel and duebel.anzahl > 0:
        for flaeche, _, gewaehlt in inseln:
            if not gewaehlt:
                continue
            punkte = duebel_positionen(flaeche, duebel)
            if not punkte and log:
                log(f"  Schnittfläche zu klein für Verbinder ({flaeche.area:.0f} mm²)")
            if punkte:
                mitten += list(zu_3d(punkte))

    haelften = {}
    for seite in (-1, 1):
        t = mesh.slice_plane(origin, seite * normal, cap=True)
        if t is not None and len(t.faces):
            haelften[seite] = t

    if mitten and len(haelften) == 2:
        haelften = verbinder_anbringen(haelften, mitten, normal, duebel)
    haelften = list(haelften.items())

    if all(i[2] for i in inseln):
        return [t for _, t in haelften], len(mitten)

    # Nur im Fenster schneiden: Stücke, die über eine nicht gewählte Insel zusammenhängen,
    # werden wieder vereinigt.
    stuecke = []  # (seite, mesh)
    for seite, t in haelften:
        stuecke += [(seite, s) for s in t.split(only_watertight=False) if len(s.faces) > 3]
    eltern = list(range(len(stuecke)))

    def wurzel(i):
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    for _, innen, gewaehlt in inseln:
        if gewaehlt:
            continue
        beteiligt = []
        for k, (seite, s) in enumerate(stuecke):
            probe = innen + seite * normal * 0.05
            if s.contains([probe])[0]:
                beteiligt.append(k)
        for k in beteiligt[1:]:
            eltern[wurzel(k)] = wurzel(beteiligt[0])

    gruppen = {}
    for k in range(len(stuecke)):
        gruppen.setdefault(wurzel(k), []).append(stuecke[k][1])
    teile = []
    for g in gruppen.values():
        teile.append(g[0] if len(g) == 1 else trimesh.boolean.union(g, engine="manifold"))
    return teile, len(mitten)


def _zylinder(radius, von, bis, normal, mitte):
    """Zylinder entlang normal von Abstand von bis bis (mm, bezogen auf die Schnittebene)."""
    z = trimesh.creation.cylinder(radius=radius, height=bis - von, sections=32)
    z.apply_translation([0, 0, (von + bis) / 2])
    z.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], normal))
    z.apply_translation(mitte)
    return z


def _zapfen(d: Duebel, normal, mitte):
    """Zapfen mit 0,5 mm Fase an der Spitze, 0,5 mm in die Hälfte versenkt für eine saubere Verbindung."""
    r, f, laenge = d.durchmesser / 2, min(0.5, d.durchmesser / 4), d.tiefe
    profil = [[0, -0.5], [r, -0.5], [r, laenge - f], [r - f, laenge], [0, laenge]]
    z = trimesh.creation.revolve(profil, sections=48)
    z.apply_transform(trimesh.geometry.align_vectors([0, 0, 1], normal))
    z.apply_translation(mitte)
    return z


def verbinder_anbringen(haelften, mitten, normal, d: Duebel):
    """Bohrt Löcher bzw. formt Zapfen an. haelften: {-1: unten, 1: oben} relativ zur Normalen."""
    r_loch = (d.durchmesser + d.spiel) / 2
    if d.art == "zapfen":
        # Zapfen an die größere Hälfte, Loch in die kleinere
        traeger = max(haelften, key=lambda s: haelften[s].volume)
        richtung = -traeger * normal  # zeigt aus der Schnittfläche des Trägers heraus
        zapfen = [_zapfen(d, richtung, m) for m in mitten]
        loecher = [_zylinder(r_loch, -0.5, d.tiefe + 0.3, richtung, m) for m in mitten]
        haelften[traeger] = trimesh.boolean.union([haelften[traeger]] + zapfen, engine="manifold")
        haelften[-traeger] = trimesh.boolean.difference([haelften[-traeger]] + loecher, engine="manifold")
        return haelften
    zusatz = 0.5 if d.art == "duebel" else 0.2
    loecher = [_zylinder(r_loch, -(d.tiefe + zusatz), d.tiefe + zusatz, normal, m) for m in mitten]
    return {s: trimesh.boolean.difference([t] + loecher, engine="manifold") for s, t in haelften.items()}


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


def gitter_ebenen(mesh, bauraum, rand=3.0):
    """Gleichmäßiges Gitter aus Schnittebenen, damit jedes Teil in den Bauraum (minus Rand) passt."""
    lo = mesh.bounds[0]
    ebenen = []
    for a in range(3):
        nutzbar = bauraum[a] - 2 * rand
        laenge = mesh.extents[a]
        anzahl = max(1, math.ceil(laenge / nutzbar))
        schritt = laenge / anzahl
        ebenen += [ebene_achse(a, lo[a] + i * schritt) for i in range(1, anzahl)]
    return ebenen


def schnitt_2d(mesh, origin, normal, hoehen):
    """Querschnitte (Path2D oder None) in Ebenen parallel zu (origin, normal), um hoehen verschoben.

    section_multiplane ist hier zuverlässiger als mesh.section, das bei manchen Ebenen None liefert.
    """
    return mesh.section_multiplane(np.asarray(origin, float), np.asarray(normal, float), list(hoehen))


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
        # Angeformte Zapfen machen ein Teil länger, dafür Platz lassen
        zapfen = duebel.tiefe if duebel and duebel.art == "zapfen" and duebel.anzahl > 0 else 0.0
        platz = np.array(sorted(bauraum), dtype=float) - 2 * rand - zapfen
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
        normal = ebene_achse(achse, 1.0)[1]
        flaechen = [s.area if s is not None else 0.0 for s in schnitt_2d(t, np.zeros(3), normal, kandidaten)]
        # Leicht zur Mitte hin bevorzugen, damit bei gleicher Fläche ausgewogene Teile entstehen
        mitte = (a + b) / 2
        kosten = [f * (1 + 0.1 * abs(p - mitte) / max(b - a, 1e-6)) for f, p in zip(flaechen, kandidaten)]
        pos = kandidaten[int(np.argmin(kosten))]
        if log:
            log(f"Schnitt {'XYZ'[achse]} bei {pos - mesh.bounds[0][achse]:.1f} mm (Fläche {min(flaechen):.0f} mm²)")
        haelften, n = schneide(t, ebene_achse(achse, pos), duebel, log)
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


def lies_schnitte(mesh, texte):
    """Wandelt z.B. ["z=50", "x=120"] (mm ab Modell-Unterkante) in Ebenen um."""
    ebenen = []
    for s in texte:
        achse, pos = s.split("=")
        a = ACHSEN[achse.strip().lower()]
        ebenen.append(ebene_achse(a, mesh.bounds[0][a] + float(pos.replace(",", "."))))
    return ebenen


def wird_geschnitten(teil, ebene):
    abstand = (teil.vertices - ebene[0]) @ (np.asarray(ebene[1]) / np.linalg.norm(ebene[1]))
    return abstand.min() < -1e-6 and abstand.max() > 1e-6


def zerteile(mesh, ebenen, duebel=None, log=None):
    """Schneidet an beliebigen Ebenen (punkt, normale[, fenster]). Rückgabe: (teile, anzahl_dübel)"""
    teile, zaehler = [mesh], 0
    for ebene in ebenen:
        neu = []
        for t in teile:
            if wird_geschnitten(t, ebene):
                fenster = ebene[2] if len(ebene) > 2 else None
                haelften, n = schneide(t, ebene[:2], duebel, log, fenster)
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


def platte_lage(teil, bauraum=None):
    """4x4-Matrix, die das Teil druckfertig auf die Platte legt (Ecke im Ursprung).

    Bevorzugt die größte ebene Fläche (meist die Schnittfläche) nach unten. Passt das Teil so
    nicht in den Bauraum, wird die nächstkleinere ebene Fläche bzw. eine 90°-Lage genommen.
    """
    lagen = []
    if len(teil.facets):
        for i in np.argsort(teil.facets_area)[::-1][:5]:
            rot = trimesh.geometry.align_vectors(teil.facets_normal[i], [0, 0, -1])
            # Nur wenn die Fläche danach ganz unten liegt (ein Zapfen darf nicht in die Platte ragen)
            z_flaeche = trimesh.transform_points(teil.vertices[teil.faces[teil.facets[i][0]]], rot)[:, 2].min()
            z_min = trimesh.transform_points(teil.convex_hull.vertices, rot)[:, 2].min()
            if z_flaeche - z_min < 0.05:
                lagen.append(rot)
    for v in ([0, 0, -1], [0, 0, 1], [1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]):
        lagen.append(trimesh.geometry.align_vectors(v, [0, 0, -1]))
    hull = teil.convex_hull.vertices if len(teil.vertices) > 2000 else teil.vertices

    def auf_ecke(m):
        pts = trimesh.transform_points(hull, m)
        return trimesh.transformations.translation_matrix(-pts.min(axis=0)) @ m

    erstes = None
    for rot in lagen:
        m = auf_ecke(rot)
        if erstes is None:
            erstes = m
        if bauraum is None:
            return m
        ausmass = np.ptp(trimesh.transform_points(hull, m), axis=0)
        x, y, z = ausmass
        if z <= bauraum[2] and ((x <= bauraum[0] and y <= bauraum[1]) or (y <= bauraum[0] and x <= bauraum[1])):
            if x > bauraum[0] or y > bauraum[1]:
                m = auf_ecke(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]) @ m)
            return m
    return erstes


def auf_platte_legen(teil, bauraum=None):
    t = teil.copy()
    t.apply_transform(platte_lage(teil, bauraum))
    return t


def passt(teil, bauraum):
    """Passt das Teil, notfalls um 90° um Z gedreht?"""
    x, y, z = teil.extents
    bx, by, bz = bauraum
    return z <= bz and ((x <= bx and y <= by) or (y <= bx and x <= by))


def exportiere(teile, name, ordner, bauraum, drehen=True, dreimf=False, duebel=None, anzahl_duebel=0, log=print,
               lagen=None):
    """lagen: {index: 4x4-Matrix} für Teile, die von Hand im Bauraum platziert wurden."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    szene = trimesh.Scene()
    lagen = lagen or {}
    for i, t in enumerate(teile, 1):
        if i - 1 in lagen:
            t = t.copy()
            t.apply_transform(lagen[i - 1])
            t.apply_translation([0, 0, -t.bounds[0][2]])  # auf die Platte setzen
        elif drehen:
            t = auf_platte_legen(t, bauraum)
        datei = ordner / f"{name}_teil{i:02d}.stl"
        t.export(datei)
        szene.add_geometry(t, node_name=f"teil{i:02d}")
        status = "ok" if passt(t, bauraum) else "PASST NICHT"
        log(f"Teil {i:02d}: {' x '.join(f'{v:.1f}' for v in t.extents)} mm  {status}  -> {datei.name}")
    if duebel and duebel.art == "zapfen" and anzahl_duebel:
        log(f"{anzahl_duebel} Zapfen {duebel.durchmesser:g} x {duebel.tiefe:g} mm angeformt")
    elif duebel and duebel.art == "magnet" and anzahl_duebel:
        log(f"Magnete nötig: {2 * anzahl_duebel} Stück {duebel.durchmesser:g} x {duebel.tiefe:g} mm "
            f"(Löcher {duebel.durchmesser + duebel.spiel:g} x {duebel.tiefe + 0.2:g} mm). Polung beim Einkleben beachten!")
    elif duebel and duebel.drucken and anzahl_duebel:
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
    p.add_argument("--verbinder", choices=list(VERBINDER_ARTEN), default="duebel",
                   help="duebel, zapfen (angeformt) oder magnet (Löcher für Scheibenmagnete)")
    p.add_argument("--duebel", type=int, default=2, help="Verbinder pro Schnittfläche (0 = keine)")
    p.add_argument("--duebel-durchmesser", type=float, default=6.0)
    p.add_argument("--duebel-tiefe", type=float, default=10.0,
                   help="Dübel: Lochtiefe je Seite, Zapfen: Zapfenlänge, Magnet: Magnethöhe (mm)")
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
        duebel = Duebel(a.duebel, a.duebel_durchmesser, a.duebel_tiefe, a.duebel_spiel,
                        drucken=not a.keine_duebel_teile, art=a.verbinder)

    if a.schnitt:
        teile, n = zerteile(mesh, lies_schnitte(mesh, a.schnitt), duebel, log=print)
    elif a.gitter:
        teile, n = zerteile(mesh, gitter_ebenen(mesh, bauraum, a.rand), duebel, log=print)
    else:
        teile, n = automatisch(mesh, bauraum, a.rand, duebel)
    aus = a.aus or pfad.with_name(pfad.stem + "_teile")
    exportiere(teile, pfad.stem, aus, bauraum, drehen=not a.nicht_drehen, dreimf=a.dreimf,
               duebel=duebel, anzahl_duebel=n)


if __name__ == "__main__":
    main()
