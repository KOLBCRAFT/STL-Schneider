"""Einfache Unterstützung für 3D-Mäuse von 3Dconnexion (SpaceMouse, SpaceNavigator) unter Windows.

Liest die HID-Berichte direkt über pywinusb. Ohne Windows, ohne pywinusb oder ohne Gerät
liefert finde() einfach None, das Programm läuft dann normal mit der Maus weiter.
"""
import struct
import threading

LOGITECH_SPACE_PRODUKTE = range(0xC603, 0xC650)


class SpaceMouse:
    def __init__(self, geraet):
        self.geraet = geraet
        self.name = geraet.product_name or "3D-Maus"
        self._sperre = threading.Lock()
        self._werte = [0.0] * 6  # tx, ty, tz, rx, ry, rz, jeweils etwa -1..1
        self.knoepfe = 0
        geraet.open()
        geraet.set_raw_data_handler(self._bericht)

    def _bericht(self, daten):
        daten = bytes(daten)
        kennung = daten[0]
        with self._sperre:
            if kennung == 1 and len(daten) >= 7:
                self._werte[0:3] = [v / 350.0 for v in struct.unpack("<hhh", daten[1:7])]
                if len(daten) >= 13:  # neuere Geräte schicken Drehung im selben Bericht
                    self._werte[3:6] = [v / 350.0 for v in struct.unpack("<hhh", daten[7:13])]
            elif kennung == 2 and len(daten) >= 7:
                self._werte[3:6] = [v / 350.0 for v in struct.unpack("<hhh", daten[1:7])]
            elif kennung == 3 and len(daten) >= 2:
                self.knoepfe = int.from_bytes(daten[1:5], "little")

    def lesen(self):
        with self._sperre:
            return list(self._werte)

    def schliessen(self):
        try:
            self.geraet.close()
        except Exception:
            pass


def finde():
    try:
        import pywinusb.hid as hid
    except Exception:
        return None
    for geraet in hid.HidDeviceFilter().get_devices():
        if geraet.vendor_id == 0x256F or (geraet.vendor_id == 0x046D and geraet.product_id in LOGITECH_SPACE_PRODUKTE):
            try:
                return SpaceMouse(geraet)
            except Exception:
                continue
    return None
