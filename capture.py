"""
Screen sources and input. Two ways, all with the same interface.

  ADB      frames and clicks both via ADB. The default: the window may sit
           behind other windows or be minimised, the real mouse stays free,
           colour is unaffected by night light or an HDR profile. Costs
           roughly 400 ms per frame against 9 ms for a window capture.
  window   frames by screen capture, input by mouse and keyboard. No ADB
           needed, but the window must stay visible, unobscured and in the
           foreground, and it drives the real mouse.

Measured directly, with two Tk windows of known colour and the same mss
WindowCapture uses (see PLAN_ADB_ONLY.md, section 0, not shipped publicly):
mss photographs the *screen rectangle*, not the window. A window covered by
another one returns that other window's picture; a minimised window returns
black, pygetwindow reporting its position as -32000,-32000. Neither raises
an error. Focus alone is not the trigger -- a visible, unfocused window is
captured correctly -- but obscured, minimised, on another virtual desktop,
moved off a disabled second monitor, or behind a sleeping or locked screen
all fail silently, and so does night light or any colour profile: every
threshold in dungeon.py is a colour threshold. ADB was measured immune to
all of it and stays fresh while the window is minimised (frame-to-frame
motion 0.009 against 0.014 visible, the same scene).

There used to be a third way, frames from the window with clicks via ADB,
kept because a window capture is far faster. It needed a conversion between
window and device coordinates in one direction or the other, and that
conversion is the trap this module no longer has: image and click now
always come from the same source, so no coordinate ever needs converting.

All classes provide `grab`, `tap`, `swipe`, `back` and `focus`, plus a
`moves_mouse` attribute saying whether that class drives the real cursor.
That matters because the bots used to reach through to ADB directly in
several places, and a missing method would only have surfaced during a run.
"""

import glob
import os
import re
import struct
import time

import cv2
import numpy as np

import noconsole
import userdata


class CaptureError(RuntimeError):
    pass


# LDPlayer ships ADB but does not put it on the PATH, so it has to be found.
# These are the last resort, after the registry and after every drive has
# been looked at; they only still earn their place for an install Windows has
# no record of. DGUP_ADB, an environment variable, overrides the lot.
ADB_CANDIDATES = [
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer64\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\adb.exe",
    r"C:\Program Files (x86)\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
]



# Where the game sits inside the emulator window: left, top, right, bottom in
# pixels. It does not scale with the window. Measured on two window sizes on
# the same machine, each matched against the ADB frame of the same screen:
#
#   window 805 x 1390   game 758 x 1348 at 4, 40   correlation 0.99
#   window 619 x 1059   game 572 x 1017 at 4, 40   correlation 0.95
#
# The 43 px on the right are LDPlayer's own sidebar, the 40 on top its tab
# bar. Both are in every window frame and in none of an ADB frame, which is
# the whole reason the two have to be reconciled at all.
WINDOW_CHROME = (4, 40, 43, 2)

# The same thing as fractions of the 805 x 1390 window the dungeon bot's
# positions were measured in. That window is the reference: see game_rect in
# dungeon.py for what the numbers there mean.
GAME_IN_WINDOW = (4 / 805.0, 40 / 1390.0, 758 / 805.0, 1348 / 1390.0)

# A window frame and an ADB frame of the same moment correlate at 0.99 once
# the chrome is off. A window frame showing something else scores near zero.
# Measured on four real pairs:
#
#   the same screen, 805 window          0.998
#   the same screen, 619 window          0.995
#   window one screen behind             0.036
#   window on the title screen, game on the dungeon list   -0.090
#
# The threshold sits in the middle of that gap. Without the chrome removed
# the same pairs score 0.43 against 0.24 and cannot be told apart at all.
#
# Nothing in this module calls frames_agree any more: it was what the third,
# mixed way (window frames, ADB clicks) used to tell a stale window frame
# from a live one before trusting it for a click. With image and click
# always from the same source now, the question it answered does not come
# up -- it stays, with its test, as the record of why that mixed way needed
# watching in the first place.
FRAMES_AGREE_MIN = 0.5


