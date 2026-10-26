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

    # In Bambu Studio öffnen: speichert neben dem Modell, auch wenn 3MF abgewählt ist
    f.dreimf.setChecked(False)
    gestartet = []
    datei = f._in_bambu(starten=lambda dateien, programm: gestartet.append(dateien) or True)
    assert datei == modell.parent / "zylinder_teile" / "zylinder_teile.3mf" and datei.exists()
    assert gestartet == [[datei]]
    assert "In Bambu Studio geöffnet" in f.protokoll.toPlainText()
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


def test_beste_lage_und_stuetzen(app, tmp_path):
    modell = tmp_path / "zylinder.stl"
    trimesh.creation.cylinder(radius=60, height=500).export(modell)
    f = gui.Fenster()
    f.show()
    f._oeffnen(str(modell))
    ergebnisse = []
    f.signale.fertig.disconnect()
    f.signale.fertig.connect(ergebnisse.append)
    f._arbeite(f._einstellungen())
    app.processEvents()
    f._berechnet(ergebnisse[0])
    f.teile_liste.setCurrentRow(0)
    f._in_bauraum()
    # Teil um 90° kippen: liegender Zylinder braucht Stützen
    f._teil_drehen(0)
    assert "Stützen nötig" in f.passt_info.text()
    assert "ueberhang" in f.ansicht.actors
    lagen = []
    f.signale.lage.disconnect()
    f.signale.lage.connect(lagen.append)
    f._beste_lage(alle=True)
    import time
    for _ in range(100):
        app.processEvents()
        if lagen:
            break
        time.sleep(0.1)
    assert lagen and set(lagen[0]) == {0, 1}
    f._lage_gefunden(lagen[0])
    assert "ueberhang" not in f.ansicht.actors  # stehender Zylinder: keine Stützen
    f.close()


def test_skalieren(app, tmp_path):
    modell = tmp_path / "zylinder.stl"
    trimesh.creation.cylinder(radius=60, height=500).export(modell)
    f = gui.Fenster()
    f.show()
    f._oeffnen(str(modell))
    f.manuell.setChecked(True)
    f.ebene = (f.mesh.bounds.mean(axis=0), np.array([0.0, 0.0, 1.0]))
    f._plane_widget()
    f._schnitt_dazu()
    unten = f.mesh.bounds[0].copy()

    # Zielhöhe 250 mm -> 50 %, der Schnitt wandert mit
    f.groesse[2].setValue(250)
    f._groesse_gewaehlt(2)
    assert f.faktor == pytest.approx(0.5)
    assert f.massstab.value() == pytest.approx(50)
    assert f.mesh.extents == pytest.approx([60, 60, 250])
    assert f.schnitte[0]["punkt"][2] == pytest.approx(unten[2] + 125)
    assert "125 mm" in f.schnitte[0]["text"]

    # Prozent, bezogen auf das Original
    f.massstab.setValue(200)
    f._skalieren(f.massstab.value() / 100)
    assert f.mesh.extents[2] == pytest.approx(1000)
    assert f.groesse[0].value() == pytest.approx(240)
    assert f.schnitte[0]["punkt"][2] == pytest.approx(unten[2] + 500)

    ergebnisse = []
    f.signale.fertig.disconnect()
    f.signale.fertig.connect(ergebnisse.append)
    f._arbeite(f._einstellungen())
    app.processEvents()
    teile = ergebnisse[0][0]
    assert sorted(round(t.extents[2]) for t in teile) == [500, 500]  # Schnitt in der Mitte des 1000-mm-Modells
    f._skalieren(1.0)
    assert f.mesh is f.original
    f.close()


def test_moderne_oberflaeche(app, tmp_path, monkeypatch):
    monkeypatch.setattr(gui.profile, "pfad", lambda: tmp_path / "einstellungen.json")
    modell = tmp_path / "zylinder.stl"
    trimesh.creation.cylinder(radius=60, height=500).export(modell)
    f = gui.Fenster()
    f.show()
    assert f.seiten.currentIndex() == 0 and not f.k_zuletzt.isEnabled()

    # Datei ins Fenster ziehen
    mime = gui.QtCore.QMimeData()
    mime.setUrls([gui.QtCore.QUrl.fromLocalFile(str(modell))])
    assert f._modell_aus(mime) == str(modell)
    mime.setUrls([gui.QtCore.QUrl.fromLocalFile(str(tmp_path / "bild.png"))])
    assert f._modell_aus(mime) is None
    f._oeffnen(str(modell))
    assert f.einstellungen["zuletzt"] == [str(modell)] and f.k_zuletzt.isEnabled()
    # Nach dem Neuzeichnen müssen Lampen da sein, sonst wirkt das Modell flach
    assert len(f.ansicht.renderer.lights) > 1
    assert f.status.text() == "Geladen: zylinder.stl"

    # Design umschalten wird gemerkt
    f.a_design.trigger()
    assert f.design_name == "hell" and gui.profile.lade()["design"] == "hell"
    f.a_design.trigger()
    assert f.design_name == "dunkel"

    # Nach dem Berechnen springt die Seite auf „Teile“, Karten haben Vorschaubilder
    ergebnisse = []
    f.signale.fertig.disconnect()
    f.signale.fertig.connect(ergebnisse.append)
    f._arbeite(f._einstellungen())
    app.processEvents()
    f._berechnet(ergebnisse[0])
    assert f.seiten.currentIndex() == 3 and not f.teile_leer.isVisibleTo(f)
    assert not f.teile_liste.item(0).icon().isNull()
    assert "Teil 1" in f.teile_liste.item(0).text()
    f._zeige_modell()
    assert f.seiten.currentIndex() == 1

    # Fehler klappen das Protokoll auf
    monkeypatch.setattr(gui.QtWidgets.QMessageBox, "critical", lambda *a: None)
    f._fehler("Test")
    assert f.protokoll.isVisibleTo(f)
    f.close()
