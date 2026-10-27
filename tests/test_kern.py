"""Schnelle Tests für den Schneide-Kern. Ausführen mit: python -m pytest tests"""
import numpy as np
import pytest
import trimesh

import stl_schneider as kern

H2D = kern.DRUCKER[kern.STANDARD_DRUCKER]


@pytest.fixture
def zylinder():
    return trimesh.creation.cylinder(radius=60, height=500, sections=64)


@pytest.fixture
def gabel():
    basis = trimesh.creation.box([100, 30, 30])
    zinken = []
    for x in (-30, 30):
        z = trimesh.creation.cylinder(10, 120)
        z.apply_translation([x, 0, 60])
        zinken.append(z)
    return trimesh.boolean.union([basis] + zinken, engine="manifold")


def test_automatisch_passt_auf_h2d(zylinder):
    teile, n = kern.automatisch(zylinder, H2D, log=lambda *_: None)
    assert len(teile) == 2
    assert all(t.is_watertight for t in teile)
    assert all(kern.passt_irgendwie(t, H2D) for t in teile)
    assert sum(t.volume for t in teile) == pytest.approx(zylinder.volume, rel=1e-3)


def test_duebelloecher_in_beiden_haelften(zylinder):
    d = kern.Duebel(anzahl=3)
    teile, n = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)], d)
    assert n == 3
    loch = np.pi * ((d.durchmesser + d.spiel) / 2) ** 2 * (d.tiefe + 0.5) * 3
    ohne, _ = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)])
    for mit_loch, voll in zip(sorted(teile, key=lambda t: t.centroid[2]), sorted(ohne, key=lambda t: t.centroid[2])):
        assert mit_loch.is_watertight
        assert voll.volume - mit_loch.volume == pytest.approx(loch, rel=0.05)


def test_schraeger_schnitt(zylinder):
    teile, _ = kern.zerteile(zylinder, [(np.zeros(3), np.array([0.3, 0.0, 1.0]))])
    assert len(teile) == 2
    assert sum(t.volume for t in teile) == pytest.approx(zylinder.volume, rel=1e-3)


def test_schnittfenster_trennt_nur_einen_zinken(gabel):
    punkt = np.array([30.0, 0.0, 80.0])
    normale = np.array([0.0, 0.0, 1.0])
    u, v = kern.ebenen_achsen(normale)
    fenster = kern.Fenster(punkt, u, v, 40, 40)
    teile, _ = kern.zerteile(gabel, [(punkt, normale, fenster)])
    assert len(teile) == 2
    assert all(t.is_watertight for t in teile)
    spitze = min(teile, key=lambda t: t.volume)
    assert spitze.centroid[0] > 0 and spitze.bounds[0][2] == pytest.approx(80.0, abs=0.01)


def test_platte_lage_liegt_auf_platte(zylinder):
    teile, _ = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)])
    for t in teile:
        gelegt = kern.auf_platte_legen(t, H2D)
        assert gelegt.bounds[0] == pytest.approx([0, 0, 0], abs=1e-6)
        assert kern.passt(gelegt, H2D)


def test_export(tmp_path, zylinder):
    teile, n = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)], kern.Duebel(2))
    kern.exportiere(teile, "test", tmp_path, H2D, dreimf=True, duebel=kern.Duebel(2), anzahl_duebel=n,
                    log=lambda *_: None)
    namen = sorted(p.name for p in tmp_path.iterdir())
    assert namen == ["test_duebel_2x.stl", "test_teil01.stl", "test_teil02.stl", "test_teile.3mf"]


def test_3mf_teile_nebeneinander(tmp_path, zylinder):
    teile, n = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)], kern.Duebel(2))
    datei = kern.exportiere(teile, "test", tmp_path, H2D, dreimf=True, duebel=kern.Duebel(2), anzahl_duebel=n,
                            log=lambda *_: None)
    assert datei == tmp_path / "test_teile.3mf"
    szene = trimesh.load(datei)
    boxen = [g.bounds for g in szene.dump()]
    assert len(boxen) == 3
    for i, a in enumerate(boxen):
        assert a[0][2] == pytest.approx(0, abs=0.01)  # alle liegen auf der Platte
        for b in boxen[i + 1:]:
            ueberlappt = all(a[0][k] < b[1][k] and b[0][k] < a[1][k] for k in (0, 1))
            assert not ueberlappt


