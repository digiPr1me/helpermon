"""
Start LDPlayer and open the game.

LDPlayer ships `ldconsole.exe` for this, in the same folder as the ADB we
already look for. That covers the cold start.

  list instances     list2
  is it running      isrunning --index N
  start              launch --index N
  start the app      launchex --index N --packagename P
  quit               quit --index N

Deliberately not included: navigating the menus from the title screen into the
minigame. Those are daily rewards, event banners and shifting buttons, the most
fragile part and the one that changes with every game update. Instead the bot
waits until the board is recognisable and then takes over.

  py ldplayer.py                    show instances
  py ldplayer.py --start            start the emulator and wait
  py ldplayer.py --start --app      also open the game
  py ldplayer.py --quit
"""

import argparse
import glob
import os
import re
import time

import noconsole

# Fallback locations for ldconsole.exe, same idea as the ADB search in
# capture.py. Only a fallback: capture.ld_installs finds the newest install
# by version, which these fixed paths cannot express.
CONSOLE_CANDIDATES = [
    r"C:\LDPlayer\LDPlayer9\ldconsole.exe",
    r"C:\LDPlayer\LDPlayer64\ldconsole.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\ldconsole.exe",
    r"C:\Program Files (x86)\LDPlayer\LDPlayer9\ldconsole.exe",
    r"D:\LDPlayer\LDPlayer9\ldconsole.exe",
]

# How the game package is recognised when no package name was given
PACKAGE_HINTS = ("digimon", "bandai", "bnei", "namco")

# How long an emulator that was just told to start gets to produce an ADB
# device before the window is accepted instead. A freshly launched LDPlayer
# lists no device for the first several seconds, so anything shorter turns
# "still booting" into "this machine has no ADB".
WINDOW_GRACE = 45.0


class LdError(RuntimeError):
    pass


