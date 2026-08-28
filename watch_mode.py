"""
Watch mode. Continuously reads grid, figure, counters and banners. Clicks
nothing.

Purpose: check whether recognition is sound before the bot acts. You play, the
script logs. Every action of yours has to show up as a correct delta; then the
foundation holds.

  py watch_mode.py                 loop until Ctrl C
  py watch_mode.py --interval 1.0
  py watch_mode.py --input mouse   window capture, no ADB
"""

import argparse
import datetime
import os
import time

import cv2

import capture
import tracker
import userdata
import vision

DELTA_LABEL = {
    "paws": "Tatzen",
    "claws": "Krallen",
    "fireballs": "Feuerbaelle",
    "meters": "Meter",
    "top_orange": "orange",
    "top_green": "gruen",
    "top_pink": "rosa",
}


def grid_text(grid):
    short = {
        "ticket_orange": "TO",
        "ticket_green": "TG",
        "ticket_pink": "TP",
        "claw": "KR",
        "paw": "TA",
        "fireball": "FB",
        "pyramid": "PY",
        "figure": "@@",
        "?": "??",
    }
    lines = []
    for row in grid:
        lines.append(" ".join(short.get(cell, " .") if cell else " ." for cell in row))
    return lines


def format_deltas(deltas, values):
    return ["%s %+d -> %s" % (DELTA_LABEL.get(k, k), d, values.get(k))
            for k, d in deltas.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames via adb or via the window. Default: the "
                         "stored switch (Helpermon's window, or "
                         "DGUP_ADB_MODE)")
    ap.add_argument("--title", default="LDPlayer")
    ap.add_argument("--debugdir", default="debug_explore")
    ap.add_argument("--save-every", type=int, default=0,
                    help="jedes n-te Bild speichern, 0 nur bei Aenderungen")
    ap.add_argument("--calib-frames", type=int, default=8,
                    help="so viele gute Frames mitteln, danach Geometrie einfrieren")
    args = ap.parse_args()

    os.makedirs(args.debugdir, exist_ok=True)
    os.makedirs(os.path.join(args.debugdir, "unknown"), exist_ok=True)
    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb, title_contains=args.title)

    templates = vision.load_templates()
    if not templates:
        raise SystemExit("keine Templates in templates/ gefunden")
    tpl_objects = vision.board_templates(templates)
    missing = [d for pol in ("bright", "dark") for d in "0123456789"
               if not os.path.exists(os.path.join(vision.DIGIT_DIR, pol, d + ".png"))]
    if missing:
        print("Hinweis, fehlende Zifferntemplates:", missing,
              "-> learn_digits.py verwenden, sobald so eine Zahl auftaucht")

    calib = None
    calib_samples = []
    counters_state = tracker.CounterTracker(max_actions_per_frame=3)
    last_grid = None
    frame_no = 0
    print("Lesemodus laeuft, Strg C beendet. Es wird nicht geklickt.")

    while True:
        frame_no += 1
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            img = cap.grab()
        except Exception as err:
            print(stamp, "Bildquelle Fehler:", err)
            time.sleep(args.interval)
            continue

        # Geometrie aus den ersten guten Frames mitteln und dann einfrieren.
        # Nicht auf einem Frame mit Banner kalibrieren, das verzerrt die
        # Kantenprofile.
        if len(calib_samples) < args.calib_frames:
            try:
                fresh = vision.calibrate(img)
                if not vision.banner_visible(img, fresh):
                    calib_samples.append(fresh)
                    calib = vision.median_calib(calib_samples)
                    if len(calib_samples) == args.calib_frames:
                        print("Geometrie eingefroren, Zelle %.2f x %.2f"
                              % (calib["cell_w"], calib["cell_h"]))
            except vision.CalibrationError as err:
                print(stamp, "Kalibrierung fehlgeschlagen:", err)
        if calib is None:
            time.sleep(args.interval)
            continue

        banner = vision.classify_banner(img, calib)
        grid, scores = vision.read_grid(img, calib, tpl_objects)
        figure = vision.find_figure(img, calib, templates)
        counters = vision.read_counters(img, calib)
        deltas = counters_state.update(counters)
        changed = format_deltas(deltas, counters_state.values)
        grid_changed = grid != last_grid

        if changed or grid_changed or banner or frame_no == 1:
            pos = ("r%d c%d %s" % (figure["row"] + 1, figure["col"] + 1, figure["how"])
                   if figure else "?")
            print("\n[%s] Figur %s  Zelle %.1fx%.1f  Banner %s"
                  % (stamp, pos, calib["cell_w"], calib["cell_h"], banner or "nein"))
            for line in grid_text(grid):
                print("   ", line)
            print("    Zaehler", " ".join(
                "%s=%s" % (DELTA_LABEL.get(k, k), v) for k, v in counters.items()))
            for line in changed:
                print("    DELTA", line)
            for key, old, new in counters_state.suspicious:
                print("    REJECTED %s %s -> %s, implausible"
                      % (DELTA_LABEL.get(key, key), old, new))
                x, y, w, h = calib["roi_" + key] if "roi_" + key in calib else (0, 0, 0, 0)
                if w:
                    cv2.imwrite(os.path.join(args.debugdir,
                                "bad_%s_f%05d.png" % (key, frame_no)),
                                img[y : y + h, x : x + w])
            if banner == "unknown":
                # sehr wahrscheinlich der Text bei fehlender Energie. Den
                # brauche ich noch, deshalb wird er gesichert
                path = os.path.join(args.debugdir, "banner_UNBEKANNT_%s.png" % frame_no)
                cv2.imwrite(path, vision.banner_roi(img, calib))
                print("    UNBEKANNTER Bannertext gespeichert:", path)

        # unbekannte Objekte einzeln wegschreiben, damit Templates ergaenzt
        # werden koennen statt sie zu uebersehen
        for r in range(vision.ROWS):
            for c in range(vision.COLS):
                if grid[r][c] == "?":
                    patch = vision.search_patch(img, calib, r, c)
                    name = "unknown/f%05d_r%d_c%d.png" % (frame_no, r + 1, c + 1)
                    cv2.imwrite(os.path.join(args.debugdir, name), patch)

        if args.save_every and frame_no % args.save_every == 0 or frame_no == 1:
            vis = vision.draw_overlay(img, calib, grid, figure, counters)
            cv2.imwrite(os.path.join(args.debugdir, "frame_%05d.png" % frame_no), vis)

        last_grid = grid
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
