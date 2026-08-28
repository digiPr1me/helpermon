"""
Helpermon, the launcher for all three bots. One entry point for new users.

  py app.py

Layout, and why it is this one:

  +---------------------------------------------------------------+
  |  emulator state            [Start LDPlayer]  [Check again]    |   header
  +-----------+---------------------------------------------------+
  | Helpermon |                                                   |
  |           |                                                   |
  | Dungeons  |   the selected section                            |   sidebar
  | Minigame  |                                                   |   + content
  |           |                                                   |
  | Setup     |                                                   |
  | About     |                                                   |
  +-----------+---------------------------------------------------+
  |  status                                                       |
  +---------------------------------------------------------------+

One navigation, not two. The previous version had tabs across the top AND a
card per bot in the middle, which is the same list of destinations offered
twice -- and neither of them said what to do first.

Anything that is not about one particular bot lives in the header, where it is
reachable from every page. Starting the emulator was buried in the minigame
window before, although all three bots need it.

The sidebar is ordered the way a new user should meet things: Helpermon, then
the bots with the one that needs no setup first, then setup and legal.
"""

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

import feedback
import guard
import noconsole
import unlock
import userdata
import widgets
from version import VERSION

GITHUB_ISSUES = "https://github.com/digiPrime000/helpermon/issues/new/choose"

HERE = os.path.dirname(os.path.abspath(__file__))
_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
STATE_FILE = os.path.join(_APPDATA, "helpermon.json")
# What the file was called before the program was named. Read once if the new
# one is not there yet, so renaming the program does not silently throw away
# everyone's settings.
OLD_STATE_FILE = os.path.join(_APPDATA, "digibot_app.json")

# One entry per bot, in the order a new user should meet them: the one that
# needs no setup first, so there is something to run before anything is
# learned. `step` names the wizard step that makes this bot runnable.
# `name` is what the game calls it, `short` is what fits in the sidebar.
BOTS = [
    {"key": "dungeon", "name": "Dungeons", "short": "Dungeons",
     # It needs no images to play. The game icon is only what tells the
     # emulator's home screen from the game, which is why this bot stays
     # "ready" without it.
     "colour": "#3b6fd4", "step": "Game icon",
     "why": ("Spends your daily dungeon attempts and watches the ads for the "
             "extra tickets, so a day's rewards are collected without you "
             "sitting through them. Nothing has to be taught first, so this "
             "is the one to try first."),
     "what": "Works through the dungeon list and uses ad tickets"},
    {"key": "mini", "name": "Digital World Search", "short": "World Search",
     "colour": "#7a4fd4", "step": "Counters",
     "why": ("Walks the board collecting tickets, paws, claws and fireballs "
             "and keeps going as long as the paws last."),
     "what": "Collects power-ups and runs to the right"},
]

# Bots with a page of their own but no place in BOTS: they need nothing
# taught, so there is no wizard step to send them to and no readiness dot
# to show for them. test_launcher.py checks that every BOTS entry has a
# matching setup_wizard.BOT_STEPS entry and a "step" it opens on -- true
# for the three above, and never true for one of these, so they stay out
# of the list itself rather than growing a step that does not exist. The
# passive helper set this pattern; _bot_by_key below is what lets the
# rest of the page machinery (_first_run_notice, feedback) treat them the
# same as a BOTS entry regardless.
EXTRA_BOTS = {
    "summon": {"key": "summon", "name": "Special Summon", "short": "Summon",
              "why": ("Spends Skill Card, Support Digimon and Crest Summon "
                      "tickets on the biggest draw available, watching the "
                      "two free ads in each mode first, so a stash of "
                      "tickets does not just sit there unspent."),
              "what": "Spends Skill, Support and Crest summon tickets on "
                      "the biggest draw"},
    # It set the pattern above and was then the one page left out of it:
    # its switch goes through the same gate as a Start button, the gate
    # asked `_bot_by_key` who it was working for, and the answer was the
    # fall back to Dungeons -- so the notice in front of the helper was
    # titled after another bot and then died on a missing REQUIREMENTS
    # entry, half drawn, with the grab still on it.
    "passive": {"key": "passive", "name": "Bond & Auto Spend",
                "short": "Bond & Auto Spend",
                "why": ("Collects the bond token from your partner and "
                        "keeps Auto Spend for Hologram Tickets running, "
                        "for as long as Helpermon is open."),
                "what": "Collects the bond token and keeps Auto Spend "
                        "running"},
    # The other half of that same page, and the one entry here with no page
    # of its own: the quest loop shares the passive helper's page and its
    # thread. It still needs a key, because a key is what the gate, the
    # requirements notice and the report menu all speak -- and it needs its
    # own rather than riding on "passive" because it is a supporter feature
    # and the free half beside it is not.
    "quest": {"key": "quest", "name": "Quest loop", "short": "Quest loop",
              "why": ("Works through the game's own row of repeating "
                      "quests: claims each one the moment it is done, and "
                      "plays the dungeon and summon steps itself where you "
                      "let it."),
              "what": "Works through the game's row of repeating quests"},
}

def needs_setup_button(bot):
    """Whether this bot's page offers the way into the wizard.

    Both halves have cost a bug, so both are here rather than in the widget
    that draws the button.

    Not the dungeon bot: its step is the game icon, which is what tells the
    emulator's home screen from the game and not something the bot itself
    needs. Its own requirements box says "nothing has to be taught", and a
    button offering to teach it something anyway contradicts that sentence.

    Not a bot without a step either. `_setup_for` reads `bot["step"]` to
    say which wizard page to open on, and the EXTRA_BOTS -- Summon, the
    passive helper, the quest loop -- have none, because there is no wizard
    page for them to be sent to. Summon's page carried the button anyway
    and it would have died of KeyError on the press; nobody found out,
    because nothing renders a page in the suites and the button is one
    nobody needs.
    """
    return bot["key"] != "dungeon" and bool(bot.get("step"))


# Which pages are supporter features, and the only place that decides it.
# A bot becomes paid or free by a line here and nothing else in the window
# has to know -- but see `_may_run`: the gate is one function, and a key put
# in this set whose start path does not go through it would be locked in the
# table and open in fact. test_unlock.py checks that for every key here.
#
# The Special Summon bot and the quest loop, because they are the two
# newest and neither has ever shipped free. Taking a bot back off people
# who already had it is a different and much worse thing than asking for
# the next one -- which is also why the lock is on "quest" and not on
# "passive": the bond token and Auto Spend share that page, they shipped
# free, and they stay free.
SUPPORTER_ONLY = {"summon", "quest"}

SUPPORTER_TITLE = "Early access for supporters"
SUPPORTER_WHY = (
    "Helpermon is free and open source, and the skills that were here before "
    "stay that way. This one requires a code (for now), which you can get with a donation on Ko-fi. "
    )
SUPPORTER_HOW = (
    "Once your donation is received, I will send you the code via the email address you provided on Ko-fi. "
    "The donations help support the time and effort that goes into developing the next bot. "
    "Its valid for a lifetime.")
SUPPORTER_THANKS = "Supporter code active! Thank you for your support <3"
# The third state, and the one nobody thinks of: a code that was redeemed
# here and is no longer in the list. That is what a revoked code looks like
# from the inside, and without a line of its own it looks like the program
# forgetting -- which is the one reading that sends somebody to donate a
# second time.
SUPPORTER_STALE = (
    "The code on this machine, %s, is not accepted by this version any "
    "more. If that is a surprise, write to me before paying again \u2014 "
    "it is usually a code that turned up shared in public.")

def feedback_parts():
    """What the report dialog's "What is this about?" menu offers, as
    (label, key) pairs -- the key being the bot the label names, or None
    where the label is not a bot at all.

    Out here rather than inside the dialog, and built from both bot tables
    rather than from BOTS alone, because that is exactly how the two newest
    pages came to be missing from the menu with nothing able to notice: a
    report about Special Summon or the quest loop could only be filed under
    another bot's name, and then it carried that other bot's log. Reachable
    from a test now, without a display.
    """
    parts = [(bot["name"], bot["key"]) for bot in BOTS]
    parts += [(bot["name"], bot["key"]) for bot in EXTRA_BOTS.values()]
    # The rest of the program a report can be about. The supporter code is
    # named because it belongs to no page: it is a dialog in front of one
    # bot, a code that will not take is nothing to do with that bot, and it
    # is the one problem whose answer can only come from the person reading
    # these reports.
    parts += [(label, None) for label in
              ("The Helpermon window itself", "Setup / the wizard",
               "Supporter code")]
    return parts


DEFAULT_NOTES = {
    "dungeon": ("Opened here because the game's icon is what lets "
                "Helpermon tell the emulator's home screen from the game "
                "itself. The dungeon skill needs nothing from this wizard."),
    "mini": ("Opened here because the Digital World Search bot still needs "
             "its images. Work through this step and the three after it."),
}

# The passive helper: how long to wait after it could not reach the emulator,
# and how many lines its log keeps. It runs all day, so both matter.
PASSIVE_RETRY = 30
PASSIVE_LOG_LINES = 4000

# How long a Start button waits for a quest-loop action to let go of the
# emulator before starting anyway (PLAN_QUEST_LOOP.md 6). The sub-bot's own
# control is aborted immediately; this is only the time its own finally
# block needs to walk back to the main screen.
QUEST_YIELD = 8.0

# How long the game gets to become the app in front after ADB has been told
# to start it. Generous, because this is a Unity game booting on a cold
# emulator, and because the cost of being wrong is one-sided: waiting too
# long only wastes a minute of a run that is meant to last hours, while
# giving up too early stops the run outright. The wait says every ten
# seconds what it is looking at, so a stuck one is visible.
APP_FRONT_TIMEOUT = 180

# What has to be true before a bot can do anything.
#
# Kept in one place and shown in two: on the bot's own page, where it cannot
# be missed, and in a dialog the first time that bot is started. A
# requirement that lives only in a README is a requirement nobody meets, and
# every one of these is something that makes the bot do nothing at all if it
# is not so -- the World Search waiting for a board nobody opened, Special
# Summon looking for a button on a screen that never shows it.
REQUIREMENTS = {
    "dungeon": [
        "Digimon UP has to be on the stage battle screen.",
        "After the skill is done or you press Stop it returns to the home screen.",
    ],
    "mini": [
        "Digimon UP has to be on the stage battle screen.",
        "After the skill is done or you press Stop it returns to the home screen.",
        "All digimon skins should work. Use Botamon skin, if something doesn't work.",
    ],
    "summon": [
        "Digimon UP has to be open, on the stage battle screen.",
        "After the skill is done or you press Stop it returns to the home screen.",
    ],
    "passive": [
        "This skill is supposed to be always on. It activates only while on the stage battle screen and then does its thing. If you are on any other screen, it does nothing at all, so it "
        "costs nothing to leave switched on.",
    ],
    "quest": [
        "Digimon UP has to be on the stage battle screen. This skill "
        "reads the quest card there and completes it. It does nothing on any other screen.",
    ],
}

# True for every bot, so it is said once rather than three times.
INPUT_REQUIREMENT = [
    "With ADB, taps go to the emulator directly and your mouse stays yours.",
    "Without ADB the bot uses your real mouse. Leave it alone while the bot "
    "runs: every move of yours goes into the game as well. F7 pauses it "
    "when you want your machine back, F8 stops it.",
    "Without ADB the emulator window also has to stay visible, in front and "
    "uncovered, and the screen must not go to sleep. Screen capture returns "
    "the last picture that was drawn, and a bot reading that clicks at what "
    "was there minutes ago.",
]

ADB_TITLE = "First: how Helpermon reaches the emulator"

ADB_NOTICE = (
    "There are two ways, and the first one is better.\n\n"
    "1. Through ADB. Helpermon sends its taps straight to the emulator. Your\n"
    "   mouse stays yours, and the emulator window may sit behind other\n"
    "   windows while a bot works.\n\n"
    "   You have to switch it on first: in LDPlayer, Settings, Other\n"
    "   settings, ADB debugging. Then press 'Check ADB now' below - that\n"
    "   asks the emulator rather than guessing.\n\n"
    "   One thing to know: LDPlayer itself puts up an error when a lot is\n"
    "   driven through ADB in one sitting. That is the emulator complaining,\n"
    "   not the game. Restart the emulator, or put that bot on mouse input\n"
    "   for the rest of the session.\n\n"
    "2. Through your mouse. If ADB is off or unavailable, the bot moves the\n"
    "   real cursor. Then leave the mouse alone while a bot runs, because\n"
    "   the two of you are sharing it -- press F7 when you want it back,\n"
    "   F8 to stop the bot. The emulator window has to stay visible and\n"
    "   in front, and the screen must not go to sleep."
)

HOTKEY_HINT = ("F7 pauses and resumes, F8 stops - both work with any window in front.")

# The header thumbs ask a question rather than announcing a feature, the
# way the run page's bar does, and their buttons answer that question.
# "Feedback: Good / Bad" left the reader to work out what Good referred to.
# Short on purpose: it sits in the middle column of the header, between the
# emulator line and the ADB switch, where there is not much room.
HEADER_FEEDBACK = "Everything working?"

FAN_TITLE = "An unofficial fan project"

# First, before anything else that is read. Somebody meeting this program for
# the first time should not have to work out from the tone whether it comes
# from the people who made the game.
FAN_NOTICE = (
    "Helpermon is a fan project. It is not made, endorsed, sponsored or\n"
    "supported by Bandai Namco, Bandai, Toei Animation, or anyone else\n"
    "involved in Digimon UP.\n\n"
    "Digimon and every name, character and image belonging to the game are\n"
    "the property of their owners. Nothing from the game is shipped with this\n"
    "program; what the bots need, they learn from your own screen."
)

LEGAL_NOTICE = (
    "Helpermon automates Digimon UP, running in an emulator software.\n\n"
    "The publisher's terms of service explicitly prohibit the use of bots,\n"
    "emulators and similar tools in section 11 g. Anyone using it risks having\n"
    "their game account suspended.\n\n"
    "This software is provided without warranty. The decision to use it, and\n"
    "the consequences of doing so, are yours."
)

# Not offered in this build. The daily dungeon changes what it is from day
# to day, and nothing has been measured against enough of its faces to let a
# bot loose on it. It keeps its place in the list the bot counts against.
HIDDEN_DUNGEONS = {"Daily changing dungeon"}

# What one day hands out per dungeon: two tickets from the daily reset and
# two more for watching ads. What an individual box starts at, on a first
# run or for a dungeon the tick-box version had checked.
DAY_ATTEMPTS = 4

# "Set all" starts at its own number, not DAY_ATTEMPTS. The two are allowed
# to differ; asked for explicitly, not a rounding of the constant above.
SET_ALL_DEFAULT = 5

BG = "#f4f5f7"
NAV_BG = "#e8eaed"
NAV_ACTIVE = "#ffffff"
# Wide enough for the longest sidebar label drawn in bold, which is what
# the selected page is drawn in: "Bond & Quest Loop" measures 150 there,
# padding included. Measure a new name against this before adding it -- a
# label with nowhere to go is simply cut off at the edge.
NAV_WIDTH = 170

# The Skills heading, and the only thing in the sidebar with a colour. It
# used to be a readiness dot on every skill row instead.
NAV_HEADING = "#0c0c0d"


