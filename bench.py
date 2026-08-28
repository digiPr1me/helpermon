"""
Measure speed. Clicks nothing.

Shows how long a screenshot and the analysis really take. That is the part which
determines the bot's pace.

  py bench.py
  py bench.py --rounds 10
"""
import argparse
import time

import capture
import vision


def timed(fn, rounds):
    t0 = time.time()
    for _ in range(rounds):
        out = fn()
    return (time.time() - t0) / rounds, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=6)
    args = ap.parse_args()

    cap = capture.open_adb()
    print("\nScreenshot per ADB")
    best = None
    for method in ("png", "raw"):
        cap.method = method
        try:
            dt, img = timed(cap.grab, args.rounds)
        except Exception as err:
            print("  %-4s nicht nutzbar (%s)" % (method, err))
            continue
        print("  %-4s %6.0f ms   Bild %d x %d" % (method, dt * 1000,
                                                  img.shape[1], img.shape[0]))
        if best is None or dt < best[1]:
            best = (method, dt)
    if best:
        cap.method = best[0]
        print("  schnellstes Verfahren: %s" % best[0])

    img = cap.grab()
    calib = vision.calibrate(img)
    templates = vision.load_templates()
    board = vision.board_templates(templates)

    print("\nAuswertung, jeweils ohne neuen Screenshot")
    dt, _ = timed(lambda: vision.calibrate(img), args.rounds)
    print("  kalibrieren     %6.0f ms" % (dt * 1000))
    dt, _ = timed(lambda: vision.read_grid(img, calib, board), args.rounds)
    print("  Brett lesen     %6.0f ms" % (dt * 1000))
    dt, _ = timed(lambda: vision.read_counters(img, calib), args.rounds)
    print("  Zaehler lesen   %6.0f ms" % (dt * 1000))
    dt, _ = timed(lambda: vision.find_figure(img, calib, templates), args.rounds)
    print("  Figur finden    %6.0f ms" % (dt * 1000))
    dt, _ = timed(lambda: vision.classify_banner(img, calib), args.rounds)
    print("  Banner pruefen  %6.0f ms" % (dt * 1000))

    print("\nScreenshot per Fensteraufnahme, zum Vergleich")
    print("(braucht ein sichtbares, unverdecktes Fenster -- siehe")
    print(" PLAN_ADB_ONLY.md dazu, warum die ADB-Seite trotzdem der Standard ist)")
    try:
        win = capture.open_window()
        dt, wimg = timed(win.grab, args.rounds)
        print("  fenster %6.0f ms   Bild %d x %d"
              % (dt * 1000, wimg.shape[1], wimg.shape[0]))
        if best:
            print("  Unterschied zu ADB: %.0f ms pro Bild"
                  % ((best[1] - dt) * 1000))
    except Exception as err:
        print("  nicht nutzbar (%s)" % err)

    print("\nEine Aktion braucht 1 Klick, 1 bis 3 Bilder plus Auswertung.")
    print("Dominieren die Bilder unter ADB, hilft eine kleinere")
    print("Emulatorauflaesung, zum Beispiel 540 x 960 statt 1080 x 1920.")


if __name__ == "__main__":
    main()
