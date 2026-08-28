"""
Measure figure recognition over many frames. Clicks nothing.

Purpose: find out how often and by which stage the figure is found. Helps decide
whether a different character skin is worthwhile.

  py figure_probe.py --frames 60
  py figure_probe.py --frames 60 --color red     test the colour mode
"""
import argparse
import collections
import os
import time

import cv2

import capture
import userdata
import vision

PRESETS = {
    # kraeftiges Rot, am Brett sonst nicht vorhanden
    "red": [((0, 150, 110), (8, 255, 255)), ((170, 150, 110), (180, 255, 255))],
    "magenta": [((140, 120, 110), (168, 255, 255))],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=40)
    ap.add_argument("--interval", type=float, default=0.7)
    ap.add_argument("--color", choices=sorted(PRESETS))
    ap.add_argument("--debugdir", default="debug_explore")
    args = ap.parse_args()

    if args.color:
        vision.FIGURE_COLOR = PRESETS[args.color]
        print("Farbmodus", args.color)
    os.makedirs(args.debugdir, exist_ok=True)

    print("Suche Emulator...", flush=True)
    cap = capture.open_for(userdata.adb_mode())
    templates = vision.load_templates()
    print("Messe %d Frames, es wird nicht geklickt." % args.frames, flush=True)
    calib = None
    stats = collections.Counter()
    misses = 0

    for i in range(args.frames):
        img = cap.grab()
        if calib is None:
            try:
                calib = vision.calibrate(img)
            except vision.CalibrationError:
                time.sleep(args.interval)
                continue
        fig = vision.find_figure(img, calib, templates)
        if fig:
            stats[fig["how"]] += 1
            print("%3d  r%d c%d  %s" % (i + 1, fig["row"] + 1, fig["col"] + 1, fig["how"]),
                  flush=True)
        else:
            stats["not found"] += 1
            misses += 1
            if misses <= 6:  # ein paar Fehlschlaege sichern
                cv2.imwrite(os.path.join(args.debugdir, "miss_%03d.png" % (i + 1)), img)
            print("%3d  nicht gefunden" % (i + 1), flush=True)
        time.sleep(args.interval)

    total = sum(stats.values())
    print("\nErgebnis ueber %d Frames" % total)
    for how, n in stats.most_common():
        print("  %-16s %3d  %5.1f Prozent" % (how, n, 100.0 * n / max(total, 1)))
    print("\nFehlschlaege liegen als miss_*.png in", args.debugdir)


if __name__ == "__main__":
    main()
