#!/usr/bin/env python3
"""KOLBCRAFT Cutter: Fenster-Programm mit 3D-Ansicht."""
import os
import sys
import threading
from pathlib import Path

import numpy as np
import pyvista as pv
import trimesh
from pyvistaqt import QtInteractor
from qtpy import QtCore, QtGui, QtWidgets

import bambu_studio
import design
import profile_speicher as profile
import stl_schneider as kern

EIGENER = "Eigene Maße"
PASST_FARBE = "#40c057"
ZU_GROSS_FARBE = "#fa5252"
PASST_TOENE = (PASST_FARBE, "#2b8a3e")
ZU_GROSS_TOENE = (ZU_GROSS_FARBE, "#c92a2a")
MONTAGE_TOENE = ("#fd7e14", "#d9480f")  # Orange: passt, aber Problem beim Zusammenbau
MODELLFARBE = "#adb5bd"
SCHNITTFARBE = "#d9480f"
# Leichter Glanz, damit Rillen und Kanten der Oberfläche plastisch wirken
OBERFLAECHE = dict(smooth_shading=True, specular=0.4, specular_power=20)
SCHRITTE = ("Modell", "Schneiden", "Verbinder", "Teile", "Ausgabe")


def zu_pyvista(mesh):
    return pv.PolyData.from_regular_faces(np.asarray(mesh.vertices), np.asarray(mesh.faces))


def raster(x0, y0, z, breite, tiefe, abstand=25.0):
    """Linien im Abstand von abstand mm auf der Druckplatte, wie in Bambu Studio."""
    punkte, linien = [], []
    for x in np.arange(0, breite + 1e-6, abstand):
        punkte += [(x0 + x, y0, z), (x0 + x, y0 + tiefe, z)]
    for y in np.arange(0, tiefe + 1e-6, abstand):
        punkte += [(x0, y0 + y, z), (x0 + breite, y0 + y, z)]
    for i in range(0, len(punkte), 2):
        linien += [2, i, i + 1]
    return pv.PolyData(np.array(punkte, float), lines=np.array(linien))


def vorschaubild(teil, farbe, passt, groesse=128):
    """Kleines Bild des Teils (schräg von oben) mit grünem oder rotem Punkt in der Ecke.

    Gerechnet mit numpy aus Punkten auf der Oberfläche, damit kein zweites OpenGL-Fenster nötig ist.
    """
    try:
        punkte, flaechen = trimesh.sample.sample_surface(teil, 30000)
        normalen = teil.face_normals[flaechen]
    except Exception:
        return None
    blick = -np.ones(3) / np.sqrt(3)                       # von der Kamera (+1,+1,+1) zur Mitte
    rechts = np.cross(blick, [0, 0, 1.0])
    rechts /= np.linalg.norm(rechts)
    hoch = np.cross(rechts, blick)
    licht = -blick + 0.6 * hoch
    licht /= np.linalg.norm(licht)
    x, y, tiefe = punkte @ rechts, punkte @ hoch, punkte @ -blick
    rand = 6
    massstab = (groesse - 2 * rand) / max(np.ptp(x), np.ptp(y), 1e-6)
    ix = ((x - (x.min() + x.max()) / 2) * massstab + groesse / 2).astype(int)
    iy = (groesse / 2 - (y - (y.min() + y.max()) / 2) * massstab).astype(int)
    grund = np.array(QtGui.QColor(farbe).getRgb()[:3], float)
    hell = 0.35 + 0.65 * np.clip(normalen @ licht, 0, 1)
    farben = np.clip(grund[None, :] * hell[:, None], 0, 255).astype(np.uint8)
    bild = np.zeros((groesse, groesse, 4), np.uint8)
    reihenfolge = np.argsort(tiefe)                        # nahe Punkte zuletzt, sie übermalen die fernen
    for dx in (0, 1):
        for dy in (0, 1):
            px = np.clip(ix[reihenfolge] + dx, 0, groesse - 1)
            py = np.clip(iy[reihenfolge] + dy, 0, groesse - 1)
            bild[py, px, :3] = farben[reihenfolge]
            bild[py, px, 3] = 255
    bild = np.ascontiguousarray(bild)
    h, w = bild.shape[:2]
    qbild = QtGui.QImage(bild.data, w, h, 4 * w, QtGui.QImage.Format_RGBA8888).copy()
    maler = QtGui.QPainter(qbild)
    maler.setRenderHint(QtGui.QPainter.Antialiasing)
    maler.setPen(QtGui.QPen(QtGui.QColor("white"), 3))
    maler.setBrush(QtGui.QColor(PASST_FARBE if passt else ZU_GROSS_FARBE))
    r = groesse // 7
    maler.drawEllipse(w - 2 * r - 4, 4, 2 * r, 2 * r)
    maler.end()
    return QtGui.QIcon(QtGui.QPixmap.fromImage(qbild))


class Signale(QtCore.QObject):
    log = QtCore.Signal(str)
    fertig = QtCore.Signal(object)
    fehler = QtCore.Signal(str)
    lage = QtCore.Signal(object)


