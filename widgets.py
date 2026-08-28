"""
Tk pieces that more than one window needs.

One switch: the global "use ADB" switch that picks capture.open_adb or
capture.open_window for every bot at once (see userdata.adb_mode and
capture.open_for). It is here rather than in `capture.py` because capture
has to stay importable by a bot running in a console with no display, and
rather than in `app.py` because more than one window shows it.

It belongs on windows where a bot runs and nowhere else. The setup wizard
reads whichever source the switch already says, so a control for it there
would be a control for something that is not happening in front of you.

There used to be a second switch beside it, for the mouse-movement pause.
It went from every window first -- a checkbox offering to switch off the one
thing that got your hand out from under a running bot was an invitation, not
a setting -- and then the pause itself went too, because under ADB the bot
never drives the mouse and the pause was firing at people using their own
machine. Nothing watches the cursor any more, so there is nothing here to
switch. See guard.py.
"""

import time
import tkinter as tk
from tkinter import messagebox

import userdata

# How often the switch re-reads the flag. The launcher, the minigame window
# and a bot started from a console are separate processes, so a switch
# flipped in one has to show up in the others without a restart. A second is
# far below noticing and costs one file check.
POLL_MS = 1000

# The clock in front of a log line. Hours, minutes and seconds only: the
# date would be twenty characters in front of every line of a window that
# already wraps, and it is not lost -- a run writes it in its opening line,
# and a feedback report carries the full date in its header, which is what
# a log tail read days later is actually attached to.
STAMP = "%H:%M:%S"


def stamp_lines(text, when=None):
    """Split one block written to a log into (stamp, line) pairs.

    Pairs rather than one finished string, because the two carry different
    tags: a warning line is red, and a clock that turned red along with it
    would read as part of the warning rather than as the time it happened.

    Every line with something on it gets its own stamp, the inner lines of
    a multi-line summary included, so searching the log for a time finds
    them too. An empty line keeps its emptiness: it is there to separate
    two blocks, and a line holding nothing but a clock separates nothing.
    """
    clock = time.strftime(STAMP, time.localtime(when)) + "  "
    return [(clock if line.strip() else "", line)
            for line in text.split("\n")]


ADB_LABEL = "Use ADB for screen and clicks"
ADB_NOTE = ("Off: Helpermon reads the window instead and drives your real "
           "mouse. The window then has to stay visible and in front.")


class AdbSwitch(tk.Frame):
    """On/off for the global ADB switch, for the top row of a window where
    a bot runs. It stands for both frames and clicks together -- see
    userdata.adb_mode.

    No `adb devices` in the poll: that would start a subprocess every
    second just to keep three windows in sync. The poll only rereads the
    flag file; whether ADB actually answers is checked at the moment the
    switch is flipped and again wherever a run starts, which is what
    capture.require_adb is for.

    Turning it on is checked immediately, before the flag is written: a
    switch that shows "on" while ADB cannot be reached is worse than no
    switch. On failure it stays off and shows why.
    """

    def __init__(self, parent, bg=None, **kwargs):
        bg = bg or parent.cget("bg")
        tk.Frame.__init__(self, parent, bg=bg, **kwargs)
        self.var = tk.BooleanVar(value=userdata.adb_mode())
        self.button = tk.Checkbutton(
            self, text=ADB_LABEL, variable=self.var, bg=bg, activebackground=bg,
            font=("Segoe UI", 9), command=self._toggle)
        self.button.pack(anchor="w")
        tk.Label(self, text=ADB_NOTE, bg=bg, fg="#777", font=("Segoe UI", 8),
                 wraplength=260, justify="left").pack(anchor="w")
        self._poll()

    def _toggle(self):
        want = self.var.get()
        if want:
            import capture
            try:
                capture.require_adb()
            except capture.CaptureError as err:
                self.var.set(False)
                messagebox.showwarning("ADB", str(err))
                return
        self.var.set(userdata.set_adb_mode(want))

    def _poll(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        now = userdata.adb_mode()
        if now != self.var.get():
            self.var.set(now)
        self.after(POLL_MS, self._poll)
