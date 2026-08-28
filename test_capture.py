"""
Check the interface of the screen sources, no emulator needed.

Both have to be able to do the same, otherwise switching between them only
fails during a run. That is exactly what happened when ADB went away.

  py test_capture.py
"""
import inspect
import os
import shutil
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture
import userdata

NOETIG = ["grab", "tap", "swipe", "back", "focus"]
KLASSEN = ["WindowCapture", "AdbCapture"]


def main():
    print("Required methods per screen source\n")
    errors = 0
    for name in KLASSEN:
        klasse = getattr(capture, name)
        missing = [m for m in NOETIG if not hasattr(klasse, m)]
        errors += len(missing)
        print("  %-16s %s" % (name, "complete" if not missing
                              else "MISSING " + ", ".join(missing)))

    print("\nSignatures of swipe, they have to match")
    for name in KLASSEN:
        fn = getattr(getattr(capture, name), "swipe", None)
        if fn:
            print("  %-16s %s" % (name, inspect.signature(fn)))

    print("\nEntry points")
    for name in ("open_adb", "open_window", "open_for", "require_adb"):
        print("  %-16s %s" % (name, "present" if hasattr(capture, name) else "MISSING"))

    print("\n%s" % ("all good" if not errors
                    else "%d missing methods" % errors))
    agreement()
    no_third_way()
    two_modes_no_mixing()
    adb_path_never_grabs_the_screen()
    require_adb_without_adb()


def a_screen(seed):
    """Something with enough structure in it to correlate on."""
    rng = np.random.RandomState(seed)
    img = np.zeros((1920, 1080, 3), np.uint8)
    for _ in range(40):
        x, y = rng.randint(0, 900), rng.randint(0, 1700)
        cv2.rectangle(img, (x, y), (x + rng.randint(40, 180),
                                    y + rng.randint(40, 180)),
                      tuple(int(c) for c in rng.randint(30, 255, 3)), -1)
    return img


def in_a_window(device_img, width=805):
    """The same screen as screen capture delivers it, chrome included."""
    left, top, right, bottom = capture.WINDOW_CHROME
    gw = width - left - right
    gh = int(round(gw / (1080 / 1920.0)))
    out = np.full((gh + top + bottom, width, 3), 40, np.uint8)
    out[top:top + gh, left:left + gw] = cv2.resize(
        device_img, (gw, gh), interpolation=cv2.INTER_AREA)
    return out


def agreement():
    """A window frame that has gone stale has to be caught, not used.

    While the display sleeps, screen capture keeps returning the last picture
    drawn, with no error anywhere. frames_agree has no caller left in this
    module -- the mixed mode it protected is gone -- but the measurement
    behind it is the record of why that mode needed watching, so it and this
    check stay.
    """
    print("\nWindow frame against device frame")
    device = a_screen(1)
    same = capture.frames_agree(in_a_window(device), device)
    small = capture.frames_agree(in_a_window(device, 619), device)
    stale = capture.frames_agree(in_a_window(a_screen(2)), device)
    print("  the same screen               %.3f" % same)
    print("  the same screen, small window %.3f" % small)
    print("  a window one screen behind    %.3f" % stale)
    assert same > capture.FRAMES_AGREE_MIN, same
    assert small > capture.FRAMES_AGREE_MIN, small
    assert stale < capture.FRAMES_AGREE_MIN, stale
    print("  a stale window is told apart from a live one")


def no_third_way():
    """HybridCapture does not come back. It was the mixed mode, frames from
    the window and clicks via ADB, that PLAN_ADB_ONLY.md set out to remove
    because it needed a window-to-device coordinate conversion nothing else
    in the program needs. If this fails, something has quietly restored it."""
    print("\nThe third mode")
    assert not hasattr(capture, "HybridCapture"), \
        "HybridCapture must not exist any more"
    for gone in ("open_capture", "open_best", "open_window_adb", "open_hybrid"):
        assert not hasattr(capture, gone), "%s must not exist any more" % gone
    print("  HybridCapture and its entry points are gone, only two modes remain")


