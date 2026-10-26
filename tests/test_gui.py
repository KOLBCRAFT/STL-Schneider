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
