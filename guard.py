"""
Shared run control for every bot: pause, resume, abort.

One implementation instead of each bot inventing its own pause handling.
Two ways to trigger a pause, both landing on the same flag:

  - a bot's own console key (space), handled by the bot itself
  - a global hotkey (default F7), works even when the emulator window has
    focus instead of the console, because it hooks the keyboard driver
    directly instead of reading console input

**There used to be a third, and it is gone: moving the real mouse paused
the bot by itself.** It was written for the mode where the bot drives the
real cursor, where a person reaching for their mouse and a bot clicking
with it is a conflict the bot has to lose -- but it watched the cursor in
every mode, and ADB is the default now. There the bot never puts a hand on
the mouse, so every movement is somebody using their own machine, and a
run spent more time paused than playing: "mouse moved, pausing" between
two dungeon attempts, then three seconds of stillness demanded before it
went on. The window switch for it had already been taken out, so there was
nothing left anywhere that could turn it off either.

Nothing watches the cursor any more. `cursor_pos` stays because the passive
helper asks where the mouse is before it taps, which is a question about
one tap and not a pause holding up a whole run.

Needs the `keyboard` package for the global hotkeys. It is optional at
runtime: without it, they quietly do nothing instead of crashing a bot that
only cares about its own console keys.
"""

import time

try:
    import keyboard
except ImportError:
    keyboard = None


def cursor_pos():
    """Current physical mouse position on screen, or None if it cannot be
    read (only Windows is supported)."""
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    except Exception:
        return None


class Stop:
    """Abort and pause signal. Checked before every action.

    The two belong together because both are checked at the same point,
    between two actions and never in the middle of one. Otherwise a click
    could be sent but never verified, and the bookkeeping would drift out of
    sync with what actually happened on screen.
    """

    def __init__(self):
        self._set = False
        self._paused = False
        self.reason = ""

    # abort
    def request(self, reason="abort requested"):
        self.reason = reason
        self._set = True

    def clear(self):
        self._set = False
        self._paused = False
        self.reason = ""

    def is_set(self):
        return self._set

    # pause
    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def toggle_pause(self):
        self._paused = not self._paused
        return self._paused

    def is_paused(self):
        return self._paused

    def wait_while_paused(self, emit=None, tick=0.15):
        """Blocks while paused. Returns (go_on, was_paused).

        was_paused tells the caller whether it actually waited, so it can
        re-read the screen afterwards. During the pause, a human may have
        moved the figure, or the mouse, themselves.
        """
        if not self._paused:
            return True, False
        if emit:
            emit({"art": "info", "text": "paused"})
        while self._paused and not self._set:
            time.sleep(tick)
        if self._set:
            return False, True
        if emit:
            emit({"art": "info", "text": "resuming, re-reading"})
        return True, True


class RunControl:
    """Global pause and abort hotkeys, layered on top of a Stop.

    F7 toggles the pause, F8 aborts, both hooked into the keyboard driver so
    they answer while the emulator window has focus rather than the console.
    A hotkey pause needs an explicit resume: it is somebody deciding to
    stop, so nothing lifts it on its own.
    """

    def __init__(self, control, hotkey="f7", abort_key="f8", log=print):
        self.control = control
        self.hotkey = hotkey
        self.abort_key = abort_key
        self.log = log

    def start(self):
        self._register_hotkeys()

    def stop(self):
        if keyboard is not None:
            try:
                keyboard.remove_hotkey(self.hotkey)
                keyboard.remove_hotkey(self.abort_key)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _register_hotkeys(self):
        if keyboard is None:
            # Not "pip install keyboard": the packages live in the .venv
            # install.bat builds, and a pip typed into a terminal is a
            # different Python that this one never sees.
            self.log("'keyboard' package missing, no global hotkey. "
                     "Run install.bat again to repair the installation.")
            return
        try:
            keyboard.add_hotkey(self.hotkey, self._on_hotkey_pause)
            keyboard.add_hotkey(self.abort_key, self._on_hotkey_abort)
            self.log("Keys: %s pauses/resumes, %s aborts, work even without "
                     "focus on this console" % (self.hotkey, self.abort_key))
        except Exception as err:
            self.log("global hotkeys not available (%s). If the emulator "
                     "runs as administrator, this script has to as well, "
                     "or neither of them does. Windows lets no ordinary "
                     "program reach an elevated window." % err)

    def _on_hotkey_pause(self):
        paused = self.control.toggle_pause()
        self.log("    %s (hotkey %s)"
                 % ("paused" if paused else "resumed", self.hotkey))

    def _on_hotkey_abort(self):
        self.control.request("hotkey %s" % self.abort_key)
        self.log("    abort requested (hotkey %s)" % self.abort_key)


def start(control, log=print, **kwargs):
    """Create and start a RunControl in one call."""
    rc = RunControl(control, log=log, **kwargs)
    rc.start()
    return rc
