"""Rauchtest für die Oberfläche: Fenster öffnen, Modell laden, schneiden, in den Bauraum legen, speichern."""
import numpy as np
import pytest
import trimesh

qtpy = pytest.importorskip("qtpy")
from qtpy import QtWidgets  # noqa: E402

import gui  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_ablauf(app, tmp_path):
    modell = tmp_path / "zylinder.stl"
    trimesh.creation.cylinder(radius=60, height=500).export(modell)

    f = gui.Fenster()
    f.show()
    f._oeffnen(str(modell))
    assert f.mesh is not None

    # Manueller schräger Schnitt mit Fenster
    f.d_art.setCurrentIndex(f.d_art.findData("zapfen"))
    assert f.d_tiefe_label.text() == "Zapfenlänge mm" and not f.d_drucken.isVisibleTo(f)
    assert f._einstellungen()["duebel"].art == "zapfen"
    f.manuell.setChecked(True)
    f.fenster_an.setChecked(True)
    f.ebene = (f.mesh.bounds.mean(axis=0), np.array([0.2, 0.0, 1.0]))
    f._plane_widget()
    f._schnitt_dazu()
    assert len(f.schnitte) == 1

    ergebnisse = []
    f.signale.fertig.disconnect()
    f.signale.fertig.connect(ergebnisse.append)
    f._arbeite(f._einstellungen())
    app.processEvents()
    assert ergebnisse, "Berechnung lieferte kein Ergebnis"
    f._berechnet(ergebnisse[0])
    assert len(f.ergebnis[0]) == 2

    f.teile_liste.setCurrentRow(0)
    f._in_bauraum()
    assert "passt" in f.passt_info.text()
    f._teil_drehen(0)

    f._speichern(str(tmp_path))
    ausgabe = tmp_path / "zylinder_teile"
    assert (ausgabe / "zylinder_teil01.stl").exists()
    assert (ausgabe / "zylinder_teile.3mf").exists()
    f.close()


def test_verbinder_setzen_und_rueckgaengig(app, tmp_path):
    modell = tmp_path / "zylinder.stl"
    trimesh.creation.cylinder(radius=60, height=500).export(modell)
    f = gui.Fenster()
    f.show()
    f._oeffnen(str(modell))
    f.manuell.setChecked(True)
    f.ebene = (f.mesh.bounds.mean(axis=0), np.array([0.0, 0.0, 1.0]))
    f._schnitt_dazu()
    f._schnitt_dazu()
    assert len(f.schnitte) == 2
    f._rueckgaengig()
    assert len(f.schnitte) == 1
    f._wiederholen()
    assert len(f.schnitte) == 2
    f._schnitt_weg()
    assert len(f.schnitte) == 1

    # Eigenen Verbinder setzen: freie Stelle -> neuer Punkt
    mitte = f.mesh.bounds.mean(axis=0)
    f._verbinder_umschalten(0, mitte + [30, 0, 0])
    assert len(f.schnitte[0]["punkte"]) == 1
    # Nochmal draufklicken -> wieder weg
    f._verbinder_umschalten(0, mitte + [31, 0, 0])
    assert f.schnitte[0]["punkte"] == []
    f._rueckgaengig()
    assert len(f.schnitte[0]["punkte"]) == 1

    e = f._einstellungen()
    teile, n = gui.kern.zerteile(f.mesh, e["schnitte"], e["duebel"])
    assert n == 1 and len(teile) == 2
    f.close()
