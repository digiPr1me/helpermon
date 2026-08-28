r"""
Start child processes without a black console window flashing on screen.

The desktop shortcut points at `pythonw.exe`, which has no console of its
own -- that is the whole reason it is used. Windows then gives every
console program *it* starts a brand new console window, because there is
none to inherit, and a program that runs for 200 ms gets a window that
lives for 200 ms. Helpermon runs `adb.exe` several times a second, one
call per frame and one per tap, so the effect is not a flash but a
flicker for as long as a bot is running. It happens on every machine
started from the shortcut; it is not one player's setup.

`CREATE_NO_WINDOW` is the flag that says "no console for this child". The
output is unaffected -- it is read through pipes here anyway -- and on a
run started from a terminal nothing changes either: the child simply does
not open a second window.

So: nothing in Helpermon calls `subprocess.run` or `subprocess.Popen`
directly any more, it goes through here. test_noconsole.py reads the
source of every module and fails on a call site that does not, because
the one that slips through is invisible until somebody watches the
screen for the rest of a run.
"""

import os
import subprocess

# Documented as CREATE_NO_WINDOW in the Windows process-creation flags.
# Written out rather than taken from `subprocess`, where it only exists on
# Windows and only since 3.7.
CREATE_NO_WINDOW = 0x08000000


def _hidden(kw):
    """The caller's keyword arguments plus the flag, on Windows only."""
    if os.name != "nt":
        return kw
    kw = dict(kw)
    kw["creationflags"] = kw.get("creationflags", 0) | CREATE_NO_WINDOW
    return kw


def run(cmd, **kw):
    """`subprocess.run`, without the console window."""
    return subprocess.run(cmd, **_hidden(kw))


def popen(cmd, **kw):
    """`subprocess.Popen`, without the console window."""
    return subprocess.Popen(cmd, **_hidden(kw))