class _StopHolder:
    """The minigame bot is a loop, not an object, so there is nothing to hold
    its Stop. Pause and Stop reach every bot through `.control`, and this
    gives the loop the same shape as the other two."""

    def __init__(self):
        self.control = guard.Stop()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Helpermon " + VERSION)
        # Big enough that the longest page -- Dungeons, controls and log --
        # is there on the first look. A window that opened with the log
        # below the edge meant nobody saw the log until they scrolled, and
        # the log is where the bot says what it is doing. Clamped to what
        # the screen actually has, so a short laptop display does not get a
        # window taller than its desktop.
        self.geometry("%dx%d" % (min(980, self.winfo_screenwidth() - 40),
                                 min(950, self.winfo_screenheight() - 90)))
        self.minsize(880, 560)
        self.state_data = self._load()
        # capture.find_adb() checks this environment variable before it
        # checks anything else, so a path picked on the Helpermon
        # page has to land here before the first thing that might go
        # looking for adb.exe.
        adb_path = self.state_data.get("adb_path")
        if adb_path:
            os.environ["DGUP_ADB"] = adb_path
        self.events = queue.Queue()
        self.worker = None
        self.stop = None
        self.vars = {}
        # One entry per bot that runs in this window: its start buttons, its
        # pause and stop buttons, and its own log. Only one bot runs at a
        # time, and `active` names whose buttons the event pump talks to.
        self.panels = {}
        self.active = None
        # The passive helper runs beside the bots rather than as one of
        # them, so it has its own thread, its own stop flag and its own log.
        self.passive_thread = None
        self.passive_stop = None
        self.passive_bot = None
        self.passive_log = None
        # The quest loop rides the same thread as the passive helper
        # (PLAN_QUEST_LOOP.md 6): quest_loop is the object, quest_busy is
        # set for as long as it owns the emulator to play a dungeon or
        # summon step, and _bot_running() answers yes while either a
        # worker thread or this flag is alive -- one gate, checked
        # everywhere a bot's ownership of the emulator matters.
        self.quest_loop = None
        self.quest_busy = threading.Event()
        # Which of the two switches on that page have been through
        # `_may_run` while they have been on. Not "is the thread up": they
        # share one thread and no longer share one answer, now that the
        # quest loop is a supporter feature and the bond token is not.
        self._gated = set()
        self.run_started = None
        self.emulator_ok = None  # None = not checked yet
        # Declared before the header is built: the header sets the emulator
        # state, which asks the start page to refresh, and tkinter turns a
        # missing attribute into a baffling error about the Tk object.
        self.pages = {}
        self.current_page = None
        # Every supporter banner on every page, so that redeeming a
        # code in one dialog updates all of them at once.
        self.supporter_boxes = []

        self._build_header()
        self._build_body()
        self._build_statusbar()

        self._build_pages()
        self.show_page("home")
        # Passive by name and by nature: no button starts it, the switch on
        # its page does, and if that switch was on when the window last
        # closed it is on again now. Either switch: the quest loop rides the
        # same thread, and a window that started it only for `passive_on`
        # left the loop switched on and not running.
        if self.state_data.get("quest_on") and not unlock.unlocked():
            # A code that has been revoked, or settings carried over from a
            # machine that had one. Off, and said so on the page, rather
            # than a switch reading "on" beside a loop that will not run.
            self.state_data["quest_on"] = False
            var = self.vars.get("quest_on")
            if var is not None:
                var.set(False)
            self._save()
        if self.state_data.get("passive_on") or self.state_data.get("quest_on"):
            self._start_passive()

        self.bind_all("<MouseWheel>", self._on_wheel)

        self.after(80, self._pump)
        self.after(150, self._first_run_dialogs)
        self.after(400, self.check_emulator)

    # ==================================================================
    # Frame of the window: header, sidebar, content, status bar
    # ==================================================================
    def _build_header(self):
        head = tk.Frame(self, bg="#ffffff", padx=14, pady=10)
        head.pack(fill="x")
        tk.Frame(self, height=1, bg="#d0d3d8").pack(fill="x")

        # Three columns, not pack's left and right. The thumbs in the
        # middle are meant to sit on the centre line of the window, and pack
        # can only centre them in whatever space the other two leave over --
        # which is some 40 px off centre here, because the ADB switch is
        # wider than the emulator line. The two edge columns share a uniform
        # group, so they are given the same width whatever they hold, and
        # the middle one then lands where it should.
        head.columnconfigure(0, weight=1, uniform="edge")
        head.columnconfigure(2, weight=1, uniform="edge")

        left = tk.Frame(head, bg="#ffffff")
        left.grid(row=0, column=0, sticky="w")
        self.emu_dot = tk.Canvas(left, width=12, height=12, bg="#ffffff",
                                 highlightthickness=0)
        self.emu_dot.pack(side="left", padx=(0, 8))
        # Wrapped, because this line has no fixed width: "start failed"
        # carries 60 characters of the error with it. Unwrapped, it would
        # widen its column, take the same width from the ADB switch through
        # the uniform group, and squeeze the thumbs between them.
        self.emu_label = tk.Label(left, text="Emulator: not checked yet",
                                  bg="#ffffff", font=("Segoe UI", 10),
                                  wraplength=250, justify="left")
        self.emu_label.pack(side="left")
        self._set_emulator(None, "Emulator: not checked yet")

        # The header reports, it does not act. Both emulator buttons live on
        # the emulator row of the Helpermon page -- a row
        # of buttons repeated on every page competes with whatever that page
        # is actually for.
        #
        # Two exceptions, in the top row. The ADB switch is not about a
        # page or a bot, it is about whether the machine is yours or the
        # bot's for the next hour, and it is wanted at the moment a bot has
        # just grabbed the mouse -- which is the worst possible moment to go
        # looking for it on some other page. It used to be three checkboxes
        # repeated on three pages, one global switch here is what those
        # three were always trying to be.
        #
        # The second is feedback. The thumbs on a bot's page are shown by
        # _maybe_ask_feedback, which means after a run that lasted a minute
        # and at most once a day -- the right moment to be asked, and the
        # wrong one to be able to answer: somebody who wants to say now that
        # this is going badly should not have to finish a run first or go
        # looking for the Feedback page. These two are here whatever page is
        # open and whatever is running, and they send the same report every
        # other route sends.
        widgets.AdbSwitch(head, bg="#ffffff").grid(row=0, column=2,
                                                   sticky="e")

        thumbs = tk.Frame(head, bg="#ffffff")
        thumbs.grid(row=0, column=1, padx=20)
        self.header_fb_label = tk.Label(thumbs, text=HEADER_FEEDBACK,
                                        bg="#ffffff", fg="#5f6368",
                                        font=("Segoe UI", 9))
        self.header_fb_label.pack(side="left", padx=(0, 6))
        self.header_fb_buttons = []
        for label, thumb in (("Yes", "up"), ("No", "down")):
            button = tk.Button(thumbs, text=label, width=6,
                               font=("Segoe UI", 9),
                               command=lambda t=thumb: self._header_thumb(t))
            button.pack(side="left", padx=(0, 4))
            self.header_fb_buttons.append(button)

    def _build_body(self):
        body = tk.Frame(self)
        body.pack(fill="both", expand=True)

        self.nav = tk.Frame(body, bg=NAV_BG, width=NAV_WIDTH)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)

        self.content = tk.Frame(body, bg=BG, padx=18, pady=16)
        self.content.pack(side="left", fill="both", expand=True)

        self.nav_buttons = {}
        self._nav_entry("home", "Helpermon")
        # The heading carries the colour now. There used to be a readiness
        # dot beside every skill, which said "ready" four times over and
        # nothing else -- three of the four can never say anything but
        # ready, and the fourth says it again on its own page, in words,
        # in the blue panel by the setup button.
        self._nav_heading("Skills", fg=NAV_HEADING)
        for bot in BOTS:
            self._nav_entry(bot["key"], bot["short"])
        self._nav_entry("summon", "Summon")
        self._nav_entry("passive", "Bond & Quest Loop")
        self._nav_heading("")
        # No Setup entry. Setting a bot up is part of that bot, and it is
        # reached from that bot's own page. One shared Setup page was how
        # people ended up in the wrong bot's steps.
        self._nav_entry("feedback", "Feedback")
        self._nav_entry("about", "About")

    def _nav_heading(self, text, fg="#70757c"):
        tk.Label(self.nav, text=text.upper(), bg=NAV_BG, fg=fg,
                 font=("Segoe UI", 8, "bold"), anchor="w", padx=14
                 ).pack(fill="x", pady=(14, 2))

    def _nav_entry(self, key, label):
        row = tk.Frame(self.nav, bg=NAV_BG)
        row.pack(fill="x")
        button = tk.Button(row, text=label, bg=NAV_BG, relief="flat", bd=0,
                           anchor="w", padx=14, pady=7, font=("Segoe UI", 10),
                           activebackground="#dcdfe3",
                           command=lambda k=key: self.show_page(k))
        button.pack(side="left", fill="x", expand=True)
        self.nav_buttons[key] = button

    def _build_statusbar(self):
        tk.Frame(self, height=1, bg="#d0d3d8").pack(fill="x")
        self.status = tk.Label(self, text="ready", anchor="w", fg="#555",
                               padx=14, pady=4, justify="left")
        self.status.pack(fill="x")
        # Wrap to whatever width the window currently is, so a long message
        # neither runs off the edge nor makes the window grow.
        self.status.bind(
            "<Configure>",
            lambda e: self.status.configure(wraplength=max(200, e.width - 28)))

    # ------------------------------------------------------------------
    # Scrolling
    # ------------------------------------------------------------------
    def _scrollable(self, parent):
        """A page taller than the window has to stay reachable.

        On a short window the dungeon page ran off the bottom edge and its
        log could not be seen at all. Every page is built inside one of
        these: while the content fits it behaves exactly like the plain
        frame it replaced, and it grows a scrollbar the moment it does not.
        """
        host = tk.Frame(parent, bg=BG)
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        canvas = tk.Canvas(host, bg=BG, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        bar = tk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.grid(row=0, column=1, sticky="ns")
        inner = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        shown = {"bar": True}

        def fit(_event=None):
            view = canvas.winfo_height()
            needed = inner.winfo_reqheight()
            height = max(needed, view)
            # While it fits, the inner frame is stretched to the full height
            # of the view, so whatever is packed with expand=True -- the log
            # -- still fills the page as it did before there was a canvas in
            # the way.
            canvas.itemconfigure(window, width=canvas.winfo_width(),
                                 height=height)
            canvas.configure(scrollregion=(0, 0, 0, height))
            wanted = needed > view
            if wanted != shown["bar"]:
                shown["bar"] = wanted
                if wanted:
                    bar.grid()
                else:
                    canvas.yview_moveto(0)
                    bar.grid_remove()

        inner.bind("<Configure>", fit)
        canvas.bind("<Configure>", fit)
        inner.scroll_host = host
        inner.scroll_canvas = canvas
        inner.scroll_fit = fit
        return inner

    @staticmethod
    def _host(frame):
        """The widget a page is packed by: its scroll host if it has one."""
        return getattr(frame, "scroll_host", frame)

    def _on_wheel(self, event):
        """Scroll the page under the pointer -- unless that is something
        which scrolls itself. A bot's log is a Text with its own wheel
        binding, and without this check one turn of the wheel moved both."""
        widget = event.widget
        while widget is not None:
            if isinstance(widget, (tk.Text, tk.Listbox)):
                return
            widget = getattr(widget, "master", None)
        page = self.pages.get(self.current_page)
        canvas = getattr(page["frame"], "scroll_canvas", None) if page else None
        if canvas is not None:
            canvas.yview_scroll(int(-event.delta / 120), "units")

    # ------------------------------------------------------------------
    def show_page(self, key):
        for name, page in self.pages.items():
            self._host(page["frame"]).pack_forget()
            self.nav_buttons[name].configure(
                bg=NAV_BG, font=("Segoe UI", 10))
        page = self.pages[key]
        self._host(page["frame"]).pack(fill="both", expand=True)
        self.nav_buttons[key].configure(bg=NAV_ACTIVE,
                                        font=("Segoe UI", 10, "bold"))
        self.current_page = key
        # Setup happens in another window, so anything showing state has to
        # re-read it on the way in rather than trust what it found at launch.
        if page.get("refresh"):
            page["refresh"]()

    # ==================================================================
    # State everything else reads
    # ==================================================================
    def bot_states(self):
        """Per bot: is it runnable, and one line saying why or why not."""
        out = {b["key"]: {"ready": True, "detail": ""} for b in BOTS}
        # Summon and the passive helper need nothing taught, so they are
        # always ready -- same reasoning as the dungeon bot below, just
        # without an icon to check.
        for key in EXTRA_BOTS:
            out[key] = {"ready": True, "detail": "Needs no setup."}
        # The dungeon bot plays without a single learned image, so it stays
        # ready either way. The icon only decides whether the emulator check
        # in the header can tell the home screen from the game.
        try:
            import launcher
            out["dungeon"]["icon"] = bool(launcher.have_icon())
        except Exception:
            out["dungeon"]["icon"] = False
        out["dungeon"]["detail"] = (
            "Needs no setup. The game icon is learned, so Helpermon can tell "
            "the emulator's home screen from the game."
            if out["dungeon"]["icon"] else
            "Needs no setup to play. The game icon is optional.")
        try:
            import learning
            st = learning.status()
        except Exception as err:
            out["mini"].update(ready=False,
                               detail="Cannot read state: %s" % err)
            out["test_mode"] = False
            return out

        missing, digits = len(st["missing"]), len(st["ziffern_fehlen"])
        out["mini"]["ready"] = st["fertig"]
        out["mini"]["detail"] = (
            "Ready" if st["fertig"]
            else "%d image%s and %d digit%s missing"
                 % (missing, "" if missing == 1 else "s",
                    digits, "" if digits == 1 else "s"))
        out["test_mode"] = learning.only_learned()
        out["folder"] = st["ort"]
        return out

    # ==================================================================
    # Emulator, the one thing every bot depends on
    # ==================================================================
    def _set_emulator(self, ok, text):
        """ok True = ready, "idle" = emulator up but the game is not,
        False = nothing found, None = not looked yet."""
        self.emulator_ok = ok
        colour = {True: "#1a7f37", "idle": "#c98a00",
                  False: "#b3261e", None: "#9aa0a6"}[ok]
        self.emu_dot.delete("all")
        self.emu_dot.create_oval(1, 1, 11, 11, fill=colour, outline="")
        self.emu_label.configure(text=text)
        self._refresh_home()

    def _refresh_home(self):
        home = self.pages.get("home")
        if home and home.get("refresh"):
            home["refresh"]()

    def check_emulator(self):
        self.status.configure(text="looking for the emulator window")

        def job():
            # The header says what, the status bar says why. The capture
            # error is a paragraph long and ran off both the header and the
            # window when it was put in either.
            #
            # The window is still what answers "is the emulator running" --
            # a window search is the one check that needs no ADB and works
            # whichever way the switch is set. Once it is found, the actual
            # picture to look at comes from the configured source, so this
            # reports what a bot would actually see, ADB and all.
            import capture
            try:
                capture.open_window()
            except Exception as err:
                self.events.put(("emu_bad", "Emulator: not found"))
                self.events.put(("status", str(err)))
                return

            source = "ADB" if userdata.adb_mode() else "window"
            try:
                img = capture.open_for(userdata.adb_mode()).grab()
            except Exception as err:
                self.events.put(("emu_bad",
                                 "Emulator: window found, %s not answering" % source))
                self.events.put(("status", str(err)))
                return
            size = "%d x %d" % (img.shape[1], img.shape[0])
            # Emulator up and game not open are different problems. The
            # learned icon settles it: if it is on screen, we are looking at
            # the emulator's home screen.
            try:
                import launcher
                found = launcher.find_icon(img) if launcher.have_icon() else None
            except Exception:
                found = None
            if found and found["ok"]:
                self.events.put(("emu_idle",
                                 "Emulator: running, game not open"))
                self.events.put(("status", "Emulator %s (%s), showing its home "
                                 "screen. The game icon is visible at %d,%d."
                                 % (size, source, found["x"], found["y"])))
            else:
                self.events.put(("emu_ok", "Emulator: found, %s (%s)" % (size, source)))

        threading.Thread(target=job, daemon=True).start()

    def start_emulator(self):
        """Cold start, the same one engine.cold_start does for the minigame,
        but reachable from anywhere instead of only from that bot."""
        self.status.configure(text="starting LDPlayer, this takes a while")

        def job():
            try:
                import ldplayer
                ld = ldplayer.LdPlayer(
                    log=lambda t: self.events.put(("status", t)))
                serial = ld.ensure_running(0)
                os.environ["DGUP_SERIAL"] = serial
                self.events.put(("status", "emulator up, device %s" % serial))
            except Exception as err:
                self.events.put(("emu_bad", "Emulator: start failed (%s)"
                                 % str(err)[:60]))
                return
            self.events.put(("recheck", ""))

        threading.Thread(target=job, daemon=True).start()

    # ==================================================================
    # Pages
    # ==================================================================
    def _build_pages(self):
        self.pages["home"] = self._page_home()
        self.pages["dungeon"] = self._page_dungeon()
        self.pages["mini"] = self._page_mini()
        self.pages["summon"] = self._page_summon()
        self.pages["passive"] = self._page_passive()
        self.pages["feedback"] = self._page_feedback()
        self.pages["about"] = self._page_about()

    def _page_frame(self, title, subtitle=""):
        """Heading, then what this is for.

        There used to be a third, grey line under that saying how the bot
        goes about it -- which buttons it recognises by colour, which
        images it needs. It is gone from every page: what a player decides
        anything by is on the two lines above it and in the yellow box
        below, and a paragraph of workings in between only pushed the box
        further down the page.
        """
        frame = self._scrollable(self.content)
        tk.Label(frame, text=title, bg=BG, font=("Segoe UI", 17, "bold")
                 ).pack(anchor="w")
        if subtitle:
            tk.Label(frame, text=subtitle, bg=BG, fg="#3c4043", justify="left",
                     wraplength=700, font=("Segoe UI", 10)
                     ).pack(anchor="w", pady=(4, 0))
        return frame

    # The two lines on the Bond & Quest page that say what is happening
    # right now: "watching -- holograms 12,340, ..." and whatever step the
    # quest loop is on. They are the only things on that page that change
    # by themselves -- everything else is a switch that stays where it was
    # put -- so they get a box and a colour of their own rather than
    # sitting among the grey notes under the switches, where a line that
    # had just changed looked exactly like one that never would. Blue, and
    # not the yellow of the requirements box above them: that one says
    # what you have to do, these say what the program is doing.
    STATE_BG = "#e8f0fe"
    STATE_FG = "#1a3d7c"
    STATE_EDGE = "#a8c3f0"

    def _state_box(self, parent, font, pady=(0, 0), side=None, padx=(0, 0),
                   text="off", **kw):
        """A blue panel holding one live status line. Returns the label.

        `side` for the World Search, where the panel shares a line with the
        setup button instead of having one to itself: it takes the width
        the button leaves over rather than the width of the page.
        """
        box = tk.Frame(parent, bg=self.STATE_BG, padx=12, pady=8,
                       highlightbackground=self.STATE_EDGE,
                       highlightthickness=1)
        if side:
            box.pack(side=side, fill="x", expand=True, pady=pady, padx=padx)
        else:
            box.pack(anchor="w", fill="x", pady=pady, padx=padx)
        line = tk.Label(box, bg=self.STATE_BG, fg=self.STATE_FG, text=text,
                        justify="left", anchor="w", font=font, **kw)
        line.pack(anchor="w", fill="x")
        return line

    def _requirements(self, parent, key, title="Before you press Start"):
        """What has to be true before this bot can do anything.

        High on the page and in a colour nothing else on it uses, because
        every line in it is a way for the bot to sit there achieving
        nothing while looking like it is working. The same lines come up
        again in a dialog the first time this bot is started.

        `title` because not everything with requirements has a Start
        button: the passive helper and the quest loop are switches, and a
        heading naming a button that is not on the page sends a player
        looking for it.
        """
        bot = self._bot_by_key(key)
        setup = needs_setup_button(bot)

        box = tk.Frame(parent, bg="#fff8e1", bd=1, relief="solid",
                       padx=14, pady=10)
        # The gap under the box belongs to the button row where there is
        # one, and to the box itself where there is not -- otherwise the
        # page below it starts flush against the yellow.
        box.pack(anchor="w", fill="x", pady=(14, 0 if setup else 10))
        tk.Label(box, text=title, bg="#fff8e1",
                 fg="#7a4b00", anchor="w", font=("Segoe UI", 10, "bold")
                 ).pack(anchor="w")
        for line in REQUIREMENTS[key]:
            tk.Label(box, text="•  " + line, bg="#fff8e1", fg="#5a3a00",
                     anchor="w", justify="left", wraplength=680,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        # The way into setup, directly under the box that says what is still
        # missing and at the same right edge. It used to sit at the very
        # bottom of the page, under the log, which is the furthest point on
        # the page from the line that sends anybody there.
        #
        # Here rather than in each of the three pages: this method is called
        # by all of them and already knows which bot it is drawing for.
        #
        # The row is returned so that a page with a line of its own to show
        # -- "Ready to run.", on the World Search -- can put it on the left
        # of the same line instead of under it. That line and this button
        # answer the same question, and stacked they left a hand's breadth
        # of empty page between the yellow box and the first setting.
        if not setup:
            return None
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x", pady=(6, 0))
        tk.Button(row, width=20, text="Set up this bot",
                  command=lambda b=bot: self._setup_for(b)).pack(side="right")
        return row

    # --- Helpermon -----------------------------------------------------
    def _page_home(self):
        frame = self._page_frame(
            "Helpermon",
            # True whether or not the teaching has happened, because
            # this line is built once and the page is redrawn often.
            )

        # Loud, and above everything else on the page. What follows it was
        # measured against one emulator and one language, and someone
        # running a different pair should learn that before their first run
        # rather than from a bot clicking at the wrong place.
        note = tk.Frame(frame, bg="#fff4e0", padx=14, pady=10,
                        highlightbackground="#e0a24a", highlightthickness=1)
        note.pack(anchor="w", fill="x", pady=(14, 0))
        tk.Label(note, text="What this has been tested with",
                 bg="#fff4e0", fg="#7a4a05", anchor="w",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(note, bg="#fff4e0", fg="#5a3a05", justify="left",
                 font=("Segoe UI", 10),
                 text=("LDPlayer 9 and LDPlayer 14, and Digimon UP in "
                       "English.\n\nAnother emulator may well not work: the "
                       "bots find the game window by name and\nsend their "
                       "clicks into it, and both of those differ from one "
                       "emulator to the next.\nThe game in another language "
                       "is the smaller risk, since the bots read colours\nand "
                       "positions rather than words - but it has not been "
                       "tried.")).pack(anchor="w", pady=(4, 0))

        body = tk.Frame(frame, bg=BG)
        body.pack(anchor="w", fill="x", pady=(16, 0))
        self.home_steps = body

        def refresh():
            for child in body.winfo_children():
                child.destroy()

            emu_done = self.emulator_ok is True
            emu_detail = self.emu_label.cget("text").replace("Emulator: ", "")
            if self.emulator_ok == "idle":
                emu_detail += " - press Start LDPlayer, it opens the game too"

            tk.Label(body, text="Quick setup", bg=BG, anchor="w",
                     font=("Segoe UI", 13, "bold")).pack(anchor="w")

            # Checking belongs on the step that is about the emulator, not
            # only in the header.
            self._step_row(
                body, "Start the emulator and the game", emu_done,
                emu_detail,
                ("Check if running", self.check_emulator),
                None if emu_done else ("Start LDPlayer", self.start_emulator))

            # No tick of its own -- most players need none of this, since
            # the automatic search now covers the registry and every fixed
            # disk. It sits under the emulator row because it is the same
            # concern, reaching the emulator, and it stays visible after
            # setup is done since it is a standing setting rather than
            # something to tick off once.
            self._adb_setting_row(body)

        return {"frame": frame, "refresh": refresh}

    def _adb_setting_row(self, parent):
        """Where adb.exe was found, or a way to point at it by hand.

        The automatic search covers the registry and every fixed disk, and
        finds it without help on most machines. This is what is left for
        the rest: an install somewhere neither of those looks, or a copy of
        adb.exe kept apart from LDPlayer's own folder entirely.
        """
        import capture
        row = tk.Frame(parent, bg="#ffffff", bd=1, relief="solid",
                       padx=14, pady=12)
        row.pack(anchor="w", fill="x", pady=5)

        tk.Label(row, text="adb.exe", bg="#ffffff", anchor="w",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")

        manual = self.state_data.get("adb_path")
        if manual:
            found = os.path.isfile(manual)
            status = manual if found else manual + "  -- not there any more"
            colour = "#1a7f37" if found else "#b3261e"
            prefix = "Set by hand: "
        else:
            auto = capture.find_adb()
            status = auto or "not found"
            colour = "#1a7f37" if auto else "#b3261e"
            prefix = "Found automatically: "

        tk.Label(row, text=prefix + status, bg="#ffffff", fg=colour,
                 anchor="w", wraplength=680, font=("Segoe UI", 9)
                 ).pack(anchor="w", pady=(3, 10))

        buttons = tk.Frame(row, bg="#ffffff")
        buttons.pack(anchor="w")
        tk.Button(buttons, text="Browse for adb.exe...", width=20,
                  command=self._pick_adb_path).pack(side="left")
        tk.Button(buttons, text="Or pick the LDPlayer folder...", width=24,
                  command=self._pick_adb_folder).pack(side="left", padx=(6, 0))
        if manual:
            tk.Button(buttons, text="Use automatic search again", width=22,
                      command=self._clear_adb_path
                      ).pack(side="left", padx=(6, 0))

    def _pick_adb_path(self):
        """Point Helpermon at one specific adb.exe, chosen by hand."""
        path = filedialog.askopenfilename(
            title="Select adb.exe",
            filetypes=[("adb.exe", "adb.exe"), ("Programs", "*.exe"),
                       ("All files", "*.*")])
        if not path:
            return
        if os.path.basename(path).lower() != "adb.exe":
            # Not refused outright, a renamed or custom build is
            # conceivable, but checked with the player first: the probe
            # below runs whatever was picked with the "devices" argument,
            # and a program that is not adb.exe may do anything with that.
            if not messagebox.askyesno(
                    "Not named adb.exe",
                    "%s\n\nis not called adb.exe. Use it anyway?" % path):
                return
        self._set_adb_path(path)

    def _pick_adb_folder(self):
        """Point Helpermon at the LDPlayer folder rather than the file.

        adb.exe sits directly inside it, next to dnplayer.exe, so this is
        mostly the folder-shaped version of the same thing -- easier when
        the player knows where LDPlayer lives but not the exact file.
        """
        folder = filedialog.askdirectory(
            title="Select the LDPlayer install folder")
        if not folder:
            return
        candidate = os.path.join(folder, "adb.exe")
        if not os.path.exists(candidate):
            import glob
            deeper = glob.glob(os.path.join(folder, "*", "adb.exe"))
            candidate = deeper[0] if deeper else None
        if not candidate:
            messagebox.showwarning(
                "No adb.exe found",
                "No adb.exe turned up directly inside\n\n%s\n\n"
                "or one folder below it. Browse for the file itself "
                "instead if you know where it is." % folder)
            return
        self._set_adb_path(candidate)

    def _set_adb_path(self, path):
        self.state_data["adb_path"] = path
        self._save()
        os.environ["DGUP_ADB"] = path
        # Tried immediately rather than left for the player to wonder about:
        # the same probe the ADB dialog uses, so the wording matches
        # whatever they already know from there.
        ok, text = self._adb_probe()
        (messagebox.showinfo if ok else messagebox.showwarning)(
            "adb.exe", text)
        self._refresh_home()

    def _clear_adb_path(self):
        self.state_data.pop("adb_path", None)
        self._save()
        os.environ.pop("DGUP_ADB", None)
        self._refresh_home()

    def _step_row(self, parent, title, done, detail, *actions):
        """One step: where you are, and the buttons that move you on. The
        tick is the whole point -- a new user should be able to see how far
        they have got without reading anything.

        The disc carried a step number while there were three of them to
        keep in order. There is one now, and a lone "1" only invites the
        question of where 2 and 3 went; the grey disc says "not yet" by
        itself and turns into the tick when it is done.
        """
        row = tk.Frame(parent, bg="#ffffff", bd=1, relief="solid",
                       padx=14, pady=12)
        row.pack(anchor="w", fill="x", pady=5)

        mark = tk.Canvas(row, width=30, height=30, bg="#ffffff",
                         highlightthickness=0)
        mark.create_oval(2, 2, 28, 28,
                         fill="#1a7f37" if done else "#c8ccd1", outline="")
        if done:
            mark.create_line(9, 15, 13, 20, 21, 10, fill="white", width=3)
        mark.pack(side="left", padx=(0, 14))

        middle = tk.Frame(row, bg="#ffffff")
        middle.pack(side="left", fill="x", expand=True)
        tk.Label(middle, text=title, bg="#ffffff", anchor="w",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(middle, text=detail, bg="#ffffff", fg="#5f6368", anchor="w",
                 justify="left", font=("Segoe UI", 9)).pack(anchor="w")

        for action in actions:
            if not action:
                continue
            label, command = action
            tk.Button(row, text=label, width=16, command=command
                      ).pack(side="right", padx=(6, 0))

    # --- Dungeons -----------------------------------------------------
    def _page_dungeon(self):
        bot = self._bot_by_key("dungeon")
        frame = self._page_frame(bot["name"], bot["why"])
        import dungeon as D
        self._requirements(frame, "dungeon")

        settings = tk.Frame(frame, bg=BG)
        # No padding above: the row with the setup button already carries
        # its own, and the two together left a hand's breadth of nothing
        # between the yellow box and the first heading.
        settings.pack(anchor="w", fill="x")

        # Both columns carry their own heading, on the same line as each
        # other. Before this the right column started with "Rounds" level
        # with the heading "Which dungeons", which read as if Rounds were
        # one of the dungeons.
        left = tk.Frame(settings, bg=BG)
        left.pack(side="left", anchor="n")
        tk.Label(left, text="How many attempts per dungeon", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")

        # One number that stamps all of them, above the list rather than
        # under it: it is what a player reaches for first, and the single
        # dungeons below are the corrections to it. Deliberately a button
        # rather than a variable the others follow, so that after stamping
        # SET_ALL_DEFAULT on everything you can still put one dungeon back
        # to 0 -- which is the way this actually gets used.
        #
        # A rule under it, because without one the row reads as one of the
        # dungeons: same box, same place, one line apart.
        stamp = tk.Frame(left, bg=BG)
        stamp.pack(anchor="w", fill="x", pady=(6, 0))
        all_var = tk.IntVar(value=SET_ALL_DEFAULT)
        tk.Spinbox(stamp, from_=0, to=99, textvariable=all_var, width=4
                   ).pack(side="left")

        def stamp_all():
            for j, other in enumerate(D.DUNGEON_NAMES):
                if other not in HIDDEN_DUNGEONS:
                    self.vars["dg_%d" % j].set(all_var.get())

        tk.Button(stamp, text="Set all", width=8, command=stamp_all
                  ).pack(side="left", padx=(8, 0))
        tk.Frame(left, bg="#c8ccd1", height=1).pack(fill="x", pady=(8, 6))

        saved = self.state_data.get("attempts", {})
        old_ticks = self.state_data.get("dungeons")
        for i, name in enumerate(D.DUNGEON_NAMES):
            # The hidden ones still get a variable, at 0. The bot counts
            # cards, so the list it plans against has to keep every entry
            # the game shows -- only the control goes away.
            if name in HIDDEN_DUNGEONS:
                start = 0
            elif str(i) in saved:
                start = saved[str(i)]
            elif old_ticks is not None:
                # Coming from the version with tick boxes: a dungeon that
                # was ticked gets a day's worth, one that was not gets zero.
                start = DAY_ATTEMPTS if i in old_ticks else 0
            else:
                start = DAY_ATTEMPTS
            var = tk.IntVar(value=start)
            self.vars["dg_%d" % i] = var
            if name in HIDDEN_DUNGEONS:
                continue
            row = tk.Frame(left, bg=BG)
            row.pack(anchor="w", fill="x", pady=1)
            tk.Spinbox(row, from_=0, to=99, textvariable=var, width=4
                       ).pack(side="left")
            tk.Label(row, text=name, bg=BG, anchor="w").pack(side="left",
                                                             padx=(8, 0))

        right = tk.Frame(settings, bg=BG, padx=28)
        right.pack(side="left", anchor="n")
        tk.Label(right, text="How it runs", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        # No Rounds any more. It asked how often the bot should walk past a
        # dungeon, when what a player knows is how often they want it
        # played. That is the column on the left now, and the bot keeps
        # going round until those numbers are used up.
        self._spin(right, "max_minutes", "Time limit, minutes (0 = none)",
                   0, 0, 600)
        # Not seconds: dungeon.py multiplies every one of its waits by
        # this, so 1 is the pace it was written for.
        self._spin(right, "langsam", "Patience, 1 = normal pace",
                   1.5, 0.5, 4.0, floaty=True)
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    Prevents too fast and therefore wrong "
                       "clicking.\n    Raise if you have a slow computer.")
                 ).pack(anchor="w")
        # Always on, no switch. Reading the ticket counters before opening
        # anything is what keeps the bot from working through dungeons that
        # have nothing left, and there is no reason a player would want it
        # off.
        self.vars["survey"] = tk.BooleanVar(value=True)
        for key, text, default in (
                ("use_ads", "Use ad tickets", True),):
            var = tk.BooleanVar(value=self.state_data.get(key, default))
            self.vars[key] = var
            tk.Checkbutton(right, text=text, variable=var, bg=BG).pack(anchor="w")
            if key == "use_ads":
                tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                         font=("Segoe UI", 8),
                         text=("    Ads are only watched if you have bought "
                               "the ad pass.")).pack(anchor="w")

        self._run_controls(frame, "dungeon",
                           [("Start", lambda: self._start_dungeon(True))],
                           extra=[("Dry run",
                                   lambda: self._start_dungeon(False))])
        return {"frame": frame, "refresh": None}

    # --- Special Summon -------------------------------------------------
    def _page_summon(self):
        bot = self._bot_by_key("summon")
        frame = self._page_frame(bot["name"], bot["why"])
        self._supporter_box(frame, "summon")
        self._requirements(frame, "summon")

        settings = tk.Frame(frame, bg=BG)
        settings.pack(anchor="w", fill="x")

        left = tk.Frame(settings, bg=BG)
        left.pack(side="left", anchor="n")
        tk.Label(left, text="Which modes", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        for key, text, default in (
                ("summon_skill", "Skill Card Summon", True),
                ("summon_support", "Support Digimon Summon", True),
                ("summon_crest", "Crest Summon", True)):
            var = tk.BooleanVar(value=self.state_data.get(key, default))
            self.vars[key] = var
            tk.Checkbutton(left, text=text, variable=var, bg=BG
                           ).pack(anchor="w")

        right = tk.Frame(settings, bg=BG, padx=28)
        right.pack(side="left", anchor="n")
        tk.Label(right, text="How it runs", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        ads_var = tk.BooleanVar(
            value=self.state_data.get("summon_ads", True))
        self.vars["summon_ads"] = ads_var
        tk.Checkbutton(right, text="Watch the free ads first", variable=ads_var,
                       bg=BG).pack(anchor="w")
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    A free ad is a free 15x draw, on top of the "
                       "tickets spent below.")).pack(anchor="w")
        # Short enough to fit _spin's 30-character label column: the longer
        # wording was cut off mid-bracket and read "(0 = unb".
        self._spin(right, "summon_max",
                   "Summons per mode (0 = all)", 0, 0, 500)
        self._spin(right, "summon_patience", "Patience, 1 = normal pace",
                   1.5, 0.5, 4.0, floaty=True)

        self._run_controls(frame, "summon",
                           [("Start", lambda: self._start_summon(True))],
                           extra=[("Dry run",
                                   lambda: self._start_summon(False))])
        return {"frame": frame, "refresh": None}

    def _start_summon(self, real_run):
        if not self._may_run("summon"):
            return
        if self.worker and self.worker.is_alive():
            return
        self._yield_emulator_from_quest()
        import capture
        import summon as S

        enabled = {S.SKILL: bool(self.vars["summon_skill"].get()),
                  S.SUPPORT: bool(self.vars["summon_support"].get()),
                  S.CREST: bool(self.vars["summon_crest"].get())}
        if not any(enabled.values()):
            messagebox.showwarning("Nothing to spend",
                                   "Every mode is switched off.")
            return
        self._save_keys(["summon_skill", "summon_support", "summon_crest",
                         "summon_ads", "summon_max", "summon_patience"])
        self._lock("summon")
        watch_ads = bool(self.vars["summon_ads"].get())
        max_per_mode = int(self.vars["summon_max"].get())
        patience = self.vars["summon_patience"].get()
        self._write("\n%s, modes: %s%s"
                    % ("Start" if real_run else "Dry run",
                       ", ".join(S.MODE_NAMES[m] for m in S.MODE_ORDER
                                 if enabled[m]),
                       "" if max_per_mode else ", unbounded"), "dim")

        def job():
            watcher = None
            try:
                cap = capture.open_for(userdata.adb_mode())
                bot = S.SummonBot(
                    cap, dry_run=not real_run,
                    log=lambda t: self.events.put(("log", t)),
                    enabled=enabled, watch_ads_first=watch_ads,
                    max_per_mode=max_per_mode, patience=patience)
                self.stop = bot
                watcher = self._start_guard(bot)
                stats = bot.run()
                self.events.put(("log", "\n%s" % S.format_summary(stats)))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                if watcher:
                    watcher.stop()
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    # --- Digital World Search -----------------------------------------
    def _page_mini(self):
        bot = self._bot_by_key("mini")
        frame = self._page_frame(bot["name"], bot["why"])
        import world as world_mod
        row = self._requirements(frame, "mini")

        # The same blue panel the Bond & Quest page gives its two live
        # lines, for the same reason: this is the one thing on the page
        # that changes by itself, and everything around it is a setting
        # that stays where it was put.
        #
        # Beside the setup button where there is one, which is the whole
        # point of the row: the two say the same thing from either end --
        # whether this bot can run, and the way to make it able to. It
        # takes the width the button leaves over. On its own line where
        # there is no button, so that a bot which stops needing setup does
        # not lose the line as well.
        if row is not None:
            self.mini_state = self._state_box(row, ("Segoe UI", 10), text="",
                                              side="left", padx=(0, 12),
                                              wraplength=520)
        else:
            self.mini_state = self._state_box(frame, ("Segoe UI", 10), text="",
                                              pady=(14, 0), wraplength=640)

        settings = tk.Frame(frame, bg=BG)
        settings.pack(anchor="w", fill="x", pady=(10, 0))

        left = tk.Frame(settings, bg=BG)
        left.pack(side="left", anchor="n")
        tk.Label(left, text="What to collect", bg=BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        wanted = self.state_data.get("wanted", list(world_mod.ALL_WANTED))
        for key in world_mod.ALL_WANTED:
            var = tk.BooleanVar(value=key in wanted)
            self.vars["want_" + key] = var
            tk.Checkbutton(left, text=world_mod.wanted_label(key),
                           variable=var, bg=BG).pack(anchor="w")

        right = tk.Frame(settings, bg=BG, padx=28)
        right.pack(side="left", anchor="n")
        self._spin(right, "min_paws", "Stop below this many paws", 0, 0, 500)
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    0 keeps going until the paws run out. Set it "
                       "higher to\n    leave yourself a reserve to spend.")
                 ).pack(anchor="w")
        self._spin(right, "max_actions", "Action limit (0 = none)", 0, 0, 5000)
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    Stops after this many moves, whatever is left "
                       "over.\n    Handy for a short test run; 0 lets it "
                       "play on.")).pack(anchor="w")
        self._spin(right, "target_meters", "Stop at metres (0 = none)",
                   0, 0, 100000)
        # This one really is seconds, engine passes it to actions.Actor.
        self._spin(right, "click_delay", "Seconds between clicks",
                   0.7, 0.1, 5.0, floaty=True)
        # No control any more, and a fixed three minutes. It is a fallback
        # and nothing else now that the bot always opens the board itself:
        # it is what waits if that navigation failed and left the player to
        # open the board by hand. Nothing a player has to decide, so it is
        # not asked -- but it is not 0 either, because 0 is the old refusal
        # that gave up in fifteen seconds on a board nobody had opened yet.
        self.vars["wait_for_board"] = tk.IntVar(value=180)

        # Always on, no switch. Opening the board from the main screen and
        # going back there afterwards is what this bot does, and it is the
        # setting the rest of the page is written around -- the
        # requirements box above says which screen to be on because of it.
        # Still a variable: `engine.Settings` and `_save_keys` both speak
        # it, and setting it here rather than reading state_data means a
        # stored False from the version that had the switch is overwritten
        # on the next save instead of quietly kept.
        self.vars["navigate"] = tk.BooleanVar(value=True)

        var = tk.BooleanVar(value=self.state_data.get("adaptive", True))
        self.vars["adaptive"] = var
        tk.Checkbutton(right, text="Speed up while it goes well",
                       variable=var, bg=BG).pack(anchor="w")
        tk.Label(right, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 8),
                 text=("    Shortens the wait between clicks while every "
                       "move lands, and\n    goes back to the full wait the "
                       "moment one does not.")).pack(anchor="w")

        self._run_controls(frame, "mini",
                           [("Start", lambda: self._start_mini(True))],
                           extra=[("Dry run", lambda: self._start_mini(False))])

        def refresh():
            state = self.bot_states()["mini"]
            self.mini_state.configure(
                text=("Ready to run." if state["ready"]
                      else "Not ready yet: %s. Press Start and the setup "
                           "opens where it is needed." % state["detail"]))

        return {"frame": frame, "refresh": refresh}

    def _start_mini(self, real_run):
        if not self._may_run("mini"):
            return
        if self.worker and self.worker.is_alive():
            return
        self._yield_emulator_from_quest()
        import engine
        import world as world_mod

        # Same rule as the other two: never start without the images it
        # matches against, send them to the step that fixes it instead.
        states = self.bot_states()
        if not states["mini"]["ready"]:
            self._lock("mini")
            self._write("\nNot set up yet (%s), opening the setup."
                        % states["mini"]["detail"], "warn")
            self.events.put(("done", ""))
            self._setup_for(self._bot_by_key("mini"))
            return

        wanted = [k for k in world_mod.ALL_WANTED
                  if self.vars["want_" + k].get()]
        if not wanted:
            messagebox.showwarning("Nothing selected",
                                   "Pick at least one thing to collect.")
            return
        self.state_data["wanted"] = wanted
        self._save_keys(["min_paws", "max_actions", "target_meters",
                         "click_delay", "adaptive", "wait_for_board",
                         "navigate"])
        self._lock("mini")
        self._write("\n%s, collecting %s"
                    % ("Start" if real_run else "Dry run", ", ".join(wanted)),
                    "dim")

        settings = engine.Settings(
            dry_run=not real_run, is_selected=wanted,
            min_paws=self.vars["min_paws"].get(),
            max_actions=self.vars["max_actions"].get(),
            target_meters=self.vars["target_meters"].get(),
            click_delay=self.vars["click_delay"].get(),
            adaptive=self.vars["adaptive"].get(),
            navigate=self.vars["navigate"].get(),
            # Only the fallback now: navigate is always on from this page,
            # so engine.run opens the board itself before this wait is ever
            # reached. It stays for the navigation that failed and left the
            # player to open the board by hand -- and for gui.py, the
            # developer window, which can still turn navigate off.
            wait_for_board=self.vars["wait_for_board"].get())

        # engine.run starts its own guard, so this bot needs no _start_guard.
        holder = _StopHolder()
        self.stop = holder

        def job():
            try:
                stats = engine.run(settings, self._emit_engine, holder.control)
                self.events.put(("log", "\nSummary: %s" % stats))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _emit_engine(self, event):
        """engine speaks in event dicts, the log wants lines."""
        text = str(event.get("text", "")) if isinstance(event, dict) else str(event)
        if not text:
            return
        kind = event.get("art", "") if isinstance(event, dict) else ""
        self.events.put(("warn" if str(kind).lower().startswith("w") else "log",
                         text))

    # --- The passive helper -------------------------------------------
    def _page_passive(self):
        """Bond token, Auto Spend, and the quest loop -- all three watched
        for as long as this is open.

        Not one of BOTS: those are the things a player starts, and this one
        has no Start button. It runs from the moment the window opens, does
        nothing but read most of the time, and taps only when the main
        screen is plainly in front. The quest loop's own dungeon and summon
        steps are the one exception -- while one of those plays, it *is*
        one of the three bots, briefly, and hands the emulator back the
        moment it is done (PLAN_QUEST_LOOP.md 6).
        """
        frame = self._page_frame(
            "Bond & Quest Loop",
            "Runs by itself while Helpermon is open. It collects the bond "
            "token from your partner, keeps Auto Spend for Hologram "
            "Tickets running, and can work through the game's own row of "
            "repeating quests.")

        # Both halves of this page carry their own box, and neither says
        # "Start": this page has no Start button, only switches, and the
        # two halves do not need the same things to be true. It was the
        # one page left without either, which is how a helper whose whole
        # failure mode is standing on the wrong screen was the one page
        # that never said which screen it wanted.
        self._requirements(frame, "passive",
                           title="Before you switch this on")

        self.passive_state = self._state_box(frame, ("Segoe UI", 10),
                                             pady=(14, 8), wraplength=640)

        var = tk.BooleanVar(value=self.state_data.get("passive_on", False))
        self.vars["passive_on"] = var
        tk.Checkbutton(frame, text="Watch the main screen while Helpermon is "
                                   "open", variable=var, bg=BG,
                       font=("Segoe UI", 10, "bold"),
                       command=self._toggle_passive).pack(anchor="w")
        tk.Label(frame, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9),
                 text=("    Takes effect at once, both ways, and is "
                       "remembered for the next start.")
                 ).pack(anchor="w", pady=(2, 8))
        for key, text, default, note in (
                ("passive_bond", "Collect the bond token", True,
                 "        The partner shows a speech bubble with food in "
                 "it. The token is collected by tapping the figure,\n"
                 "        so the bubble has to be seen first -- tapping the "
                 "figure without one only opens the Partner\n"
                 "        window. That one it taps away again, because it "
                 "opened it. A window you opened yourself is\n"
                 "        never touched."),
                ("passive_auto", "Keep Auto Spend for Hologram Tickets "
                                 "running", False,
                 "        The counter under the device is read either "
                 "way. While Auto Spend works it falls\n"
                 "        every three to four seconds; with this on, a "
                 "counter that stands still gets the button\n"
                 "        pressed again. At zero tickets there is "
                 "nothing to press for."),
                ("passive_verbose", "Show everything it sees", False,
                 "        Every round in the log instead of the events and "
                 "a line a minute. Long, and useful for a report.")):
            box = tk.BooleanVar(value=self.state_data.get(key, default))
            self.vars[key] = box
            tk.Checkbutton(frame, text=text, variable=box, bg=BG,
                           command=self._toggle_passive
                           ).pack(anchor="w", padx=(24, 0))
            tk.Label(frame, bg=BG, fg="#5f6368", justify="left",
                     font=("Segoe UI", 8), text=note).pack(anchor="w")

        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x", pady=(10, 10))
        tk.Label(frame, text="Quest loop", bg=BG, anchor="w",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        # Under this heading and not at the top of the page, which is where
        # every other supporter banner sits: only the half below it is a
        # supporter feature. At the top it would read as a price on the bond
        # token and Auto Spend as well, and those have always been free.
        self._supporter_box(frame, "quest")
        self._requirements(frame, "quest",
                           title="Before you switch the quest loop on")

        self.quest_state = self._state_box(frame, ("Segoe UI", 9),
                                           pady=(2, 6), wraplength=640)

        quest_on = tk.BooleanVar(value=self.state_data.get("quest_on", False))
        self.vars["quest_on"] = quest_on
        # Live even while this is locked, on purpose: it is the Start button
        # this feature has, and `_may_run` is a gate behind a press rather
        # than a switch nobody can reach. Ticking it on a locked machine
        # opens the supporter dialog and, if no code arrives, unticks itself.
        tk.Checkbutton(frame, text="Work through the repeating quests",
                       variable=quest_on, bg=BG, font=("Segoe UI", 10, "bold"),
                       command=self._toggle_quest_loop).pack(anchor="w")
        tk.Label(frame, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9), wraplength=640,
                 text=("    The quests come in a fixed order, so one that "
                       "cannot be done holds up the rest -- the line above "
                       "says which one it is on, and why, once it is "
                       "waiting on something. Starting one of the three "
                       "bots by hand takes the emulator back from a dungeon "
                       "or summon step in progress within a few seconds.")
                 ).pack(anchor="w", pady=(2, 6))

        quest_boxes = []
        for key, text, default, note in (
                ("quest_dungeon", "Play the dungeon quests", True,
                 "        Spends two of the day's dungeon attempts each "
                 "time one comes up -- the Dungeons bot then finds\n"
                 "        fewer left when it runs."),
                ("quest_summon", "Do the summon quests", True,
                 "        Watches the free ads first, then makes one draw "
                 "of 35 for 30 tickets if the quest still\n"
                 "        needs it afterwards."),
                ("quest_claim_only", "Claim only, never play anything",
                 False,
                 "        Collects a quest the moment it is done, but "
                 "never plays a dungeon or a summon to finish\n"
                 "        one -- it just waits for the game itself or Auto "
                 "Spend to get there.")):
            box = tk.BooleanVar(value=self.state_data.get(key, default))
            self.vars[key] = box
            check = tk.Checkbutton(frame, text=text, variable=box, bg=BG,
                                   command=self._toggle_quest_loop)
            check.pack(anchor="w", padx=(24, 0))
            quest_boxes.append(check)
            tk.Label(frame, bg=BG, fg="#5f6368", justify="left",
                     font=("Segoe UI", 8), text=note).pack(anchor="w")

        def draw_quest_lock():
            """The three boxes follow the lock; the switch above them does
            not. They are what the loop does once it is allowed to run, so
            on a locked machine they can only set something up that nothing
            will read -- greyed out they also say which half of this page
            the banner above is about. Redrawn with every other banner in
            the window the moment a code is redeemed."""
            state = "normal" if unlock.unlocked() else "disabled"
            for widget in quest_boxes:
                widget.configure(state=state)

        draw_quest_lock()
        self.supporter_boxes.append(draw_quest_lock)

        row = tk.Frame(frame, bg=BG, pady=12)
        row.pack(anchor="w", fill="x")
        tk.Button(row, text="Clear log", width=12,
                  command=self._clear_passive_log).pack(side="right")

        box = tk.Frame(frame, bg=BG)
        box.pack(fill="both", expand=True)
        log = tk.Text(box, height=16, wrap="word", font=("Consolas", 9),
                      state="disabled")
        bar = tk.Scrollbar(box, command=log.yview)
        log.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        log.pack(side="left", fill="both", expand=True)
        log.tag_configure("warn", foreground="#b3261e")
        log.tag_configure("dim", foreground="#777")
        # Lighter than the dimmest line it stands in front of: the clock is
        # there to be looked up, not read along with every line.
        log.tag_configure("time", foreground="#9aa0a6")
        self.passive_log = log
        return {"frame": frame, "refresh": None}

    # --- Setup --------------------------------------------------------
    # --- About --------------------------------------------------------
    def _remake_shortcut(self):
        """Put the desktop shortcut and the starter back.

        make_shortcut.py is asked to do it rather than the work being
        repeated here, because it is the same module install.bat runs and
        it is the one that knows where Windows keeps the desktop -- a
        second answer to that question is a second thing to get wrong on
        a machine with OneDrive.

        The interpreter it points at is the one running this window, which
        is right by construction: this window is what the shortcut has to
        open.
        """
        import make_shortcut as ms
        try:
            bat = ms.write_bat()
        except Exception as err:
            messagebox.showwarning(
                "Desktop shortcut",
                "The starter could not be written:\n\n%s" % err)
            return

        target = ms.desktop()
        if not target:
            messagebox.showinfo(
                "Desktop shortcut",
                "Windows did not say where the desktop is, so the shortcut "
                "was not created.\n\nThe starter is there though:\n\n%s"
                "\n\nRight-click it, Send to, Desktop." % bat)
            return

        link = os.path.join(target, "Helpermon.lnk")
        try:
            ms.make_shortcut(ms.pythonw(), "app.py", ms.HERE, link)
        except Exception as err:
            messagebox.showwarning(
                "Desktop shortcut",
                "The shortcut could not be created:\n\n%s\n\nThe starter "
                "was written and works:\n\n%s" % (err, bat))
            return

        messagebox.showinfo(
            "Desktop shortcut",
            "Created:\n\n%s\n\nIt opens this folder's app.py:\n\n%s"
            "\n\nThe starter beside it was written again as well."
            % (link, ms.HERE))

    def _page_about(self):
        frame = self._page_frame(
            "About",
            )
        tk.Label(frame, text="Version " + VERSION, bg=BG, fg="#70757c",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 0))
        tk.Label(frame, text=FAN_TITLE, bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(16, 4))
        tk.Label(frame, text=FAN_NOTICE, bg=BG, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w")
        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x", pady=(14, 0))
        tk.Label(frame, text=LEGAL_NOTICE, bg=BG, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(14, 12))
        tk.Label(frame, text=HOTKEY_HINT, bg=BG, justify="left", fg="#5f6368",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))
        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", fill="x")
        tk.Button(row, text="Show the notice again", width=24,
                  command=self._legal_notice).pack(side="left")
        tk.Button(row, text="How it reaches the emulator", width=26,
                  command=self._adb_notice).pack(side="left", padx=(8, 0))

        # Not on the Helpermon page, although that is the one about getting
        # set up. This is a repair, and it is wanted at the moment
        # something about the installation has already gone odd -- a
        # shortcut deleted by accident, or one install.bat never managed
        # to write, which it reports as "not fatal" and carries on from.
        #
        # What it deliberately does not claim to fix is a folder that has
        # been moved. That breaks .venv, which records the folder it was
        # built in, and a broken .venv means this window does not open at
        # all -- so a button inside it would be behind the very door that
        # shut. The note says where to go instead rather than leaving
        # somebody to press this and wonder why nothing improved.
        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x", pady=(18, 0))
        tk.Label(frame, text="Desktop shortcut", bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(14, 4))
        tk.Label(frame, bg=BG, fg="#5f6368", justify="left", wraplength=700,
                 font=("Segoe UI", 9),
                 text=("Puts Helpermon back on the desktop, pointing at this "
                       "folder, and writes the starter beside it again. For "
                       "a shortcut that was deleted, or that never "
                       "arrived.\n\nAfter moving this folder, run "
                       "install.bat in the new place instead. It rebuilds "
                       ".venv, which nothing in here can do, and puts the "
                       "shortcut back as part of that.")
                 ).pack(anchor="w")
        tk.Button(frame, text="Create it again", width=22,
                  command=self._remake_shortcut).pack(anchor="w", pady=(10, 0))

        # The code, on the one page that is about the program rather than
        # about a bot. Reachable even when every supporter feature is
        # switched off -- somebody handing this machine on has to be able
        # to find out what is on it without hunting for the bot the code
        # happens to unlock.
        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x", pady=(18, 0))
        tk.Label(frame, text="Supporter code", bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(14, 4))
        state = tk.Label(frame, bg=BG, anchor="w", justify="left",
                         wraplength=700, font=("Segoe UI", 10))
        state.pack(anchor="w")
        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", fill="x", pady=(8, 0))
        enter = tk.Button(row, text="Enter a code", width=22,
                          command=self._code_dialog)
        enter.pack(side="left")
        tk.Button(row, text="Open Ko-fi", width=16,
                  command=lambda: webbrowser.open(unlock.KOFI_URL)
                  ).pack(side="left", padx=(8, 0))
        # No button for giving the code back. It is the one thing in this
        # window that nothing else can undo -- the copy that matters is in
        # a Ko-fi message from months ago -- and a live-looking button
        # beside a line naming the code invites a press to find out what
        # it does. The command has to be typed out instead, which is
        # enough of a pause to think in.
        tk.Label(frame, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9), wraplength=700,
                 text=("Handing this machine on?  py unlock.py --forget  "
                       "gives the code back, in a terminal in the Helpermon "
                       "folder. It prints the code once before it goes -- "
                       "write it down, nothing shows it again.")
                 ).pack(anchor="w", pady=(8, 0))

        def draw_code():
            code = unlock.saved()
            if unlock.unlocked():
                state.configure(
                    text="%s\nThis machine is using %s."
                         % (SUPPORTER_THANKS, unlock.pretty(code)),
                    fg="#1e5c33")
                enter.configure(text="Use a different code")
            elif code:
                # Kept, and no longer accepted. The code is still shown: it
                # is the only thing that lets somebody say which one it was
                # when they ask why it stopped.
                state.configure(text=SUPPORTER_STALE % unlock.pretty(code),
                                fg="#b3261e")
                enter.configure(text="Enter a different code")
            else:
                state.configure(
                    text=("No code on this machine, so %s %s locked. %s"
                          % (", ".join(sorted(self._locked_name(k)
                                              for k in SUPPORTER_ONLY)),
                             "is" if len(SUPPORTER_ONLY) == 1 else "are",
                             SUPPORTER_HOW)),
                    fg="#5f6368")
                enter.configure(text="Enter a code")

        draw_code()
        self.supporter_boxes.append(draw_code)

        # Last, and behind a line, because these undo things. There is no way
        # into the full wizard from here on purpose: setting a bot up belongs
        # on that bot's page, and a button offering all eight steps at once is
        # the thing that used to land people in the wrong bot's setup.
        #
        # Settings only. Throwing the learned images away used to be a
        # button beside this one and is gone: it is the one thing on
        # this page that a mis-click cannot undo in a minute, since
        # relearning them is twenty minutes of a player's evening.
        # remove.bat still asks about them, where somebody is
        # uninstalling anyway.
        tk.Frame(frame, height=1, bg="#d0d3d8").pack(fill="x", pady=(18, 0))
        tk.Label(frame, text="Starting over", bg=BG, anchor="w",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(14, 4))

        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        tk.Button(row, text="Reset the settings", width=22,
                  command=self._reset_settings).pack(side="left")
        tk.Label(row, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9),
                 text=("  Puts every setting on every page back to its "
                       "default.\n  Nothing you taught it is "
                       "touched.")).pack(side="left")
        return {"frame": frame, "refresh": None}

    def _reset_settings(self):
        """Every page back to its defaults. Nothing learned is touched."""
        if not messagebox.askyesno(
                "Reset the settings",
                "Puts every setting on every page back to its default: "
                "which dungeons are ticked, rounds, patience, all of it.\n\n"
                "The images and digits you taught it stay where they are.\n\n"
                "Carry on?"):
            return

        failed = []
        for path in (STATE_FILE, OLD_STATE_FILE):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as err:
                failed.append(str(err))
        self.state_data = {}

        if failed:
            messagebox.showwarning(
                "Not reset", "Could not remove the settings: %s"
                % ", ".join(failed))
            return
        messagebox.showinfo(
            "Settings reset",
            "Every setting is back to its default.\n\n"
            "The pages you have open still show the old values until you "
            "restart Helpermon.")
        self.status.configure(text="settings reset to their defaults")

    # ==================================================================
    # Shared widgets
    # ==================================================================
    def _spin(self, parent, key, label, default, lo, hi, floaty=False):
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x", pady=1)
        tk.Label(row, text=label, width=30, anchor="w", bg=BG).pack(side="left")
        # Clamped, not trusted. A value saved before a limit moved -- the
        # minigame's speed used to go to 4 -- would otherwise sit in the box
        # above its own maximum and be handed straight back to the bot.
        saved = self.state_data.get(key, default)
        try:
            saved = min(hi, max(lo, saved))
        except TypeError:
            saved = default
        var = (tk.DoubleVar if floaty else tk.IntVar)(value=saved)
        self.vars[key] = var
        tk.Spinbox(row, from_=lo, to=hi, textvariable=var, width=7,
                   increment=0.1 if floaty else 1).pack(side="left")

    def _run_controls(self, parent, key, starts, extra=()):
        """The same row of controls and the same log for every bot that runs
        in this window, so one bot's page never looks like a different
        program from the next.

        `extra` holds the actions that are for finding out what is wrong
        rather than for playing -- dry run, diagnostics. They still disable
        while something runs, but they sit apart from the button a player
        actually wants.
        """
        buttons = tk.Frame(parent, bg=BG, pady=12)
        buttons.pack(anchor="w", fill="x")
        start_buttons = []
        for label, command in starts:
            button = tk.Button(buttons, text=label, width=14, command=command)
            button.pack(side="left", padx=(0, 8))
            start_buttons.append(button)
        pause = tk.Button(buttons, text="Pause", width=12, state="disabled",
                          command=self._pause)
        pause.pack(side="left")
        stop = tk.Button(buttons, text="Stop", width=12, state="disabled",
                         command=self._panic)
        stop.pack(side="left", padx=8)
        tk.Button(buttons, text="Clear log", width=12,
                  command=lambda: self._clear_log(key)).pack(side="right")

        tk.Label(parent, bg=BG, fg="#5f6368", justify="left",
                 font=("Segoe UI", 9), text=HOTKEY_HINT
                 ).pack(anchor="w", pady=(0, 6))

        # Hidden until a run finishes; _maybe_ask_feedback shows it. Not a
        # dialog and it takes no focus -- packed into the page like any
        # other row, so it cannot eat a click meant for the emulator the
        # way a Toplevel with grab_set() would.
        fb_frame = tk.Frame(parent, bg="#eef3fb", bd=1, relief="solid",
                            padx=10, pady=6)
        fb_label = tk.Label(fb_frame, bg="#eef3fb", font=("Segoe UI", 9),
                            text="Did this run do what you wanted?")
        fb_label.pack(side="left")
        fb_buttons = tk.Frame(fb_frame, bg="#eef3fb")
        fb_buttons.pack(side="left", padx=(10, 0))
        tk.Button(fb_buttons, text="Yes", width=6,
                 command=lambda k=key: self._feedback_thumb(k, "up")
                 ).pack(side="left")
        tk.Button(fb_buttons, text="No", width=6,
                 command=lambda k=key: self._feedback_thumb(k, "down")
                 ).pack(side="left", padx=(4, 0))
        fb_more = tk.Button(fb_frame, text="Tell me more", bd=0, bg="#eef3fb",
                            fg="#1a56c4", activebackground="#eef3fb",
                            cursor="hand2",
                            command=lambda k=key: self._feedback_form(k))
        fb_more.pack(side="left", padx=(14, 0))
        fb_frame.pack(anchor="w", fill="x", pady=(0, 6))
        fb_frame.pack_forget()

        # The bottom row is packed BEFORE the log, so the log takes the space
        # that is left and this row ends up below it, as far from the button
        # a player wants as the page allows. That is the right place for a
        # dry run and for diagnostics, which are for reporting a problem.
        #
        # Setup no longer sits here. It is under the requirements box now,
        # beside the sentence that says what is missing. It is still on the
        # bot's own page and nowhere else: there used to be one Setup page
        # for all three, and from it one wizard that walked through
        # everybody's steps in a row -- so setting up the Night Market
        # carried you on into the World Search's four steps with nothing
        # saying you had left what you came for.
        bottom = tk.Frame(parent, bg=BG, pady=6)
        bottom.pack(side="bottom", anchor="w", fill="x")
        if extra:
            tk.Label(bottom, text="For testing:", bg=BG, fg="#70757c",
                     font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
            for label, command in extra:
                button = tk.Button(bottom, text=label, width=13,
                                   command=command)
                button.pack(side="left", padx=(0, 6))
                start_buttons.append(button)

        log_box = tk.Frame(parent, bg=BG)
        log_box.pack(fill="both", expand=True)
        # Wrapped, not clipped. With wrap="none" and no horizontal
        # scrollbar, a long line simply had its end cut off by the window
        # edge -- and the interesting half of a bot's line is the end.
        log = tk.Text(log_box, height=12, wrap="word", font=("Consolas", 9),
                      state="disabled")
        bar = tk.Scrollbar(log_box, command=log.yview)
        log.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        log.pack(side="left", fill="both", expand=True)
        log.tag_configure("warn", foreground="#b3261e")
        log.tag_configure("dim", foreground="#777")
        # Lighter than the dimmest line it stands in front of: the clock is
        # there to be looked up, not read along with every line.
        log.tag_configure("time", foreground="#9aa0a6")

        self.panels[key] = {"starts": start_buttons, "pause": pause,
                            "stop": stop, "log": log,
                            "feedback": fb_frame, "feedback_label": fb_label,
                            "feedback_buttons": fb_buttons,
                            "feedback_more": fb_more,
                            # Where the bar re-inserts itself: packed before
                            # the log every time, or a hidden frame packed
                            # again after the log claimed the rest of the
                            # page with expand=True lands as an invisible
                            # sliver underneath it instead.
                            "feedback_anchor": log_box}

    def _clear_log(self, key):
        log = self.panels[key]["log"]
        log.configure(state="normal")
        log.delete("1.0", "end")
        log.configure(state="disabled")

    def _log_text(self, key):
        """What that bot's log says right now, wherever the bot keeps it.

        Most of them are in `self.panels`, put there by `_run_controls`.
        The passive helper builds its own page and keeps its log in
        `self.passive_log`, so a lookup in `panels` alone answers "there is
        no log" for the one bot that runs all day -- and whose "Show
        everything it sees" switch exists to be turned on for a report.
        """
        if key in ("passive", "quest"):
            # One log for both: the quest loop writes into the passive
            # helper's page, because it runs on that page's thread.
            log = getattr(self, "passive_log", None)
            return log.get("1.0", "end") if log is not None else ""
        panel = self.panels.get(key)
        return panel["log"].get("1.0", "end") if panel else ""

    def _bot_by_key(self, key):
        for bot in BOTS:
            if bot["key"] == key:
                return bot
        if key in EXTRA_BOTS:
            return EXTRA_BOTS[key]
        return BOTS[0]

    # ==================================================================
    # Running the bots
    # ==================================================================
    def _start_dungeon(self, real_run):
        if not self._may_run("dungeon"):
            return
        if self.worker and self.worker.is_alive():
            return
        self._yield_emulator_from_quest()
        import capture
        import dungeon as D

        budgets = {i: int(self.vars["dg_%d" % i].get())
                   for i in range(len(D.DUNGEON_KEYS))}
        chosen = [i for i, n in budgets.items() if n > 0]
        if not chosen:
            messagebox.showwarning("Nothing to play",
                                   "Every dungeon is set to 0 attempts.")
            return
        self._save_keys(["max_minutes", "langsam", "use_ads", "survey"],
                        attempts={str(i): n for i, n in budgets.items()})
        self._lock("dungeon")
        self._write("\n%s, playing: %s"
                    % ("Start" if real_run else "Dry run",
                       ", ".join("%s %dx" % (D.DUNGEON_NAMES[i], budgets[i])
                                 for i in chosen)), "dim")

        values = {k: self.vars[k].get() for k in
                  ("max_minutes", "langsam", "use_ads", "survey")}
        # How many dungeons the list holds is not a setting, it is the length
        # of the list the player is looking at.
        values["entries"] = len(D.DUNGEON_NAMES)

        def job():
            watcher = None
            try:
                cap = capture.open_for(userdata.adb_mode())
                bot = D.DungeonBot(
                    cap, dry_run=not real_run,
                    log=lambda t: self.events.put(("log", t)),
                    entries=values["entries"], use_ads=values["use_ads"],
                    survey_first=values["survey"], patience=values["langsam"],
                    max_minutes=values["max_minutes"], only=set(chosen),
                    budgets=budgets)
                self.stop = bot
                watcher = self._start_guard(bot)
                stats = bot.run()
                self.events.put(("log", "\n%s" % D.format_summary(stats)))
            except Exception as err:
                self.events.put(("warn", "Error: %s" % err))
            finally:
                if watcher:
                    watcher.stop()
                self.events.put(("done", ""))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    # ------------------------------------------------------------------
    # The passive helper
    # ------------------------------------------------------------------
    # It is not one of the bots and deliberately does not use `self.worker`:
    # that field belongs to whatever the player started, and _lock, Pause and
    # Stop all speak to it. This runs beside all of that, and stands back the
    # moment `self.worker` is alive.
    def _toggle_passive(self):
        """The switch on the page, and the three boxes under it."""
        self._save_keys(["passive_on", "passive_bond", "passive_auto",
                         "passive_verbose"])
        self._sync_helper_thread()
        self._passive_options()
        self._quest_options()      # passive_auto also feeds the quest loop
        if not self.vars["passive_on"].get():
            # Switched off while the thread carries on for the quest loop.
            # Nothing else would touch this line, and a status left standing
            # from the last round reads as a helper that is still working.
            self.events.put(("passive_status", "off"))

    def _toggle_quest_loop(self):
        """The quest loop's own switch, and the three boxes under it.

        A second switch on the same page as passive_on, both keeping the
        one shared thread alive (PLAN_QUEST_LOOP.md 6): either one on is
        enough to start it, and it stops only once both are off.
        """
        self._save_keys(["quest_on", "quest_dungeon", "quest_summon",
                         "quest_claim_only"])
        self._sync_helper_thread()
        self._quest_options()
        if not self.vars["quest_on"].get():
            self.events.put(("quest_status", "off"))

    def _helper_wanted(self):
        return (bool(self.vars.get("passive_on") and self.vars["passive_on"].get())
                or bool(self.vars.get("quest_on") and self.vars["quest_on"].get()))

    def _sync_helper_thread(self):
        """Start or stop the shared thread to match what the two switches
        on the page now ask for.

        A switch rather than a Start button, and still a start: the gate
        belongs here too -- and one of these two switches is now a supporter
        feature while the other is not, so each one is asked about its own
        key. Asking once for the pair was enough while the pair was free;
        it is not any more, because the thread being up for the bond token
        says nothing about whether the quest loop may run.

        Only when a switch really goes on, though. Every box on the page
        calls into here, so without `_gated`, ticking "show everything it
        sees" put the start notice in front of somebody who had started the
        helper ten minutes ago -- and its Cancel then switches the helper
        off, which is not what ticking a box asked for. A switch that goes
        off is forgotten again, so switching it back on asks afresh: for an
        unlocked machine that is silent, and for a locked one it is the
        whole point.
        """
        # The key is written out at the call rather than passed in as the
        # loop variable, and that is not decoration: test_unlock.py and
        # test_launcher.py both read the calls to `_may_run` out of this
        # source, quoted key and all, to check that everything startable
        # goes through the gate and has a name and requirements of its own.
        # A variable in that place is invisible to
        # both, and the first draft of this loop turned the passive helper's
        # own gate into something no test could see any more.
        for key, name, ask in (
                ("passive", "passive_on", lambda: self._may_run("passive")),
                ("quest", "quest_on", lambda: self._may_run("quest"))):
            var = self.vars.get(name)
            if var is None:
                continue
            if not var.get():
                self._gated.discard(key)
            elif key not in self._gated:
                if ask():
                    self._gated.add(key)
                else:
                    # Back into the settings file too. The toggle saved the
                    # switch before it called in here, so a switch that was
                    # turned down would otherwise stand "on" on disk and be
                    # honoured, unasked, by the next start of the window.
                    var.set(False)
                    self._save_keys([name])
        if self._helper_wanted():
            self._start_passive()
        else:
            self._stop_passive()

    def _passive_options(self):
        """Push the boxes into a helper that is already running.

        Ticking a box has to reach it now, not at the next start of the
        program: the boxes are what a player reaches for when they are
        watching it do the wrong thing.
        """
        bot = self.passive_bot
        if bot is None:
            return
        bot.do_bond = bool(self.vars["passive_bond"].get())
        bot.do_auto = bool(self.vars["passive_auto"].get())
        bot.verbose = bool(self.vars["passive_verbose"].get())

    def _quest_options(self):
        """Push the quest loop's own boxes into a loop that already exists.

        auto_spend_on comes from passive_auto, not from a box of its own:
        a holo step waits on the same switch that actually spends the
        tickets (PLAN_QUEST_LOOP.md 5.4), so there is nothing a second
        checkbox here could mean that is not already answered by that one.
        """
        loop = self.quest_loop
        if loop is None:
            return
        loop.do_dungeon = bool(self.vars["quest_dungeon"].get())
        loop.do_summon = bool(self.vars["quest_summon"].get())
        loop.claim_only = bool(self.vars["quest_claim_only"].get())
        loop.auto_spend_on = bool(self.vars["passive_auto"].get())

    def _start_passive(self):
        if self.passive_thread and self.passive_thread.is_alive():
            return
        self.passive_stop = threading.Event()
        self.passive_thread = threading.Thread(target=self._passive_loop,
                                               daemon=True)
        self.passive_thread.start()

    def _stop_passive(self):
        if self.passive_stop:
            self.passive_stop.set()
        self.passive_bot = None
        self.quest_loop = None
        self.events.put(("passive", "passive helper off"))
        self.events.put(("passive_status", "off"))
        self.events.put(("quest_status", "off"))

    def _save_quest_step(self, step):
        """Where the quest loop is in its 15-step routine, kept across a
        restart. Called from the passive thread; state_data is written
        from there elsewhere already (see _passive_loop's own comment on
        why it reads settings rather than Tk variables)."""
        self.state_data["quest_step"] = step
        self._save()

    def _quest_reserve_emulator(self):
        """True and quest_busy set, if no worker thread already owns the
        emulator. Called from the passive thread; a plain attribute check
        and a threading.Event, neither of which touches Tkinter."""
        if self.worker and self.worker.is_alive():
            return False
        self.quest_busy.set()
        return True

    def _quest_release_emulator(self):
        self.quest_busy.clear()

    def _passive_loop(self):
        """Tick the passive helper, then the quest loop, until the switches
        or the window say stop.

        Everything that can throw lives in here rather than in passive.py
        or quest.py: the emulator can be closed, ADB can drop the device,
        and none of that is worth more than a line in the log and another
        try. One capture, shared by both -- PLAN_QUEST_LOOP.md 6 makes the
        quest loop the third user of it, not a second thread.
        """
        import capture
        import guard
        import passive as P
        import quest as Q

        stop = self.passive_stop
        cap = None
        bot = None
        quest_loop = None
        retry_at = 0.0
        last_mouse = None
        self.events.put(("passive", "passive helper on, watching the main "
                                    "screen"))
        while not stop.is_set():
            try:
                if self._bot_running():
                    # A bot is playing. Let the capture go as well: it is the
                    # bot's emulator now, and holding a second handle on it
                    # buys nothing.
                    if bot is not None:
                        self.events.put(("passive", "  another bot is "
                                                    "running, standing back"))
                    cap, bot, self.passive_bot = None, None, None
                    quest_loop, self.quest_loop = None, None
                elif time.time() >= retry_at:
                    # Read from the saved settings, not from the Tk
                    # variables: tkinter is not thread-safe, and a .get()
                    # from here goes into Tcl on the wrong thread. The
                    # window writes these on every tick of a checkbox, and
                    # _passive_options/_quest_options push them into a
                    # running helper from the thread that owns them.
                    settings = self.state_data
                    if cap is None:
                        cap = capture.open_for(userdata.adb_mode())
                        bot = P.PassiveBot(
                            cap,
                            log=lambda t: self.events.put(("passive", t)),
                            do_bond=bool(settings.get("passive_bond", True)),
                            do_auto=bool(settings.get("passive_auto", True)),
                            verbose=bool(settings.get("passive_verbose",
                                                      False)))
                        self.passive_bot = bot
                        quest_loop = Q.QuestLoop(
                            cap,
                            log=lambda t: self.events.put(("passive", t)),
                            do_dungeon=bool(settings.get("quest_dungeon", True)),
                            do_summon=bool(settings.get("quest_summon", True)),
                            claim_only=bool(settings.get("quest_claim_only",
                                                         False)),
                            auto_spend_on=bool(settings.get("passive_auto",
                                                            True)),
                            step=int(settings.get("quest_step", 0)),
                            save_step=self._save_quest_step,
                            reserve_emulator=self._quest_reserve_emulator,
                            release_emulator=self._quest_release_emulator,
                            start_guard=self._start_guard,
                            stop_guard=lambda w: w.stop())
                        self.quest_loop = quest_loop
                    # Without ADB a tap moves the real mouse. Somebody whose
                    # hand is on it is using the machine, and a tap into the
                    # game is the last thing they want -- so the round still
                    # reads and logs, it just does not touch anything.
                    where = guard.cursor_pos()
                    may_tap = (not cap.moves_mouse or where is None
                              or where == last_mouse)
                    last_mouse = where
                    if settings.get("passive_on", False):
                        # The switch itself, not only its three boxes. Both
                        # switches keep this one thread alive, so without
                        # this the bond token was still being collected by
                        # a helper whose own switch was off, whenever the
                        # quest loop beside it was on.
                        bot.may_tap = may_tap
                        bot.tick()
                        self.events.put(("passive_status", bot.status()))
                    # `unlocked()` and not the switch alone: the switch is a
                    # line in a settings file, and this is the one place
                    # that acts on it.
                    if settings.get("quest_on", False) and unlock.unlocked():
                        quest_loop.may_tap = may_tap
                        quest_loop.tick()
                        self.events.put(("quest_status", quest_loop.status()))
            except Exception as err:
                self.events.put(("passive_warn",
                                 "  passive helper: %s -- trying again in "
                                 "%d s" % (err, PASSIVE_RETRY)))
                cap, bot, self.passive_bot = None, None, None
                quest_loop, self.quest_loop = None, None
                retry_at = time.time() + PASSIVE_RETRY
            stop.wait(P.TICK)

    def _clear_passive_log(self):
        self.passive_log.configure(state="normal")
        self.passive_log.delete("1.0", "end")
        self.passive_log.configure(state="disabled")

    def _write_passive(self, text, tag=None):
        """Into the helper's own log, whatever page is on show.

        Not through _write: that one writes to the panel of the bot that is
        running, and this helper runs while nothing else does.
        """
        # Long days produce long logs. Kept to the last few thousand lines so
        # a window left open overnight does not grow without end.
        self._write_into(self.passive_log, text, tag, trim=PASSIVE_LOG_LINES)

    def _afk_cold_start(self):
        """Emulator up, then the game, before a bot touches anything.

        Nothing calls this any more: the Instant AFK switch that did was
        taken off the dungeon page, and a run now starts against a game
        somebody has already opened. Kept because it is the only code that
        gets from a cold machine to a running game, and because what it
        knows was measured the hard way -- the findings in CLAUDE.md about
        monkey, about dumpsys, and about an emulator too young to have an
        ADB device yet all live in here.

        With the global ADB switch on: the game by its package name,
        started and confirmed through ADB alone -- see
        _afk_cold_start_via_adb and PLAN_ADB_ONLY.md, section 4.3. No icon
        needed, and no guessing whether the game is actually the thing in
        front.

        With the switch off: the old way, clicking the game's icon on the
        emulator's home screen. It is the only way that needs no ADB at
        all, which is the only reason it still exists.

        Returns whether the game may now be handed to a bot. False means
        neither way worked, and the caller must stop: what is on screen is
        then the emulator's own home screen, and a bot tapping at that hits
        the search bar, which is exactly what happened in a live run.

        Runs on the worker thread, so it reports through the event queue like
        everything else.
        """
        self.events.put(("step", "Instant AFK: starting the emulator"))
        say = lambda t: self.events.put(("step", "  " + str(t)))
        try:
            import ldplayer
            ld = ldplayer.LdPlayer(log=say)
        except Exception as err:
            self.events.put(("warn", "emulator tool not usable (%s)" % err))
            return False

        try:
            if not ld.is_running(0):
                say("starting LDPlayer instance 0")
                ld.launch(0)
            else:
                say("LDPlayer instance 0 is already running")
        except Exception as err:
            self.events.put(("warn", "could not start the emulator (%s)" % err))
            return False

        if userdata.adb_mode():
            return self._afk_cold_start_via_adb(ld, say)
        return self._afk_cold_start_via_icon(ld, say)

    def _afk_cold_start_via_adb(self, ld, say):
        """Package name, then ADB starts it, then dumpsys confirms it is
        actually in front. No icon, no wait_for_home, no reading pixel
        movement as evidence the game has loaded."""
        # No require_adb() in front of this. The emulator may have been
        # launched a second ago, and an emulator that young lists no ADB
        # device yet -- asking here answered "ADB is not answering" and
        # threw the whole cold start away while LDPlayer was still booting.
        # wait_ready is the function whose job is that wait, and it says the
        # same thing about ADB debugging if the device never turns up.
        try:
            serial = ld.wait_ready(0, window_ok=False)
            if serial and serial != "window":
                os.environ["DGUP_SERIAL"] = serial
        except Exception as err:
            self.events.put(("warn", str(err)))
            return False

        package = ld.find_package(0)
        if not package:
            self.events.put(("warn",
                             "Instant AFK could not find the game's package "
                             "among the installed apps. Pin it with the "
                             "DGUP_PACKAGE environment variable."))
            return False

        # Ask before starting. The game is often already up -- Instant AFK
        # is also pressed on a machine that has been sitting at the main
        # screen for an hour -- and launching it again is at best pointless
        # and at worst throws away whatever it was doing.
        front = ld.foreground_package()
        if front == package:
            say("game is already in front, %s" % front)
            return True
        say("package %s, %s is in front, starting it via ADB"
            % (package, front or "nothing"))
        try:
            ld.start_app_via_adb(package)
        except Exception as err:
            self.events.put(("warn", "Instant AFK could not start the game: "
                                     "%s" % err))
            return False
        front = ld.wait_for_app(package, timeout=APP_FRONT_TIMEOUT)
        if front != package:
            self.events.put(("warn",
                             "the game did not come to the foreground within "
                             "%d s (dumpsys says %s is in front instead)"
                             % (APP_FRONT_TIMEOUT, front or "nothing")))
            return False
        say("game in front, %s" % front)
        return True

    def _afk_cold_start_via_icon(self, ld, say):
        """The way that needs no ADB at all: click the learned icon on the
        emulator's home screen. Unchanged from before this switch existed,
        which is exactly the point -- with ADB off it is the only way in."""
        import capture
        import launcher
        import time

        try:
            cap = capture.open_window()
        except Exception as err:
            self.events.put(("warn", "no emulator window (%s)" % err))
            return False

        # The emulator's own home screen sometimes shows a full-screen ad
        # pop-up over the app icons before anything else has drawn -- LDStore
        # promoting some other game. Escape is the Android back key here
        # (WindowCapture.back), the same key that closes it by hand, and it
        # does nothing if there is no pop-up to close. Done before
        # wait_for_home: a pop-up sitting there long enough reads as "nothing
        # is moving", which wait_for_home takes as the game already running.
        say("closing any ad pop-up on the emulator's home screen")
        cap.back()
        time.sleep(1.0)
        cap.back()
        time.sleep(0.5)

        if not launcher.have_icon():
            # Without the icon there is no way to open the game and no way
            # to tell the emulator's home screen from the game either --
            # wait_for_home can only ever answer "busy" here, and "busy" is
            # read as "the game must be up". So this stops instead.
            self.events.put(("warn",
                             "Instant AFK cannot open the game with ADB off: "
                             "its icon has not been learned. Teach it under "
                             "Setup, wizard step 'Game icon' -- or turn ADB "
                             "on, or start the game yourself and run "
                             "without Instant AFK."))
            return False

        # The window exists within a couple of seconds, the Android behind it
        # does not. Asking "is the icon there?" straight away answers "no",
        # because a boot screen has no icons on it -- which is how this used
        # to decide the game must already be open and then tap at a splash.
        say("waiting for the emulator to finish starting")
        ready = launcher.wait_for_home(cap, log=say)

        if ready["state"] == "timeout":
            self.events.put(("warn", "the emulator never settled; is it "
                                     "actually starting?"))
            return False
        if ready["state"] == "busy":
            say("no home screen, so something is already running - assuming "
                "it is the game")
            return True

        say("opening the game by clicking its icon")
        if launcher.start_game(cap, log=say):
            say("game opened, waiting for it to load")
            return True
        self.events.put(("warn", "the game icon did not open anything, "
                                 "stopping rather than tapping at the "
                                 "emulator's own home screen"))
        return False

    def _start_guard(self, bot):
        """The global F7/F8 pause and abort keys, same as the CLI.

        Without this the buttons in this window are unreachable the moment a
        bot starts driving the mouse.
        """
        import guard
        try:
            return guard.start(bot.control,
                               log=lambda t: self.events.put(("log", t)))
        except Exception as err:
            self.events.put(("warn", "no global hotkeys: %s" % err))
            return None

    def _yield_emulator_from_quest(self):
        """The player wins. Called by every one of this window's own Start
        buttons before it claims the emulator for itself.

        PLAN_QUEST_LOOP.md 6: the quest loop is the one thing here that
        starts a long-running bot on its own, unattended, and a player
        reaching for Start has to be able to take the emulator back from
        it without first switching the quest loop off. Aborting the quest
        action's own control is what actually stops it -- its own finally
        block brings the game back to the main screen -- and the wait here
        is only so the new run does not start typing into a game the old
        one has not let go of yet.
        """
        loop = self.quest_loop
        if loop is not None and loop.current_control is not None:
            loop.current_control.request("player pressed Start")
        deadline = time.time() + QUEST_YIELD
        while self.quest_busy.is_set() and time.time() < deadline:
            time.sleep(0.05)

    # ------------------------------------------------------------------
    def _panel_now(self):
        return self.panels.get(self.active) or self.panels["dungeon"]

    def _lock(self, name):
        """Hand the buttons and the log over to the bot that is starting."""
        self._hide_feedback_bar(name)
        self.run_started = time.time()
        self.active = name
        self.show_page(name)
        panel = self.panels[name]
        for b in panel["starts"]:
            b.configure(state="disabled")
        for b in (panel["pause"], panel["stop"]):
            b.configure(state="normal")
        panel["pause"].configure(text="Pause")

    def _pause(self):
        # Both bots carry a guard.Stop as `control`; that is the only thing
        # they check between two actions.
        if not self.stop:
            return
        paused = self.stop.control.toggle_pause()
        self._panel_now()["pause"].configure(
            text="Continue" if paused else "Pause")
        self.status.configure(text="paused" if paused else "running")

    def _panic(self):
        if self.stop:
            self.stop.control.request("stop from the launcher")
            self.status.configure(
                text="Stopping, it will halt after the current action")

    # ==================================================================
    # Feedback
    # ==================================================================
    def _bot_running(self):
        """Whether a feedback dialog may safely grab_set().

        A bot without ADB drives the real mouse and keyboard, and a
        Toplevel that grabs focus mid-run eats the clicks meant for
        LDPlayer -- the reason the thumbs bar is a plain row rather than a
        popup in the first place. The same risk applies to every dialog
        this feature can open, not only the ones on the run page: the
        Feedback page's own thumbs are reachable while another bot runs.

        quest_busy counts too: while the quest loop is playing a dungeon or
        summon step it is one of these bots, just started by itself rather
        than by a Start button (PLAN_QUEST_LOOP.md 6).
        """
        return bool(self.worker and self.worker.is_alive()) or self.quest_busy.is_set()

    def _maybe_ask_feedback(self):
        """Show the thumbs bar for the bot that just finished, but only
        when there is something worth judging and nobody has said no."""
        key = self.active
        if not key or key not in self.panels or self.run_started is None:
            return
        elapsed = time.time() - self.run_started
        if elapsed < 60:
            return
        today = time.strftime("%Y-%m-%d")
        if self.state_data.get("feedback_asked_on") == today:
            return
        if self.state_data.get("feedback_declined"):
            return
        self.state_data["feedback_asked_on"] = today
        self._save()
        self._show_feedback_bar(key, elapsed)

    def _show_feedback_bar(self, key, elapsed):
        panel = self.panels[key]
        panel["feedback_elapsed"] = elapsed
        panel["feedback_label"].configure(text="Did this run do what you "
                                                "wanted?")
        panel["feedback_buttons"].pack(side="left", padx=(10, 0))
        panel["feedback_more"].configure(
            text="Tell me more", command=lambda: self._feedback_form(key))
        panel["feedback_more"].pack(side="left", padx=(14, 0))
        panel["feedback"].pack(anchor="w", fill="x", pady=(0, 6),
                               before=panel["feedback_anchor"])

    def _hide_feedback_bar(self, key):
        panel = self.panels.get(key)
        if panel:
            panel["feedback"].pack_forget()

    def _page_name(self):
        """What a report should call the page the header thumbs were
        pressed on.

        Read off the sidebar button rather than retyped: the label the
        player has been looking at is the name they would use themselves,
        and there is then only one place a page can be renamed.
        """
        button = self.nav_buttons.get(self.current_page)
        return button["text"] if button else "Helpermon"

    def _send_feedback(self, report, payload):
        """Hand a report to the network on a thread of its own.

        Sending is an HTTPS POST with a ten-second timeout, and ten seconds
        on the Tk thread is ten seconds of frozen window. So it goes the way
        a bot run goes: a thread that touches no widget and reports back
        through self.events, which the pump turns into feedback_ok or
        feedback_failed.
        """
        def job():
            payload["result"] = feedback.submit(report, self.state_data)
            self.events.put(("feedback_ok" if payload["result"]["ok"]
                             else "feedback_failed", payload))

        threading.Thread(target=job, daemon=True).start()

    def _header_thumb(self, thumb):
        """One click from the header, at any moment.

        Including in the middle of a run, which is why it never touches a
        run page's thumbs bar: that bar belongs to a run that has finished,
        and relabelling it from here would leave it saying "Thanks." over a
        run still going. The log of the page being looked at travels all the
        same -- a report about a bot without its log says very little.
        """
        if not self._feedback_consent():
            return
        panel = self.panels.get(self.current_page)
        report = feedback.build_report(
            self._page_name(), thumb=thumb,
            log=panel["log"].get("1.0", "end") if panel else "")
        self.header_fb_label.configure(text="Sending...")
        for button in self.header_fb_buttons:
            button.configure(state="disabled")
        self._send_feedback(report, {"key": None, "thumb": thumb,
                                     "header": True})

    def _header_feedback_done(self, text=HEADER_FEEDBACK):
        """Say what became of a header click in the header itself.

        A header button has no page to answer on, and the status bar is the
        line the next bot run writes over.
        """
        self.header_fb_label.configure(text=text)
        for button in self.header_fb_buttons:
            button.configure(state="normal")
        self.after(4000,
                   lambda: self.header_fb_label.configure(
                       text=HEADER_FEEDBACK))

    def _feedback_thumb(self, key, thumb):
        """One click, from either the run page's bar or the Feedback page's
        own pair -- `key` is None from the latter, since there is no run to
        attach a log or a duration to."""
        if not self._feedback_consent():
            return
        panel = self.panels.get(key) if key else None
        log_text = panel["log"].get("1.0", "end") if panel else ""
        bot_name = self._bot_by_key(key)["name"] if key else "Feedback page"
        report = feedback.build_report(
            bot_name, thumb=thumb, log=log_text,
            seconds=panel.get("feedback_elapsed") if panel else None)
        if panel:
            panel["feedback_label"].configure(text="Sending...")
        else:
            self.status.configure(text="Sending feedback...")

        self._send_feedback(report, {"key": key, "thumb": thumb})

    def _on_feedback_ok(self, payload):
        self._save()  # feedback.submit records the send in state_data
        key, thumb = payload["key"], payload["thumb"]
        if payload.get("header"):
            self._header_feedback_done("Thanks.")
            # A thumbs-down sent from the header has said that something is
            # wrong and nothing about what. The one place with room for
            # that is the Feedback page, so it gets named -- but in the
            # status bar, not in a dialog that would land on top of a run.
            self.status.configure(
                text="Thanks." if thumb == "up" else
                     "Thanks. The Feedback page has room to say what went "
                     "wrong.")
            return
        panel = self.panels.get(key) if key else None
        if not panel:
            self.status.configure(text="Thanks.")
            return
        panel["feedback_label"].configure(text="Thanks.")
        panel["feedback_buttons"].pack_forget()
        if thumb == "down":
            # A thumbs-down that sent fine still means something went
            # wrong; the one button left is the invitation to say what.
            panel["feedback_more"].configure(
                text="What went wrong?",
                command=lambda k=key: self._feedback_form(k, thumb="down"))
        else:
            panel["feedback_more"].pack_forget()
            self.after(4000, lambda k=key: self._hide_feedback_bar(k))

    def _on_feedback_failed(self, payload):
        self._save()
        if payload.get("header"):
            self._header_feedback_done()
        # The fallback dialog is now the thing asking the player to act;
        # left showing, the bar would be stuck reading "Sending..." with
        # its Yes/No still underneath it.
        if payload["key"]:
            self._hide_feedback_bar(payload["key"])
        self._feedback_fallback_dialog(payload["result"]["path"])

    def _feedback_fallback_dialog(self, path):
        """Nothing is ever silently dropped: a failed send becomes a file
        plus two buttons, never a swallowed exception."""
        dlg = tk.Toplevel(self)
        dlg.title("Could not send it")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        if not self._bot_running():
            dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="Could not send it.", font=("Segoe UI", 13, "bold")
                 ).pack(anchor="w")
        tk.Label(dlg, text="Your report was saved here:", justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 2))
        tk.Label(dlg, text=path or "(no path)", justify="left", fg="#3c4043",
                 font=("Consolas", 9), wraplength=520
                 ).pack(anchor="w")

        def copy():
            try:
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
            except Exception:
                text = ""
            self.clipboard_clear()
            self.clipboard_append(text)

        row = tk.Frame(dlg)
        row.pack(fill="x", pady=(16, 0))
        tk.Button(row, text="Copy to clipboard", width=17, command=copy
                  ).pack(side="left")
        tk.Button(row, text="Report on GitHub", width=17,
                  command=lambda: webbrowser.open(GITHUB_ISSUES)
                  ).pack(side="left", padx=(6, 0))
        tk.Button(row, text="Close", width=10, command=dlg.destroy
                  ).pack(side="right")

    def _feedback_consent(self):
        """Asked once. Returns whether it is all right to send."""
        if self.state_data.get("feedback_consent"):
            return True
        if self.state_data.get("feedback_declined"):
            return False

        dlg = tk.Toplevel(self)
        dlg.title("Send feedback?")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        if not self._bot_running():
            dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="Before this goes anywhere",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(dlg, justify="left", wraplength=520, font=("Segoe UI", 10),
                 text=("A report carries what you write, the last part of "
                       "the log if there is one, and the version, Windows "
                       "and Python version, and whether adb was found.\n\n"
                       "Nothing from the game screen is ever included.\n\n"
                       )).pack(anchor="w", pady=(10, 14))
        row = tk.Frame(dlg)
        row.pack(fill="x")
        answer = {"go": False}

        def decline():
            answer["go"] = False
            dlg.destroy()

        def accept():
            answer["go"] = True
            dlg.destroy()

        tk.Button(row, text="Not now", width=12, command=decline
                  ).pack(side="left")
        tk.Button(row, text="Send it", width=14, command=accept
                  ).pack(side="right")
        self.wait_window(dlg)
        if answer["go"]:
            self.state_data["feedback_consent"] = True
        else:
            self.state_data["feedback_declined"] = True
        self._save()
        return answer["go"]

    def _feedback_form(self, bot_key=None, thumb=None):
        parts = feedback_parts()
        labels = [label for label, _key in parts]
        key_for_label = {label: key for label, key in parts if key}

        dlg = tk.Toplevel(self)
        dlg.title("Tell me what happened")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        if not self._bot_running():
            dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="Tell me what happened",
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")

        tk.Label(dlg, text="What is this about?",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(14, 2))
        part_var = tk.StringVar(
            value=self._bot_by_key(bot_key)["name"] if bot_key
            else "The Helpermon window itself")
        ttk.Combobox(dlg, textvariable=part_var, state="readonly", width=36,
                    values=labels).pack(anchor="w")

        tk.Label(dlg, text="What happened? What did you expect instead?",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(14, 2))
        text_box = tk.Text(dlg, width=60, height=6, font=("Segoe UI", 10))
        text_box.pack(anchor="w")

        include_log = tk.BooleanVar(value=True)
        log_check = tk.Checkbutton(
            dlg, text="Include the last %d lines of the log"
                     % feedback.LOG_LINES, variable=include_log)
        log_check.pack(anchor="w", pady=(8, 0))

        def current_log():
            return self._log_text(key_for_label.get(part_var.get()))

        def sync_log_checkbox(*_args):
            has_log = bool(current_log().strip())
            log_check.configure(state="normal" if has_log else "disabled")
            include_log.set(has_log)

        part_var.trace_add("write", sync_log_checkbox)
        sync_log_checkbox()

        tk.Label(dlg, text="How can I reach you? (optional - mail, "
                           "Discord, anything)", font=("Segoe UI", 9, "bold")
                 ).pack(anchor="w", pady=(14, 2))
        contact_var = tk.StringVar()
        tk.Entry(dlg, textvariable=contact_var, width=44).pack(anchor="w")
        tk.Label(dlg, text="Leave it empty if you'd rather not say.",
                 fg="#5f6368", font=("Segoe UI", 8)).pack(anchor="w")

        def current_report():
            return feedback.build_report(
                part_var.get(), thumb=thumb,
                text=text_box.get("1.0", "end").strip(),
                log=current_log() if include_log.get() else "",
                contact=contact_var.get().strip())

        disclosure_state = {"open": False}
        disclosure_frame = tk.Frame(dlg)
        preview = tk.Text(disclosure_frame, width=60, height=8,
                          font=("Consolas", 9), state="disabled")
        preview.pack(fill="both", expand=True)

        def toggle_disclosure():
            if disclosure_state["open"]:
                disclosure_frame.pack_forget()
                disclosure_state["open"] = False
                disclosure_button.configure(
                    text="Show exactly what will be sent")
                return
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("1.0", feedback.as_text(current_report()))
            preview.configure(state="disabled")
            disclosure_frame.pack(anchor="w", fill="x", pady=(6, 0))
            disclosure_state["open"] = True
            disclosure_button.configure(text="Hide what will be sent")

        disclosure_button = tk.Button(dlg, text="Show exactly what will be "
                                                 "sent", command=toggle_disclosure)
        disclosure_button.pack(anchor="w", pady=(14, 0))

        row = tk.Frame(dlg)
        row.pack(fill="x", pady=(16, 0))
        tk.Button(row, text="Cancel", width=12, command=dlg.destroy
                  ).pack(side="left")
        send_button = tk.Button(row, text="Send", width=12, state="disabled")
        send_button.pack(side="right")

        def sync_send_button(*_args):
            has_text = bool(text_box.get("1.0", "end").strip())
            send_button.configure(state="normal" if has_text else "disabled")

        text_box.bind("<KeyRelease>", sync_send_button)

        def do_send():
            if not self._feedback_consent():
                return
            report = current_report()
            dlg.destroy()

            self._send_feedback(report, {"key": None, "thumb": thumb})
            self.status.configure(text="Sending feedback...")

        send_button.configure(command=do_send)

    def _page_feedback(self):
        frame = self._page_frame(
            "Feedback",
            "One person reads these. Say what worked, what did not, or "
            "what you would want different.")

        row = tk.Frame(frame, bg=BG)
        row.pack(anchor="w", pady=(14, 4))
        tk.Label(row, text="How is it going?", bg=BG,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=(0, 12))
        tk.Button(row, text="Yes, good", width=11,
                 command=lambda: self._feedback_thumb(None, "up")
                 ).pack(side="left")
        tk.Button(row, text="No, bad", width=11,
                 command=lambda: self._feedback_thumb(None, "down")
                 ).pack(side="left", padx=(6, 0))

        tk.Button(frame, text="Write a report", width=18,
                 command=lambda: self._feedback_form()
                 ).pack(anchor="w", pady=(10, 14))

        tk.Label(frame, text="What travels with a report", bg=BG,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(frame, bg=BG, fg="#70757c", justify="left", wraplength=680,
                 font=("Segoe UI", 9),
                 text=("Version, Windows and Python version, whether adb "
                       "was found, how long the run took, and the log."
                       )).pack(anchor="w", pady=(2, 14))

        tk.Button(frame, text="Open the GitHub form instead", width=28,
                 command=lambda: webbrowser.open(GITHUB_ISSUES)
                 ).pack(anchor="w")

        pending_row = tk.Frame(frame, bg=BG)
        pending_row.pack(anchor="w", pady=(14, 0))

        def refresh():
            for child in pending_row.winfo_children():
                child.destroy()
            try:
                files = [f for f in os.listdir(feedback.FEEDBACK_DIR)
                        if f.endswith(".txt")]
            except OSError:
                files = []
            if not files:
                return
            tk.Label(pending_row, bg=BG, fg="#8a4b00", justify="left",
                     font=("Segoe UI", 9),
                     text="%d report%s saved but not sent."
                          % (len(files), "" if len(files) == 1 else "s")
                     ).pack(side="left", padx=(0, 8))
            tk.Button(pending_row, text="Open the folder", width=16,
                     command=lambda: os.startfile(feedback.FEEDBACK_DIR)
                     ).pack(side="left")

        return {"frame": frame, "refresh": refresh}

    # ==================================================================
    # Plumbing
    # ==================================================================
    def _setup_for(self, bot, note=""):
        """Open a setup window for this bot and nothing else.

        `--bot` decides which steps that window has at all, so Continue past
        the last one finishes instead of wandering into another bot's setup.
        """
        self._start_file("setup_wizard.py",
                         ["--bot", bot["key"],
                          "--step", bot["step"] or "",
                          "--note", note or DEFAULT_NOTES.get(bot["key"], "")])

    def _start_file(self, name, args=()):
        try:
            noconsole.popen([sys.executable, name] + list(args), cwd=HERE)
            self.status.configure(text="%s started" % name)
        except Exception as err:
            messagebox.showerror("Could not start", str(err))

    # ------------------------------------------------------------------
    def _first_run_dialogs(self):
        """What a new user is told before anything else, in this order.

        How Helpermon reaches the emulator comes first, because it decides
        whether the next hour is spent with the mouse or without it, and
        because somebody who reads only the first dialog should have read
        that one.
        """
        if not self.state_data.get("adb_notice_read"):
            self._adb_notice()
        if not self.state_data.get("notice_read"):
            self._legal_notice()

    def _adb_notice(self):
        dlg = tk.Toplevel(self)
        dlg.title("How Helpermon reaches the emulator")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text=ADB_TITLE, font=("Segoe UI", 15, "bold")
                 ).pack(anchor="w")
        tk.Label(dlg, text=ADB_NOTICE, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(10, 12))
        # ADB debugging has to be switched on in LDPlayer -- the first read
        # of this said otherwise, from a config file that showed it off
        # because the player had turned it off again after testing. So the
        # dialog says to switch it on, and this button reports whether that
        # worked rather than leaving anyone to wonder.
        result = tk.Label(dlg, text="", justify="left", fg="#3c4043",
                          wraplength=560, font=("Segoe UI", 10, "bold"))
        result.pack(anchor="w", pady=(0, 12))
        row = tk.Frame(dlg)
        row.pack(fill="x")

        def check():
            result.configure(text="checking...", fg="#3c4043")
            dlg.update_idletasks()
            ok, text = self._adb_probe()
            result.configure(text=text, fg="#1a7f37" if ok else "#8a4b00")

        tk.Button(row, text="Check ADB now", width=16, command=check
                  ).pack(side="left")
        tk.Button(row, text="Continue", width=14, command=dlg.destroy
                  ).pack(side="right")
        self.wait_window(dlg)
        self.state_data["adb_notice_read"] = True
        self._save()

    @staticmethod
    def _adb_probe():
        """(is it usable, one line about it)."""
        try:
            import capture
            path = capture.find_adb()
            if not path:
                # Spelled out, because "point DGUP_ADB at it" was read
                # by a player as the name of a file to go and look for
                # in the Helpermon folder. It is an environment
                # variable, and nothing in the old wording said so.
                return False, (
                    "adb.exe was not found. It comes with LDPlayer and "
                    "sits in the LDPlayer folder, beside dnplayer.exe. "
                    "Helpermon asks Windows where LDPlayer is and looks "
                    "on every hard disk, so this means yours is "
                    "somewhere neither of those finds.\n\n"
                    "Easiest: the Helpermon page has a 'Browse for "
                    "adb.exe...' button under Quick setup, for pointing at "
                    "it directly.\n\n"
                    "DGUP_ADB is not a file to look for, it is an "
                    "environment variable, which is what that button sets. "
                    "Command-line use (dungeon.py --go and the rest) needs "
                    "it set by hand instead:\n\n"
                    '  $env:DGUP_ADB = "C:\\LDPlayer\\LDPlayer14\\adb.exe"\n'
                    "  py app.py")
            devices = capture.AdbCapture().devices()
            if not devices:
                return False, (
                    "adb.exe is there, but no device answers. Most "
                    "likely ADB debugging is still off: LDPlayer, "
                    "Settings, Other settings, ADB debugging. It offers "
                    "three choices and the one to pick is Enable local "
                    "connection -- remote is for driving the emulator "
                    "from another machine.\n\n"
                    "If it is already on, start the emulator and check "
                    "again. LDPlayer turns the setting off again "
                    "between sessions often enough to be worth looking "
                    "twice.")
            return True, ("ADB works, device %s. Nothing to do, the bots will "
                          "use it and leave your mouse alone."
                          % ", ".join(devices))
        except Exception as err:
            return False, "ADB could not be asked: %s" % err

    def _may_run(self, key):
        """The one gate in front of every Start button in this window.

        Two questions, one function, deliberately: `wait_while_paused` in
        the bots answered one of a pair and every bot had to remember to
        ask the other one beside it, and the summon bot forgot -- its Stop
        button did nothing for a release. A gate that answers everything
        standing between a press and a run cannot be half-called.

        Returns whether to go on.
        """
        if key in SUPPORTER_ONLY and not unlock.unlocked():
            return self._supporter_gate(key)
        return self._first_run_notice(key)

    # --- the supporter code -------------------------------------------
    def _locked_name(self, key):
        """The name of a page, without _bot_by_key's fall back to Dungeons.

        That fall back is right where it is used -- any bot's page furniture
        is better than none -- and quietly wrong here, where it would put
        the wrong bot's name on a dialog asking somebody for money.
        """
        for bot in BOTS:
            if bot["key"] == key:
                return bot["name"]
        if key in EXTRA_BOTS:
            return EXTRA_BOTS[key]["name"]
        return key.replace("_", " ").capitalize()

    def _supporter_gate(self, key):
        """Pressed Start on a locked bot. Explain, and offer the two ways on.

        Returns whether the run may go ahead, which it may if a code is
        typed in here and holds -- it carries straight on into the
        requirements notice rather than making somebody press Start again.
        """
        dlg = tk.Toplevel(self)
        dlg.title(SUPPORTER_TITLE)
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text=self._locked_name(key),
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(dlg, text=SUPPORTER_TITLE, fg="#5b3fa8",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(2, 10))
        for text, colour in ((SUPPORTER_WHY, "#202124"),
                             (SUPPORTER_HOW, "#5f6368")):
            tk.Label(dlg, text=text, justify="left", fg=colour,
                     wraplength=520, font=("Segoe UI", 10)
                     ).pack(anchor="w", pady=(0, 8))
        row = tk.Frame(dlg)
        row.pack(fill="x", pady=(10, 0))
        tk.Button(row, text="Not now", width=12, command=dlg.destroy
                  ).pack(side="left")
        got = {"in": False}

        def enter_code():
            if self._code_dialog(parent=dlg):
                got["in"] = True
                dlg.destroy()

        tk.Button(row, text="I have a code", width=16, command=enter_code
                  ).pack(side="right")
        tk.Button(row, text="Open Ko-fi", width=14,
                  command=lambda: webbrowser.open(unlock.KOFI_URL)
                  ).pack(side="right", padx=(0, 8))
        self.wait_window(dlg)
        # Only now the requirements, and only if it is unlocked: a list of
        # what has to be on screen is noise in front of a bot that is not
        # going to start.
        return got["in"] and self._first_run_notice(key)

    def _code_dialog(self, parent=None):
        """Type a code in. Returns whether one was accepted.

        The shape is checked before the code is: the hashing costs a sixth
        of a second on purpose, and a typo should come back at once saying
        it is the wrong length rather than stalling first.
        """
        dlg = tk.Toplevel(parent or self)
        dlg.title("Supporter code")
        dlg.configure(padx=26, pady=20)
        dlg.transient(parent or self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="Type in your supporter code",
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(dlg, fg="#5f6368", justify="left", wraplength=440,
                 font=("Segoe UI", 9),
                 text=("Twelve letters and numbers, like ABCD-EFGH-JKMN. "
                       "Upper or lower case, with or without the dashes.")
                 ).pack(anchor="w", pady=(4, 12))
        entry = tk.Entry(dlg, width=30, font=("Consolas", 14), justify="center")
        entry.pack(anchor="w")
        entry.focus_set()
        note = tk.Label(dlg, text=" ", fg="#b3261e", justify="left",
                        wraplength=440, font=("Segoe UI", 9))
        note.pack(anchor="w", pady=(8, 0))
        done = {"ok": False}

        def try_it(_event=None):
            code = entry.get()
            if not unlock.looks_like_code(code):
                note.configure(
                    text="That is %d characters, and a code is %d."
                         % (len(unlock.normalise(code)), unlock.LENGTH),
                    fg="#b3261e")
                return
            note.configure(text="Checking...", fg="#5f6368")
            dlg.update_idletasks()
            if unlock.redeem(code):
                done["ok"] = True
                dlg.destroy()
                return
            note.configure(
                text=("This version does not know that code. Check it "
                      "character for character -- and if it was working "
                      "before, write to me rather than paying again."),
                fg="#b3261e")

        entry.bind("<Return>", try_it)
        row = tk.Frame(dlg)
        row.pack(fill="x", pady=(14, 0))
        tk.Button(row, text="Cancel", width=12, command=dlg.destroy
                  ).pack(side="left")
        tk.Button(row, text="Unlock", width=14, command=try_it
                  ).pack(side="right")
        self.wait_window(dlg)
        if done["ok"]:
            self._refresh_supporter()
            messagebox.showinfo(
                "Thank you",
                "%s\n\nThe supporter features are open on this machine."
                % SUPPORTER_THANKS)
        return done["ok"]

    def _supporter_box(self, parent, key):
        """The banner on a supporter feature's own page.

        On the page and not only in the dialog, because a bot whose Start
        button opens a request for money with no warning is a worse thing
        than one that says so while you are still reading what it does.
        """
        box = tk.Frame(parent, bd=1, relief="solid", padx=14, pady=10)
        box.pack(anchor="w", fill="x", pady=(14, 0))

        def draw():
            for child in box.winfo_children():
                child.destroy()
            if unlock.unlocked():
                tint, ink = "#e9f5ec", "#1e5c33"
                box.configure(bg=tint)
                tk.Label(box, text=SUPPORTER_THANKS, bg=tint, fg=ink,
                         anchor="w", font=("Segoe UI", 9, "bold")
                         ).pack(anchor="w")
                return
            tint, ink = "#f3edff", "#4b2a91"
            box.configure(bg=tint)
            tk.Label(box, text=SUPPORTER_TITLE, bg=tint, fg=ink, anchor="w",
                     font=("Segoe UI", 10, "bold")).pack(anchor="w")
            stale = unlock.saved()
            if stale:
                tk.Label(box, text=SUPPORTER_STALE % unlock.pretty(stale),
                         bg=tint, fg="#b3261e", anchor="w", justify="left",
                         wraplength=660, font=("Segoe UI", 9, "bold")
                         ).pack(anchor="w", pady=(4, 0))
            for text in (SUPPORTER_WHY, SUPPORTER_HOW):
                tk.Label(box, text=text, bg=tint, fg=ink, anchor="w",
                         justify="left", wraplength=660,
                         font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
            row = tk.Frame(box, bg=tint)
            row.pack(anchor="w", fill="x", pady=(8, 0))
            tk.Button(row, text="Open Ko-fi", width=16,
                      command=lambda: webbrowser.open(unlock.KOFI_URL)
                      ).pack(side="left")
            tk.Button(row, text="I have a code", width=16,
                      command=self._code_dialog).pack(side="left", padx=(8, 0))

        draw()
        self.supporter_boxes.append(draw)
        return box

    def _refresh_supporter(self):
        """Every banner in the window, after a code was redeemed or given
        back. The pages are built once at startup, so without this nothing
        else would notice."""
        for draw in list(self.supporter_boxes):
            try:
                draw()
            except tk.TclError:
                # A page that was torn down. Nothing left to redraw.
                self.supporter_boxes.remove(draw)

    def _first_run_notice(self, key):
        """The bot's requirements, once, the first time it is started.

        Returns whether to go on. Once per bot rather than once per run: the
        list is about what has to be on screen before pressing Start, and
        that is a thing you learn once and then know.
        """
        if self.state_data.get("req_seen_" + key):
            return True
        bot = self._bot_by_key(key)
        dlg = tk.Toplevel(self)
        # "the %s bot" was fine while every caller was one; the
        # passive helper is not a bot and does not read as one.
        dlg.title("Before %s can work" % bot["short"])
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text=bot["name"], font=("Segoe UI", 15, "bold")
                 ).pack(anchor="w")
        tk.Label(dlg, text="This has to be true before it can do anything:",
                 fg="#5f6368", font=("Segoe UI", 10)).pack(anchor="w",
                                                           pady=(4, 10))
        for line in REQUIREMENTS[key]:
            tk.Label(dlg, text="\u2022  " + line, justify="left",
                     wraplength=560, font=("Segoe UI", 10)
                     ).pack(anchor="w", pady=(0, 6))
        tk.Frame(dlg, height=1, bg="#d0d3d8").pack(fill="x", pady=(8, 10))
        for line in INPUT_REQUIREMENT:
            tk.Label(dlg, text="\u2022  " + line, justify="left", fg="#5f6368",
                     wraplength=560, font=("Segoe UI", 9)
                     ).pack(anchor="w", pady=(0, 5))
        row = tk.Frame(dlg)
        row.pack(fill="x", pady=(12, 0))
        go = {"on": False}
        tk.Button(row, text="Cancel", width=12, command=dlg.destroy
                  ).pack(side="left")

        def carry_on():
            go["on"] = True
            dlg.destroy()

        tk.Button(row, text="All set, start", width=16, command=carry_on
                  ).pack(side="right")
        self.wait_window(dlg)
        if go["on"]:
            # Only once it has been read to the end and acted on. Cancelling
            # is not having read it.
            self.state_data["req_seen_" + key] = True
            self._save()
        return go["on"]

    def _legal_notice(self):
        dlg = tk.Toplevel(self)
        dlg.title("Please read")
        dlg.configure(padx=26, pady=20)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text="Before first use",
                 font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(dlg, text=FAN_TITLE, justify="left",
                 font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 2))
        tk.Label(dlg, text=FAN_NOTICE, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 12))
        tk.Label(dlg, text=LEGAL_NOTICE, justify="left",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 14))
        row = tk.Frame(dlg)
        row.pack(fill="x")
        read_ok = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="I have read and understood this",
                       variable=read_ok).pack(side="left")
        button = tk.Button(row, text="Continue", width=14, state="disabled",
                           command=dlg.destroy)
        button.pack(side="right")
        read_ok.trace_add("write", lambda *_: button.configure(
            state="normal" if read_ok.get() else "disabled"))
        self.wait_window(dlg)
        if read_ok.get():
            self.state_data["notice_read"] = True
            self._save()

    def _pump(self):
        while True:
            try:
                kind, text = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                panel = self._panel_now()
                for b in panel["starts"]:
                    b.configure(state="normal")
                for b in (panel["pause"], panel["stop"]):
                    b.configure(state="disabled")
                panel["pause"].configure(text="Pause")
                self.status.configure(text="stopped")
                self._maybe_ask_feedback()
                self.stop = None
                self.active = None
            elif kind == "emu_ok":
                self._set_emulator(True, text)
                self.status.configure(text=text)
            elif kind == "emu_idle":
                self._set_emulator("idle", text)
            elif kind == "emu_bad":
                self._set_emulator(False, text)
                self.status.configure(text=text)
            elif kind == "step":
                # Progress: worth seeing in both places, because the log
                # scrolls and the status bar does not.
                self._write(text, "dim")
                self.status.configure(text=str(text).strip()[:110])
            elif kind == "recheck":
                self.check_emulator()
            elif kind == "status":
                self.status.configure(text=str(text)[:110])
            elif kind == "warn":
                self._write(text, "warn")
                self.status.configure(text=text[:110])
            elif kind == "passive":
                self._write_passive(text)
            elif kind == "passive_warn":
                self._write_passive(text, "warn")
            elif kind == "passive_status":
                self.passive_state.configure(text=text)
            elif kind == "quest_status":
                self.quest_state.configure(text=text)
            elif kind == "feedback_ok":
                self._on_feedback_ok(text)
            elif kind == "feedback_failed":
                self._on_feedback_failed(text)
            else:
                self._write(text)
        self._sync_pause_button()
        self.after(80, self._pump)

    def _sync_pause_button(self):
        """Follow the bot's pause state instead of assuming this window
        caused it. F7 pauses without touching the button, and a button
        claiming the opposite is worse than no button.
        """
        if self.stop is None:
            return
        paused = self.stop.control.is_paused()
        button = self._panel_now()["pause"]
        want = "Continue" if paused else "Pause"
        if button.cget("text") != want:
            button.configure(text=want)
            self.status.configure(text="paused" if paused else "running")

    def _write(self, text, tag=None):
        self._write_into(self._panel_now()["log"], text, tag)

    def _write_into(self, log, text, tag=None, trim=None):
        """The one place either log is written, so the two cannot drift
        apart in how a line looks.

        The clock goes in as its own insert under its own tag. Putting it in
        front of the text and handing both to `tag` would have painted the
        time red on every warning, where it reads as part of the warning
        rather than as when it happened.
        """
        log.configure(state="normal")
        for stamp, line in widgets.stamp_lines(text):
            if stamp:
                log.insert("end", stamp, "time")
            log.insert("end", line + "\n", tag or ())
        if trim and int(log.index("end-1c").split(".")[0]) > trim:
            log.delete("1.0", "%d.0" % (trim // 4))
        log.see("end")
        log.configure(state="disabled")

    # ------------------------------------------------------------------
    def _load(self):
        for path in (STATE_FILE, OLD_STATE_FILE):
            try:
                with open(path) as fh:
                    return json.load(fh)
            except Exception:
                continue
        return {}

    def _save(self):
        try:
            with open(STATE_FILE, "w") as fh:
                json.dump(self.state_data, fh, indent=2)
        except Exception:
            pass

    def _save_keys(self, keys, **extra):
        for key in keys:
            if key in self.vars:
                self.state_data[key] = self.vars[key].get()
        self.state_data.update(extra)
        self._save()


def main():
    app = App()

    def on_close():
        if app.stop:
            app.stop.control.request("window closed")
        if app.passive_stop:
            app.passive_stop.set()
        app._save()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