def find_console():
    """Order: environment variable, newest install, next to the found ADB,
    fixed fallback locations.

    The newest install comes first on purpose. A machine that has had two
    versions installed keeps both folders, and driving the old one is how
    "Start LDPlayer" ended up launching version 9 on a machine using 14.
    """
    env = os.environ.get("DGUP_LDCONSOLE")
    if env and os.path.exists(env):
        return env

    try:
        import capture
        installs = capture.ld_installs("ldconsole.exe")
        if installs:
            return installs[0]
        # ADB sits in the same folder, so look there too
        adb = capture.find_adb()
        if adb and adb != "adb":
            guess = os.path.join(os.path.dirname(adb), "ldconsole.exe")
            if os.path.exists(guess):
                return guess
    except Exception:
        pass

    for path in CONSOLE_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class LdPlayer:
    def __init__(self, console=None, log=print):
        self.console = console or find_console()
        self.log = log
        if not self.console:
            raise LdError(
                "ldconsole.exe nicht gefunden. Pfad setzen mit\n"
                '  $env:DGUP_LDCONSOLE = "C:\\LDPlayer\\LDPlayer9\\ldconsole.exe"')

    # ------------------------------------------------------------------
    def _run(self, *args, timeout=60):
        res = noconsole.run([self.console] + list(args), capture_output=True,
                            timeout=timeout)
        # ldconsole liefert je nach Version cp1252 oder utf-8, deshalb tolerant
        out = (res.stdout or b"").decode("utf-8", errors="replace")
        return out.strip()

    def instances(self):
        """Liste der Instanzen. list2 gibt Komma getrennte Felder, das erste ist
        der Index, das zweite der Name, das fuenfte der Laufstatus."""
        out = self._run("list2")
        rows = []
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) < 2 or not parts[0].strip().isdigit():
                continue
            running = None
            if len(parts) >= 5:
                running = parts[4].strip() not in ("0", "")
            rows.append({"index": int(parts[0]), "name": parts[1],
                         "running": running})
        return rows

    def is_running(self, index=0):
        out = self._run("isrunning", "--index", str(index)).lower()
        if "running" in out and "not" not in out:
            return True
        if "stop" in out or "not" in out:
            return False
        # manche Versionen antworten nur ueber list2
        for inst in self.instances():
            if inst["index"] == index and inst["running"] is not None:
                return inst["running"]
        return False

    def launch(self, index=0):
        self._run("launch", "--index", str(index), timeout=120)

    def quit(self, index=0):
        self._run("quit", "--index", str(index), timeout=120)

    def launch_app(self, index=0, package=None):
        package = package or self.find_package(index)
        if not package:
            raise LdError("game package not found. Provide it with --package.")
        self._run("launchex", "--index", str(index), "--packagename", package,
                  timeout=120)
        return package

    # ------------------------------------------------------------------
    def find_package(self, index=0):
        """The game's package name. Needs ADB.

        There is no way to find it without ADB. Then it has to be given
        through DGUP_PACKAGE, or the game started by hand.
        """
        env = os.environ.get("DGUP_PACKAGE")
        if env:
            return env
        import capture
        cap = capture.AdbCapture()
        for serial in cap.devices():
            cap.serial = serial
            out = noconsole.run(
                cap._cmd("shell", "pm", "list", "packages"),
                capture_output=True, timeout=30).stdout.decode(
                    "utf-8", errors="replace")
            names = [line.split(":", 1)[1].strip()
                     for line in out.splitlines() if ":" in line]
            for hint in PACKAGE_HINTS:
                for name in names:
                    if hint in name.lower():
                        return name
        return None

    # ------------------------------------------------------------------
    def launcher_activity(self, package):
        """The activity a home-screen tap on this package would open.

        Asked of the system rather than guessed: the game's entry point is
        `com.google.firebase.MessagingUnityPlayerActivity`, a name no
        amount of reasoning about the package would have produced.
        """
        import capture
        cap = capture.AdbCapture()
        out = noconsole.run(
            cap._cmd("shell", "cmd", "package", "resolve-activity",
                     "--brief", package),
            capture_output=True, timeout=30).stdout.decode(
                "utf-8", errors="replace")
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith(package + "/"):
                return line
        return None

    def start_app_via_adb(self, package):
        """Start the game by its package name, through ADB alone.

        Needs no ldconsole, and so works on an emulator that ships none.

        `am start` on the activity the system itself resolves, because
        `monkey` -- the obvious tool for "launch this package" -- is simply
        not on the device any more: LDPlayer 14 runs Android 14 and answers
        `monkey: inaccessible or not found`, exit 127. That failure was
        invisible for a whole run, because this function used to throw the
        output away and the caller then spent 60 s waiting for a game
        nothing had started. Hence both the change and the checking: the
        result of a command whose success is confirmed a minute later has
        to be read at the moment it comes back.

        `monkey` stays as the second attempt for a device that has it and
        no `cmd package`.
        """
        import capture
        cap = capture.AdbCapture()
        activity = self.launcher_activity(package)
        tried = []
        if activity:
            res = noconsole.run(cap._cmd("shell", "am", "start", "-n", activity),
                                capture_output=True, timeout=30)
            out = ((res.stdout or b"") + (res.stderr or b"")).decode(
                "utf-8", errors="replace").strip()
            # "Activity not started, intent has been delivered to currently
            # running top-most instance" is success: the game was already
            # in front. "Error:" is not.
            if res.returncode == 0 and "Error" not in out:
                self.log("started %s" % activity)
                return activity
            tried.append("am start: %s" % (out or "exit %d" % res.returncode))
        else:
            tried.append("the system could not resolve a launcher activity "
                         "for %s" % package)

        res = noconsole.run(cap._cmd("shell", "monkey", "-p", package, "-c",
                                     "android.intent.category.LAUNCHER", "1"),
                            capture_output=True, timeout=30)
        out = ((res.stdout or b"") + (res.stderr or b"")).decode(
            "utf-8", errors="replace").strip()
        if res.returncode == 0 and "No activities found" not in out:
            self.log("started %s through monkey" % package)
            return package
        tried.append("monkey: %s" % (out or "exit %d" % res.returncode))
        raise LdError("could not start %s through ADB. %s"
                      % (package, "; ".join(tried)))

    def foreground_package(self):
        """Package name of whichever app has focus right now, or None.

        Read from the window manager rather than guessed from pixel
        movement: `dumpsys window` says which app is in front, which is
        better evidence than "nothing is moving, so it must be up" ever
        was -- that read a bare emulator home screen as the finished game
        once already.
        """
        import capture
        cap = capture.AdbCapture()
        try:
            out = noconsole.run(
                cap._cmd("shell", "dumpsys", "window"),
                capture_output=True, timeout=20).stdout.decode(
                    "utf-8", errors="replace")
        except Exception:
            return None
        for line in out.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                m = re.search(r"([A-Za-z][\w.]*)/[\w.$]+", line)
                if m:
                    return m.group(1)
        return None

    def wait_for_app(self, package, timeout=60, poll=1.5):
        """Wait until `package` is the foreground app.

        Returns the package name actually in front when it gives up, which
        may not be `package` -- the caller decides what a mismatch means,
        this only reports it rather than turning it into True/False and
        losing the name of whatever is in front instead.
        """
        started = time.time()
        deadline = started + timeout
        front = None
        said = 0.0
        while time.time() < deadline:
            front = self.foreground_package()
            if front == package:
                return front
            # A game loading for a minute and a game that was never started
            # look identical from outside, and the first run to hit this
            # spent 60 s silent before saying so. Name what is in front
            # while waiting, so the log tells the two apart as it happens.
            waited = time.time() - started
            if waited - said >= 10:
                said = waited
                self.log("waiting for %s, %s is in front, %d s of %d"
                         % (package, front or "nothing", waited, timeout))
            time.sleep(poll)
        return front

    # ------------------------------------------------------------------
    def wait_ready(self, index=0, timeout=180, poll=2.0, window_ok=True):
        """Wartet, bis Android hochgefahren ist und ADB ein Bild liefert.

        Zwei Bedingungen, weil die eine ohne die andere nichts wert ist. Ein
        Geraet kann in der Liste stehen und trotzdem kein Bild liefern, das
        hatten wir bei einer alten TCP Verbindung schon.
        """
        import capture
        started = time.time()
        deadline = started + timeout
        cap = capture.AdbCapture()
        said = 0.0
        while time.time() < deadline:
            for serial in cap.devices():
                cap.serial = serial
                booted = noconsole.run(
                    cap._cmd("shell", "getprop", "sys.boot_completed"),
                    capture_output=True, timeout=20).stdout.decode(
                        "utf-8", errors="replace").strip()
                if booted.startswith("1") and cap.works():
                    self.log("emulator ready, device %s" % serial)
                    return serial
            waited = time.time() - started
            # The window is the answer only for a machine where ADB is not
            # coming at all, and that is not the same question as "is it
            # here yet". Asked once at the top, one second after `launch`,
            # it was always "no": an emulator that had just been told to
            # start has no device yet, and the whole cold start was
            # abandoned on a reading taken before the thing it measures
            # could possibly exist. So the device gets WINDOW_GRACE before
            # the window is even considered.
            if window_ok and waited >= WINDOW_GRACE:
                try:
                    win = capture.open_window()
                    if win.grab() is not None:
                        self.log("no ADB device after %d s, but the window is "
                                 "there" % waited)
                        return "window"
                except Exception:
                    pass
            # Silence for three minutes looks like a hang. Say something
            # every ten seconds, with the number that matters.
            if waited - said >= 10:
                said = waited
                self.log("waiting for the emulator, %d s of %d"
                         % (waited, timeout))
            time.sleep(poll)
        raise LdError(
            "no ADB device after %d s. The emulator may still be starting, "
            "or ADB debugging is off: LDPlayer, Settings, Other settings, "
            "ADB debugging." % timeout)

    def ensure_running(self, index=0, package=None, start_app=True,
                       timeout=180):
        """Kaltstart. Startet den Emulator falls noetig, wartet, oeffnet das
        Spiel. Rueckgabe ist die ADB Kennung der Instanz."""
        if not self.is_running(index):
            self.log("starting LDPlayer instance %d" % index)
            self.launch(index)
        else:
            self.log("LDPlayer instance %d is already running" % index)
        serial = self.wait_ready(index, timeout=timeout)
        # Whether the game itself came up is a separate question from whether
        # the emulator did, and the caller has to be able to tell: without
        # ADB this fails quietly and leaves the emulator on its home screen,
        # where a bot must not start tapping.
        self.app_started = False
        if start_app:
            try:
                pkg = self.launch_app(index, package)
                self.log("game started, %s" % pkg)
                self.app_started = True
            except LdError as err:
                self.log("game not started: %s" % err)
        return serial


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--app", action="store_true", help="dazu das Spiel oeffnen")
    ap.add_argument("--quit", action="store_true")
    ap.add_argument("--package")
    args = ap.parse_args()

    ld = LdPlayer()
    print("ldconsole: %s" % ld.console)
    for inst in ld.instances():
        print("  Instanz %d  %-24s laeuft %s"
              % (inst["index"], inst["name"], inst["running"]))

    if args.quit:
        ld.quit(args.index)
        print("instance %d stopped" % args.index)
        return
    if args.start:
        serial = ld.ensure_running(args.index, package=args.package,
                                   start_app=args.app)
        print("ready, device %s" % serial)
        print('Fuer den Bot festnageln mit\n  $env:DGUP_SERIAL = "%s"' % serial)


if __name__ == "__main__":
    main()
