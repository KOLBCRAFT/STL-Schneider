# STL-Schneider

Zerteilt STL-Dateien für den 3D-Druck, damit jedes Teil auf die Druckplatte passt, und bohrt
Löcher für gedruckte Dübel in die Schnittflächen. Voreingestellt ist der Bambu Lab H2D.

## Starten unter Windows

1. Python 3.11 oder neuer von [python.org](https://www.python.org/downloads/) installieren.
2. Dieses Repository herunterladen (grüner Knopf „Code“ → „Download ZIP“) und entpacken.
3. `start.bat` doppelklicken. Beim ersten Start werden die nötigen Pakete installiert, das dauert ein paar Minuten.

## Aktualisieren

`aktualisieren.bat` doppelklicken. Es holt die neueste Version vom Zweig `main` (eigene Ausgabeordner
bleiben erhalten). Voraussetzung ist [Git für Windows](https://git-scm.com/download/win)
(`winget install --id Git.Git -e`). Beim ersten Mal öffnet sich die GitHub-Anmeldung im Browser, weil das
Repository privat ist. Danach `start.bat` starten, neue Pakete werden automatisch nachinstalliert.

## Bedienung

- **Modell öffnen**: STL, 3MF oder OBJ. Das Modell erscheint in der 3D-Ansicht, der grüne Rahmen
  ist der Bauraum.
- **Ansicht**: linke Maustaste drehen, Mausrad zoomen, mittlere Maustaste (oder Umschalt + links)
  verschieben. Eine 3D-Maus von 3Dconnexion wird unter Windows automatisch erkannt
  (Haken „3D-Maus verwenden“, Empfindlichkeit per Regler).
- **Drucker**: H2D mit einer Düse (325 × 320 × 325 mm), mit beiden Düsen (300 × 320 × 325 mm) und
  weitere Bambu-Drucker sind vorgegeben. X, Y und Z lassen sich frei eintragen. Mit „Als Profil
  speichern …“ werden die Maße unter einem eigenen Namen gespeichert, mit „Profil löschen“ wieder
  entfernt. Die Profile liegen in `%APPDATA%\STL-Schneider\einstellungen.json` und bleiben beim
  Aktualisieren erhalten. Das zuletzt gewählte Profil ist beim nächsten Start wieder eingestellt.
- **Automatisch**: Schneidet nur Teile, die nicht passen, und legt jeden Schnitt an die dünnste
  Stelle im erlaubten Bereich. Probiert das Modell in Originallage und ausgerichtet und nimmt die
  Variante mit weniger Teilen.
- **Manuell**: Die rote Schnittebene im 3D-Fenster mit der Maus ziehen (Fläche = verschieben,
  Pfeil = kippen). Mit ⟂ X / ⟂ Y / ⟂ Z wird sie gerade ausgerichtet, mit dem Regler verschoben.
  „Schnitt hinzufügen“ merkt sich die Ebene, beliebig viele Schnitte sind möglich, auch schräge.
- **Schnittfenster**: Mit „Schnittfenster begrenzen“ wird nur geschnitten, wo der Querschnitt das blaue
  Rechteck (Breite × Höhe, Mitte = Mittelpunkt der Ebene) berührt. So lässt sich z.B. ein einzelner Ast
  abtrennen, während andere Äste in derselben Ebene ganz bleiben.
- **Dübel**: Anzahl pro Schnittfläche, Durchmesser, Lochtiefe je Seite und Spiel. Die Dübel werden
  automatisch mit Abstand zum Rand verteilt und als eigene STL mit ausgegeben. Ist eine
  Schnittfläche zu klein, steht das im Protokoll.
- **Teile berechnen** zeigt die Teile farbig und nummeriert, **Speichern …** schreibt jedes Teil als
  STL (auf die Schnittfläche gelegt) und auf Wunsch alles zusammen als 3MF für Bambu Studio.

## Kommandozeile

```
python stl_schneider.py modell.stl                          # automatisch, H2D eine Düse, 2 Dübel
python stl_schneider.py modell.stl --drucker "H2D beide Düsen"
python stl_schneider.py modell.stl --schnitt z=50 --schnitt x=120   # manuell
python stl_schneider.py modell.stl --duebel 3 --duebel-durchmesser 8
python stl_schneider.py modell.stl --duebel 0               # ohne Dübel
python stl_schneider.py modell.stl --3mf
```

`python stl_schneider.py --help` zeigt alle Optionen.
