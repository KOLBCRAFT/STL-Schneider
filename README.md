# STL-Schneider

Zerteilt STL-Dateien für den 3D-Druck, damit jedes Teil auf die Druckplatte passt, und bohrt
Löcher für gedruckte Dübel in die Schnittflächen. Voreingestellt ist der Bambu Lab H2D.

## Starten unter Windows

1. Python 3.11 oder neuer von [python.org](https://www.python.org/downloads/) installieren.
2. Dieses Repository herunterladen (grüner Knopf „Code“ → „Download ZIP“) und entpacken.
3. `start.bat` doppelklicken. Beim ersten Start werden die nötigen Pakete installiert, das dauert ein paar Minuten.

## Bedienung

- **Modell öffnen**: STL, 3MF oder OBJ. Die Vorschau zeigt das Modell von vorne, von der Seite
  und von oben, der grüne Rahmen ist der Bauraum.
- **Drucker**: H2D mit einer Düse (325 × 320 × 325 mm), mit beiden Düsen (300 × 320 × 325 mm),
  weitere Bambu-Drucker oder eigene Maße.
- **Automatisch**: Schneidet nur Teile, die nicht passen, und legt jeden Schnitt an die dünnste
  Stelle im erlaubten Bereich. Probiert das Modell in Originallage und ausgerichtet und nimmt die
  Variante mit weniger Teilen.
- **Manuell**: Achse wählen, Position mit dem Regler oder als Zahl einstellen (mm ab Unterkante
  des Modells), „Schnitt hinzufügen“. Die Schnitte werden in der Vorschau rot angezeigt.
- **Dübel**: Anzahl pro Schnittfläche, Durchmesser, Lochtiefe je Seite und Spiel. Die Dübel werden
  automatisch mit Abstand zum Rand verteilt und als eigene STL mit ausgegeben. Ist eine
  Schnittfläche zu klein, steht das im Protokoll.
- **Ausgabe**: Jedes Teil als STL, auf die Schnittfläche gelegt, und auf Wunsch alles zusammen als
  3MF für Bambu Studio.

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
