"""
Learning the game's icon, finding it again, and waiting out a cold boot.

Synthetic screens throughout: the point is the mechanism -- learn a crop, find
it at another window size, refuse when it is absent, and tell a booting
emulator from a finished one -- and none of that needs the real thing.

Uses a throwaway data folder, never the real userdata.

  py test_launcher.py
"""
import io
import os
import shutil
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FRESH = os.path.join(tempfile.gettempdir(), "helpermon_test_launcher")
shutil.rmtree(FRESH, ignore_errors=True)
os.makedirs(FRESH)
os.environ["DGUP_DATA"] = FRESH

import launcher
import userdata

assert userdata.data_dir() == FRESH, userdata.data_dir()


# =====================================================
# The icon: learning it, and finding it again
# =====================================================
def home_screen(width=765, height=1390, with_game=True):
    """A grid of coloured tiles. The game's is the distinctive one."""
    rng = np.random.RandomState(7)
    img = np.full((height, width, 3), 24, np.uint8)
    step = int(width * 0.24)
    size = int(width * 0.11)
    k = 0
    for row in range(4):
        for col in range(4):
            cx = int(width * 0.14) + col * step
            cy = int(height * 0.12) + row * step
            colour = tuple(int(c) for c in rng.randint(40, 200, 3))
            cv2.rectangle(img, (cx - size // 2, cy - size // 2),
                          (cx + size // 2, cy + size // 2), colour, -1)
            k += 1
    if with_game:
        # The game's icon: a shape nothing else on this screen has.
        cx, cy = int(width * 0.62), int(height * 0.36)
        cv2.rectangle(img, (cx - size // 2, cy - size // 2),
                      (cx + size // 2, cy + size // 2), (30, 200, 250), -1)
        cv2.circle(img, (cx, cy), size // 3, (250, 60, 30), -1)
        cv2.putText(img, "D", (cx - size // 5, cy + size // 5),
                    cv2.FONT_HERSHEY_SIMPLEX, size / 60.0, (255, 255, 255), 3)
    return img


frame = home_screen()
assert not launcher.have_icon()
print("nothing learned to start with")

# Learn it the way the wizard does: a square around the point clicked.
w = frame.shape[1]
half = max(16, int(round(0.055 * w)))
cx, cy = int(w * 0.62), int(frame.shape[0] * 0.36)
launcher.save_icon(frame[cy - half:cy + half, cx - half:cx + half].copy(), w)
launcher.forget_icon()
assert launcher.have_icon()
print("icon learned, %dx%d px" % (2 * half, 2 * half))

found = launcher.find_icon(frame)
assert found and found["ok"], found
assert abs(found["x"] - cx) <= 4 and abs(found["y"] - cy) <= 4, found
print("found again at %d,%d (wanted %d,%d), score %.3f, runner-up %.3f"
      % (found["x"], found["y"], cx, cy, found["score"], found["second"]))

# A home screen without the game must not produce a confident hit.
missing = launcher.find_icon(home_screen(with_game=False))
print("without the game on screen: score %.3f -> %s"
      % (missing["score"], "found" if missing["ok"] else "correctly refused"))
assert not missing["ok"], missing

# A differently sized window: the template is rescaled by the width it was
# learned at, so it still matches.
small = cv2.resize(frame, (574, int(1390 * 574 / 765.0)),
                   interpolation=cv2.INTER_AREA)
resized = launcher.find_icon(small)
print("in a 574 px window: score %.3f -> %s"
      % (resized["score"], "found" if resized["ok"] else "MISSED"))
assert resized["ok"], resized
expect_x = int(574 * 0.62)
assert abs(resized["x"] - expect_x) <= 8, (resized, expect_x)
print("and in the right place, %d vs %d expected" % (resized["x"], expect_x))


# start_game has to verify, not assume.
class FakeCap:
    def __init__(self, changes):
        self.changes = changes
        self.taps = []
        self.n = 0

    def grab(self):
        self.n += 1
        if self.changes and self.taps:
            # What a launching game actually looks like: the whole screen
            # goes to a loading splash, not just the icon disappearing.
            return np.full(frame.shape, 12, np.uint8)
        return frame

    def tap(self, x, y):
        self.taps.append((x, y))


logs = []
cap = FakeCap(changes=True)
assert launcher.start_game(cap, log=logs.append, settle=0.01) is True
assert len(cap.taps) == 1, cap.taps
print("clicks once and confirms the screen changed")

logs = []
cap = FakeCap(changes=False)
assert launcher.start_game(cap, log=logs.append, settle=0.01, tries=2) is False
assert any("did not change" in t for t in logs), logs
print("screen unchanged -> reports failure instead of claiming success")


# =====================================================
# The boot: telling a starting emulator from a started one
# =====================================================
W, H = 960, 540


def boot_frame(n):
    """A boot animation: a spinner that moves every frame."""
    img = np.full((H, W, 3), 12, np.uint8)
    cv2.circle(img, (W // 2 + (n % 5) * 30, H // 2), 40, (200, 200, 200), -1)
    return img


def home_frame():
    img = np.full((H, W, 3), 28, np.uint8)
    rng = np.random.RandomState(2)
    for i in range(8):
        cx = 90 + i * 100
        cv2.rectangle(img, (cx - 35, 120), (cx + 35, 190),
                      tuple(int(c) for c in rng.randint(50, 200, 3)), -1)
    # the game's icon
    cv2.rectangle(img, (455, 300), (525, 370), (30, 200, 250), -1)
    cv2.circle(img, (490, 335), 22, (250, 60, 30), -1)
    return img


def game_frame():
    """The game, already running: static, and no icon on it."""
    img = np.full((H, W, 3), 70, np.uint8)
    cv2.rectangle(img, (100, 100), (860, 440), (120, 40, 40), -1)
    return img


home = home_frame()
launcher.save_icon(home[300:370, 455:525].copy(), W)
launcher.forget_icon()
assert launcher.have_icon()


class Cap:
    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def grab(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f() if callable(f) else f


# --- boots, then the home screen -----------------------------------------
logs = []
cap = Cap([lambda n=i: boot_frame(n) for i in range(6)] + [home] * 10)
out = launcher.wait_for_home(cap, log=logs.append, busy_after=0.0,
                             poll=0.0, timeout=20, still_needed=3)
print("booting then home  -> %s after %d frames" % (out["state"], cap.i))
assert out["state"] == "home", (out, logs)
assert out["icon"]["ok"]

# It must not answer while the thing is still moving.
early = [l for l in logs if "home screen is up" in l]
assert early, logs
print("  said: %s" % early[0])

# --- boots, then the game is already running -----------------------------
logs = []
cap = Cap([lambda n=i: boot_frame(n) for i in range(6)] + [game_frame()] * 10)
out = launcher.wait_for_home(cap, log=logs.append, busy_after=0.0,
                             poll=0.0, timeout=20, still_needed=3)
print("booting then game  -> %s after %d frames" % (out["state"], cap.i))
assert out["state"] == "busy", (out, logs)
assert not (out["icon"] and out["icon"]["ok"])

# --- the real failure: wallpaper up, icons not yet -----------------------
# Perfectly still, and not the finished home screen. Declaring it "already
# running" here is what sent the cold start down the wrong path.
def wallpaper_only():
    img = np.full((H, W, 3), 28, np.uint8)
    cv2.circle(img, (W - 200, H - 120), 90, (40, 60, 90), -1)
    return img


logs = []
frames = ([lambda n=i: boot_frame(n) for i in range(4)]
          + [wallpaper_only()] * 8      # still, no icons -- the trap
          + [home] * 10)
cap = Cap(frames)
out = launcher.wait_for_home(cap, log=logs.append, poll=0.0, timeout=20,
                             busy_after=0.5, still_needed=5)
print("wallpaper then icons -> %s after %d frames" % (out["state"], cap.i))
assert out["state"] == "home", (out, logs)
print("  waits through the half-drawn home screen instead of guessing")

# and with a long enough quiet stretch it still gives up on the icon
logs = []
cap = Cap([lambda n=i: boot_frame(n) for i in range(4)]
          + [wallpaper_only()] * 40)
out = launcher.wait_for_home(cap, log=logs.append, poll=0.0, timeout=20,
                             busy_after=0.0, still_needed=5)
print("wallpaper for ever    -> %s" % out["state"])
assert out["state"] == "busy", out

# --- never settles -------------------------------------------------------
logs = []
cap = Cap([lambda n=i: boot_frame(i) for i in range(200)])


class Forever:
    def __init__(self):
        self.i = 0

    def grab(self):
        self.i += 1
        return boot_frame(self.i)


out = launcher.wait_for_home(Forever(), log=logs.append, busy_after=0.0,
                             poll=0.0, timeout=0.6)
print("never settles      -> %s" % out["state"])
assert out["state"] == "timeout", out


# --- an icon learned by somebody else -------------------------------------
# The wizard runs in its own process. A launcher that had already looked and
# found nothing kept answering "no icon" for the rest of the session, and
# Instant AFK refused to start with the icon sitting on disk. The cache is
# keyed on the file's own timestamp now, so it notices.
import time

os.remove(launcher.icon_path())
launcher.forget_icon()
assert not launcher.have_icon(), "an icon that is gone was still reported"
assert launcher.have_icon() is False   # and the answer "no" is now cached

time.sleep(0.01)
frame = home_screen()
half = max(16, int(round(0.055 * frame.shape[1])))
cx, cy = int(frame.shape[1] * 0.62), int(frame.shape[0] * 0.36)
launcher.save_icon(frame[cy - half:cy + half, cx - half:cx + half].copy(),
                   frame.shape[1])
assert launcher.have_icon(), ("an icon written while 'no icon' was cached "
                              "went unnoticed")
found = launcher.find_icon(frame)
assert found and found["ok"], found
print("an icon learned elsewhere is picked up, no forgetting needed")


# --- one bot, one setup window -------------------------------------------
# The tables in app.py and setup_wizard.py describe the same three bots from
# two sides, and nothing checks that they agree at runtime: a bot whose
# steps are missing would simply open the full wizard again, which is the
# thing that was wrong in the first place. Cheap to check here.
import app
import setup_wizard as W

assert set(W.PAGE_FOR) == set(W.STEPS), \
    "a step with no page, or a page with no step: %s" % (
        set(W.PAGE_FOR) ^ set(W.STEPS))
for name, method in W.PAGE_FOR.items():
    assert hasattr(W.Wizard, method), "%s has no %s" % (name, method)

for bot in app.BOTS:
    key = bot["key"]
    assert key in app.REQUIREMENTS, "%s has nothing to say about what it needs" % key
    assert app.REQUIREMENTS[key], key
    assert key in W.BOT_STEPS, "%s has no setup window of its own" % key
    title, order = W.BOT_STEPS[key]
    assert title and order, key
    stray = [step for step in order if step not in W.STEPS]
    assert not stray, "%s asks for steps that do not exist: %s" % (key, stray)
    # The step a bot opens on has to be one of its own, or the window falls
    # back to the first step without saying so.
    assert bot["step"] in order, \
        "%s opens on %r, which is not in %s" % (key, bot["step"], order)
print("every bot has its own steps, and only its own")

# --- everything the gate is asked about, not just the three bots ----------
# `_may_run` is one function in front of every start in the window, and it
# ends in the requirements notice, which reads two tables: `_bot_by_key` for
# the name on it and REQUIREMENTS for the lines in it. The passive helper
# was in neither. `_bot_by_key` says nothing about that -- it falls back to
# Dungeons -- so the notice came up titled after the wrong bot and then
# raised KeyError half way down, leaving a modal dialog with a grab on it,
# no buttons, and no way on. The loop above only ever looked at BOTS, and
# the helper is not one.
#
# Read out of the source rather than listed here, for the same reason
# test_unlock.py reads it: a new start button is a new line of code, not a
# line in a test file somebody remembers to add.
import re

app_src = io.open(os.path.join(os.path.dirname(os.path.abspath(app.__file__)),
                               "app.py"), encoding="utf-8").read()
gated = sorted(set(re.findall(r'_may_run\("([^"]+)"\)', app_src)))
assert gated, "nothing in the window goes through the gate"
for key in gated:
    assert key in app.REQUIREMENTS, \
        "%s can be started and has nothing to say about what it needs" % key
    assert app.REQUIREMENTS[key], key
    # The fall back in `_bot_by_key` is right where it is used and wrong
    # here: it would put another bot's name on this one's notice, so the
    # tables are asked directly.
    entry = app.EXTRA_BOTS.get(key) or next(
        (b for b in app.BOTS if b["key"] == key), None)
    assert entry, "%s can be started and is in neither bot table" % key
    for field in ("name", "short"):
        assert entry.get(field), "%s has no %s" % (key, field)
print("every key the gate is asked about has a name and its own "
      "requirements: %s" % ", ".join(gated))

# --- the way into the wizard is offered only where it leads somewhere -----
# `_setup_for` reads `bot["step"]` to say which wizard page to open on, so a
# "Set up this bot" button on a bot without one dies of KeyError on the
# press. Summon's page carried exactly that, and nothing found out: no suite
# renders a page, and the button is one nobody on that page needs. The
# decision is a function rather than a condition inside the widget so that
# it can be asked here at all.
offered = [bot for bot in list(app.BOTS) + list(app.EXTRA_BOTS.values())
           if app.needs_setup_button(bot)]
assert offered, "no page offers the way into setup at all"
for bot in offered:
    assert bot.get("step"),         "%s offers a setup button and has no step to open on" % bot["key"]
    assert bot["key"] not in app.EXTRA_BOTS,         "%s has no wizard page and is offered one" % bot["key"]
# And the other way round: a bot whose box says nothing has to be taught
# must not be offered the button, which is the dungeon bot's whole case.
assert not app.needs_setup_button(app.BOTS[0]),     "the dungeon bot needs nothing taught and is offered setup anyway"
print("the setup button is offered only where the wizard has a page: %s"
      % ", ".join(bot["name"] for bot in offered))

# --- every requirements box on every page has something to say ------------
# The Bond & Quest page was the one page with no box at all, which is how a
# helper whose only failure mode is standing on the wrong screen was the
# page that never said which screen it wants. Read out of the source, so a
# new page is covered without anybody adding a line here.
drawn = sorted(set(re.findall(r'_requirements\(\w+, "([^"]+)"', app_src)))
assert drawn, "no page says what it needs"
for key in drawn:
    assert key in app.REQUIREMENTS,         "%s draws a requirements box out of a table that has no entry" % key
    assert app.REQUIREMENTS[key], key
for key in app.REQUIREMENTS:
    assert key in drawn,         "%s has requirements and no page that shows them" % key
print("every page says what it needs, and every entry is shown: %s"
      % ", ".join(drawn))

# --- the report dialog knows about every bot ------------------------------
# "What is this about?" was built out of BOTS alone, so the two pages that
# are not in BOTS -- Special Summon and the quest loop, the newest things in
# the window and the likeliest to be reported -- could not be named in a
# report at all. Whoever wrote one had to file it under another bot's name,
# and the log that travelled with it was that other bot's log. Both tables
# again, checked the same way the gate above is.
parts = app.feedback_parts()
labels = [label for label, _key in parts]
assert len(labels) == len(set(labels)), "two menu entries read the same: %s" % labels
named = {key for _label, key in parts if key}
for bot in list(app.BOTS) + list(app.EXTRA_BOTS.values()):
    assert bot["key"] in named,         "%s has a page of its own and cannot be named in a report" % bot["key"]
    assert bot["name"] in labels, bot["name"]
# And the other way: a key in the menu that no page answers to would send
# the dialog looking for a log that does not exist.
known = {b["key"] for b in app.BOTS} | set(app.EXTRA_BOTS)
assert named <= known, "menu names a bot that is in neither table: %s" % (
    named - known)
assert [label for label, key in parts if key is None],     "nothing in the menu for the parts of the program that are not a bot"
print("the report dialog offers every bot page and nothing else: %s"
      % ", ".join(labels))

everything = [s for order in
              (o for _t, o in W.BOT_STEPS.values()) for s in order]
spare = [s for s in W.STEPS if s not in everything]
print("steps no single bot owns, reachable only in the full wizard: %s"
      % (", ".join(spare) or "none"))

shutil.rmtree(FRESH, ignore_errors=True)
print("all launcher cases as expected")