def test_zapfen_angeformt(zylinder):
    d = kern.Duebel(anzahl=2, durchmesser=8, tiefe=8, art="zapfen")
    ohne, _ = kern.zerteile(zylinder, [kern.ebene_achse(2, 50.0)])
    teile, n = kern.zerteile(zylinder, [kern.ebene_achse(2, 50.0)], d)
    assert n == 2 and len(teile) == 2
    assert all(t.is_watertight for t in teile)
    gross_ohne, klein_ohne = sorted(ohne, key=lambda t: -t.volume)
    gross, klein = sorted(teile, key=lambda t: -t.volume)
    zapfen = np.pi * 4 ** 2 * 8 * 2
    # Größere Hälfte trägt die Zapfen, die kleinere hat die Löcher
    assert gross.volume - gross_ohne.volume == pytest.approx(zapfen, rel=0.08)
    assert klein_ohne.volume - klein.volume == pytest.approx(np.pi * 4.1 ** 2 * 8.3 * 2, rel=0.08)
    # Zapfen ragen über die Schnittfläche hinaus
    assert gross.bounds[1][2] == pytest.approx(50.0 + 8, abs=0.01)


def test_zapfen_teil_nicht_auf_zapfen_gelegt(zylinder):
    d = kern.Duebel(anzahl=1, durchmesser=8, tiefe=8, art="zapfen")
    teile, _ = kern.zerteile(zylinder, [kern.ebene_achse(2, 50.0)], d)
    gross = max(teile, key=lambda t: t.volume)
    gelegt = kern.auf_platte_legen(gross, H2D)
    unten = gelegt.vertices[gelegt.vertices[:, 2] < 0.01]
    # Liegt flächig auf (Deckel des Zylinders), nicht auf der Zapfenspitze
    assert np.ptp(unten[:, 0]) > 100


def test_magnetloecher(zylinder):
    d = kern.Duebel(anzahl=3, durchmesser=6, tiefe=3, art="magnet")
    ohne, _ = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)])
    teile, n = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)], d)
    assert n == 3
    loch = np.pi * 3.1 ** 2 * 3.2 * 3
    for a, b in zip(sorted(ohne, key=lambda t: t.centroid[2]), sorted(teile, key=lambda t: t.centroid[2])):
        assert a.volume - b.volume == pytest.approx(loch, rel=0.05)


def test_eigene_verbinder_positionen(zylinder):
    d = kern.Duebel(anzahl=2)
    eigene = [np.array([20.0, 10.0, 0.0])]
    vorschau = kern.querschnitt(zylinder, kern.ebene_achse(2, 0.0), d, punkte=eigene)
    assert len(vorschau) == 1 and vorschau[0].manuell
    assert np.allclose(vorschau[0].verbinder[0], eigene[0], atol=1e-6)
    teile, n = kern.zerteile(zylinder, [(*kern.ebene_achse(2, 0.0), None, eigene)], d)
    assert n == 1
    # Loch genau an der gewählten Stelle: Punkt knapp über der Schnittfläche liegt außerhalb des Materials
    oben = max(teile, key=lambda t: t.centroid[2])
    assert not oben.contains([[20.0, 10.0, 1.0]])[0]
    assert oben.contains([[-20.0, -10.0, 1.0]])[0]


def test_beste_lage_pilz_kopfueber():
    stiel = trimesh.creation.cylinder(10, 60)
    stiel.apply_translation([0, 0, 30])
    schirm = trimesh.creation.cylinder(40, 10)
    schirm.apply_translation([0, 0, 65])
    pilz = trimesh.boolean.union([stiel, schirm], engine="manifold")
    _, aufrecht = kern.ueberhang(pilz, np.eye(4))
    assert aufrecht["stuetzflaeche"] > 4000  # Unterseite des Schirms hängt über
    m, k = kern.beste_lage(pilz, H2D)
    assert k["stuetzflaeche"] < 10
    gelegt = pilz.copy()
    gelegt.apply_transform(m)
    assert gelegt.bounds[0] == pytest.approx([0, 0, 0], abs=1e-6)
    # Schirm liegt auf der Platte: große Auflage
    assert k["auflage"] > 4000


