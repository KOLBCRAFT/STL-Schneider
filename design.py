"""Helles und dunkles Erscheinungsbild für die Oberfläche (Qt-Stil „Fusion“ + Stylesheet)."""
from qtpy import QtGui, QtWidgets

AKZENT = "#00ae42"         # Grün, angelehnt an Bambu Studio
AKZENT_HOVER = "#00c94c"
AKZENT_GEDRUECKT = "#00913a"

FARBEN = {
    "dunkel": dict(fenster="#1f2227", flaeche="#272b31", feld="#16181c", rand="#3a3f47", text="#e9ecef",
                   leise="#9aa1a9", knopf="#30353c", knopf_hover="#3a4048", aus="#5c636b",
                   hintergrund_3d=("#30353c", "#16181c"), platte="#2b3036", raster="#4a525c"),
    "hell": dict(fenster="#f1f3f5", flaeche="#ffffff", feld="#ffffff", rand="#ced4da", text="#212529",
                 leise="#6c757d", knopf="#ffffff", knopf_hover="#e9ecef", aus="#adb5bd",
                 hintergrund_3d=("#ffffff", "#dee2e6"), platte="#dee2e6", raster="#adb5bd"),
}


def hintergrund_3d(name):
    """(oben, unten) für den Farbverlauf der 3D-Ansicht."""
    return FARBEN[name]["hintergrund_3d"]


def platte(name):
    """(Plattenfarbe, Rasterfarbe) für die Druckplatte in der 3D-Ansicht."""
    return FARBEN[name]["platte"], FARBEN[name]["raster"]


def _palette(f):
    p = QtGui.QPalette()
    farbe = QtGui.QColor
    rollen = QtGui.QPalette.ColorRole
    p.setColor(rollen.Window, farbe(f["fenster"]))
    p.setColor(rollen.WindowText, farbe(f["text"]))
    p.setColor(rollen.Base, farbe(f["feld"]))
    p.setColor(rollen.AlternateBase, farbe(f["flaeche"]))
    p.setColor(rollen.Text, farbe(f["text"]))
    p.setColor(rollen.Button, farbe(f["knopf"]))
    p.setColor(rollen.ButtonText, farbe(f["text"]))
    p.setColor(rollen.ToolTipBase, farbe(f["flaeche"]))
    p.setColor(rollen.ToolTipText, farbe(f["text"]))
    p.setColor(rollen.Highlight, farbe(AKZENT))
    p.setColor(rollen.HighlightedText, farbe("#ffffff"))
    p.setColor(rollen.PlaceholderText, farbe(f["leise"]))
    for rolle in (rollen.WindowText, rollen.Text, rollen.ButtonText):
        p.setColor(QtGui.QPalette.ColorGroup.Disabled, rolle, farbe(f["aus"]))
    return p


def _stylesheet(f):
    return f"""
    QWidget {{ font-size: 10pt; }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: {f['fenster']}; border: none; }}
    QGroupBox {{
        background: {f['flaeche']}; border: 1px solid {f['rand']}; border-radius: 8px;
        margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: 600;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {f['leise']}; }}
    QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton {{ font-weight: normal; }}
    QPushButton {{
        background: {f['knopf']}; border: 1px solid {f['rand']}; border-radius: 6px; padding: 5px 10px;
    }}
    QPushButton:hover {{ background: {f['knopf_hover']}; }}
    QPushButton:disabled {{ color: {f['aus']}; }}
    QPushButton[rolle="haupt"] {{
        background: {AKZENT}; border: none; color: white; font-weight: 600; font-size: 11pt;
    }}
    QPushButton[rolle="haupt"]:hover {{ background: {AKZENT_HOVER}; }}
    QPushButton[rolle="haupt"]:pressed {{ background: {AKZENT_GEDRUECKT}; }}
    QPushButton[rolle="haupt"]:disabled {{ background: {f['knopf']}; color: {f['aus']}; }}
    QToolButton[rolle="schritt"] {{
        background: transparent; border: none; border-bottom: 3px solid transparent;
        padding: 6px 2px; color: {f['leise']}; font-weight: 600;
    }}
    QToolButton[rolle="schritt"]:hover {{ color: {f['text']}; }}
    QToolButton[rolle="schritt"]:checked {{ color: {f['text']}; border-bottom: 3px solid {AKZENT}; }}
    QToolButton[rolle="schritt"]:disabled {{ color: {f['aus']}; }}
    QToolBar {{ background: {f['flaeche']}; border: none; border-bottom: 1px solid {f['rand']}; spacing: 2px;
                padding: 3px; }}
    QToolBar QToolButton {{ border-radius: 5px; padding: 4px 8px; }}
    QToolBar QToolButton:hover {{ background: {f['knopf_hover']}; }}
    QToolBar QToolButton:checked {{ background: {AKZENT}; color: white; }}
    QLineEdit, QListWidget, QPlainTextEdit {{
        background: {f['feld']}; border: 1px solid {f['rand']}; border-radius: 5px; padding: 3px;
    }}
    QListWidget::item {{ padding: 4px; border-radius: 4px; }}
    QListWidget::item:selected {{ background: {f['knopf_hover']}; color: {f['text']};
                                  border-left: 3px solid {AKZENT}; }}
    QLabel[rolle="hinweis"] {{ color: {f['leise']}; }}
    QSplitter::handle {{ background: {f['rand']}; }}
    """


def anwenden(app, name="dunkel"):
    f = FARBEN[name]
    app.setStyle("Fusion")
    app.setPalette(_palette(f))
    app.setStyleSheet(_stylesheet(f))
