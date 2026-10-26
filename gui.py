#!/usr/bin/env python3
"""Fenster-Programm für den STL-Schneider."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

import stl_schneider as kern

ANSICHTEN = [("Vorne (X/Z)", 0, 2), ("Seite (Y/Z)", 1, 2), ("Oben (X/Y)", 0, 1)]
FARBEN = {"modell": "#9aa7b4", "schnitt": "#d9480f", "bauraum": "#2b8a3e"}


def silhouette(u, v, s, w, h, ox, oy):
    """Projiziert eine Punktwolke als ausgefüllte Fläche in ein Tk-Bild der Größe w x h."""
    px = np.clip((ox + u * s).astype(int), 0, w - 1)
    py = np.clip((oy - v * s).astype(int), 0, h - 1)
    belegt = np.zeros((h, w), bool)
    belegt[py, px] = True
    # Lücken zwischen den Punkten schließen
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        belegt[dy:, max(dx, 0):w + min(dx, 0)] |= belegt[:h - dy, max(-dx, 0):w - max(dx, 0)]
    rgb = np.full((h, w, 3), 255, np.uint8)
    rgb[belegt] = (154, 167, 180)
    bild = tk.PhotoImage(width=w, height=h)
    kopf = f"P6 {w} {h} 255 ".encode()
    bild.configure(data=kopf + rgb.tobytes(), format="PPM")
    return bild


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("STL-Schneider")
        self.geometry("1200x820")
        self.minsize(950, 700)

        self.mesh = None
        self.vorschau = None  # (dreiecke, unterkante) für die Ansichten
        self.schnitte = []    # (achse, position ab Unterkante)
        self.meldungen = queue.Queue()

        self._baue_oberflaeche()
        self.after(100, self._hole_meldungen)

    # ---------- Oberfläche ----------

    def _baue_oberflaeche(self):
        links = ttk.Frame(self, padding=10)
        links.pack(side="left", fill="y")
        self.knopf = ttk.Button(links, text="Schneiden", command=self._schneiden)
        self.knopf.pack(side="bottom", fill="x", pady=(10, 0), ipady=4)
        rechts = ttk.Frame(self, padding=(0, 10, 10, 10))
        rechts.pack(side="left", fill="both", expand=True)

        # Datei
        rahmen = ttk.LabelFrame(links, text="Modell", padding=8)
        rahmen.pack(fill="x")
        self.datei = tk.StringVar()
        ttk.Entry(rahmen, textvariable=self.datei, width=34).grid(row=0, column=0, sticky="ew")
        ttk.Button(rahmen, text="Öffnen …", command=self._oeffnen).grid(row=0, column=1, padx=(4, 0))
        self.info = ttk.Label(rahmen, text="Noch keine Datei geladen", foreground="#666")
        self.info.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Drucker
        rahmen = ttk.LabelFrame(links, text="Drucker", padding=8)
        rahmen.pack(fill="x", pady=(8, 0))
        self.drucker = tk.StringVar(value=kern.STANDARD_DRUCKER)
        box = ttk.Combobox(rahmen, textvariable=self.drucker, values=list(kern.DRUCKER) + ["Eigener"],
                           state="readonly", width=20)
        box.grid(row=0, column=0, columnspan=6, sticky="w")
        box.bind("<<ComboboxSelected>>", lambda e: self._drucker_gewaehlt())
        self.bauraum = [tk.DoubleVar(value=v) for v in kern.DRUCKER[kern.STANDARD_DRUCKER]]
        for i, (name, var) in enumerate(zip("XYZ", self.bauraum)):
            ttk.Label(rahmen, text=name).grid(row=1, column=2 * i, padx=(0 if i == 0 else 6, 2), pady=(6, 0))
            ttk.Entry(rahmen, textvariable=var, width=6).grid(row=1, column=2 * i + 1, pady=(6, 0))
        for var in self.bauraum:
            var.trace_add("write", lambda *a: self._zeichne())

        # Modus
        rahmen = ttk.LabelFrame(links, text="Schneiden", padding=8)
        rahmen.pack(fill="x", pady=(8, 0))
        self.modus = tk.StringVar(value="auto")
        ttk.Radiobutton(rahmen, text="Automatisch (an dünnen Stellen)", value="auto", variable=self.modus,
                        command=self._modus_gewaehlt).pack(anchor="w")
        ttk.Radiobutton(rahmen, text="Manuell (eigene Schnitte)", value="manuell", variable=self.modus,
                        command=self._modus_gewaehlt).pack(anchor="w")

        self.manuell = ttk.Frame(rahmen)
        self.manuell.pack(fill="x", pady=(6, 0))
        zeile = ttk.Frame(self.manuell)
        zeile.pack(fill="x")
        ttk.Label(zeile, text="Achse").pack(side="left")
        self.achse = tk.StringVar(value="Z")
        box = ttk.Combobox(zeile, textvariable=self.achse, values=["X", "Y", "Z"], state="readonly", width=3)
        box.pack(side="left", padx=4)
        box.bind("<<ComboboxSelected>>", lambda e: self._achse_gewaehlt())
        ttk.Label(zeile, text="bei").pack(side="left")
        self.position = tk.DoubleVar(value=0)
        ttk.Entry(zeile, textvariable=self.position, width=7).pack(side="left", padx=4)
        ttk.Label(zeile, text="mm").pack(side="left")
        self.regler = ttk.Scale(self.manuell, from_=0, to=100, variable=self.position,
                                command=lambda v: self._zeichne())
        self.regler.pack(fill="x", pady=4)
        zeile = ttk.Frame(self.manuell)
        zeile.pack(fill="x")
        ttk.Button(zeile, text="Schnitt hinzufügen", command=self._schnitt_dazu).pack(side="left")
        ttk.Button(zeile, text="Entfernen", command=self._schnitt_weg).pack(side="left", padx=4)
        self.liste = tk.Listbox(self.manuell, height=4)
        self.liste.pack(fill="x", pady=(4, 0))
        ttk.Label(self.manuell, text="Position in mm ab Unterkante des Modells", foreground="#666").pack(anchor="w")

        # Dübel
        rahmen = ttk.LabelFrame(links, text="Dübel", padding=8)
        rahmen.pack(fill="x", pady=(8, 0))
        self.d_anzahl = tk.IntVar(value=2)
        self.d_durchmesser = tk.DoubleVar(value=6.0)
        self.d_tiefe = tk.DoubleVar(value=10.0)
        self.d_spiel = tk.DoubleVar(value=0.2)
        felder = [("Anzahl pro Schnitt", self.d_anzahl), ("Durchmesser mm", self.d_durchmesser),
                  ("Tiefe je Seite mm", self.d_tiefe), ("Spiel mm", self.d_spiel)]
        for i, (text, var) in enumerate(felder):
            ttk.Label(rahmen, text=text).grid(row=i, column=0, sticky="w")
            if var is self.d_anzahl:
                ttk.Spinbox(rahmen, from_=0, to=8, textvariable=var, width=6).grid(row=i, column=1, sticky="w")
            else:
                ttk.Entry(rahmen, textvariable=var, width=7).grid(row=i, column=1, sticky="w")
        self.d_drucken = tk.BooleanVar(value=True)
        ttk.Checkbutton(rahmen, text="Dübel mitdrucken (sonst nur Löcher,\nz.B. für Holzdübel)",
                        variable=self.d_drucken).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Ausgabe
        rahmen = ttk.LabelFrame(links, text="Ausgabe", padding=8)
        rahmen.pack(fill="x", pady=(8, 0))
        self.dreimf = tk.BooleanVar(value=True)
        self.drehen = tk.BooleanVar(value=True)
        ttk.Checkbutton(rahmen, text="3MF für Bambu Studio", variable=self.dreimf).pack(anchor="w")
        ttk.Checkbutton(rahmen, text="Teile auf Schnittfläche legen", variable=self.drehen).pack(anchor="w")


        # Vorschau
        self.leinwand = []
        oben = ttk.Frame(rechts)
        oben.pack(fill="both", expand=True)
        for i, (titel, _, _) in enumerate(ANSICHTEN):
            rahmen = ttk.LabelFrame(oben, text=titel, padding=2)
            rahmen.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            oben.columnconfigure(i, weight=1)
            c = tk.Canvas(rahmen, background="white", highlightthickness=0)
            c.pack(fill="both", expand=True)
            c.bind("<Configure>", lambda e: self._zeichne())
            self.leinwand.append(c)
        oben.rowconfigure(0, weight=1)

        rahmen = ttk.LabelFrame(rechts, text="Protokoll", padding=2)
        rahmen.pack(fill="both", pady=(8, 0))
        self.log_feld = tk.Text(rahmen, height=12, state="disabled", font=("Consolas", 9))
        self.log_feld.pack(fill="both", expand=True)

        self._modus_gewaehlt()

    # ---------- Ereignisse ----------

    def _drucker_gewaehlt(self):
        werte = kern.DRUCKER.get(self.drucker.get())
        if werte:
            for var, v in zip(self.bauraum, werte):
                var.set(v)

    def _modus_gewaehlt(self):
        zustand = "normal" if self.modus.get() == "manuell" else "disabled"
        for kind in self.manuell.winfo_children():
            for w in [kind] + list(kind.winfo_children()):
                try:
                    w.configure(state=zustand if not isinstance(w, ttk.Combobox) or zustand == "disabled"
                                else "readonly")
                except tk.TclError:
                    pass
        self._zeichne()

    def _achse_gewaehlt(self):
        if self.mesh is not None:
            laenge = self.mesh.extents["XYZ".index(self.achse.get())]
            self.regler.configure(to=laenge)
            self.position.set(round(laenge / 2, 1))
        self._zeichne()

    def _oeffnen(self):
        pfad = filedialog.askopenfilename(filetypes=[("3D-Modelle", "*.stl *.3mf *.obj"), ("Alle Dateien", "*.*")])
        if not pfad:
            return
        self.datei.set(pfad)
        self.info.configure(text="Lade …")
        self.update_idletasks()
        try:
            self.mesh = kern.lade(pfad)
        except Exception as e:
            messagebox.showerror("Fehler", f"Datei konnte nicht geladen werden:\n{e}")
            return
        m = self.mesh
        x, y, z = m.extents
        self.info.configure(text=f"{x:.1f} x {y:.1f} x {z:.1f} mm, {len(m.faces):,} Dreiecke"
                                 + ("" if m.is_watertight else "  (nicht geschlossen!)"))
        # Für die Vorschau reichen Eckpunkte und Dreiecksmitten als Punktwolke
        self.vorschau = (np.vstack([m.vertices, m.triangles_center]), m.bounds[0])
        self.schnitte.clear()
        self.liste.delete(0, "end")
        self._achse_gewaehlt()
        self._log(f"Geladen: {Path(pfad).name}")

    def _schnitt_dazu(self):
        if self.mesh is None:
            return
        achse = "XYZ".index(self.achse.get())
        try:
            pos = float(self.position.get())
        except (tk.TclError, ValueError):
            return
        self.schnitte.append((achse, pos))
        self.liste.insert("end", f"{self.achse.get()} = {pos:.1f} mm")
        self._zeichne()

    def _schnitt_weg(self):
        for i in reversed(self.liste.curselection()):
            self.liste.delete(i)
            del self.schnitte[i]
        self._zeichne()

    # ---------- Vorschau ----------

    def _zeichne(self):
        for c in self.leinwand:
            c.delete("all")
        if self.vorschau is None:
            return
        punkte, lo = self.vorschau
        ausmass = self.mesh.extents
        try:
            bauraum = [v.get() for v in self.bauraum]
        except tk.TclError:
            bauraum = None
        manuell = self.modus.get() == "manuell"

        for c, (_, a, b) in zip(self.leinwand, ANSICHTEN):
            w, h = c.winfo_width(), c.winfo_height()
            if w < 20 or h < 20:
                continue
            breite = max(ausmass[a], bauraum[a] if bauraum else 0)
            hoehe = max(ausmass[b], bauraum[b] if bauraum else 0)
            s = 0.9 * min(w / breite, h / hoehe)
            ox, oy = (w - ausmass[a] * s) / 2, (h + ausmass[b] * s) / 2

            def punkt(u, v):
                return ox + u * s, oy - v * s

            bild = silhouette(punkte[:, a] - lo[a], punkte[:, b] - lo[b], s, w, h, ox, oy)
            c.bild = bild  # Referenz halten, sonst räumt Tk das Bild weg
            c.create_image(0, 0, image=bild, anchor="nw")
            if bauraum:
                x0, y0 = punkt(0, 0)
                x1, y1 = punkt(bauraum[a], bauraum[b])
                c.create_rectangle(x0, y0, x1, y1, outline=FARBEN["bauraum"], dash=(4, 3))
            if manuell:
                linien = list(self.schnitte)
                try:
                    linien.append(("XYZ".index(self.achse.get()), float(self.position.get()), True))
                except (tk.TclError, ValueError):
                    pass
                for eintrag in linien:
                    achse, pos = eintrag[0], eintrag[1]
                    neu = len(eintrag) > 2
                    farbe = FARBEN["schnitt"]
                    muster = (6, 4) if neu else None
                    if achse == a:
                        x, _ = punkt(pos, 0)
                        c.create_line(x, 0, x, h, fill=farbe, width=2, dash=muster)
                    elif achse == b:
                        _, y = punkt(0, pos)
                        c.create_line(0, y, w, y, fill=farbe, width=2, dash=muster)

    # ---------- Schneiden ----------

    def _schneiden(self):
        if self.mesh is None:
            messagebox.showinfo("STL-Schneider", "Bitte zuerst ein Modell öffnen.")
            return
        if self.modus.get() == "manuell" and not self.schnitte:
            messagebox.showinfo("STL-Schneider", "Bitte mindestens einen Schnitt hinzufügen.")
            return
        try:
            bauraum = [v.get() for v in self.bauraum]
            duebel = None
            if self.d_anzahl.get() > 0:
                duebel = kern.Duebel(self.d_anzahl.get(), self.d_durchmesser.get(), self.d_tiefe.get(),
                                     self.d_spiel.get(), drucken=self.d_drucken.get())
        except tk.TclError:
            messagebox.showerror("Fehler", "Bitte nur Zahlen eingeben (Dezimalpunkt statt Komma).")
            return
        quelle = Path(self.datei.get())
        ordner = filedialog.askdirectory(title="Ausgabeordner wählen", initialdir=quelle.parent,
                                         mustexist=False)
        if not ordner:
            return
        ordner = Path(ordner) / f"{quelle.stem}_teile"
        einstellungen = dict(modus=self.modus.get(), schnitte=list(self.schnitte), bauraum=bauraum,
                             duebel=duebel, dreimf=self.dreimf.get(), drehen=self.drehen.get())
        self.knopf.configure(state="disabled", text="Schneide …")
        threading.Thread(target=self._arbeite, args=(quelle.stem, ordner, einstellungen), daemon=True).start()

    def _arbeite(self, name, ordner, e):
        log = self.meldungen.put
        try:
            if e["modus"] == "auto":
                teile, n = kern.automatisch(self.mesh, e["bauraum"], duebel=e["duebel"], log=log)
            else:
                teile, n = kern.zerteile(self.mesh, e["schnitte"], e["duebel"], log=log)
            kern.exportiere(teile, name, ordner, e["bauraum"], drehen=e["drehen"], dreimf=e["dreimf"],
                            duebel=e["duebel"], anzahl_duebel=n, log=log)
            log(("fertig", str(ordner)))
        except Exception as fehler:
            log(("fehler", str(fehler)))

    def _hole_meldungen(self):
        while not self.meldungen.empty():
            m = self.meldungen.get()
            if isinstance(m, tuple):
                self.knopf.configure(state="normal", text="Schneiden")
                if m[0] == "fertig":
                    self._log("Fertig.")
                    if messagebox.askyesno("STL-Schneider", "Fertig. Ausgabeordner öffnen?"):
                        import os
                        os.startfile(m[1]) if hasattr(os, "startfile") else None
                else:
                    self._log(f"FEHLER: {m[1]}")
                    messagebox.showerror("Fehler", m[1])
            else:
                self._log(m)
        self.after(100, self._hole_meldungen)

    def _log(self, text):
        self.log_feld.configure(state="normal")
        self.log_feld.insert("end", text + "\n")
        self.log_feld.see("end")
        self.log_feld.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
