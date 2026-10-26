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

Links führen fünf Reiter durch die Arbeit: **1 Modell → 2 Schneiden → 3 Verbinder → 4 Teile → 5 Ausgabe**.
Nach „Teile berechnen“ springt das Programm selbst zu „Teile“. Über der 3D-Ansicht liegt eine
Werkzeugleiste mit festen Ansichten (Iso, Vorn, Seite, Oben, Einpassen), Rückgängig/Wiederholen,
„Stützen“ ein/aus und dem Umschalter für helles oder dunkles Design (wird gemerkt). Unten zeigt eine
Statuszeile die letzte Meldung, „Protokoll“ klappt alle Meldungen auf (bei Fehlern automatisch).

- **Modell öffnen**: STL, 3MF oder OBJ, per „Öffnen …“, „Zuletzt ▾“ (die letzten 8 Dateien) oder
  einfach die Datei ins Fenster ziehen. Das Modell erscheint in der 3D-Ansicht auf einer Druckplatte mit
  25-mm-Raster, der grüne Rahmen ist der Bauraum.
- **Skalieren**: Unter dem Modell lässt sich der Maßstab in Prozent oder ein Zielmaß in X, Y oder Z
  eintragen, die anderen Achsen wachsen gleichmäßig mit. „100 %“ stellt die Originalgröße wieder her.
  Bereits gesetzte Schnitte wandern mit, Dübel, Zapfen und Magnetlöcher behalten ihre Größe in mm.
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
- **Verbinder**: Dübel (Löcher in beiden Hälften, Dübel als eigene STL), angeformte Zapfen (an der
  größeren Hälfte, passendes Loch in der anderen) oder Löcher für Scheibenmagnete. Anzahl pro
  Schnittfläche, Durchmesser, Tiefe/Länge/Magnethöhe und Spiel sind einstellbar. Die Verbinder werden
  automatisch mit Abstand zum Rand verteilt. Ist eine Schnittfläche zu klein, steht das im Protokoll.
- **Verbinder selbst setzen** (manuell): Schnitt in der Liste wählen. Das Modell wird an der Ebene
  aufgeklappt, die Schnittfläche ist orange, die Verbinder als Kugeln (blau = automatisch, orange =
  selbst gesetzt). Rechtsklick auf die Fläche setzt einen Verbinder, Rechtsklick auf einen Verbinder
  entfernt ihn. Rechts ziehen zoomt weiterhin.
- **Rückgängig / Wiederholen**: Strg+Z / Strg+Y oder die Knöpfe unter der Schnittliste, für Schnitte und
  Verbinder.
- **Teile im Bauraum testen**: Nach „Teile berechnen“ sind passende Teile grün, zu große rot. Ein Teil
  aus der Liste wählen und „In den Bauraum legen“: Es liegt dann druckfertig auf der Platte und lässt
  sich mit den Pfeilen verschieben und mit den Ringen drehen (oder mit ↻ X/Y/Z um 90°). Teil und
  Bauraum werden grün, solange alles passt, sonst rot mit Angabe, wo es übersteht. „Auto-Lage“ legt
  das Teil wieder automatisch hin. Die von Hand gewählte Lage wird beim Speichern übernommen.
- **Beste Lage / Stützen**: „Beste Lage“ probiert rund 180 Ausrichtungen und wählt die mit möglichst wenig
  Stützmaterial, guter Auflage und geringer Höhe, die in den Bauraum passt („Beste Lage für alle“ für alle
  Teile). Mit „Stützen anzeigen ab 45°“ werden Überhänge, die Stützen brauchen, orange gefärbt und ihr
  Schatten auf der Platte gezeigt; darunter stehen Stützfläche, Auflage und Höhe. Die Stützen selbst
  erzeugt Bambu Studio (z.B. Baumstützen) beim Slicen der gespeicherten Lage.
- **Teile berechnen** zeigt die Teile nummeriert und links als Karten mit Vorschaubild und grünem bzw.
  rotem Punkt (passt / zu groß), **Speichern …** schreibt jedes Teil als
  STL (auf die Schnittfläche gelegt) und auf Wunsch alles zusammen als 3MF für Bambu Studio. In der 3MF
  liegen die Teile nebeneinander statt übereinander.
- **In Bambu Studio öffnen** speichert die Teile in den Ordner `<Modell>_teile` neben dem Modell und
  öffnet die 3MF sofort in Bambu Studio. Dort am besten noch „Anordnen“ (Taste A) drücken, damit Bambu
  Studio die Teile auf die Platten verteilt. Bambu Studio wird automatisch gesucht (Installationseintrag,
  „C:\Programme\Bambu Studio“). Liegt es woanders, unter „Ausgabe“ mit „Wählen …“ die
  `bambu-studio.exe` angeben, der Pfad wird gemerkt.

## Kommandozeile

```
python stl_schneider.py modell.stl                          # automatisch, H2D eine Düse, 2 Dübel
python stl_schneider.py modell.stl --drucker "H2D beide Düsen"
python stl_schneider.py modell.stl --schnitt z=50 --schnitt x=120   # manuell
python stl_schneider.py modell.stl --duebel 3 --duebel-durchmesser 8
python stl_schneider.py modell.stl --duebel 0               # ohne Dübel
python stl_schneider.py modell.stl --3mf
python stl_schneider.py modell.stl --skalieren z=200        # vorher auf 200 mm Höhe skalieren (oder 150 für 150 %)
python stl_schneider.py modell.stl --bambu                  # 3MF schreiben und in Bambu Studio öffnen
```

`python stl_schneider.py --help` zeigt alle Optionen.