class _FakeAdb:
    """Enough of AdbCapture's shape for open_for(True) to succeed without a
    real adb.exe or emulator: a device that lists itself and returns a
    trivial frame."""

    moves_mouse = False

    def __init__(self, adb=None, serial=None):
        self.adb = adb or "adb-fake"
        self.serial = serial
        self.method = "png"
        self.grabs = 0

    def devices(self):
        return ["emulator-fake"]

    def grab(self):
        self.grabs += 1
        return np.zeros((1920, 1080, 3), np.uint8)

    def works(self):
        return True

    def benchmark(self, rounds=3):
        return {"png": 0.01}

    def tap(self, x, y):
        pass

    def swipe(self, x1, y1, x2, y2, ms=300):
        pass

    def back(self):
        return True

    def focus(self):
        return True


def two_modes_no_mixing():
    """open_for picks by the stored switch alone: True gives something that
    never touches the real mouse, False gives something that does."""
    print("\nopen_for and moves_mouse")
    old_cls = capture.AdbCapture
    old_find = capture.find_adb
    capture.AdbCapture = _FakeAdb
    capture.find_adb = lambda: "adb-fake"
    old_env = os.environ.pop("DGUP_SCREENCAP", None)
    os.environ["DGUP_SCREENCAP"] = "png"  # skip the benchmark, not the point here
    try:
        adb_side = capture.open_for(True)
        assert adb_side.moves_mouse is False, \
            "the ADB side must not claim the real mouse"
        print("  open_for(True) does not move the mouse")
    finally:
        capture.AdbCapture = old_cls
        capture.find_adb = old_find
        if old_env is None:
            os.environ.pop("DGUP_SCREENCAP", None)
        else:
            os.environ["DGUP_SCREENCAP"] = old_env
    assert capture.WindowCapture.moves_mouse is True, \
        "the window side has to say it drives the real mouse"
    print("  the window side says it moves the mouse")


def adb_path_never_grabs_the_screen():
    """The ADB path must not fall back to mss for anything. If it did, a
    minimised or obscured window would silently start feeding it stale or
    black frames again -- the exact failure PLAN_ADB_ONLY.md measured."""
    print("\nADB path touches no screen capture")

    import builtins
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mss":
            raise AssertionError("the ADB path must never import mss")
        return real_import(name, *args, **kwargs)

    old_cls = capture.AdbCapture
    old_find = capture.find_adb
    capture.AdbCapture = _FakeAdb
    capture.find_adb = lambda: "adb-fake"
    old_env = os.environ.get("DGUP_SCREENCAP")
    os.environ["DGUP_SCREENCAP"] = "png"
    builtins.__import__ = guarded_import
    try:
        cap = capture.open_for(True)
        img = cap.grab()
        assert img is not None and img.size > 0
        print("  open_for(True).grab() delivers a frame with mss blocked")
    finally:
        builtins.__import__ = real_import
        capture.AdbCapture = old_cls
        capture.find_adb = old_find
        if old_env is None:
            os.environ.pop("DGUP_SCREENCAP", None)
        else:
            os.environ["DGUP_SCREENCAP"] = old_env


def require_adb_without_adb():
    """Without any adb.exe findable, require_adb() has to say so, and the
    message has to point at ADB debugging -- that is the one sentence a
    player is meant to act on."""
    print("\nrequire_adb without ADB")
    old_find = capture.find_adb
    capture.find_adb = lambda: None
    try:
        try:
            capture.require_adb()
            raise AssertionError("require_adb() must raise without adb.exe")
        except capture.CaptureError as err:
            assert "ADB debugging" in str(err), str(err)
            print("  raises CaptureError, and the message names ADB debugging")
    finally:
        capture.find_adb = old_find


if __name__ == "__main__":
    main()
