r"""
Measure what ADB actually delivers, before anything is built on the answer.

Three questions, and the whole "read the screen through ADB only" idea rests
on the first of them:

  1. does ADB keep delivering FRESH frames while the emulator window is
     minimised? Screen capture does not -- it hands out the picture of
     whatever window is on top, or black for a minimised one, with no error
     anywhere. If ADB went stale too, there would be nothing to gain.
  2. what does one ADB frame cost on this machine? Measured 9 ms for screen
     capture against 430 ms for ADB on the machine this project grew up on,
     and that gap is what the frame source was chosen for.
  3. what size and shape is the ADB frame? Every position in dungeon.py is a
     fraction of a 9:16 screen. Anything else falls through game_rect's
     "use the picture as it comes" branch, where no constant holds any more.

  py adb_probe.py                  all of it
  py adb_probe.py --no-minimise    leave the window alone, skip question 1
  py adb_probe.py --package        also look up the game's package name

Open the game first and leave it on a screen where something moves -- the
main screen does, the partner idles there. A perfectly still screen cannot
tell "ADB is frozen" from "nothing was happening", and this says so rather
than guessing.

Nothing from the game is written to disk. This prints numbers.
"""

import argparse
import time

import cv2
import numpy as np

import capture

# How much of the picture has to differ before two frames count as different.
# Same test as launcher._changed, same reason: a clock ticking is not motion,
# a running game is. The number is printed either way, so a screen that sits
# just under it can be seen rather than guessed at.
CHANGE_MIN = 0.002


def change_share(a, b):
    """Fraction of pixels that differ, or -1 if the two cannot be compared."""
    if a is None or b is None or a.shape != b.shape:
        return -1.0
    diff = cv2.absdiff(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY),
                       cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    return float(np.count_nonzero(diff > 30)) / diff.size


def series(grab, rounds=4, pause=1.2, label=""):
    """Grab a few frames and report how much moved between them."""
    frames = []
    for i in range(rounds):
        if i:
            time.sleep(pause)
        try:
            frames.append(grab())
        except Exception as err:
            print("    %s frame %d failed: %s" % (label, i + 1, err))
            frames.append(None)
    shares = [change_share(frames[i], frames[i + 1])
              for i in range(len(frames) - 1)]
    identical = sum(1 for s in shares if s == 0.0)
    print("    change between frames: %s"
          % ", ".join("%.4f" % s for s in shares))
    if identical:
        print("    %d of %d pairs are pixel for pixel identical"
              % (identical, len(shares)))
    return max(shares) if shares else -1.0


# ----------------------------------------------------------------------------
def question_3(cap):
    print("\n3. Size and shape of the ADB frame")
    img = cap.grab()
    h, w = img.shape[:2]
    aspect = w / float(h)
    print("    %d x %d, aspect %.4f" % (w, h, aspect))
    wanted = 1080 / 1920.0
    if abs(aspect - wanted) <= 0.008:
        print("    9:16 as expected, every fraction in dungeon.py holds")
    else:
        print("    NOT 9:16 (%.4f wanted). game_rect will fall through to "
              "'use the picture as it comes', and the bots' positions do not "
              "hold on this shape. Set the emulator back to a phone "
              "resolution." % wanted)
    return img


def question_2(cap):
    print("\n2. What one ADB frame costs")
    keep = cap.method
    for method in ("png", "raw"):
        cap.method = method
        try:
            t0 = time.time()
            for _ in range(5):
                cap.grab()
            print("    %-4s %6.0f ms per frame" % (method,
                                                   (time.time() - t0) / 5 * 1000))
        except Exception as err:
            print("    %-4s not usable: %s" % (method, err))
    cap.method = keep
    print("    (screen capture measured 9 ms on the reference machine. The "
          "difference is the price of the change, and it belongs in the log "
          "of the first real run.)")