class Fenster(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KOLBCRAFT Cutter")
        self.resize(1400, 900)

        self.mesh = None          # trimesh des geladenen Modells
        self.pfad = None
        self.ebene = None         # aktuelle Ebene des Widgets (punkt, normale)
        self.schnitte = []        # hinzugefügte Schnitte: dict(punkt, normale, fenster, punkte, text)
        self.verlauf, self.zukunft = [], []  # für Rückgängig / Wiederholen
        self.ebene_widget = None
        self.lagen = {}           # Teil-Index -> 4x4-Matrix, von Hand im Bauraum platziert
        self.teil_akteur = None
        self.teil_widget = None
        self.ergebnis = None      # (teile, anzahl_dübel, einstellungen) nach "Teile berechnen"
        self.montage = []         # [(teil_index, text)] aus kern.montage_pruefen

        self.signale = Signale()
        self.signale.log.connect(self._log)
        self.signale.fertig.connect(self._berechnet)
        self.signale.fehler.connect(self._fehler)
        self.signale.lage.connect(self._lage_gefunden)

        self._baue_oberflaeche()

    # ---------- Oberfläche ----------

    def _baue_oberflaeche(self):
        teiler = QtWidgets.QSplitter()
        self.setCentralWidget(teiler)

        # Links: Arbeitsschritte als Reiter, darunter je Schritt eine eigene, rollbare Seite
        linke_seite = QtWidgets.QWidget()
        linke_seite.setMinimumWidth(390)
        lv = QtWidgets.QVBoxLayout(linke_seite)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(0)
        reiter = QtWidgets.QHBoxLayout()
        reiter.setContentsMargins(6, 4, 6, 0)
        reiter.setSpacing(0)
        lv.addLayout(reiter)
        self.seiten = QtWidgets.QStackedWidget()
        lv.addWidget(self.seiten, 1)
        self.schritt_knoepfe = QtWidgets.QButtonGroup(self)
        self.schritt_knoepfe.setExclusive(True)
        self.rollen_je_schritt, spalten = [], []
        for nr, titel in enumerate(SCHRITTE):
            k = QtWidgets.QToolButton()
            k.setText(f"{nr + 1}  {titel}")
            k.setCheckable(True)
            k.setProperty("rolle", "schritt")
            k.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.schritt_knoepfe.addButton(k, nr)
            reiter.addWidget(k)
            inhalt = QtWidgets.QWidget()
            spalten.append(QtWidgets.QVBoxLayout(inhalt))
            rollen = QtWidgets.QScrollArea()
            rollen.setWidgetResizable(True)
            rollen.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            rollen.setWidget(inhalt)
            self.rollen_je_schritt.append(rollen)
            self.seiten.addWidget(rollen)
        self.schritt_knoepfe.idClicked.connect(self._schritt)
        self.schritt_knoepfe.button(0).setChecked(True)
        unten = QtWidgets.QVBoxLayout()
        unten.setContentsMargins(8, 4, 8, 8)
        lv.addLayout(unten)
        teiler.addWidget(linke_seite)

        oben = QtWidgets.QWidget()
        ov = QtWidgets.QVBoxLayout(oben)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(0)
        self.werkzeuge = QtWidgets.QToolBar()
        ov.addWidget(self.werkzeuge)
        self.ansicht = QtInteractor(oben)
        # Rechtsklick ohne Ziehen setzt Verbinder; Rechts ziehen bleibt Zoomen.
        # Hohe Priorität, damit der Druck vor der Kamera-Steuerung ankommt.
        self._rechts_druck = None
        self.ansicht.iren.interactor.AddObserver("RightButtonPressEvent", self._rechts_gedrueckt, 10.0)
        self.ansicht.iren.add_observer("RightButtonReleaseEvent", self._rechts_losgelassen)
        ov.addWidget(self.ansicht.interactor, 1)
        # Statuszeile mit der letzten Meldung, darunter das einklappbare Protokoll
        status = QtWidgets.QHBoxLayout()
        status.setContentsMargins(8, 3, 4, 3)
        self.status = QtWidgets.QLabel("Modell öffnen oder STL-Datei ins Fenster ziehen.")
        self.status.setProperty("rolle", "hinweis")
        status.addWidget(self.status, 1)
        self.k_protokoll = QtWidgets.QToolButton()
        self.k_protokoll.setText("Protokoll ▴")
        self.k_protokoll.setCheckable(True)
        self.k_protokoll.toggled.connect(self._protokoll_zeigen)
        status.addWidget(self.k_protokoll)
        ov.addLayout(status)
        self.protokoll = QtWidgets.QPlainTextEdit()
        self.protokoll.setReadOnly(True)
        self.protokoll.setMaximumHeight(200)
        self.protokoll.setVisible(False)
        ov.addWidget(self.protokoll)
        teiler.addWidget(oben)
        teiler.setStretchFactor(1, 1)
        teiler.setSizes([430, 970])
        self.setAcceptDrops(True)

        # Modell
        spalte = spalten[0]
        gruppe, form = self._gruppe(spalte, "Modell")
        zeile = QtWidgets.QHBoxLayout()
        knopf = QtWidgets.QPushButton("Öffnen …")
        knopf.setToolTip("STL, 3MF oder OBJ öffnen. Dateien lassen sich auch einfach ins Fenster ziehen.")
        knopf.clicked.connect(self._oeffnen)
        zeile.addWidget(knopf, 1)
        self.k_zuletzt = QtWidgets.QPushButton("Zuletzt ▾")
        self.zuletzt_menue = QtWidgets.QMenu(self)
        self.k_zuletzt.setMenu(self.zuletzt_menue)
        zeile.addWidget(self.k_zuletzt)
        form.addRow(zeile)
        self.info = QtWidgets.QLabel("Noch keine Datei geladen")
        self.info.setWordWrap(True)
        form.addRow(self.info)
        self.k_reparieren = QtWidgets.QPushButton("Modell reparieren")
        self.k_reparieren.setToolTip("Kleine Löcher schließen, Dreiecke einheitlich ausrichten, entartete Dreiecke "
                                     "entfernen. Rückgängig: Datei neu öffnen.")
        self.k_reparieren.clicked.connect(self._reparieren)
        self.k_reparieren.setVisible(False)
        form.addRow(self.k_reparieren)
        zeile = QtWidgets.QHBoxLayout()
        self.massstab = self._zahl(100, 0.1, 100000, 1, 10)
        self.massstab.setSuffix(" %")
        self.massstab.setToolTip("Modell gleichmäßig skalieren, bezogen auf die Originalgröße")
        self.massstab.editingFinished.connect(lambda: self._skalieren(self.massstab.value() / 100))
        knopf = QtWidgets.QPushButton("100 %")
        knopf.setToolTip("Zurück zur Originalgröße")
        knopf.clicked.connect(lambda: self._skalieren(1.0))
        zeile.addWidget(self.massstab, 1)
        zeile.addWidget(knopf)
        form.addRow("Maßstab", zeile)
        zeile = QtWidgets.QHBoxLayout()
        self.groesse = []
        for i, name in enumerate("XYZ"):
            feld = self._zahl(0, 0.1, 100000, 1)
            feld.setToolTip(f"Gewünschtes Maß in {name} eintragen, die anderen Achsen werden mitskaliert")
            feld.editingFinished.connect(lambda i=i: self._groesse_gewaehlt(i))
            zeile.addWidget(QtWidgets.QLabel(name))
            zeile.addWidget(feld, 1)
            self.groesse.append(feld)
        form.addRow("Größe mm", zeile)

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
        self._zuletzt_fuellen()

        # Schneiden
        spalte = spalten[1]
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
        self.liste.currentRowChanged.connect(lambda _: self._zeichne_schnitte(True))
        m.addWidget(self.liste)
        zeile = QtWidgets.QHBoxLayout()
        self.k_zurueck = QtWidgets.QPushButton("↶ Rückgängig")
        self.k_zurueck.setToolTip("Strg+Z")
        self.k_zurueck.clicked.connect(self._rueckgaengig)
        zeile.addWidget(self.k_zurueck)
        self.k_vor = QtWidgets.QPushButton("↷ Wiederholen")
        self.k_vor.setToolTip("Strg+Y")
        self.k_vor.clicked.connect(self._wiederholen)
        zeile.addWidget(self.k_vor)
        m.addLayout(zeile)
        hilfe = QtWidgets.QLabel("Verbinder: Schnitt in der Liste wählen. Rechtsklick auf die Schnittfläche setzt "
                                 "einen Verbinder, Rechtsklick auf einen Verbinder entfernt ihn. "
                                 "Blau = automatisch, orange = selbst gesetzt.")
        hilfe.setWordWrap(True)
        hilfe.setProperty("rolle", "hinweis")
        m.addWidget(hilfe)
        QtWidgets.QShortcut(QtGui.QKeySequence.Undo, self, self._rueckgaengig)
        QtWidgets.QShortcut(QtGui.QKeySequence.Redo, self, self._wiederholen)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Y"), self, self._wiederholen)
        form.addRow(self.manuell_box)

        # Verbinder
        spalte = spalten[2]
        gruppe, form = self._gruppe(spalte, "Verbinder")
        self.d_art = QtWidgets.QComboBox()
        for art, name in kern.VERBINDER_ARTEN.items():
            self.d_art.addItem(name, art)
        self.d_art.currentIndexChanged.connect(self._art_gewaehlt)
        form.addRow("Art", self.d_art)
        self.d_art_info = QtWidgets.QLabel("")
        self.d_art_info.setWordWrap(True)
        self.d_art_info.setProperty("rolle", "hinweis")
        form.addRow(self.d_art_info)
        self.d_anzahl = QtWidgets.QSpinBox()
        self.d_anzahl.setRange(0, 8)
        self.d_anzahl.setValue(2)
        self.d_durchmesser = self._zahl(6.0, 2, 30, 1)
        self.d_tiefe = self._zahl(10.0, 2, 50, 1)
        self.d_spiel = self._zahl(0.2, 0, 2, 2, schritt=0.05)
        form.addRow("Anzahl pro Schnitt", self.d_anzahl)
        form.addRow("Durchmesser mm", self.d_durchmesser)
        self.d_tiefe_label = QtWidgets.QLabel("Tiefe je Seite mm")
        form.addRow(self.d_tiefe_label, self.d_tiefe)
        form.addRow("Spiel mm", self.d_spiel)
        self.d_drucken = QtWidgets.QCheckBox("Dübel mitdrucken")
        self.d_drucken.setChecked(True)
        form.addRow(self.d_drucken)
        for feld in (self.d_anzahl, self.d_durchmesser, self.d_spiel):
            feld.valueChanged.connect(lambda *_: self._zeichne_schnitte(True))
        self._art_werte = {}  # merkt sich Maße je Art beim Umschalten
        self._art_alt = "duebel"
        self._art_gewaehlt()

        # Teile im Bauraum testen
        spalte = spalten[3]
        self.teile_leer = QtWidgets.QLabel("Noch keine Teile. Erst unten auf „Teile berechnen“ klicken.")
        self.teile_leer.setWordWrap(True)
        self.teile_leer.setProperty("rolle", "hinweis")
        spalte.addWidget(self.teile_leer)
        self.teile_gruppe, form = self._gruppe(spalte, "Teile im Bauraum testen")
        hilfe = QtWidgets.QLabel("Grün = passt in den Bauraum, rot = zu groß, orange = Problem beim Zusammenbau "
                                 "(steht im Protokoll). Teil wählen und in den Bauraum legen. Dann mit den Pfeilen verschieben "
                                 "und mit den Ringen drehen. Die Lage wird beim Speichern übernommen.")
        hilfe.setWordWrap(True)
        form.addRow(hilfe)
        self.teile_liste = QtWidgets.QListWidget()
        self.teile_liste.setIconSize(QtCore.QSize(64, 64))
        self.teile_liste.setSpacing(2)
        self.teile_liste.setMinimumHeight(220)
        self.teile_liste.setMaximumHeight(320)
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
        zeile = QtWidgets.QHBoxLayout()
        self.k_beste = QtWidgets.QPushButton("Beste Lage")
        self.k_beste.setToolTip("Lage mit möglichst wenig Stützmaterial, guter Auflage und geringer Höhe suchen")
        self.k_beste.clicked.connect(lambda: self._beste_lage(alle=False))
        zeile.addWidget(self.k_beste)
        self.k_beste_alle = QtWidgets.QPushButton("Beste Lage für alle")
        self.k_beste_alle.clicked.connect(lambda: self._beste_lage(alle=True))
        zeile.addWidget(self.k_beste_alle)
        form.addRow(zeile)
        zeile = QtWidgets.QHBoxLayout()
        self.stuetzen_an = QtWidgets.QCheckBox("Stützen anzeigen ab")
        self.stuetzen_an.setChecked(True)
        self.stuetzen_an.setToolTip("Überhänge, die Stützen brauchen, orange färben")
        self.stuetzen_an.toggled.connect(lambda *_: self._zeige_ueberhang())
        zeile.addWidget(self.stuetzen_an)
        self.ueberhang_winkel = self._zahl(45, 10, 89, 0)
        self.ueberhang_winkel.setSuffix("°")
        self.ueberhang_winkel.setToolTip("Überhangwinkel von der Senkrechten, ab dem Stützen nötig sind "
                                         "(wie in Bambu Studio, meist 30–45°)")
        self.ueberhang_winkel.valueChanged.connect(lambda *_: self._zeige_ueberhang())
        zeile.addWidget(self.ueberhang_winkel)
        zeile.addStretch(1)
        form.addRow(zeile)
        self.passt_info = QtWidgets.QLabel("")
        self.passt_info.setWordWrap(True)
        form.addRow(self.passt_info)
        self.teile_gruppe.setVisible(False)

        # Ausgabe
        spalte = spalten[4]
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
        self.k_bambu = QtWidgets.QPushButton("In Bambu Studio öffnen")
        self.k_bambu.setToolTip("Speichert die Teile neben dem Modell und öffnet die 3MF in Bambu Studio")
        self.k_bambu.clicked.connect(self._in_bambu)
        unten.addWidget(self.k_berechnen)
        zeile = QtWidgets.QHBoxLayout()
        zeile.addWidget(self.k_modell)
        zeile.addWidget(self.k_speichern)
        unten.addLayout(zeile)
        unten.addWidget(self.k_bambu)
        for k in (self.k_modell, self.k_speichern):
            k.setMinimumHeight(32)
        for k in (self.k_berechnen, self.k_bambu):
            k.setProperty("rolle", "haupt")
            k.setMinimumHeight(40)
        for spalte in spalten:
            spalte.addStretch(1)
        self._baue_einstellungen()
        self._baue_werkzeuge()

        self._modus_gewaehlt()
        self._bambu_anzeigen()
        self._design(self.einstellungen.get("design", "dunkel"))
        self._knoepfe()
        QtCore.QTimer.singleShot(0, lambda: self.maus3d.setChecked(self.einstellungen.get("maus3d", True)))

    def _baue_einstellungen(self):
        """Fenster hinter dem Zahnrad: Dinge, die man einmal einstellt und dann vergisst."""
        e = self.einstellungen
        d = QtWidgets.QDialog(self)
        d.setWindowTitle("Einstellungen")
        d.setMinimumWidth(460)
        self.einstellungs_fenster = d
        spalte = QtWidgets.QVBoxLayout(d)

        gruppe, form = self._gruppe(spalte, "Darstellung")
        self.design_wahl = QtWidgets.QComboBox()
        self.design_wahl.addItem("Dunkel", "dunkel")
        self.design_wahl.addItem("Hell", "hell")
        self.design_wahl.currentIndexChanged.connect(
            lambda _: self._design(self.design_wahl.currentData(), merken=True))
        form.addRow("Design", self.design_wahl)
        self.glanz = QtWidgets.QCheckBox("Glanz auf den Oberflächen (Rillen und Kanten besser sichtbar)")
        self.glanz.setChecked(e.get("glanz", True))
        form.addRow(self.glanz)
        zeile = QtWidgets.QHBoxLayout()
        self.raster_an = QtWidgets.QCheckBox("Raster auf der Druckplatte, alle")
        self.raster_an.setChecked(e.get("raster", True))
        self.raster_abstand = self._zahl(e.get("raster_abstand", 25), 5, 100, 0, 5)
        self.raster_abstand.setSuffix(" mm")
        zeile.addWidget(self.raster_an)
        zeile.addWidget(self.raster_abstand)
        zeile.addStretch(1)
        form.addRow(zeile)

        gruppe, form = self._gruppe(spalte, "Maus und 3D-Maus")
        hilfe = QtWidgets.QLabel("Linke Maustaste drehen, Mausrad zoomen, mittlere Taste "
                                 "(oder Umschalt + links) verschieben.")
        hilfe.setWordWrap(True)
        hilfe.setProperty("rolle", "hinweis")
        form.addRow(hilfe)
        self.maus3d = QtWidgets.QCheckBox("3D-Maus verwenden")
        self.maus3d.toggled.connect(self._maus3d_umschalten)
        form.addRow(self.maus3d)
        self.maus3d_tempo = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.maus3d_tempo.setRange(1, 20)
        self.maus3d_tempo.setValue(e.get("maus3d_tempo", 8))
        form.addRow("Empfindlichkeit", self.maus3d_tempo)
        self.maus3d_umkehren = QtWidgets.QCheckBox("Richtungen umkehren")
        self.maus3d_umkehren.setToolTip("Falls sich die Ansicht genau andersherum bewegt als erwartet")
        self.maus3d_umkehren.setChecked(e.get("maus3d_umkehren", False))
        form.addRow(self.maus3d_umkehren)
        self.spacemouse = None
        self.maus3d_takt = QtCore.QTimer(self)
        self.maus3d_takt.timeout.connect(self._maus3d_schritt)

        gruppe, form = self._gruppe(spalte, "Bambu Studio")
        zeile = QtWidgets.QHBoxLayout()
        self.bambu_info = QtWidgets.QLabel("")
        self.bambu_info.setWordWrap(True)
        knopf = QtWidgets.QPushButton("Wählen …")
        knopf.setToolTip("Pfad zu bambu-studio.exe selbst festlegen")
        knopf.clicked.connect(self._bambu_waehlen)
        zeile.addWidget(self.bambu_info, 1)
        zeile.addWidget(knopf)
        form.addRow(zeile)

        ort = QtWidgets.QLabel(f"Gespeichert in {profile.pfad()}")
        ort.setWordWrap(True)
        ort.setProperty("rolle", "hinweis")
        spalte.addWidget(ort)
        zeile = QtWidgets.QHBoxLayout()
        zeile.addStretch(1)
        knopf = QtWidgets.QPushButton("Schließen")
        knopf.clicked.connect(d.close)
        zeile.addWidget(knopf)
        spalte.addLayout(zeile)

        # Jede Änderung sofort übernehmen und merken
        def merken(schluessel, wert, neu_zeichnen=False):
            self.einstellungen[schluessel] = wert
            profile.speichere(self.einstellungen)
            if neu_zeichnen:
                self._neu_zeichnen()

        self.glanz.toggled.connect(lambda an: merken("glanz", an, True))
        self.raster_an.toggled.connect(lambda an: merken("raster", an, True))
        self.raster_abstand.valueChanged.connect(lambda w: merken("raster_abstand", w, True))
        self.maus3d.toggled.connect(lambda an: merken("maus3d", an))
        self.maus3d_tempo.valueChanged.connect(lambda w: merken("maus3d_tempo", w))
        self.maus3d_umkehren.toggled.connect(lambda an: merken("maus3d_umkehren", an))

    def _einstellungen_zeigen(self):
        self.einstellungs_fenster.show()
        self.einstellungs_fenster.raise_()
        self.einstellungs_fenster.activateWindow()

    def _oberflaeche(self):
        if self.glanz.isChecked():
            return OBERFLAECHE
        return dict(smooth_shading=True)

    def _neu_zeichnen(self):
        if self.mesh is not None and self.ergebnis is None:
            self._zeige_modell()
        elif getattr(self, "im_bauraum", False):
            self._in_bauraum()
        elif self.ergebnis is not None:
            self._zeige_teile()

    def _baue_werkzeuge(self):
        w = self.werkzeuge
        w.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)

        def aktion(text, tipp, funktion, umschalter=False):
            a = w.addAction(text)
            a.setToolTip(tipp)
            a.setCheckable(umschalter)
            a.triggered.connect(funktion)
            return a

        p = self.ansicht
        aktion("◇ Iso", "Schräg von oben", lambda: self._kamera(p.view_isometric))
        aktion("Vorn", "Ansicht von vorn", lambda: self._kamera(p.view_xz))
        aktion("Seite", "Ansicht von rechts", lambda: self._kamera(p.view_yz))
        aktion("Oben", "Ansicht von oben", lambda: self._kamera(p.view_xy))
        aktion("⤢ Einpassen", "Alles ins Bild holen", lambda: self._kamera(None))
        w.addSeparator()
        self.a_zurueck = aktion("↶", "Schnitt rückgängig (Strg+Z)", self._rueckgaengig)
        self.a_vor = aktion("↷", "Wiederholen (Strg+Y)", self._wiederholen)
        w.addSeparator()
        self.a_stuetzen = aktion("Stützen", "Überhänge, die Stützen brauchen, orange zeigen",
                                 lambda an: self.stuetzen_an.setChecked(an), umschalter=True)
        self.a_stuetzen.setChecked(self.stuetzen_an.isChecked())
        self.stuetzen_an.toggled.connect(self.a_stuetzen.setChecked)
        abstand = QtWidgets.QWidget()
        abstand.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        w.addWidget(abstand)
        self.a_einstellungen = aktion("⚙", "Einstellungen: Design, 3D-Maus, Bambu Studio, Darstellung",
                                      self._einstellungen_zeigen)
        knopf = w.widgetForAction(self.a_einstellungen)
        knopf.setStyleSheet("font-size: 15pt; padding: 0 8px;")

    def _leeren(self):
        """Szene leeren. clear() entfernt auch die Lampen, ohne sie wirkt alles flach wie ein Scherenschnitt."""
        self.ansicht.clear()
        self.ansicht.enable_lightkit()

    def _kamera(self, ansicht):
        if ansicht is not None:
            ansicht()
        self.ansicht.reset_camera()
        self.ansicht.render()

    def _design(self, name, merken=False):
        if name not in design.FARBEN:
            name = "dunkel"
        app = QtWidgets.QApplication.instance()
        design.anwenden(app, name)
        oben, unten = design.hintergrund_3d(name)
        self.ansicht.set_background(unten, top=oben)
        self.design_wahl.blockSignals(True)
        self.design_wahl.setCurrentIndex(self.design_wahl.findData(name))
        self.design_wahl.blockSignals(False)
        self.design_name = name
        if merken:
            self.einstellungen["design"] = name
            profile.speichere(self.einstellungen)
            self._neu_zeichnen()  # Druckplatte in den neuen Farben

    def _schritt(self, nr):
        self.schritt_knoepfe.button(nr).setChecked(True)
        self.seiten.setCurrentIndex(nr)

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
        self.k_bambu.setEnabled(self.ergebnis is not None)

    def _log(self, text):
        self.protokoll.appendPlainText(text)
        self.status.setText(text.splitlines()[0] if text else "")

    def _protokoll_zeigen(self, an):
        self.protokoll.setVisible(an)
        self.k_protokoll.setText("Protokoll ▾" if an else "Protokoll ▴")

    # ---------- Datei ins Fenster ziehen, zuletzt geöffnet ----------

    @staticmethod
    def _modell_aus(mime):
        for url in mime.urls() if mime.hasUrls() else []:
            pfad = str(Path(url.toLocalFile()))  # Windows: Backslashes wie im Dateidialog
            if Path(pfad).suffix.lower() in (".stl", ".3mf", ".obj"):
                return pfad
        return None

    def dragEnterEvent(self, ereignis):
        if self._modell_aus(ereignis.mimeData()):
            ereignis.acceptProposedAction()

    def dropEvent(self, ereignis):
        pfad = self._modell_aus(ereignis.mimeData())
        if pfad:
            ereignis.acceptProposedAction()
            self._oeffnen(pfad)

    def _zuletzt_merken(self, pfad):
        liste = [p for p in self.einstellungen.get("zuletzt", []) if p != str(pfad)]
        self.einstellungen["zuletzt"] = [str(pfad)] + liste[:7]
        profile.speichere(self.einstellungen)
        self._zuletzt_fuellen()

    def _zuletzt_fuellen(self):
        menue = self.zuletzt_menue
        menue.clear()
        liste = [p for p in self.einstellungen.get("zuletzt", []) if Path(p).exists()]
        for p in liste:
            a = menue.addAction(Path(p).name)
            a.setToolTip(p)
            a.triggered.connect(lambda _=False, p=p: self._oeffnen(p))
        self.k_zuletzt.setEnabled(bool(liste))

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
        self.original = self.mesh
        self.faktor = 1.0
        self._groesse_anzeigen()
        self.modell_pv = zu_pyvista(self.mesh)
        self.schnitte.clear()
        self.verlauf.clear()
        self.zukunft.clear()
        self._liste_aktualisieren()
        self.ergebnis, self.montage = None, []
        self.ebene = (self.mesh.bounds.mean(axis=0), np.array([0.0, 0.0, 1.0]))
        groesse = round(float(np.max(self.mesh.extents)) / 3)
        for feld in (self.fenster_b, self.fenster_h):
            feld.blockSignals(True)
            feld.setValue(groesse)
            feld.blockSignals(False)
        self._log(f"Geladen: {self.pfad.name}")
        if self.hinweise:
            self._log("Modellprüfung: " + "; ".join(self.hinweise) + ". „Modell reparieren“ kann helfen.")
        self._zuletzt_merken(self.pfad)
        self._zeige_modell()
        self.ansicht.reset_camera()
        self._knoepfe()

    def _groesse_anzeigen(self):
        x, y, z = self.mesh.extents
        text = f"{self.pfad.name}\n{x:.1f} × {y:.1f} × {z:.1f} mm, {len(self.mesh.faces):,} Dreiecke"
        if self.faktor != 1.0:
            o = self.original.extents
            text += f"\nOriginal {o[0]:.1f} × {o[1]:.1f} × {o[2]:.1f} mm"
        self.hinweise = kern.modell_pruefen(self.mesh)
        if self.hinweise:
            text += "\nAchtung: " + "; ".join(self.hinweise)
        self.k_reparieren.setVisible(bool(self.hinweise))
        self.info.setText(text)
        for feld, wert in zip([self.massstab, *self.groesse], [self.faktor * 100, x, y, z]):
            feld.blockSignals(True)
            feld.setValue(wert)
            feld.blockSignals(False)

    def _reparieren(self):
        if self.mesh is None:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            um = self.original.bounds[0]
            self.original = kern.repariere(self.original, log=self._log)
            # Reparatur verschiebt nichts, gesetzte Schnitte und Maßstab bleiben gültig
            self.mesh = kern.skaliere(self.original, self.faktor, um) if self.faktor != 1.0 else self.original
            self.modell_pv = zu_pyvista(self.mesh)
            self._halb_schluessel = None
            self._groesse_anzeigen()
            self._zeige_modell()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def _groesse_gewaehlt(self, achse):
        if self.mesh is None:
            return
        self._skalieren(self.groesse[achse].value() / float(self.original.extents[achse]))

    def _skalieren(self, faktor):
        """Skaliert das Modell gleichmäßig (bezogen auf das Original) um seine untere Ecke.
        Vorhandene Schnitte werden mitgeschoben, Verbindergrößen bleiben in mm gleich."""
        if self.mesh is None or faktor <= 0 or abs(faktor - self.faktor) < 1e-9:
            self._groesse_anzeigen() if self.mesh is not None else None
            return
        um = self.original.bounds[0]
        schritt = faktor / self.faktor

        def weiter(p):
            return um + (np.asarray(p, float) - um) * schritt

        for s in self.schnitte:
            s["punkt"] = weiter(s["punkt"])
            s["punkte"] = [weiter(p) for p in s["punkte"]]
            f = s["fenster"]
            if f is not None:
                s["fenster"] = kern.Fenster(weiter(f.mitte), f.u, f.v, f.breite * schritt, f.hoehe * schritt)
            s["text"] = self._schnitt_text(s["punkt"], s["normale"], s["fenster"], um)
        if self.ebene is not None:
            self.ebene = (weiter(self.ebene[0]), self.ebene[1])
        self.verlauf.clear()
        self.zukunft.clear()
        self.faktor = faktor
        self.mesh = kern.skaliere(self.original, faktor, um) if faktor != 1.0 else self.original
        self.modell_pv = zu_pyvista(self.mesh)
        self._halb_schluessel = None
        self._groesse_anzeigen()
        x, y, z = self.mesh.extents
        self._log(f"Skaliert auf {faktor * 100:.4g} %: {x:.1f} × {y:.1f} × {z:.1f} mm")
        self._liste_aktualisieren()
        self._zeige_modell()
        self.ansicht.reset_camera()

    def _zeige_modell(self):
        self.ergebnis, self.montage = None, []
        self.lagen = {}
        self.teile_gruppe.setVisible(False)
        self.teile_leer.setVisible(True)
        if self.seiten.currentIndex() == 3:
            self._schritt(1)
        self._entferne_teil_widget()
        self._knoepfe()
        p = self.ansicht
        p.clear_plane_widgets()
        self.ebene_widget = None
        self._leeren()
        p.add_mesh(self.modell_pv, color=MODELLFARBE, **self._oberflaeche(), name="modell")
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
        self._druckplatte(lo[0], lo[1], lo[2], b[0], b[1])

    def _druckplatte(self, x0, y0, z, breite, tiefe):
        farbe, linien = design.platte(getattr(self, "design_name", "dunkel"))
        platte = pv.Plane(center=(x0 + breite / 2, y0 + tiefe / 2, z - 0.5), i_size=breite, j_size=tiefe)
        self.ansicht.add_mesh(platte, color=farbe, opacity=0.9, name="platte", pickable=False)
        if self.raster_an.isChecked():
            self.ansicht.add_mesh(raster(x0, y0, z - 0.4, breite, tiefe, self.raster_abstand.value()),
                                  color=linien, line_width=1, name="raster", pickable=False)

    def _zeichne_schnitte(self, neu_rendern=False):
        if self.mesh is None or self.ergebnis is not None:
            return
        groesse = float(np.linalg.norm(self.mesh.extents)) * 1.1
        for name in list(self.ansicht.actors):
            if name.startswith(("schnitt", "insel", "verbinder")):
                self.ansicht.remove_actor(name)
        gewaehlt = self.liste.currentRow()
        for i, s in enumerate(self.schnitte):
            if s["fenster"] is not None:
                flaeche = self._rechteck(s["fenster"])
            else:
                flaeche = pv.Plane(center=s["punkt"], direction=s["normale"], i_size=groesse, j_size=groesse)
            aktiv = i == gewaehlt
            self.ansicht.add_mesh(flaeche, color=SCHNITTFARBE, opacity=0.35 if aktiv else 0.2, name=f"schnitt{i}",
                                  pickable=aktiv)
        # Beim gewählten Schnitt nur die Hälfte hinter der Ebene zeigen, damit Schnittfläche und Verbinder sichtbar sind
        if 0 <= gewaehlt < len(self.schnitte) and self.manuell.isChecked():
            s = self.schnitte[gewaehlt]
            # Die Hälfte auf der von der Kamera abgewandten Seite behalten
            kamera = np.array(self.ansicht.camera.position)
            hinten = bool(np.dot(kamera - s["punkt"], s["normale"]) > 0)
            schluessel = (gewaehlt, tuple(s["punkt"]), tuple(s["normale"]), hinten)
            if getattr(self, "_halb_schluessel", None) != schluessel:
                self._halb = self.modell_pv.clip(normal=s["normale"], origin=s["punkt"], invert=hinten)
                self._halb_schluessel = schluessel
            self.ansicht.add_mesh(self._halb, color=MODELLFARBE, **self._oberflaeche(), name="modell", pickable=False)
            self._zeichne_verbinder(s)
        else:
            self.ansicht.add_mesh(self.modell_pv, color=MODELLFARBE, **self._oberflaeche(), name="modell",
                                  pickable=False)
        if neu_rendern:
            self.ansicht.render()

    def _zeichne_verbinder(self, s):
        """Umriss der Schnittflächen und die geplanten Verbinder des gewählten Schnitts."""
        e = self._einstellungen()
        inseln = kern.querschnitt(self.mesh, (s["punkt"], s["normale"]), e["duebel"], s["fenster"], s["punkte"])
        for k, insel in enumerate(inseln):
            flaeche = pv.PolyData(insel.rand[:-1], faces=[len(insel.rand) - 1] + list(range(len(insel.rand) - 1)))
            self.ansicht.add_mesh(flaeche.triangulate(), color="#ffd8a8" if insel.gewaehlt else "#dee2e6",
                                  name=f"insel{k}", pickable=False)
            linie = pv.lines_from_points(np.vstack([insel.rand, insel.rand[:1]]))
            self.ansicht.add_mesh(linie, color=SCHNITTFARBE if insel.gewaehlt else "#868e96", line_width=3,
                                  name=f"inselrand{k}", pickable=False)
            r = (e["duebel"].durchmesser / 2) if e["duebel"] else 3
            for j, p in enumerate(insel.verbinder):
                kugel = pv.Sphere(radius=r, center=p)
                self.ansicht.add_mesh(kugel, color="#e8590c" if insel.manuell else "#1971c2",
                                      name=f"verbinder{k}_{j}", pickable=False)

    def _rechts_gedrueckt(self, *_):
        self._rechts_druck = self.ansicht.iren.interactor.GetEventPosition()

    def _rechts_losgelassen(self, *_):
        if self._rechts_druck is None:
            return
        x0, y0 = self._rechts_druck
        x, y = self.ansicht.iren.interactor.GetEventPosition()
        self._rechts_druck = None
        if abs(x - x0) + abs(y - y0) <= 4:
            self._rechtsklick()

    def _rechtsklick(self, *_):
        """Setzt oder entfernt einen Verbinder auf der Schnittfläche des gewählten Schnitts."""
        i = self.liste.currentRow()
        if self.ergebnis is not None or not self.manuell.isChecked() or not 0 <= i < len(self.schnitte):
            return
        akteur = self.ansicht.actors.get(f"schnitt{i}")
        if akteur is None:
            return
        import vtk
        x, y = self.ansicht.iren.interactor.GetEventPosition()
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.0005)
        picker.PickFromListOn()
        picker.AddPickList(akteur)
        if not picker.Pick(x, y, 0, self.ansicht.renderer):
            return
        self._verbinder_umschalten(i, np.array(picker.GetPickPosition()))

    def _verbinder_umschalten(self, i, p):
        s = self.schnitte[i]
        n = s["normale"] / np.linalg.norm(s["normale"])
        p = p - n * np.dot(p - s["punkt"], n)  # genau in die Ebene legen
        e = self._einstellungen()
        if e["duebel"] is None:
            self._log("Verbinder-Anzahl ist 0, es werden keine Verbinder gesetzt.")
            return
        r = e["duebel"].durchmesser
        inseln = kern.querschnitt(self.mesh, (s["punkt"], n), e["duebel"], s["fenster"], s["punkte"])
        self._merken()
        eigene = [q for q in s["punkte"] if np.linalg.norm(q - p) > r]
        if len(eigene) < len(s["punkte"]):
            s["punkte"] = eigene  # Klick auf einen eigenen Verbinder: entfernen
        else:
            # Klick auf einen automatischen Verbinder einer Insel: alle automatischen dieser Insel übernehmen,
            # außer dem angeklickten. Sonst einen neuen Verbinder setzen.
            for insel in inseln:
                if insel.manuell or not insel.verbinder:
                    continue
                naehe = [np.linalg.norm(q - p) for q in insel.verbinder]
                if min(naehe) <= r:
                    rest = [q for q, d in zip(insel.verbinder, naehe) if d > r]
                    if not rest:
                        self.verlauf.pop()
                        self._log("Eine Schnittfläche behält mindestens einen Verbinder. "
                                  "Für ganz ohne Verbinder die Anzahl auf 0 stellen.")
                        return
                    s["punkte"] = eigene + rest
                    break
            else:
                s["punkte"] = eigene + [p]
        self._liste_aktualisieren()
        self._zeichne_schnitte(True)

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
        self.ebene_info.setText(self._ebene_beschreibung(punkt, n, lo))

    @staticmethod
    def _ebene_beschreibung(punkt, n, lo):
        rel = punkt - lo
        neigung = np.degrees(np.arccos(min(1.0, np.max(np.abs(n)))))
        achse = "XYZ"[int(np.argmax(np.abs(n)))]
        return f"Ebene ⟂ {achse}, {neigung:.0f}° gekippt, Punkt {rel[0]:.0f} / {rel[1]:.0f} / {rel[2]:.0f} mm"

    def _schnitt_text(self, punkt, n, f, lo):
        text = self._ebene_beschreibung(punkt, n, lo).replace("Ebene ", "Schnitt ")
        if f:
            text += f", Fenster {f.breite:.0f} × {f.hoehe:.0f} mm"
        return text

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
        if self.maus3d_umkehren.isChecked():
            werte = -werte
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
        text = self._schnitt_text(punkt, n, f, self.mesh.bounds[0])
        self._merken()
        self.schnitte.append(dict(punkt=punkt.copy(), normale=n.copy(), fenster=f, punkte=[], text=text))
        self._liste_aktualisieren(len(self.schnitte) - 1)
        self._zeichne_schnitte(True)

    def _schnitt_weg(self):
        i = self.liste.currentRow()
        if not 0 <= i < len(self.schnitte):
            return
        self._merken()
        del self.schnitte[i]
        self._liste_aktualisieren(min(i, len(self.schnitte) - 1))
        self._zeichne_schnitte(True)

    def _liste_aktualisieren(self, auswahl=None):
        if auswahl is None:
            auswahl = self.liste.currentRow()
        self.liste.blockSignals(True)
        self.liste.clear()
        for s in self.schnitte:
            self.liste.addItem(s["text"] + (f", {len(s['punkte'])} eigene Verbinder" if s["punkte"] else ""))
        if self.schnitte:
            self.liste.setCurrentRow(max(0, min(auswahl, len(self.schnitte) - 1)))
        self.liste.blockSignals(False)
        self.k_zurueck.setEnabled(bool(self.verlauf))
        self.k_vor.setEnabled(bool(self.zukunft))
        if hasattr(self, "a_zurueck"):
            self.a_zurueck.setEnabled(bool(self.verlauf))
            self.a_vor.setEnabled(bool(self.zukunft))

    # ---------- Rückgängig ----------

    @staticmethod
    def _kopie(schnitte):
        return [dict(s, punkte=[np.array(p) for p in s["punkte"]]) for s in schnitte]

    def _merken(self):
        self.verlauf.append(self._kopie(self.schnitte))
        del self.verlauf[:-100]
        self.zukunft.clear()

    def _rueckgaengig(self):
        if not self.verlauf or self.ergebnis is not None:
            return
        self.zukunft.append(self._kopie(self.schnitte))
        self.schnitte = self.verlauf.pop()
        self._liste_aktualisieren()
        self._zeichne_schnitte(True)

    def _wiederholen(self):
        if not self.zukunft or self.ergebnis is not None:
            return
        self.verlauf.append(self._kopie(self.schnitte))
        self.schnitte = self.zukunft.pop()
        self._liste_aktualisieren()
        self._zeichne_schnitte(True)

    VERBINDER_VORGABEN = {"duebel": (6.0, 10.0, 0.2), "zapfen": (8.0, 8.0, 0.3), "magnet": (6.0, 3.0, 0.2)}
    VERBINDER_TEXTE = {
        "duebel": ("Tiefe je Seite mm", "Löcher in beiden Hälften, die Dübel werden extra gedruckt."),
        "zapfen": ("Zapfenlänge mm", "Zapfen an der größeren Hälfte angeformt, passendes Loch in der anderen. "
                                    "Kein Extrateil, aber diese Hälfte kann nicht auf der Schnittfläche liegen."),
        "magnet": ("Magnethöhe mm", "Löcher für Scheibenmagnete (Durchmesser × Höhe des Magneten) in beiden Hälften. "
                                   "Magnete einkleben und auf die Polung achten."),
    }

    def _art_gewaehlt(self, *_):
        art = self.d_art.currentData()
        self._art_werte[self._art_alt] = (self.d_durchmesser.value(), self.d_tiefe.value(), self.d_spiel.value())
        werte = self._art_werte.get(art, self.VERBINDER_VORGABEN[art])
        for feld, w in zip((self.d_durchmesser, self.d_tiefe, self.d_spiel), werte):
            feld.setValue(w)
        self._art_alt = art
        label, info = self.VERBINDER_TEXTE[art]
        self.d_tiefe_label.setText(label)
        self.d_art_info.setText(info)
        self.d_drucken.setVisible(art == "duebel")

    def _einstellungen(self):
        duebel = None
        if self.d_anzahl.value() > 0:
            duebel = kern.Duebel(self.d_anzahl.value(), self.d_durchmesser.value(), self.d_tiefe.value(),
                                 self.d_spiel.value(), drucken=self.d_drucken.isChecked(),
                                 art=self.d_art.currentData())
        schnitte = [(s["punkt"], s["normale"], s["fenster"], s["punkte"] or None) for s in self.schnitte]
        return dict(auto=self.auto.isChecked(), schnitte=schnitte,
                    bauraum=[f.value() for f in self.bauraum], duebel=duebel)

    def _berechnen(self):
        if self.mesh is None:
            return
        e = self._einstellungen()
        if not e["auto"] and not e["schnitte"]:
            QtWidgets.QMessageBox.information(self, "KOLBCRAFT Cutter",
                                              "Bitte mindestens einen Schnitt hinzufügen.")
            return
        self.k_berechnen.setEnabled(False)
        self.k_berechnen.setText("Berechne …")
        threading.Thread(target=self._arbeite, args=(e,), daemon=True).start()

    def _arbeite(self, e):
        log = self.signale.log.emit
        try:
            montage = kern.Montage()
            if e["auto"]:
                teile, n = kern.automatisch(self.mesh, e["bauraum"], duebel=e["duebel"], log=log, montage=montage)
            else:
                teile, n = kern.zerteile(self.mesh, e["schnitte"], e["duebel"], log=log, montage=montage)
            log("Prüfe den Zusammenbau ...")
            self.signale.fertig.emit((teile, n, e, kern.montage_pruefen(teile, montage)))
        except Exception as fehler:
            self.signale.fehler.emit(str(fehler))

    def _fehler(self, text):
        self.k_berechnen.setText("Teile berechnen")
        self._knoepfe()
        self._log(f"FEHLER: {text}")
        self.k_protokoll.setChecked(True)
        QtWidgets.QMessageBox.critical(self, "Fehler", text)

    def _berechnet(self, ergebnis):
        self.k_berechnen.setText("Teile berechnen")
        teile, n, e, *montage = ergebnis
        self.ergebnis = (teile, n, e)
        self.montage = montage[0] if montage else []
        self._knoepfe()
        passt = sum(kern.passt_irgendwie(t, e["bauraum"]) for t in teile)
        self._log(f"{len(teile)} Teile, {n} Verbinder. {passt} von {len(teile)} passen auf die Platte. "
                  "Mit „Speichern …“ ausgeben oder direkt „In Bambu Studio öffnen“.")
        bilanz = kern.volumen_bilanz(self.mesh, teile)
        if bilanz:
            vorher, nachher = bilanz
            self._log(f"Volumen: Modell {vorher / 1000:.1f} cm³, Teile zusammen {nachher / 1000:.1f} cm³ "
                      f"({(nachher - vorher) / vorher * 100:+.1f} %, durch Löcher und Zapfen)")
        for i, text in self.montage:
            self._log(f"Zusammenbau: Teil {i + 1} {text}")
        if self.montage:
            self.k_protokoll.setChecked(True)
        else:
            self._log("Zusammenbau geprüft: Wände um die Löcher dick genug, nichts stößt an.")
        sorgen = {i for i, _ in self.montage}
        self.lagen = {}
        self.huellen = [t.convex_hull.vertices if len(t.vertices) > 2000 else t.vertices for t in teile]
        self.teile_liste.blockSignals(True)
        self.teile_liste.clear()
        for i, t in enumerate(teile):
            passt = kern.passt_irgendwie(t, e["bauraum"])
            x, y, z = sorted(t.extents, reverse=True)
            eintrag = QtWidgets.QListWidgetItem(f"Teil {i + 1}\n{x:.0f} × {y:.0f} × {z:.0f} mm · "
                                                + ("passt" if passt else "zu groß")
                                                + ("" if t.is_watertight else " · nicht geschlossen")
                                                + (" · Zusammenbau prüfen" if i in sorgen else ""))
            symbol = vorschaubild(t, self._toene(i, passt)[i % 2], passt)
            if symbol is not None:
                eintrag.setIcon(symbol)
            self.teile_liste.addItem(eintrag)
        self.teile_liste.setCurrentRow(0)
        self.teile_liste.blockSignals(False)
        self.teile_gruppe.setVisible(True)
        self.teile_leer.setVisible(False)
        self._schritt(3)
        self._zeige_teile()

    def _toene(self, i, passt):
        if not passt:
            return ZU_GROSS_TOENE
        return MONTAGE_TOENE if any(k == i for k, _ in self.montage) else PASST_TOENE

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
        self._leeren()
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
            farben = self._toene(i, passt)
            p.add_mesh(netz, color=farben[i % 2], **self._oberflaeche(), name=f"teil{i}")
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
        self._leeren()
        box = pv.Box(bounds=(0, b[0], 0, b[1], 0, b[2]))
        p.add_mesh(box, style="wireframe", color="#2b8a3e", line_width=2, name="bauraum", pickable=False)
        self._druckplatte(0, 0, 0, b[0], b[1])
        self.teil_akteur = p.add_mesh(zu_pyvista(teil), color=PASST_FARBE,
                                      **self._oberflaeche(), name="teil_im_bauraum")
        self.teil_akteur.user_matrix = self.lagen[i]
        pts = trimesh.transform_points(self.huellen[i], self.lagen[i])
        self.teil_widget = p.add_affine_transform_widget(
            self.teil_akteur, origin=tuple((pts.min(axis=0) + pts.max(axis=0)) / 2),
            interact_callback=self._teil_bewegt, release_callback=self._teil_losgelassen)
        p.add_axes()
        p.view_isometric()
        p.camera.elevation = -15  # etwas flacher, damit Unterseiten sichtbar sind
        p.reset_camera()
        p.render()
        self._pruefe_lage()
        self._zeige_ueberhang()
        self._schritt(3)
        QtCore.QTimer.singleShot(50, lambda: self.rollen_je_schritt[3].ensureWidgetVisible(self.passt_info))

    def _zeige_ueberhang(self):
        """Färbt Überhänge, die Stützen brauchen, orange und zeigt die Stützfläche an."""
        self.ansicht.remove_actor("ueberhang")
        self.ansicht.remove_actor("stuetzen_schatten")
        self.stuetzen_text = ""
        if not getattr(self, "im_bauraum", False) or self.teil_akteur is None:
            return
        i = self.teile_liste.currentRow()
        teil = self.ergebnis[0][i]
        maske, k = kern.ueberhang(teil, self.lagen[i], self.ueberhang_winkel.value())
        self.stuetzen_text = (f"Stützen nötig auf ca. {k['stuetzflaeche'] / 100:.0f} cm², "
                              f"Auflage {k['auflage'] / 100:.1f} cm², Höhe {k['hoehe']:.0f} mm.")
        if k["auflage"] < 100:
            self.stuetzen_text += " Wenig Auflage: in Bambu Studio einen Rand (Brim) verwenden."
        if self.stuetzen_an.isChecked() and maske.any():
            netz = zu_pyvista(teil).extract_cells(np.flatnonzero(maske))
            akteur = self.ansicht.add_mesh(netz, color="#fd7e14", name="ueberhang", pickable=False)
            akteur.mapper.SetResolveCoincidentTopologyToPolygonOffset()
            akteur.mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2, -2)
            akteur.user_matrix = self.lagen[i]
            # "Schatten" der Stützen auf der Platte, damit man sie auch von oben sieht
            schatten = netz.transform(self.lagen[i], inplace=False)
            schatten.points[:, 2] = 0.2
            self.ansicht.add_mesh(schatten, color="#fd7e14", opacity=0.45, name="stuetzen_schatten",
                                  pickable=False)
        self._pruefe_lage()

    def _beste_lage(self, alle=False):
        if self.ergebnis is None or self.teile_liste.currentRow() < 0:
            return
        teile, _, e = self.ergebnis
        welche = list(range(len(teile))) if alle else [self.teile_liste.currentRow()]
        winkel = self.ueberhang_winkel.value()
        for k in (self.k_beste, self.k_beste_alle):
            k.setEnabled(False)
        self.k_beste.setText("Suche …")

        def arbeit():
            ergebnis = {}
            for i in welche:
                m, _ = kern.beste_lage(teile[i], e["bauraum"], winkel)
                pts = trimesh.transform_points(self.huellen[i], m)
                mitte = (pts.min(axis=0) + pts.max(axis=0)) / 2
                b = e["bauraum"]
                ergebnis[i] = trimesh.transformations.translation_matrix(
                    [b[0] / 2 - mitte[0], b[1] / 2 - mitte[1], 0]) @ m
                self.signale.log.emit(f"Teil {i + 1}: beste Lage gefunden")
            self.signale.lage.emit(ergebnis)

        threading.Thread(target=arbeit, daemon=True).start()

    def _lage_gefunden(self, ergebnis):
        self.lagen.update(ergebnis)
        for k in (self.k_beste, self.k_beste_alle):
            k.setEnabled(True)
        self.k_beste.setText("Beste Lage")
        self._in_bauraum()

    def _teil_bewegt(self, matrix):
        self.lagen[self.teile_liste.currentRow()] = np.array(matrix)
        ueberhang = self.ansicht.actors.get("ueberhang")
        if ueberhang is not None:
            ueberhang.user_matrix = np.array(matrix)
        self._pruefe_lage()

    def _teil_losgelassen(self, matrix):
        self._teil_bewegt(matrix)
        self._zeige_ueberhang()
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
        stuetzen = getattr(self, "stuetzen_text", "")
        self.passt_info.setText(text + ("\n" + stuetzen if stuetzen else ""))
        self.passt_info.setStyleSheet(f"color: {farbe}; font-weight: bold;")
        akteur = self.ansicht.actors.get("bauraum")
        if akteur is not None:
            akteur.prop.color = farbe
        if self.teil_akteur is not None:
            self.teil_akteur.prop.color = ZU_GROSS_FARBE if probleme else PASST_FARBE
        self.ansicht.render()

    def _speichern(self, ordner=None, dreimf=None):
        """Liefert den Pfad der 3MF (oder None), False wenn nichts gespeichert wurde."""
        if self.ergebnis is None or not self._vor_dem_export():
            return False
        gewaehlt = not ordner
        if not ordner:
            ordner = QtWidgets.QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", str(self.pfad.parent))
        if not ordner:
            return False
        teile, n, e = self.ergebnis
        ziel = Path(ordner) / f"{self.pfad.stem}_teile"
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            datei = kern.exportiere(teile, self.pfad.stem, ziel, e["bauraum"], drehen=self.drehen.isChecked(),
                                    dreimf=self.dreimf.isChecked() if dreimf is None else dreimf,
                                    duebel=e["duebel"], anzahl_duebel=n, log=self._log, lagen=self.lagen)
        except Exception as fehler:
            self._fehler(str(fehler))
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        if gewaehlt and hasattr(os, "startfile"):
            os.startfile(ziel)
        return datei

    def _frage(self, titel, text):
        antwort = QtWidgets.QMessageBox.question(self, titel, text)
        return antwort == QtWidgets.QMessageBox.StandardButton.Yes

    def _vor_dem_export(self):
        """Prüft alle Teile; bei Problemen erst nachfragen statt still zu speichern."""
        teile, _, e = self.ergebnis
        probleme = sorted(kern.pruefe_teile(teile, e["bauraum"], self.lagen) + list(self.montage))
        if not probleme:
            return True
        zeilen = [f"Teil {i + 1}: {text}" for i, text in probleme]
        for z in zeilen:
            self._log("Prüfung: " + z)
        return self._frage("Teile prüfen", "Vor dem Speichern sind Probleme aufgefallen:\n\n"
                           + "\n".join(zeilen[:15]) + ("\n…" if len(zeilen) > 15 else "")
                           + "\n\nTrotzdem speichern?")

    # --- Bambu Studio ---
    def _bambu_programm(self):
        return bambu_studio.finde(self.einstellungen.get("bambu_studio"))

    def _bambu_anzeigen(self):
        programm = self._bambu_programm()
        if programm:
            self.bambu_info.setText(f"Bambu Studio: {programm}")
        else:
            self.bambu_info.setText("Bambu Studio nicht gefunden. Es wird die Windows-Verknüpfung für .3mf benutzt.")

    def _bambu_waehlen(self):
        filter_ = "Bambu Studio (bambu-studio.exe);;Programme (*.exe);;Alle Dateien (*)" if os.name == "nt" \
            else "Alle Dateien (*)"
        datei, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Bambu Studio auswählen", "", filter_)
        if not datei:
            return
        self.einstellungen["bambu_studio"] = datei
        profile.speichere(self.einstellungen)
        self._bambu_anzeigen()

    def _in_bambu(self, ordner=None, starten=bambu_studio.oeffne):
        """Speichert neben dem Modell (mit 3MF) und öffnet die 3MF in Bambu Studio."""
        if self.ergebnis is None:
            return None
        datei = self._speichern(ordner or str(self.pfad.parent), dreimf=True)
        if not datei:
            return None
        try:
            if starten([datei], self._bambu_programm()):
                self._log("In Bambu Studio geöffnet. Dort ggf. mit „Anordnen“ (Taste A) auf die Platten verteilen.")
            else:
                self._log(f"Bambu Studio nicht gefunden. Die 3MF liegt hier: {datei}")
        except OSError as fehler:
            self._fehler(f"Bambu Studio konnte nicht gestartet werden: {fehler}")
        return datei


