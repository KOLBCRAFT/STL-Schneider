"""Schreibt fehlgeschlagene Tests aus einer JUnit-XML als GitHub-Annotations, damit man sie ohne Log sieht."""
import sys
import xml.etree.ElementTree as ET

for datei in sys.argv[1:]:
    try:
        wurzel = ET.parse(datei).getroot()
    except (OSError, ET.ParseError) as e:
        print(f"::error title=Testbericht fehlt::{datei}: {e}")
        continue
    for fall in wurzel.iter("testcase"):
        for art in ("failure", "error"):
            for f in fall.findall(art):
                text = ((f.get("message") or "") + "\n" + (f.text or "")).strip()
                text = text[-1500:].replace("%", "%25").replace("\r", "").replace("\n", "%0A")
                print(f"::error title={fall.get('classname')}.{fall.get('name')}::{text}")