def question_1(cap, no_minimise=False):
    print("\n1. Does ADB stay fresh while the window is minimised?")
    win, _rejected = capture._find_emulator_window()
    if win is None:
        print("    no emulator window found, so this cannot be answered here")
        return

    print("  a) window visible -- how much moves on this screen at all")
    baseline = series(cap.grab, label="ADB")
    if baseline < CHANGE_MIN:
        print("    Nothing is moving on this screen (%.4f under %.4f). Bring "
              "the game to a screen where something animates, otherwise a "
              "frozen ADB and a still screen look the same."
              % (baseline, CHANGE_MIN))
        return
    if no_minimise:
        print("\n  b) skipped (--no-minimise)")
        return

    handle = win._window()
    print("\n  b) window minimised")
    try:
        handle.minimize()
        time.sleep(2.0)
        minimised = series(cap.grab, label="ADB")
        print("\n  c) what screen capture says about the same moment")
        try:
            shot = win.grab()
            print("    window frame %d x %d, mean colour %s"
                  % (shot.shape[1], shot.shape[0],
                     "/".join("%d" % v for v in shot.reshape(-1, 3).mean(0))))
        except Exception as err:
            print("    screen capture failed outright: %s" % err)
    finally:
        try:
            handle.restore()
            time.sleep(1.0)
        except Exception as err:
            print("    could not restore the window (%s), do it by hand" % err)

    print("\n    verdict")
    if minimised >= CHANGE_MIN:
        print("    ADB keeps delivering fresh frames while minimised "
              "(%.4f against %.4f visible). That is what the change is for."
              % (minimised, baseline))
    else:
        print("    ADB went STILL while minimised (%.4f against %.4f "
              "visible). Either the emulator throttles its rendering when "
              "minimised, or the screen stopped moving on its own -- run it "
              "again and watch. If it holds, ADB-only buys freedom from a "
              "*covered* window, not from a minimised one, and the plan has "
              "to say so." % (minimised, baseline))


def question_package():
    print("\n4. The game's package name, the thing ADB starts instead of "
          "clicking an icon")
    import ldplayer
    import noconsole
    cap = capture.AdbCapture()
    devices = cap.devices()
    if not devices:
        print("    no device")
        return
    cap.serial = devices[0]
    out = noconsole.run(cap._cmd("shell", "pm", "list", "packages"),
                        capture_output=True, timeout=30).stdout.decode(
                            "utf-8", errors="replace")
    names = [line.split(":", 1)[1].strip()
             for line in out.splitlines() if ":" in line]
    hits = [n for n in names
            if any(h in n.lower() for h in ldplayer.PACKAGE_HINTS)]
    print("    %d packages installed, %d match %s"
          % (len(names), len(hits), ", ".join(ldplayer.PACKAGE_HINTS)))
    for name in hits:
        print("      %s" % name)
    if len(hits) == 1:
        print("    one clear match, so the cold start needs no learned icon")
    elif not hits:
        print("    nothing matched. Pin it by hand:\n"
              '      $env:DGUP_PACKAGE = "the.package.name"')
    else:
        print("    more than one match, so pin the right one:\n"
              '      $env:DGUP_PACKAGE = "the.package.name"')


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-minimise", action="store_true",
                    help="do not touch the window, skip question 1")
    ap.add_argument("--package", action="store_true",
                    help="also look up the game's package name")
    args = ap.parse_args()

    adb = capture.find_adb()
    print("adb.exe: %s" % (adb or "NOT FOUND -- set DGUP_ADB"))
    cap = capture.AdbCapture()
    devices = cap.devices()
    print("devices: %s" % (", ".join(devices) or "none"))
    if not devices:
        raise SystemExit(
            "\nADB lists no device. In LDPlayer: Settings, Other settings, "
            "ADB debugging -> on.\nThe emulator switches it off again between "
            "sessions, so it is worth checking\nwhenever something stops here.")
    if cap.serial not in devices:
        cap.serial = devices[0]
    print("using:   %s%s" % (cap.serial,
                             "  (pin it with DGUP_SERIAL)"
                             if len(devices) > 1 else ""))

    question_3(cap)
    question_2(cap)
    question_1(cap, no_minimise=args.no_minimise)
    if args.package:
        question_package()


if __name__ == "__main__":
    main()