def selbsttest(app):
    """Kompletter Durchlauf ohne Klicks, z.B. um die fertige .exe zu prüfen: --selbsttest"""
    import tempfile

    import trimesh

    with tempfile.TemporaryDirectory() as ordner:
        modell = Path(ordner) / "zylinder.stl"
        trimesh.creation.cylinder(radius=60, height=500).export(modell)
        f = Fenster()
        f.show()
        f._oeffnen(str(modell))
        ergebnisse = []
        f.signale.fertig.disconnect()
        f.signale.fertig.connect(ergebnisse.append)
        f._arbeite(f._einstellungen())
        app.processEvents()
        if not ergebnisse:
            print("Selbsttest: Berechnung fehlgeschlagen")
            return 1
        f._berechnet(ergebnisse[0])
        f.teile_liste.setCurrentRow(0)
        f._in_bauraum()
        f._speichern(ordner)
        dateien = sorted(p.name for p in (Path(ordner) / "zylinder_teile").iterdir())
        print("Selbsttest:", ", ".join(dateien))
        f.close()
        return 0 if "zylinder_teile.3mf" in dateien and len(dateien) == 4 else 1


def main():
    app = QtWidgets.QApplication(sys.argv)
    if "--selbsttest" in sys.argv:
        sys.exit(selbsttest(app))
    fenster = Fenster()
    fenster.show()
    if len(sys.argv) > 1:
        fenster._oeffnen(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
