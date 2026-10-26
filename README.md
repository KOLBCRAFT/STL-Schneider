# STL-Schneider

Zerteilt STL-Dateien für den 3D-Druck, damit jedes Teil auf die Druckplatte passt.

## Installation

```
pip install -r requirements.txt
```

## Benutzung

```
python stl_schneider.py modell.stl                         # Bambu-Standard 256x256x256 mm
python stl_schneider.py modell.stl --bauraum 180 180 180   # z.B. A1 mini
python stl_schneider.py modell.stl --schnitt z=50 --schnitt x=0   # eigene Schnitte
python stl_schneider.py modell.stl --3mf                   # zusätzlich alle Teile als 3MF
```

Jedes Teil wird mit der größten ebenen Fläche (meist der Schnittfläche) nach unten auf die Platte gelegt
und als eigene STL im Ordner `<modell>_teile` gespeichert. Die 3MF lässt sich direkt in Bambu Studio öffnen.
