"""
Learn missing or uncertain digits.

There is one shared digit set for all seven counters, so what is learned here
helps everywhere and not just in one bar. Each digit holds several reference
images; this script adds more and averages nothing away.

  py learn_digits.py --roi paws --value 1432
  py learn_digits.py --roi claws --value 27
  py learn_digits.py --roi paws --value 1432 --image file.png

Afterwards check with counters_probe.py.
"""
import argparse
import os

import cv2

import capture
import userdata
import vision

ROIS = ["top_orange", "top_green", "top_pink", "paws", "claws", "fireballs", "meters"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roi", required=True, choices=ROIS)
    ap.add_argument("--value", required=True, help="Zahl, die dort gerade steht")
    ap.add_argument("--image", help="statt Emulator ein gespeichertes Bild")
    args = ap.parse_args()

    img = cv2.imread(args.image) if args.image \
        else capture.open_for(userdata.adb_mode()).grab()
    if img is None:
        raise SystemExit("Bild nicht lesbar")
    calib = vision.calibrate(img)
    key = "roi_" + args.roi
    pol = vision.POLARITY[key]
    glyphs = vision.segment_digits(img, calib[key], pol)
    digits = "".join(ch for ch in args.value if ch.isdigit())

    if len(glyphs) != len(digits):
        raise SystemExit(
            "gefunden %d Zeichen, angegeben %d. Steht die Zahl gerade wirklich "
            "so da?" % (len(glyphs), len(digits)))

    table = vision._digit_templates()
    for glyph, ch in zip(glyphs, digits):
        g = cv2.resize(glyph, (vision.GLYPH_W, vision.GLYPH_H))
        before, score = vision._classify_glyph(glyph, table)
        folder = os.path.join(vision.DIGIT_DIR, vision.DIGIT_SET, ch)
        os.makedirs(folder, exist_ok=True)
        n = len([f for f in os.listdir(folder) if f.endswith(".png")])
        cv2.imwrite(os.path.join(folder, "%02d.png" % n), g)
        status = "war schon sicher" if before == ch else (
            "war unsicher, Score %.3f" % score if before is None
            else "war FALSCH als %s erkannt" % before)
        print("  %s gelernt, jetzt %d Referenzen, %s" % (ch, n + 1, status))

    # Cache leeren und gleich nachpruefen
    vision._DIGITS.clear()
    value, why = vision.read_number(img, key, calib, debug=True)
    print("\nKontrolle: %s liest jetzt %s (%s)" % (args.roi, value, why))
    if str(value) != digits:
        print("Achtung, stimmt noch nicht. Nochmal ausfuehren oder "
              "counters_probe.py fuer Details.")


if __name__ == "__main__":
    main()
