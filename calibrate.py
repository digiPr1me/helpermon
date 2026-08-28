"""
Check calibration. Takes one frame, measures the geometry and writes a debug
image with the grid drawn on it.

The geometry is deliberately not saved. It is measured afresh on every start,
because window size and capture method can change.

  py calibrate.py                from the running emulator
  py calibrate.py image.png      from a file
"""
import os
import sys
import time

import cv2

import capture
import userdata
import vision

ATTEMPTS = 6


def grab_and_calibrate():
    """Mehrere Versuche, weil ein Frame mitten in einer Animation oder waehrend
    eines Szenenwechsels nicht auswertbar ist."""
    cap = capture.open_for(userdata.adb_mode())
    last = None
    for i in range(ATTEMPTS):
        img = cap.grab()
        try:
            return img, vision.calibrate(img)
        except vision.CalibrationError as err:
            last = err
            print("Versuch %d fehlgeschlagen: %s" % (i + 1, err))
            time.sleep(0.6)
    raise SystemExit(
        "Kalibrierung nach %d Versuchen fehlgeschlagen: %s\n"
        "Steht das Minispiel offen und im Vordergrund?" % (ATTEMPTS, last)
    )


def main():
    if len(sys.argv) > 1:
        img = cv2.imread(sys.argv[1])
        if img is None:
            raise SystemExit("Bild nicht lesbar: %s" % sys.argv[1])
        calib = vision.calibrate(img)
    else:
        img, calib = grab_and_calibrate()

    templates = vision.load_templates()
    objects = vision.board_templates(templates)
    grid, _ = vision.read_grid(img, calib, objects)
    figure = vision.find_figure(img, calib, templates)
    counters = vision.read_counters(img, calib)

    print("Bild       %d x %d" % (img.shape[1], img.shape[0]))
    print("Karte      ", calib["card"])
    print("Raster     x0=%.1f y0=%.1f" % (calib["grid_x0"], calib["grid_y0"]))
    print("Zelle      %.2f x %.2f  Verhaeltnis %.3f"
          % (calib["cell_w"], calib["cell_h"], calib["cell_w"] / calib["cell_h"]))
    print("Figur      ", figure)
    print("Zaehler    ", counters)
    print("Banner     ", vision.banner_visible(img, calib))
    print("Skillknopf ", calib["skill_button"],
          "erkannt" if vision.skill_button_ok(img, calib) else "NICHT erkannt")
    os.makedirs("debug", exist_ok=True)
    out = os.path.join("debug", "calib_overlay.png")
    cv2.imwrite(out, vision.draw_overlay(img, calib, grid, figure, counters))
    print("\nDebugbild:", out)
    print("Bitte pruefen, ob die sieben Zahlen mit dem Spiel uebereinstimmen.")


if __name__ == "__main__":
    main()