def test_skalieren(zylinder):
    assert kern.lies_groesse(zylinder, "150%") == pytest.approx(1.5)
    assert kern.lies_groesse(zylinder, "50") == pytest.approx(0.5)
    faktor = kern.lies_groesse(zylinder, "z=1000")
    gross = kern.skaliere(zylinder, faktor)
    assert gross.extents[2] == pytest.approx(1000)
    assert gross.extents[0] == pytest.approx(zylinder.extents[0] * faktor)
    assert gross.bounds[0] == pytest.approx(zylinder.bounds[0])  # untere Ecke bleibt
    assert zylinder.extents[2] != pytest.approx(1000)  # Original unverändert


def test_modell_pruefen_und_reparieren(zylinder):
    assert kern.modell_pruefen(zylinder) == []
    loch = zylinder.copy()
    loch.update_faces(np.arange(1, len(loch.faces)))  # ein Dreieck fehlt
    hinweise = kern.modell_pruefen(loch)
    assert hinweise and "nicht geschlossen" in hinweise[0]
    meldungen = []
    heil = kern.repariere(loch, log=meldungen.append)
    assert heil.is_watertight and kern.modell_pruefen(heil) == []
    assert not loch.is_watertight  # Original unverändert
    assert "in Ordnung" in meldungen[0]


def test_pruefe_teile_und_bilanz(zylinder):
    teile, _ = kern.zerteile(zylinder, [kern.ebene_achse(2, 0.0)])
    assert kern.pruefe_teile(teile, H2D) == []
    assert kern.pruefe_teile(teile, (100, 100, 100)) == [(0, "passt nicht in den Bauraum"),
                                                         (1, "passt nicht in den Bauraum")]
    vorher, nachher = kern.volumen_bilanz(zylinder, teile)
    assert nachher == pytest.approx(vorher, rel=1e-3)


def test_automatik_bricht_sauber_ab(zylinder):
    with pytest.raises(ValueError, match="zu klein"):
        kern.auto_zerteile(zylinder, (5, 5, 5), rand=3.0)
    alt = kern.MAX_SCHNITTE
    kern.MAX_SCHNITTE = 2
    try:
        with pytest.raises(RuntimeError, match="abgebrochen"):
            kern.auto_zerteile(zylinder, (30, 30, 30), rand=1.0)
    finally:
        kern.MAX_SCHNITTE = alt


@pytest.fixture
def balken():
    return trimesh.creation.box(extents=[200, 40, 40])


def _montage(mesh, ebenen, d):
    m = kern.Montage()
    teile, _ = kern.zerteile(mesh, ebenen, d, montage=m)
    return kern.montage_pruefen(teile, m)


@pytest.mark.parametrize("art", ["duebel", "zapfen", "magnet"])
def test_montage_normaler_schnitt_ohne_befund(balken, art):
    d = kern.Duebel(2, art=art, tiefe=3 if art == "magnet" else 10)
    assert _montage(balken, [kern.ebene_achse(0, 0.0), kern.ebene_achse(1, 0.0)], d) == []


def test_montage_wand_um_loch(balken):
    def am_rand(y):
        return _montage(balken, [(*kern.ebene_achse(0, 0.0), None, np.array([[0.0, y, 0.0]]))], kern.Duebel(1))
    assert am_rand(15.0) == []  # 1,9 mm Wand
    assert am_rand(16.5) == [(0, "Dübelloch mit dünner Wand (0.40 mm, empfohlen ab 1.2 mm)"), (1, "Dübelloch mit dünner Wand (0.40 mm, empfohlen ab 1.2 mm)")]
    assert {t for _, t in am_rand(17.5)} == {"Dübelloch bricht durch die Außenwand"}


def test_montage_zapfen_zu_lang(balken):
    # Hinter dem Schnitt bei x=95 bleiben nur 5 mm: automatisch kommt dort kein Zapfen hin ...
    zeilen = []
    teile, n = kern.zerteile(balken, [kern.ebene_achse(0, 95.0)], kern.Duebel(1, art="zapfen"), log=zeilen.append)
    assert n == 0 and any("Kein Platz für Verbinder" in z for z in zeilen)
    # ... von Hand gesetzt bohrt der 10-mm-Zapfen durch, und die Prüfung meldet es
    hand = [(*kern.ebene_achse(0, 95.0), None, np.array([[95.0, 0.0, 0.0]]))]
    assert _montage(balken, hand, kern.Duebel(1, art="zapfen")) == [(1, "Zapfenloch bricht durch die Außenwand")]