def frames_agree(window_img, device_img):
    """Do a window frame and an ADB frame show the same thing?

    Worth asking because a window frame can go stale without any error: while
    the display sleeps, screen capture returns the last thing that was drawn
    for as long as it stays asleep, and a bot reading that picture clicks at
    what the screen showed minutes ago. ADB does not have that problem, so
    when the two disagree, ADB is the one to believe.
    """
    left, top, right, bottom = WINDOW_CHROME
    game = window_img[top:window_img.shape[0] - bottom,
                      left:window_img.shape[1] - right]
    if game.size == 0 or device_img.size == 0:
        return -1.0
    size = (96, 171)
    a = cv2.resize(cv2.cvtColor(game, cv2.COLOR_BGR2GRAY), size,
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    b = cv2.resize(cv2.cvtColor(device_img, cv2.COLOR_BGR2GRAY), size,
                   interpolation=cv2.INTER_AREA).astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    spread = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / spread) if spread else -1.0


# The game runs portrait, 1080:1920, so the emulator window is markedly
# taller than it is wide: measured 574x1051 and 765x1390, ratio 1.83. The
# lower bound leaves room for LDPlayer's side toolbar, which widens the
# window without widening the game area; the upper bound is slack.
#
# This exists because a title match alone is not evidence. "DIGI" matched a
# browser window and the launcher cheerfully reported an emulator at
# 976x739, ratio 0.76, with LDPlayer not running.
EMULATOR_MIN_RATIO = 1.4
EMULATOR_MAX_RATIO = 2.3


# Window names worth trying. Which of them is the emulator is decided by
# the program behind the window, not by the name itself.
EMULATOR_TITLES = ("LDPlayer", "BlueStacks", "MEmu", "Nox", "MuMu")

# The emulator renames its own window to whatever app is running, so the
# game's name has to be tried too.
GAME_TITLES = ("DIGIMON", "DIGI")

# The executables those windows belong to. This is the part that does not
# change when the title does.
EMULATOR_PROCESSES = ("dnplayer.exe", "dnmultiplayer.exe", "ldplayer.exe",
                      "ld.exe", "ldconsole.exe", "bluestacks.exe",
                      "hd-player.exe", "bluestacksgp.exe", "memu.exe",
                      "memuheadless.exe", "nox.exe", "noxvmhandle.exe",
                      "mumuplayer.exe", "mumunxdevice.exe")


def window_process(win):
    """Executable owning a window, lowercased file name, or "" if it cannot
    be read. Windows only, and a failure here is not fatal -- the caller
    falls back to judging by shape."""
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = getattr(win, "_hWnd", None)
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            ok = ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            # Full path, not just the file name: an emulator installs its
            # programs into a folder named after itself, which identifies
            # the ones this list has never heard of.
            return buf.value.lower().replace("\\", "/")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        return ""


def is_emulator_process(path):
    """Known program, or any program living in an emulator's own folder."""
    if not path:
        return False
    if os.path.basename(path) in EMULATOR_PROCESSES:
        return True
    folder = os.path.dirname(path)
    return any(name.lower() in folder for name in EMULATOR_TITLES)


def looks_like_emulator(img):
    """True if this frame could be a portrait phone screen."""
    if img is None or getattr(img, "size", 0) == 0:
        return False
    h, w = img.shape[:2]
    if w < 200 or h < 200:
        return False
    return EMULATOR_MIN_RATIO <= h / float(w) <= EMULATOR_MAX_RATIO


def _ld_version(path):
    """Version number out of an LDPlayer install path, for sorting."""
    found = re.findall(r"ldplayer[ _-]*(\d+)", path.lower())
    return max((int(n) for n in found), default=0)


