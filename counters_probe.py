"""
Diagnose the digit recognition. Clicks nothing.

Shows for each counter over several frames whether it is readable and why not.
Saves the crops of the failures so missing digits can be learned.

  py counters_probe.py
  py counters_probe.py --frames 20
"""
import argparse
import collections
import os
import time

import cv2

import capture
import userdata
import vision

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--interval", type=float, default=0.6)
    ap.add_argument("--debugdir", default="debug_explore")
    args = ap.parse_args()
    os.makedirs(args.debugdir, exist_ok=True)

    print("Gemeinsamer Ziffernsatz, gilt fuer alle sieben Zaehler:")
    for name, table in vision.digit_stats().items():
        missing = [d for d in "0123456789" if table.get(d, 0) == 0]
        duenn = [d for d, n in sorted(table.items()) if 0 < n < 5]
        print("  %s   fehlt: %s   duenn besetzt: %s"
              % (table, ", ".join(missing) or "nichts", ", ".join(duenn) or "nichts"))

    cap = capture.open_for(userdata.adb_mode())
    calib = None
    ok = collections.Counter()
    reasons = collections.Counter()

    for i in range(args.frames):
        img = cap.grab()
        if calib is None:
            try:
                calib = vision.calibrate(img)
            except vision.CalibrationError as err:
                print("Kalibrierung:", err)
                time.sleep(args.interval)
                continue
        line = []
        for key in vision.COUNTER_KEYS:
            value, why = vision.read_number(img, key, calib, debug=True)
            short = key.replace("roi_", "")
            if value is None:
                reasons[(short, why)] += 1
                x, y, w, h = calib[key]
                cv2.imwrite(os.path.join(args.debugdir, "%s_f%02d.png" % (short, i + 1)),
                            img[y : y + h, x : x + w])
            else:
                ok[short] += 1
            line.append("%s=%s" % (short, value if value is not None else "-"))
        print("%2d  %s" % (i + 1, "  ".join(line)), flush=True)
        time.sleep(args.interval)

    print("\nTrefferquote je Zaehler")
    for key in vision.COUNTER_KEYS:
        short = key.replace("roi_", "")
        print("  %-12s %2d von %d" % (short, ok[short], args.frames))
    if reasons:
        print("\nGruende fuer Fehlschlaege")
        for (short, why), n in reasons.most_common():
            print("  %-12s %-40s %dx" % (short, why, n))
        print("\nWenn ein Zeichen als unsicher gemeldet wird, fehlt dieser Ziffer")
        print("ein Referenzbild. Nachlernen mit dem Wert, der gerade dort steht:")
        for short in sorted({s for s, _ in reasons}):
            print("  py learn_digits.py --roi %s --value <Zahl>" % short)
    print("\nAusschnitte liegen in", args.debugdir)

if __name__ == "__main__":
    main()
