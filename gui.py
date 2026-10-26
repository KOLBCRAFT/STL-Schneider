#!/usr/bin/env python3
"""Fenster-Programm für den STL-Schneider mit 3D-Ansicht."""
import os
import sys
import threading
from pathlib import Path

import numpy as np
import pyvista as pv
import trimesh
from pyvistaqt import QtInteractor
from qtpy import QtCore, QtWidgets

import profile_speicher as profile
import stl_schneider as kern

EIGENER = "Eigene Maße"
PASST_FARBE = "#40c057"
ZU_GROSS_FARBE = "#fa5252"
PASST_TOENE = (PASST_FARBE, "#2b8a3e")
ZU_GROSS_TOENE = (ZU_GROSS_FARBE, "#c92a2a")
MODELLFARBE = "#adb5bd"
SCHNITTFARBE = "#d9480f"


def zu_pyvista(mesh):
    return pv.PolyData.from_regular_faces(np.asarray(mesh.vertices), np.asarray(mesh.faces))


class Signale(QtCore.QObject):
    log = QtCore.Signal(str)
    fertig = QtCore.Signal(object)
    fehler = QtCore.Signal(str)


class Fenster(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STL-Schneider")
        self.resize(1400, 900)

        self.mesh = None          # trimesh des geladenen Modells
        self.pfad = None
        self.ebene = None         # aktuelle Ebene des Widgets (punkt, normale)
        self.schnitte = []        # hinzugefügte Ebenen
        self.ebene_widget = None
        self.lagen = {}           # Teil-Index -> 4x4-Matrix, von Hand im Bauraum platziert
        self.teil_akteur = None
        self.teil_widget = None
        self.ergebnis = None      # (teile, anzahl_dübel, einstellungen) nach "Teile berechnen"

        self.signale = Signale()
        self.signale.log.connect(self._log)
        self.signale.fertig.connect(self._berechnet)
        self.signale.fehler.connect(self._fehler)

        self._baue_oberflaeche()

    # ---------- Oberfläche ----------

    def _baue_oberflaeche(self):
        teiler = QtWidgets.QSplitter()
        self.setCentralWidget(teiler)

        links = QtWidgets.QWidget()
        spalte = QtWidgets.QVBoxLayout(links)
        rollen = QtWidgets.QScrollArea()
        rollen.setWidgetResizable(True)
        rollen.setWidget(links)
        rollen.setMinimumWidth(390)
        self.rollen = rollen
        linke_seite = QtWidgets.QWidget()
        lv = QtWidgets.QVBoxLayout(linke_seite)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(rollen, 1)
        unten = QtWidgets.QVBoxLayout()
        unten.setContentsMargins(8, 4, 8, 8)
        lv.addLayout(unten)
        teiler.addWidget(linke_seite)

        rechts = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.ansicht = QtInteractor(rechts)
        self.ansicht.set_background("white")
        rechts.addWidget(self.ansicht.interactor)
        self.protokoll = QtWidgets.QPlainTextEdit()
        self.protokoll.setReadOnly(True)
        rechts.addWidget(self.protokoll)
        rechts.setStretchFactor(0, 1)
        rechts.setSizes([760, 140])
        teiler.addWidget(rechts)
        teiler.setStretchFactor(1, 1)
        teiler.setSizes([410, 990])

        # Modell
        gruppe, form = self._gruppe(spalte, "Modell")
        knopf = QtWidgets.QPushButton("Öffnen …")
        knopf.clicked.connect(self._oeffnen)
        form.addRow(knopf)
        self.info = QtWidgets.QLabel("Noch keine Datei geladen")
        self.info.setWordWrap(True)
        form.addRow(self.info)

        # Drucker
        gruppe, form = self._gruppe(spalte, "Drucker")
        self.einstellungen = profile.lade()
        self.drucker = QtWidgets.QComboBox()
        self.drucker.currentTextChanged.connect(self._drucker_gewaehlt)
        form.addRow(self.drucker)
        zeile = QtWidgets.QHBoxLayout()
        self.bauraum = []
        for name, wert in zip("XYZ", kern.DRUCKER[kern.STANDARD_DRUCKER]):
            feld = self._zahl(wert, 10, 2000, 0)
            feld.valueChanged.connect(self._bauraum_geaendert)
            self.bauraum.append(feld)
            zeile.addWidget(QtWidgets.QLabel(name))
            zeile.addWidget(feld)
        zeile.addWidget(QtWidgets.QLabel("mm"))
        form.addRow(zeile)
        zeile = QtWidgets.QHBoxLayout()
        k = QtWidgets.QPushButton("Als Profil speichern …")
        k.clicked.connect(self._profil_speichern)
        zeile.addWidget(k)
        self.k_profil_loeschen = QtWidgets.QPushButton("Profil löschen")
        self.k_profil_loeschen.clicked.connect(self._profil_loeschen)
        zeile.addWidget(self.k_profil_loeschen)
        form.addRow(zeile)
        self._profile_fuellen(self.einstellungen.get("letztes_profil", kern.STANDARD_DRUCKER))

        # Schneiden
        gruppe, form = self._gruppe(spalte, "Schneiden")
        self.auto = QtWidgets.QRadioButton("Automatisch (an dünnen Stellen)")
        self.manuell = QtWidgets.QRadioButton("Manuell (eigene Schnitte)")
        self.auto.setChecked(True)
        self.auto.toggled.connect(self._modus_gewaehlt)
        form.addRow(self.auto)
        form.addRow(self.manuell)

        self.manuell_box = QtWidgets.QWidget()
        m = QtWidgets.QVBoxLayout(self.manuell_box)
        m.setContentsMargins(0, 4, 0, 0)
        hilfe = QtWidgets.QLabel("Rote Ebene im 3D-Fenster: Fläche ziehen = verschieben, "
                                 "Pfeil ziehen = kippen. Oder Ebene hier ausrichten:")
        hilfe.setWordWrap(True)
        m.addWidget(hilfe)
        zeile = QtWidgets.QHBoxLayout()
        for i, name in enumerate("XYZ"):
            k = QtWidgets.QPushButton(f"⟂ {name}")
            k.setToolTip(f"Ebene senkrecht zur {name}-Achse durch die Modellmitte")
            k.clicked.connect(lambda _=False, a=i: self._ebene_achse(a))
            zeile.addWidget(k)
        m.addLayout(zeile)
        zeile = QtWidgets.QHBoxLayout()
        zeile.addWidget(QtWidgets.QLabel("Verschieben"))
        self.schieber = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.schieber.setRange(-500, 500)
        self.schieber.valueChanged.connect(self._schieber_bewegt)
        self.schieber.sliderReleased.connect(self._schieber_los)
        self._schieber_alt = 0
        zeile.addWidget(self.schieber)
        m.addLayout(zeile)
        self.ebene_info = QtWidgets.QLabel("")
        m.addWidget(self.ebene_info)
        self.fenster_an = QtWidgets.QCheckBox("Schnittfenster begrenzen (nur Segmente im Fenster)")
        self.fenster_an.setToolTip("Nur Stellen, die das Rechteck berühren, werden geschnitten. "
                                   "Das Fenster sitzt am Mittelpunkt der Ebene, den du mit der Maus ziehst.")
        self.fenster_an.toggled.connect(self._zeichne_fenster)
        m.addWidget(self.fenster_an)
        zeile = QtWidgets.QHBoxLayout()
        self.fenster_b = self._zahl(100, 5, 2000, 0)
        self.fenster_h = self._zahl(100, 5, 2000, 0)
        for text, feld in (("Breite", self.fenster_b), ("Höhe", self.fenster_h)):
            zeile.addWidget(QtWidgets.QLabel(text))
            zeile.addWidget(feld)
            feld.valueChanged.connect(self._zeichne_fenster)
        zeile.addWidget(QtWidgets.QLabel("mm"))
        m.addLayout(zeile)
        zeile = QtWidgets.QHBoxLayout()
        k = QtWidgets.QPushButton("Schnitt hinzufügen")
        k.clicked.connect(self._schnitt_dazu)
        zeile.addWidget(k)
        k = QtWidgets.QPushButton("Entfernen")
        k.clicked.connect(self._schnitt_weg)
        zeile.addWidget(k)
        m.addLayout(zeile)
        self.liste = QtWidgets.QListWidget()
        self.liste.setMaximumHeight(110)
        m.addWidget(self.liste)
        form.addRow(self.manuell_box)

        # Dübel
        gruppe, form = self._gruppe(spalte, "Dübel")
        self.d_anzahl = QtWidgets.QSpinBox()
        self.d_anzahl.setRange(0, 8)
        self.d_anzahl.setValue(2)
        self.d_durchmesser = self._zahl(6.0, 2, 30, 1)
        self.d_tiefe = self._zahl(10.0, 2, 50, 1)
        self.d_spiel = self._zahl(0.2, 0, 2, 2, schritt=0.05)
        form.addRow("Anzahl pro Schnitt", self.d_anzahl)
        form.addRow("Durchmesser mm", self.d_durchmesser)
        form.addRow("Tiefe je Seite mm", self.d_tiefe)
        form.addRow("Spiel mm", self.d_spiel)
        self.d_drucken = QtWidgets.QCheckBox("Dübel mitdrucken")
        self.d_drucken.setChecked(True)
        form.addRow(self.d_drucken)

        # Ansicht
        gruppe, form = self._gruppe(spalte, "Ansicht")
        hilfe = QtWidgets.QLabel("Linke Maustaste drehen, Mausrad zoomen, mittlere Taste "
                                 "(oder Umschalt + links) verschieben.")
        hilfe.setWordWrap(True)
        form.addRow(hilfe)
        self.maus3d = QtWidgets.QCheckBox("3D-Maus verwenden")
        self.maus3d.toggled.connect(self._maus3d_umschalten)
        form.addRow(self.maus3d)
        self.maus3d_tempo = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.maus3d_tempo.setRange(1, 20)
        self.maus3d_tempo.setValue(8)
        form.addRow("Empfindlichkeit", self.maus3d_tempo)
        self.spacemouse = None
        self.maus3d_takt = QtCore.QTimer(self)
        self.maus3d_takt.timeout.connect(self._maus3d_schritt)

        # Teile im Bauraum testen
        self.teile_gruppe, form = self._gruppe(spalte, "Teile im Bauraum testen")
        hilfe = QtWidgets.QLabel("Grün = passt in den Bauraum, rot = zu groß. Teil wählen und in den Bauraum legen. Dann mit den Pfeilen verschieben "
                                 "und mit den Ringen drehen. Die Lage wird beim Speichern übernommen.")
        hilfe.setWordWrap(True)
        form.addRow(hilfe)
        self.teile_liste = QtWidgets.QListWidget()
        self.teile_liste.setMaximumHeight(130)
        self.teile_liste.currentRowChanged.connect(self._teil_gewaehlt)
        form.addRow(self.teile_liste)
        zeile = QtWidgets.QHBoxLayout()
        self.k_bauraum = QtWidgets.QPushButton("In den Bauraum legen")
        self.k_bauraum.clicked.connect(self._in_bauraum)
        zeile.addWidget(self.k_bauraum)
        self.k_alle = QtWidgets.QPushButton("Alle Teile")
        self.k_alle.clicked.connect(self._zeige_teile)
        zeile.addWidget(self.k_alle)
        form.addRow(zeile)
        zeile = QtWidgets.QHBoxLayout()
        k = QtWidgets.QPushButton("Auto-Lage")
        k.setToolTip("Teil wieder automatisch druckfertig hinlegen")
        k.clicked.connect(lambda: self._in_bauraum(neu=True))
        zeile.addWidget(k)
        for text, achse in (("↻ X", 0), ("↻ Y", 1), ("↻ Z", 2)):
            k = QtWidgets.QPushButton(text)
            k.setToolTip(f"90° um die {'XYZ'[achse]}-Achse drehen")
            k.clicked.connect(lambda _=False, a=achse: self._teil_drehen(a))
            zeile.addWidget(k)
        form.addRow(zeile)
        self.passt_info = QtWidgets.QLabel("")
        self.passt_info.setWordWrap(True)
        form.addRow(self.passt_info)
        self.teile_gruppe.setVisible(False)

        # Ausgabe
        gruppe, form = self._gruppe(spalte, "Ausgabe")
        self.dreimf = QtWidgets.QCheckBox("3MF für Bambu Studio")
        self.dreimf.setChecked(True)
        self.drehen = QtWidgets.QCheckBox("Teile auf Schnittfläche legen")
        self.drehen.setChecked(True)
        form.addRow(self.dreimf)
        form.addRow(self.drehen)

        self.k_berechnen = QtWidgets.QPushButton("Teile berechnen")
        self.k_berechnen.clicked.connect(self._berechnen)
        self.k_modell = QtWidgets.QPushButton("Zurück zum Modell")
        self.k_modell.clicked.connect(self._zeige_modell)
        self.k_speichern = QtWidgets.QPushButton("Speichern …")
        self.k_speichern.clicked.connect(self._speichern)
        for k in (self.k_berechnen, self.k_modell, self.k_speichern):
            k.setMinimumHeight(32)
            unten.addWidget(k)
        spalte.addStretch(1)

        self._modus_gewaehlt()
        self._knoepfe()
        QtCore.QTimer.singleShot(0, lambda: self.maus3d.setChecked(True))

    def _gruppe(self, spalte, titel):
        gruppe = QtWidgets.QGroupBox(titel)
        form = QtWidgets.QFormLayout(gruppe)
        spalte.addWidget(gruppe)
        return gruppe, form

    def _zahl(self, wert, lo, hi, stellen, schritt=None):
        feld = QtWidgets.QDoubleSpinBox()
        feld.setRange(lo, hi)
        feld.setDecimals(stellen)
        feld.setValue(wert)
        if schritt:
            feld.setSingleStep(schritt)
        return feld

    def _knoepfe(self):
        geladen = self.mesh is not None
        self.k_berechnen.setEnabled(geladen)
        self.k_modell.setEnabled(self.ergebnis is not None)
        self.k_speichern.setEnabled(self.ergebnis is not None)

    def _log(self, text):
        self.protokoll.appendPlainText(text)

    # ---------- Modell und Ansicht ----------

    def _oeffnen(self, pfad=None):
        if not pfad:
            pfad, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Modell öffnen", "",
                                                            "3D-Modelle (*.stl *.3mf *.obj);;Alle Dateien (*)")
        if not pfad:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.mesh = kern.lade(pfad)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Fehler", f"Datei konnte nicht geladen werden:\n{e}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.pfad = Path(pfad)
        x, y, z = self.mesh.extents
        self.info.setText(f"{self.pfad.name}\n{x:.1f} × {y:.1f} × {z:.1f} mm, {len(self.mesh.faces):,} Dreiecke"
                          + ("" if self.mesh.is_watertight else "\nAchtung: Modell ist nicht geschlossen"))
        self.modell_pv = zu_pyvista(self.mesh)
        self.schnitte.clear()
        self.liste.clear()
        self.ergebnis = None
        self.ebene = (self.mesh.bounds.mean(axis=0), np.array([0.0, 0.0, 1.0]))
        groesse = round(float(np.max(self.mesh.extents)) / 3)
        for feld in (self.fenster_b, self.fenster_h):
            feld.blockSignals(True)
            feld.setValue(groesse)
            feld.blockSignals(False)
        self._log(f"Geladen: {self.pfad.name}")
        self._zeige_modell()
        self.ansicht.reset_camera()
        self._knoepfe()

    def _zeige_modell(self):
        self.ergebnis = None
        self.lagen = {}
        self.teile_gruppe.setVisible(False)
        self._entferne_teil_widget()
        self._knoepfe()
        p = self.ansicht
        p.clear_plane_widgets()
        self.ebene_widget = None
        p.clear()
        p.add_mesh(self.modell_pv, color=MODELLFARBE, smooth_shading=True, name="modell")
        self._zeichne_bauraum()
        self._zeichne_schnitte()
        if self.manuell.isChecked():
            self._plane_widget()
        p.add_axes()
        p.render()

    def _zeichne_bauraum(self):
        if self.mesh is None or self.ergebnis is not None:
            return
        lo = self.mesh.bounds[0]
        b = [f.value() for f in self.bauraum]
        box = pv.Box(bounds=(lo[0], lo[0] + b[0], lo[1], lo[1] + b[1], lo[2], lo[2] + b[2]))
        self.ansicht.add_mesh(box, style="wireframe", color="#2b8a3e", line_width=1, name="bauraum",
                              opacity=0.6, pickable=False)

    def _zeichne_schnitte(self):
        groesse = float(np.linalg.norm(self.mesh.extents)) * 1.1
        for i in range(50):
            self.ansicht.remove_actor(f"schnitt{i}")
        for i, schnitt in enumerate(self.schnitte):
            punkt, normale = schnitt[0], schnitt[1]
            if len(schnitt) > 2:
                flaeche = self._rechteck(schnitt[2])
            else:
                flaeche = pv.Plane(center=punkt, direction=normale, i_size=groesse, j_size=groesse)
            self.ansicht.add_mesh(flaeche, color=SCHNITTFARBE, opacity=0.25, name=f"schnitt{i}", pickable=False)

    def _plane_widget(self):
        self.ansicht.clear_plane_widgets()
        lo, hi = self.mesh.bounds
        rand = 0.05 * self.mesh.extents
        widget = self.ansicht.add_plane_widget(
            self._ebene_bewegt, normal=self.ebene[1], origin=self.ebene[0],
            bounds=(lo[0] - rand[0], hi[0] + rand[0], lo[1] - rand[1], hi[1] + rand[1], lo[2] - rand[2], hi[2] + rand[2]),
            color=SCHNITTFARBE, normal_rotation=True, outline_translation=False, origin_translation=True,
            implicit=True, interaction_event="always",
        )
        self.ebene_widget = widget
        self._zeichne_fenster()
        widget.GetPlaneProperty().SetOpacity(0.3)
        widget.GetSelectedPlaneProperty().SetOpacity(0.4)
        widget.GetOutlineProperty().SetOpacity(0.2)
        self._ebene_text()

    def _ebene_bewegt(self, normale, punkt):
        self.ebene = (np.array(punkt, float), np.array(normale, float))
        self._ebene_text()
        self._zeichne_fenster()

    def _fenster(self, punkt, normale):
        if not self.fenster_an.isChecked():
            return None
        u, v = kern.ebenen_achsen(normale)
        return kern.Fenster(np.array(punkt, float), u, v, self.fenster_b.value(), self.fenster_h.value())

    @staticmethod
    def _rechteck(f):
        ecken = [f.mitte + a * f.u * f.breite / 2 + b * f.v * f.hoehe / 2 for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        return pv.PolyData(np.array(ecken), faces=[4, 0, 1, 2, 3])

    def _zeichne_fenster(self, *_):
        if self.mesh is None:
            return
        self.ansicht.remove_actor("fenster")
        if self.ebene is None or self.ebene_widget is None:
            return
        f = self._fenster(*self.ebene)
        if f is not None:
            self.ansicht.add_mesh(self._rechteck(f), color="#1971c2", opacity=0.45, show_edges=True,
                                  edge_color="#1971c2", line_width=3, name="fenster", pickable=False)
        self.ansicht.render()

    def _ebene_text(self):
        if self.ebene is None:
            return
        punkt, n = self.ebene
        n = n / np.linalg.norm(n)
        lo = self.mesh.bounds[0]
        rel = punkt - lo
        neigung = np.degrees(np.arccos(min(1.0, np.max(np.abs(n)))))
        achse = "XYZ"[int(np.argmax(np.abs(n)))]
        self.ebene_info.setText(f"Ebene ⟂ {achse}, {neigung:.0f}° gekippt, "
                                f"Punkt {rel[0]:.0f} / {rel[1]:.0f} / {rel[2]:.0f} mm")

    def _ebene_achse(self, achse):
        if self.mesh is None:
            return
        n = np.zeros(3)
        n[achse] = 1.0
        self.ebene = (self.mesh.bounds.mean(axis=0), n)
        self._plane_widget()
        self.ansicht.render()

    def _schieber_bewegt(self, wert):
        # Verschiebt die Ebene entlang ihrer Normalen; der Regler springt nach dem Loslassen auf 0 zurück
        schritt = (wert - self._schieber_alt) / 500 * 0.5 * float(np.max(self.mesh.extents)) if self.mesh is not None else 0
        self._schieber_alt = wert
        if not schritt or self.ebene_widget is None:
            return
        punkt, n = self.ebene
        n = n / np.linalg.norm(n)
        self.ebene = (punkt + n * schritt, n)
        self.ebene_widget.SetOrigin(*self.ebene[0])
        self._ebene_text()
        self._zeichne_fenster()
        self.ansicht.render()

    def _schieber_los(self):
        self.schieber.blockSignals(True)
        self.schieber.setValue(0)
        self.schieber.blockSignals(False)
        self._schieber_alt = 0

    def _modus_gewaehlt(self):
        self.manuell_box.setEnabled(self.manuell.isChecked())
        if self.mesh is not None and self.ergebnis is None:
            if self.manuell.isChecked():
                self._plane_widget()
            else:
                self.ansicht.clear_plane_widgets()
                self.ebene_widget = None
                self._zeichne_fenster()
            self.ansicht.render()

    # ---------- Drucker-Profile ----------

    def _alle_profile(self):
        return {**kern.DRUCKER, **self.einstellungen["profile"]}

    def _profile_fuellen(self, auswahl):
        self.drucker.blockSignals(True)
        self.drucker.clear()
        self.drucker.addItems(list(kern.DRUCKER))
        eigene = sorted(self.einstellungen["profile"])
        if eigene:
            self.drucker.insertSeparator(self.drucker.count())
            self.drucker.addItems(eigene)
        self.drucker.addItem(EIGENER)
        self.drucker.blockSignals(False)
        if self.drucker.findText(auswahl) < 0:
            auswahl = kern.STANDARD_DRUCKER
        self.drucker.setCurrentText(auswahl)
        self._drucker_gewaehlt(auswahl)

    def _drucker_gewaehlt(self, name):
        werte = self._alle_profile().get(name)
        if werte:
            for feld, w in zip(self.bauraum, werte):
                feld.blockSignals(True)
                feld.setValue(w)
                feld.blockSignals(False)
            self._zeichne_bauraum()
            self.einstellungen["letztes_profil"] = name
            profile.speichere(self.einstellungen)
        self.k_profil_loeschen.setEnabled(name in self.einstellungen["profile"])

    def _bauraum_geaendert(self):
        # Von Hand geänderte Maße passen nicht mehr zum Profil
        werte = self._alle_profile().get(self.drucker.currentText())
        if werte and list(werte) != [f.value() for f in self.bauraum]:
            self.drucker.blockSignals(True)
            self.drucker.setCurrentText(EIGENER)
            self.drucker.blockSignals(False)
            self.k_profil_loeschen.setEnabled(False)
        self._zeichne_bauraum()

    def _profil_speichern(self):
        vorschlag = self.drucker.currentText()
        if vorschlag == EIGENER or vorschlag in kern.DRUCKER:
            vorschlag = ""
        name, ok = QtWidgets.QInputDialog.getText(self, "Profil speichern", "Name des Profils:", text=vorschlag)
        name = name.strip()
        if not ok or not name:
            return
        if name in kern.DRUCKER or name == EIGENER:
            QtWidgets.QMessageBox.information(self, "Profil speichern",
                                              "Dieser Name ist schon vergeben, bitte einen anderen wählen.")
            return
        self.einstellungen["profile"][name] = [f.value() for f in self.bauraum]
        profile.speichere(self.einstellungen)
        self._profile_fuellen(name)
        self._log(f"Profil „{name}“ gespeichert")

    def _profil_loeschen(self):
        name = self.drucker.currentText()
        if name not in self.einstellungen["profile"]:
            return
        if QtWidgets.QMessageBox.question(self, "Profil löschen", f"Profil „{name}“ löschen?") != \
                QtWidgets.QMessageBox.Yes:
            return
        del self.einstellungen["profile"][name]
        profile.speichere(self.einstellungen)
        self._profile_fuellen(kern.STANDARD_DRUCKER)

    # ---------- 3D-Maus ----------

    def _maus3d_umschalten(self, an):
        if an and self.spacemouse is None:
            import spacemouse
            self.spacemouse = spacemouse.finde()
            if self.spacemouse is None:
                self.maus3d.blockSignals(True)
                self.maus3d.setChecked(False)
                self.maus3d.blockSignals(False)
                self.maus3d.setText("3D-Maus verwenden (keine gefunden)")
                return
            self.maus3d.setText(f"3D-Maus verwenden ({self.spacemouse.name})")
            self._log(f"3D-Maus gefunden: {self.spacemouse.name}")
        if an:
            self.maus3d_takt.start(30)
        else:
            self.maus3d_takt.stop()

    def _maus3d_schritt(self):
        if self.spacemouse is None:
            return
        tx, ty, tz, rx, ry, rz = self.spacemouse.lesen()
        werte = np.array([tx, ty, tz, rx, ry, rz])
        werte[np.abs(werte) < 0.05] = 0  # kleine Ausschläge ignorieren
        if not werte.any():
            return
        tx, ty, tz, rx, ry, rz = werte
        tempo = self.maus3d_tempo.value() / 8
        kamera = self.ansicht.renderer.GetActiveCamera()
        # Drehen um den Mittelpunkt der Ansicht
        kamera.Azimuth(-rz * 3 * tempo)
        kamera.Elevation(-rx * 3 * tempo)
        kamera.Roll(ry * 3 * tempo)
        kamera.OrthogonalizeViewUp()
        # Verschieben in Bildschirmrichtung, Kappe drücken/ziehen = zoomen
        pos, fokus = np.array(kamera.GetPosition()), np.array(kamera.GetFocalPoint())
        blick = fokus - pos
        entfernung = np.linalg.norm(blick)
        oben = np.array(kamera.GetViewUp())
        rechts = np.cross(blick / entfernung, oben)
        versatz = (rechts * tx - oben * tz) * 0.02 * entfernung * tempo
        kamera.SetPosition(*(pos + versatz))
        kamera.SetFocalPoint(*(fokus + versatz))
        if ty:
            kamera.Dolly(1 + ty * 0.04 * tempo)
        self.ansicht.renderer.ResetCameraClippingRange()
        self.ansicht.render()

    def closeEvent(self, ereignis):
        if self.spacemouse is not None:
            self.spacemouse.schliessen()
        super().closeEvent(ereignis)

    # ---------- Schnitte ----------

    def _schnitt_dazu(self):
        if self.ebene is None:
            return
        punkt, n = self.ebene
        n = n / np.linalg.norm(n)
        f = self._fenster(punkt, n)
        self.schnitte.append((punkt.copy(), n.copy(), f) if f else (punkt.copy(), n.copy()))
        text = self.ebene_info.text().replace("Ebene ", "Schnitt ")
        if f:
            text += f", Fenster {f.breite:.0f} × {f.hoehe:.0f} mm"
        self.liste.addItem(text)
        self._zeichne_schnitte()
        self.ansicht.render()

    def _schnitt_weg(self):
        for eintrag in self.liste.selectedItems():
            i = self.liste.row(eintrag)
            self.liste.takeItem(i)
            del self.schnitte[i]
        self._zeichne_schnitte()
        self.ansicht.render()

    def _einstellungen(self):
        duebel = None
        if self.d_anzahl.value() > 0:
            duebel = kern.Duebel(self.d_anzahl.value(), self.d_durchmesser.value(), self.d_tiefe.value(),
                                 self.d_spiel.value(), drucken=self.d_drucken.isChecked())
        return dict(auto=self.auto.isChecked(), schnitte=list(self.schnitte),
                    bauraum=[f.value() for f in self.bauraum], duebel=duebel)

    def _berechnen(self):
        if self.mesh is None:
            return
        e = self._einstellungen()
        if not e["auto"] and not e["schnitte"]:
            QtWidgets.QMessageBox.information(self, "STL-Schneider",
                                              "Bitte mindestens einen Schnitt hinzufügen.")
            return
        self.k_berechnen.setEnabled(False)
        self.k_berechnen.setText("Berechne …")
        threading.Thread(target=self._arbeite, args=(e,), daemon=True).start()

    def _arbeite(self, e):
        log = self.signale.log.emit
        try:
            if e["auto"]:
                teile, n = kern.automatisch(self.mesh, e["bauraum"], duebel=e["duebel"], log=log)
            else:
                teile, n = kern.zerteile(self.mesh, e["schnitte"], e["duebel"], log=log)
            self.signale.fertig.emit((teile, n, e))
        except Exception as fehler:
            self.signale.fehler.emit(str(fehler))

    def _fehler(self, text):
        self.k_berechnen.setText("Teile berechnen")
        self._knoepfe()
        self._log(f"FEHLER: {text}")
        QtWidgets.QMessageBox.critical(self, "Fehler", text)

    def _berechnet(self, ergebnis):
        self.k_berechnen.setText("Teile berechnen")
        teile, n, e = ergebnis
        self.ergebnis = ergebnis
        self._knoepfe()
        passt = sum(kern.passt_irgendwie(t, e["bauraum"]) for t in teile)
        self._log(f"{len(teile)} Teile, {n} Dübel. {passt} von {len(teile)} passen auf die Platte. "
                  "Mit „Speichern …“ ausgeben.")
        self.lagen = {}
        self.huellen = [t.convex_hull.vertices if len(t.vertices) > 2000 else t.vertices for t in teile]
        self.teile_liste.blockSignals(True)
        self.teile_liste.clear()
        for i, t in enumerate(teile):
            ok = "passt" if kern.passt_irgendwie(t, e["bauraum"]) else "zu groß"
            x, y, z = sorted(t.extents, reverse=True)
            self.teile_liste.addItem(f"Teil {i + 1}: {x:.0f} × {y:.0f} × {z:.0f} mm, {ok}")
        self.teile_liste.setCurrentRow(0)
        self.teile_liste.blockSignals(False)
        self.teile_gruppe.setVisible(True)
        self._zeige_teile()
        QtCore.QTimer.singleShot(50, lambda: self.rollen.ensureWidgetVisible(self.teile_gruppe))

    def _zeige_teile(self):
        """Alle Teile farbig und leicht auseinandergezogen zeigen."""
        if self.ergebnis is None:
            return
        teile = self.ergebnis[0]
        self.im_bauraum = False
        self._entferne_teil_widget()
        p = self.ansicht
        p.clear_plane_widgets()
        self.ebene_widget = None
        p.clear()
        mitte = self.mesh.bounds.mean(axis=0)
        abstand = 0.12 * float(np.max(self.mesh.extents))
        for i, t in enumerate(teile):
            richtung = t.bounds.mean(axis=0) - mitte
            laenge = np.linalg.norm(richtung)
            versatz = richtung / laenge * abstand if laenge > 1e-6 else np.zeros(3)
            netz = zu_pyvista(t)
            netz.translate(versatz, inplace=True)
            passt = kern.passt_irgendwie(t, self.ergebnis[2]["bauraum"])
            # Abwechselnd hell/dunkel, damit benachbarte Teile unterscheidbar bleiben
            farben = PASST_TOENE if passt else ZU_GROSS_TOENE
            p.add_mesh(netz, color=farben[i % 2], smooth_shading=True, name=f"teil{i}")
            p.add_point_labels([t.bounds.mean(axis=0) + versatz], [f"{i + 1}"], font_size=14,
                               shape_opacity=0.6, always_visible=True, name=f"nummer{i}")
        p.add_axes()
        p.reset_camera()
        p.render()
        self.passt_info.setText("")

    # ---------- Teil im Bauraum ----------

    def _entferne_teil_widget(self):
        if self.teil_widget is not None:
            try:
                self.teil_widget.remove()
            except Exception:
                pass
        self.teil_widget = None
        self.teil_akteur = None

    def _teil_gewaehlt(self, zeile):
        if getattr(self, "im_bauraum", False) and zeile >= 0:
            self._in_bauraum()

    def _in_bauraum(self, neu=False):
        if self.ergebnis is None or self.teile_liste.currentRow() < 0:
            return
        i = self.teile_liste.currentRow()
        teil = self.ergebnis[0][i]
        b = self.ergebnis[2]["bauraum"]
        if neu or i not in self.lagen:
            m = kern.platte_lage(teil, b)
            # In die Mitte der Platte schieben
            pts = trimesh.transform_points(self.huellen[i], m)
            mitte_xy = (pts.min(axis=0) + pts.max(axis=0)) / 2
            m = trimesh.transformations.translation_matrix([b[0] / 2 - mitte_xy[0], b[1] / 2 - mitte_xy[1], 0]) @ m
            self.lagen[i] = m

        self.im_bauraum = True
        self._entferne_teil_widget()
        p = self.ansicht
        p.clear_plane_widgets()
        self.ebene_widget = None
        p.clear()
        box = pv.Box(bounds=(0, b[0], 0, b[1], 0, b[2]))
        p.add_mesh(box, style="wireframe", color="#2b8a3e", line_width=2, name="bauraum", pickable=False)
        platte = pv.Plane(center=(b[0] / 2, b[1] / 2, -0.5), i_size=b[0], j_size=b[1])
        p.add_mesh(platte, color="#495057", opacity=0.5, name="platte", pickable=False)
        self.teil_akteur = p.add_mesh(zu_pyvista(teil), color=PASST_FARBE,
                                      smooth_shading=True, name="teil_im_bauraum")
        self.teil_akteur.user_matrix = self.lagen[i]
        pts = trimesh.transform_points(self.huellen[i], self.lagen[i])
        self.teil_widget = p.add_affine_transform_widget(
            self.teil_akteur, origin=tuple((pts.min(axis=0) + pts.max(axis=0)) / 2),
            interact_callback=self._teil_bewegt, release_callback=self._teil_losgelassen)
        p.add_axes()
        p.reset_camera()
        p.render()
        self._pruefe_lage()

    def _teil_bewegt(self, matrix):
        self.lagen[self.teile_liste.currentRow()] = np.array(matrix)
        self._pruefe_lage()

    def _teil_losgelassen(self, matrix):
        self._teil_bewegt(matrix)
        # Widget an die neue Teilmitte setzen, damit Drehungen um das Teil herum gehen
        i = self.teile_liste.currentRow()
        pts = trimesh.transform_points(self.huellen[i], self.lagen[i])
        if self.teil_widget is not None:
            self.teil_widget.origin = tuple((pts.min(axis=0) + pts.max(axis=0)) / 2)

    def _teil_drehen(self, achse):
        if not getattr(self, "im_bauraum", False) or self.teil_akteur is None:
            return
        i = self.teile_liste.currentRow()
        m = self.lagen[i]
        pts = trimesh.transform_points(self.huellen[i], m)
        mitte = (pts.min(axis=0) + pts.max(axis=0)) / 2
        richtung = np.zeros(3)
        richtung[achse] = 1.0
        rot = trimesh.transformations.rotation_matrix(np.pi / 2, richtung, mitte)
        m = rot @ m
        # Wieder auf die Platte setzen
        pts = trimesh.transform_points(self.huellen[i], m)
        m = trimesh.transformations.translation_matrix([0, 0, -pts.min(axis=0)[2]]) @ m
        self.lagen[i] = m
        self.teil_akteur.user_matrix = m
        self._teil_losgelassen(m)
        self.ansicht.render()

    def _pruefe_lage(self):
        i = self.teile_liste.currentRow()
        b = np.array(self.ergebnis[2]["bauraum"], float)
        pts = trimesh.transform_points(self.huellen[i], self.lagen[i])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        ueber = np.maximum(hi - b, 0)
        unter = np.maximum(-lo, 0)
        probleme = []
        for k, name in enumerate("XYZ"):
            if ueber[k] > 0.05:
                probleme.append(f"{ueber[k]:.1f} mm zu weit in +{name}")
            if unter[k] > 0.05:
                probleme.append("unter der Platte" if k == 2 else f"{unter[k]:.1f} mm zu weit in −{name}")
        x, y, z = hi - lo
        if probleme:
            text = f"Teil {i + 1} ({x:.0f} × {y:.0f} × {z:.0f} mm) ragt hinaus: " + ", ".join(probleme)
            farbe = "#c92a2a"
        else:
            text = f"Teil {i + 1} ({x:.0f} × {y:.0f} × {z:.0f} mm) passt in den Bauraum."
            farbe = "#2b8a3e"
        self.passt_info.setText(text)
        self.passt_info.setStyleSheet(f"color: {farbe}; font-weight: bold;")
        akteur = self.ansicht.actors.get("bauraum")
        if akteur is not None:
            akteur.prop.color = farbe
        if self.teil_akteur is not None:
            self.teil_akteur.prop.color = ZU_GROSS_FARBE if probleme else PASST_FARBE
        self.ansicht.render()

    def _speichern(self, ordner=None):
        if self.ergebnis is None:
            return
        if not ordner:
            ordner = QtWidgets.QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", str(self.pfad.parent))
        if not ordner:
            return
        teile, n, e = self.ergebnis
        ziel = Path(ordner) / f"{self.pfad.stem}_teile"
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            kern.exportiere(teile, self.pfad.stem, ziel, e["bauraum"], drehen=self.drehen.isChecked(),
                            dreimf=self.dreimf.isChecked(), duebel=e["duebel"], anzahl_duebel=n, log=self._log,
                            lagen=self.lagen)
        except Exception as fehler:
            self._fehler(str(fehler))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if hasattr(os, "startfile"):
            os.startfile(ziel)


def main():
    app = QtWidgets.QApplication(sys.argv)
    fenster = Fenster()
    fenster.show()
    if len(sys.argv) > 1:
        fenster._oeffnen(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