def fixed_drives():
    """Every drive letter that is there, so a search is not two guesses.

    It used to look on C: and D:. A player with LDPlayer on E: was told no
    ADB could be found, which was true only of the two places looked at.
    """
    import ctypes
    DRIVE_FIXED = 3
    try:
        bits = ctypes.windll.kernel32.GetLogicalDrives()
        out = []
        for i in range(26):
            if not bits >> i & 1:
                continue
            letter = "%s:\\" % chr(ord("A") + i)
            # Fixed disks only. A network drive that is no longer there can
            # make a search hang for seconds, and nobody installs an emulator
            # on a DVD.
            if ctypes.windll.kernel32.GetDriveTypeW(letter) == DRIVE_FIXED:
                out.append(letter)
        return out or ["C:\\"]
    except Exception:
        return ["C:\\", "D:\\"]


def ld_from_registry():
    """Install folders Windows itself has on file for LDPlayer.

    InstallLocation is the field meant for this and LDPlayer leaves it
    empty, measured on LDPlayer 14. What it does fill in is the uninstaller
    and the icon, both of which sit in the install folder, so the folder is
    read off those instead.
    """
    import winreg
    roots = [(winreg.HKEY_LOCAL_MACHINE,
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE,
              r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER,
              r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    found = []
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, name) as sub:
                        values = {}
                        for j in range(winreg.QueryInfoKey(sub)[1]):
                            vn, vv, _ = winreg.EnumValue(sub, j)
                            values[vn] = vv
                except OSError:
                    continue
                display = str(values.get("DisplayName", ""))
                if "ldplayer" not in display.lower().replace(" ", ""):
                    continue
                place = values.get("InstallLocation") or ""
                if not place:
                    for field in ("DisplayIcon", "UninstallString"):
                        raw = str(values.get(field, "")).strip('"')
                        if raw:
                            place = os.path.dirname(raw)
                            break
                if place and os.path.isdir(place):
                    found.append(place)
    return found


def ld_installs(filename, roots=None):
    """Every LDPlayer install carrying this file, newest version first.

    Newest first because a machine can have two: version 9 left behind and
    version 14 in use. A fixed list of paths cannot express "the newer one",
    and the one that happened to be typed first won.

    Windows is asked before the disk is searched, and every drive is searched
    rather than the two that used to be named.
    """
    found = set()
    for place in ld_from_registry():
        candidate = os.path.join(place, filename)
        if os.path.exists(candidate):
            found.add(candidate)
    for root in (roots if roots is not None else fixed_drives()):
        for pattern in (root + "LDPlayer*/" + filename,
                        root + "LDPlayer*/*/" + filename,
                        root + "Program Files/LDPlayer*/*/" + filename,
                        root + "Program Files (x86)/LDPlayer*/*/" + filename):
            found.update(glob.glob(pattern))
    return sorted(found, key=lambda p: (-_ld_version(p), p))


def find_adb():
    """Order: environment variable, PATH, newest LDPlayer install."""
    env = os.environ.get("DGUP_ADB")
    if env and os.path.exists(env):
        return env
    from shutil import which

    if which("adb"):
        return "adb"
    installs = ld_installs("adb.exe")
    if installs:
        return installs[0]
    for path in ADB_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class AdbCapture:
    # False on WindowCapture: whether this class drives the real cursor.
    # AdbCapture never does, input goes to the device instead.
    moves_mouse = False

    def __init__(self, adb=None, serial=None):
        self.adb = adb or find_adb() or "adb"
        serial = serial or os.environ.get("DGUP_SERIAL")
        self.serial = serial
        # DGUP_SCREENCAP pins a method outright. Failing that, a cached
        # measurement from a previous run (see open_adb, which is what
        # writes it) is trusted over guessing. "png" is only the fallback
        # for a machine that has never been measured, since it was always
        # the safe default before this had a benchmark at all.
        self.method = (os.environ.get("DGUP_SCREENCAP")
                       or userdata.cached_screencap_method() or "png")

    def _cmd(self, *args):
        base = [self.adb]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    def devices(self):
        out = noconsole.run(
            self._cmd("devices"), capture_output=True, text=True, timeout=15
        ).stdout
        return [
            line.split("\t")[0]
            for line in out.splitlines()[1:]
            if line.strip().endswith("device")
        ]

    # PNG is encoded on the device and costs time. Raw is usually faster but
    # larger to transfer. Which is faster depends on the system, so it is
    # measured.
    RAW_HEADER_SIZES = (12, 16)  # older and newer Android versions

    def grab(self):
        """One frame, with one reconnect attempt if the first try fails.

        An emulator restart or a stale TCP connection can take ADB down
        mid-run. There used to be a window frame underneath to fall back on;
        without it a `CaptureError` here means the run stops, so it is worth
        one retry -- reread the device list, pick a serial that is actually
        on it, wait a moment for the connection to settle -- before that
        happens. A second failure is not retried again and propagates: no
        wait-and-retry loop, and no silent fall back to the window. The
        caller shows capture.require_adb()'s message and the run stops.
        """
        try:
            return self._grab_once()
        except CaptureError:
            try:
                devices = self.devices()
            except Exception:
                devices = []
            if devices and self.serial not in devices:
                self.serial = devices[0]
            time.sleep(1.0)
            return self._grab_once()

    def _grab_once(self):
        if self.method == "raw":
            try:
                return self._grab_raw()
            except Exception as err:
                self.method = "png"
                print("raw frame failed (%s), falling back to PNG" % err)
        return self._grab_png()

    def _grab_raw(self):
        res = noconsole.run(
            self._cmd("exec-out", "screencap"), capture_output=True, timeout=20)
        buf = res.stdout
        if not buf:
            raise CaptureError("raw screencap empty")
        for head in self.RAW_HEADER_SIZES:
            w, h, fmt = struct.unpack("<III", buf[:12])
            if 0 < w < 10000 and 0 < h < 10000 and len(buf) - head == w * h * 4:
                arr = np.frombuffer(buf[head:], np.uint8).reshape(h, w, 4)
                return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
        raise CaptureError("raw format not recognised, %d bytes" % len(buf))

    def _grab_png(self):
        res = noconsole.run(
            self._cmd("exec-out", "screencap", "-p"), capture_output=True, timeout=20
        )
        if not res.stdout:
            hint = (res.stderr or b"").decode(errors="replace").strip()
            raise CaptureError(
                "ADB screencap empty from %s%s. The device is listed but returns no "
                "frame. Usually a stale TCP connection."
                % (self.serial or "default device", ", ADB says: " + hint if hint else ""))
        img = cv2.imdecode(np.frombuffer(res.stdout, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise CaptureError("ADB screencap could not be decoded")
        return img

    def benchmark(self, rounds=3):
        """Measure both methods and keep the faster one."""
        timings = {}
        for method in ("raw", "png"):
            self.method = method
            try:
                t0 = time.time()
                for _ in range(rounds):
                    self.grab()
                timings[method] = (time.time() - t0) / rounds
            except Exception:
                continue
        if not timings:
            self.method = "png"
            return timings
        self.method = min(timings, key=timings.get)
        return timings

    def works(self):
        """Real test. A device only counts as usable if a screenshot arrives.
        The device list alone lies, stale TCP connections still show up in
        it and yield nothing."""
        try:
            img = self.grab()
            return img is not None and img.shape[0] > 200
        except Exception:
            return False

    def tap(self, x, y):
        noconsole.run(self._cmd("shell", "input", "tap", str(int(x)), str(int(y))),
                      timeout=15)

    def swipe(self, x1, y1, x2, y2, ms=300):
        noconsole.run(self._cmd("shell", "input", "swipe", str(int(x1)),
                                str(int(y1)), str(int(x2)), str(int(y2)), str(ms)),
                      capture_output=True, timeout=20)

    def back(self):
        noconsole.run(self._cmd("shell", "input", "keyevent", "4"),
                      capture_output=True, timeout=15)
        return True

    def focus(self):
        return True


class WindowCapture:
    """Frames and input exclusively via the window, without ADB.

    Frames come from screen capture, fast (measured 9 ms against roughly
    400 ms for ADB) but not free of it: mss photographs the screen
    rectangle where the window sits, not the window itself. A window
    visible but unfocused is captured correctly, that is the case this
    mode lives on. A window obscured by another one returns that other
    window's picture instead; a minimised window returns black, and
    `_window` below refuses it outright rather than trust that; night
    light or any colour profile tints every frame, and every threshold in
    dungeon.py is a threshold on colour. Input goes through the mouse
    instead of ADB.

    The price for all of that: the mouse is blocked during the run and the
    window must be visible, unobscured and in the foreground. It also
    computes in window coordinates, not device coordinates. Anyone using
    relative positions notices none of that.

    This class used to stamp a `last_bot_move` timestamp on every cursor
    move it made, so that guard.py could tell its own clicks apart from a
    human grabbing the mouse. That watcher is gone -- see guard.py -- and
    with it the stamp.
    """

    moves_mouse = True

    def __init__(self, title_contains="LDPlayer"):
        import mss  # noqa
        import pygetwindow as gw  # noqa

        self.mss = __import__("mss").mss()
        self.gw = __import__("pygetwindow")
        self.title = title_contains
        self._input = None

    # ------------------------------------------------------------------
    def _window(self):
        for win in self.gw.getAllWindows():
            if self.title.lower() in (win.title or "").lower() and win.width > 200:
                return win
        raise CaptureError("no emulator window with title %r" % self.title)

    def geometry(self):
        win = self._window()
        return win.left, win.top, win.width, win.height

    def grab(self):
        left, top, width, height = self.geometry()
        box = {"left": left, "top": top, "width": width, "height": height}
        shot = np.array(self.mss.grab(box))
        return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)

    def obscured(self):
        """Is another window drawn over the emulator's rectangle?

        This reads the screen where the window sits, not the window itself,
        so whatever is in front of it is what comes back -- a browser, this
        program's own window, anything. A bot that a player starts and then
        watches never meets that; a helper that runs all day while the same
        player works on the same screen meets it constantly, and the frame
        it gets is a picture of something else entirely.

        Asked at five points rather than one: a window covering a corner is
        already enough to hide the counter or the button.

        True, False, or None when it cannot be told -- no Windows API, or a
        window that has gone away between two calls. None is not False:
        callers must not report a covered window on a guess.
        """
        try:
            import ctypes
            from ctypes import wintypes
            win = self._window()
            hwnd = int(getattr(win, "_hWnd", 0) or 0)
            if not hwnd:
                return None
            user32 = ctypes.windll.user32
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            left, top, width, height = self.geometry()
            spots = ((0.5, 0.5), (0.25, 0.25), (0.75, 0.25),
                     (0.25, 0.75), (0.75, 0.75))
            for fx, fy in spots:
                point = wintypes.POINT(int(left + fx * width),
                                       int(top + fy * height))
                at = user32.WindowFromPoint(point)
                if not at:
                    continue
                if int(user32.GetAncestor(at, 2) or 0) != hwnd:   # GA_ROOT
                    return True
            return False
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _pi(self):
        """Load pydirectinput lazily. It sends input at a lower level than
        pyautogui and is recognised more reliably by emulators."""
        if self._input is None:
            import pydirectinput
            pydirectinput.FAILSAFE = False
            pydirectinput.PAUSE = 0.0
            self._input = pydirectinput
        return self._input

    def focus(self):
        """Bring the window to the front. Without focus, clicks go nowhere
        or hit the wrong window."""
        try:
            win = self._window()
            if not win.isActive:
                win.activate()
                time.sleep(0.15)
            return True
        except Exception:
            return False

    def _abs(self, x, y):
        left, top, _, _ = self.geometry()
        return int(left + x), int(top + y)

    def tap(self, x, y):
        pi = self._pi()
        ax, ay = self._abs(x, y)
        self.focus()
        pi.moveTo(ax, ay)
        time.sleep(0.04)
        pi.click()
        time.sleep(0.04)

    def swipe(self, x1, y1, x2, y2, ms=300):
        """Swipe as a held-down mouse with intermediate steps.

        A jump from A to B is not recognised by the game as a swipe, it
        needs actual motion. So it moves in steps instead.
        """
        pi = self._pi()
        self.focus()
        ax1, ay1 = self._abs(x1, y1)
        ax2, ay2 = self._abs(x2, y2)
        steps = max(8, int(ms / 25))
        pi.moveTo(ax1, ay1)
        time.sleep(0.05)
        pi.mouseDown()
        for i in range(1, steps + 1):
            t = i / float(steps)
            pi.moveTo(int(ax1 + (ax2 - ax1) * t), int(ay1 + (ay2 - ay1) * t))
            time.sleep(ms / 1000.0 / steps)
        time.sleep(0.08)
        pi.mouseUp()
        time.sleep(0.1)

    def back(self):
        """Back without ADB.

        LDPlayer maps the Android back key to Escape by default. Should that
        be bound differently for you, it can be checked in the emulator's
        keyboard settings.
        """
        pi = self._pi()
        self.focus()
        pi.press("esc")
        time.sleep(0.15)
        return True

    @property
    def method(self):
        return "window"

    @method.setter
    def method(self, value):
        pass


def _pick_device(cap):
    """Serial of a device that actually returns a frame.

    The device list alone is not enough evidence, a stale TCP connection
    still shows up on it. `works()` is the real test, one per candidate,
    the preferred serial first if it is on the list at all.
    """
    try:
        devices = cap.devices()
    except Exception:
        devices = []
    order = ([cap.serial] if cap.serial in devices else []) + \
            [d for d in devices if d != cap.serial]
    if cap.serial and cap.serial not in devices:
        print("preferred device %s is not in the list %s" % (cap.serial, devices))
        order = devices
    for serial in order:
        cap.serial = serial
        if cap.works():
            return serial, devices
        print("device %s returns no frame, skipping" % serial)
    raise _adb_not_answering(cap.adb, devices)


def _adb_not_answering(adb_path, devices):
    return CaptureError(
        "Helpermon is set to read the screen through ADB, and ADB is not "
        "answering.\n\n"
        "In LDPlayer: Settings, Other settings, ADB debugging -> on. "
        "LDPlayer switches it off again between sessions, so it is worth "
        "checking whenever a run stops here.\n\n"
        "adb.exe found at: %s\n"
        "Devices it lists: %s\n\n"
        "You can also turn ADB off with the switch at the top of the "
        "window. The bot then reads the emulator window and drives your "
        "real mouse, and the window has to stay visible and in front."
        % (adb_path, ", ".join(devices) if devices else "none"))


def _no_adb_found():
    return CaptureError(
        "Helpermon is set to read the screen through ADB, and no adb.exe "
        "was found on this machine.\n\n"
        "In LDPlayer: Settings, Other settings, ADB debugging -> on. "
        "LDPlayer switches it off again between sessions, so it is worth "
        "checking whenever a run stops here.\n\n"
        "Point to adb.exe with the DGUP_ADB environment variable if it is "
        "installed somewhere this search does not look.\n\n"
        "You can also turn ADB off with the switch at the top of the "
        "window. The bot then reads the emulator window and drives your "
        "real mouse, and the window has to stay visible and in front.")


def _ensure_method_measured(cap):
    """Benchmark raw against png once per machine, and cache the winner.

    Skipped once DGUP_SCREENCAP or a previous run's cache already answers
    the question -- benchmarking costs several frames, and repeating that
    on every process start would tax exactly the run it is meant to speed
    up (see PLAN_ADB_ONLY.md, not shipped publicly).
    """
    if os.environ.get("DGUP_SCREENCAP") or userdata.cached_screencap_method():
        return
    timings = cap.benchmark()
    if timings:
        userdata.set_cached_screencap_method(cap.method)


def open_adb(adb=None, serial=None, **kwargs):
    """Frames and clicks both via ADB.

    Raises CaptureError, with the message every caller should show, if no
    adb.exe can be found or no device it lists returns a frame. No fall
    back to the window here -- that decision belongs to open_for, not to
    this function silently making it.
    """
    path = adb or find_adb()
    if not path:
        raise _no_adb_found()
    cap = AdbCapture(adb=path, serial=serial)
    chosen, devices = _pick_device(cap)
    if len(devices) > 1:
        print("ADB via %s, device %s (chosen from %s, pin it with DGUP_SERIAL)"
              % (cap.adb, chosen, devices))
    else:
        print("ADB via %s, device %s" % (cap.adb, chosen))
    _ensure_method_measured(cap)
    return cap


def require_adb():
    """Raise CaptureError, with the message every caller should show,
    unless ADB actually answers right now.

    Called from the switch (widgets.AdbSwitch), from every start button,
    from the setup wizard, from the passive helper and from every CLI
    main -- the one place that formulates the message, so it reads the
    same wherever a run can stop here.
    """
    open_adb()


def _find_emulator_window(title_contains="LDPlayer"):
    """First window that is credibly the emulator.

    Named after an emulator: believed. LDPlayer's own window is landscape
    when maximised, because its home screen is, and only the game inside it
    is portrait -- so demanding a portrait window here threw away the
    emulator itself.

    Named only after the game: has to have the shape of a phone screen.
    Those titles are matched by substring and "DIGI" finds a browser tab
    about the game, which is how the launcher once reported an emulator at
    976x739 with LDPlayer shut. What was rejected is collected and reported,
    because "not found" while a window plainly matched is the confusing case.
    """
    rejected = []
    wanted = [title_contains] + [t for t in EMULATOR_TITLES
                                 if t.lower() != title_contains.lower()]
    for title in wanted + list(GAME_TITLES):
        try:
            win = WindowCapture(title_contains=title)
            img = win.grab()
        except Exception:
            continue
        if img is None or getattr(img, "size", 0) == 0:
            continue
        h, w = img.shape[:2]
        try:
            process = window_process(win._window())
        except Exception:
            process = ""
        if is_emulator_process(process):
            return win, rejected
        if process:
            # The program is known and is not an emulator. That is a real
            # answer, not a doubt to resolve by shape.
            rejected.append("%r belongs to %s" % (title, process))
            continue
        # No answer from the system: fall back to the shape, which is all
        # there was before.
        if not looks_like_emulator(img):
            rejected.append("%r is %dx%d, not the shape of a phone screen"
                            % (title, w, h))
            continue
        return win, rejected
    return None, rejected


def _no_window_error(rejected):
    text = ("no emulator window found. Is LDPlayer running and the window "
            "visible, meaning not minimised?")
    if rejected:
        text += (" Windows matching the name but not the shape of a phone "
                 "screen were ignored: %s." % ", ".join(sorted(set(rejected))))
    return CaptureError(text)


def open_window(title_contains="LDPlayer", **kwargs):
    """Pure window mode, without ADB. Frames via screen capture, input via
    mouse and keyboard."""
    win, rejected = _find_emulator_window(title_contains)
    if win is None:
        raise _no_window_error(rejected)
    print("window mode active, input via mouse. The window has to stay visible.")
    return win


def open_for(adb, title_contains="LDPlayer", **kwargs):
    """Chooses one of the two operating modes. What every caller uses.

    `adb` is the stored switch (userdata.adb_mode()), a decision already
    made, not a preference to weigh against anything else: with the switch
    on, ADB is required, and a failure is reported through CaptureError
    rather than quietly swapped for the window. That silent fall back is
    exactly what this module used to do and what PLAN_ADB_ONLY.md set out
    to remove.
    """
    if adb:
        return open_adb(**{k: v for k, v in kwargs.items() if k in ("adb", "serial")})
    return open_window(title_contains=title_contains,
                       **{k: v for k, v in kwargs.items() if k not in ("adb", "serial")})