def test_montage_schnitt_durch_verbinder_und_anstossen(balken):
    ebenen = [kern.ebene_achse(0, 0.0), (*kern.ebene_achse(0, 5.0), None, np.array([[5.0, 0.0, 0.0]]))]
    befunde = _montage(balken, ebenen, kern.Duebel(2, art="zapfen"))
    texte = " ".join(t for _, t in befunde)
    assert "späterer Schnitt geht durch einen Verbinder" in texte
    assert "stößt beim Zusammenbau an" in texte


def test_montage_ueberschneidung():
    a = trimesh.creation.box(extents=[20, 20, 20])
    b = a.copy()
    b.apply_translation([10, 0, 0])
    assert kern.montage_pruefen([a, b]) == [(0, "stößt beim Zusammenbau an Teil 2 (4000 mm³ Überschneidung)"),
                                           (1, "stößt beim Zusammenbau an Teil 1 (4000 mm³ Überschneidung)")]


def test_gewuenschte_anzahl_auch_in_schmalen_flaechen():
    from shapely.geometry import Point, box
    for flaeche in (box(0, 0, 25, 25), Point(0, 0).buffer(15)):
        assert [len(kern.duebel_positionen(flaeche, kern.Duebel(a))) for a in (1, 2, 3, 4)] == [1, 2, 3, 4]
    # Zwei Dübel sitzen an den Enden einer länglichen Fläche, nicht einer in der Mitte
    a, b = kern.duebel_positionen(box(0, 0, 100, 20), kern.Duebel(2))
    assert abs(a[0] - b[0]) > 70


def test_duebel_und_magnete_gemischt(balken):
    d = kern.Duebel(2, magnete=2, magnet_durchmesser=8, magnet_hoehe=3)
    inseln = kern.querschnitt(balken, kern.ebene_achse(0, 0.0), d)
    assert len(inseln[0].verbinder) == 4
    m = kern.Montage()
    teile, n = kern.zerteile(balken, [kern.ebene_achse(0, 0.0)], d, montage=m)
    assert (n, m.magnete) == (2, 2) and kern.montage_pruefen(teile, m) == []
    ohne, _ = kern.zerteile(balken, [kern.ebene_achse(0, 0.0)], kern.Duebel(2))
    # Je Hälfte zwei 8,2 x 3,2 mm Magnetlöcher mehr
    loch = np.pi * 4.1 ** 2 * 3.2
    assert sum(t.volume for t in ohne) - sum(t.volume for t in teile) == pytest.approx(4 * loch, rel=0.05)
    # Bei der Art Magnete gibt es keine zusätzlichen
    assert kern.Duebel(2, art="magnet", magnete=2).gesamt == 2


def test_export_meldet_magnete(balken, tmp_path):
    d = kern.Duebel(2, magnete=2)
    m = kern.Montage()
    teile, n = kern.zerteile(balken, [kern.ebene_achse(0, 0.0)], d, montage=m)
    zeilen = []
    kern.exportiere(teile, "b", tmp_path, H2D, duebel=d, anzahl_duebel=n, anzahl_magnete=m.magnete,
                    log=zeilen.append)
    assert any("Zusätzlich Magnete nötig: 4 Stück 6 x 3 mm" in z for z in zeilen)


def test_loecher_bleiben_im_material():
    # Schräger dünner Stab: an den Enden der Schnittfläche würde ein Loch seitlich ausbrechen
    stab = trimesh.creation.box(extents=[200, 30, 40])
    stab.apply_transform(trimesh.transformations.rotation_matrix(np.radians(25), [0, 0, 1]))
    m = kern.Montage()
    teile, n = kern.zerteile(stab, [kern.ebene_achse(0, 0.0)], kern.Duebel(2), montage=m)
    assert n == 2 and kern.montage_pruefen(teile, m) == []
