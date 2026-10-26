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
