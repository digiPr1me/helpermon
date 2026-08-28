"""
Dungeon bot. Works through the dungeon list once, top half then bottom.

A different bot from the minigame one. That one solves a grid with cost
arithmetic; this one deals with screens and buttons, so it is a state machine.

Recognition without any game images. The buttons separate unambiguously by
colour and horizontal position, measured across two window sizes.

  Attempt                    blue,   rel. x 0.66, or 0.50 when it stands alone
  Find a Party               blue,   rel. x 0.50
  Clear Previous Difficulty  violet, rel. x 0.34, ignored
  Ad                         violet, rel. x 0.50

That way no third-party image material sits in the program folder, and a game
update only breaks recognition if colours or layout change.

Same principle as the other bot: never click blindly. Every action is verified
by the state change. If the expected state does not arrive, nothing is clicked
again; the bot resets or stops.

  py dungeon.py --probe          shows what is recognised, clicks nothing
  py dungeon.py                  dry run, plans but does NOT click
  py dungeon.py --go             actually clicks
  py dungeon.py --list-dungeons  short names for --only and --skip

F7 pauses/resumes and F8 aborts globally, even with the emulator window in
focus instead of this console. See guard.py. Disable both with
--no-hotkeys. Moving the mouse no longer pauses anything.
"""

import argparse
import time

import cv2
import numpy as np

import capture
import guard
import userdata
import vision

# Device aspect ratio. Used to compute away the emulator window's title bar
# without detecting it.
DEVICE_ASPECT = 1080 / 1920.0

# Colour ranges in HSV
BLUE = ((95, 150, 150), (115, 255, 255))
# Measured on the buttons themselves, H 122 to 125, S 152 to 170, V 235.
# The old lower bound of 125 sat exactly on the edge and found the ad button
# or not depending on the frame.
VIOLET = ((117, 100, 120), (145, 255, 255))

# Expected horizontal position of the buttons, relative to the game width
POS_ATTEMPT = 0.66
POS_CENTER = 0.50
POS_CLEAR = 0.34
POS_TOLERANCE = 0.06

# Attempt sits at 0.66 when Clear Previous Difficulty is next to it. If that
# is missing, Attempt sits centred, measured at Apocalymon Wall 0.501. A
# single blue button in the dialog is therefore always Attempt.
BUTTON_MAX_Y = 0.88
ATTEMPT_W = (0.18, 0.36)

# The Close button on Apocalymon Wall's results screen sits centred at 0.503
# and 0.792, almost exactly where Apocalymon's own Attempt button sits,
# measured 0.501 and 0.756. They are told apart by width, measured Close
# 0.216 against Attempt 0.261 to 0.301. The threshold sits between them with
# margin on both sides.
CLOSE_W_MAX = 0.24

# Give Up during a battle, centred at the very bottom. Measured 0.502 at
# 0.954. Without this detection the bot mistook battle artwork for the
# Attempt button, measured 0.681 at 0.698 with matching size.
POS_GIVEUP_Y = 0.90

# Buttons sit in the lower part of the dialog. The filter keeps artwork out,
# for example DemiDevimon's violet wings at y 0.34.
BUTTON_MIN_Y = 0.45

# Neutral spot for tapping away rewards. Deliberately high up, above any
# dialog. A tap in the middle of the screen acts like the back key when a
# party exists and opens the "disband the party" prompt.
NEUTRAL_TAP_Y = 0.12

# Party slots at Network Defense Ops. Three fields side by side. An empty
# slot is a uniformly dark area, measured standard deviation 0.0, an
# occupied one shows a figure, measured 28 to 56. The dialog itself looks
# identical with and without a party, both buttons sit at the same place, so
# this is the only way to see the difference before clicking.
#
# The half-width is 0.07 and not 0.10 because the wider crop reached past
# the right-hand slot onto the panel's own bright edge. Measured on a real
# frame with one slot filled, half-width against standard deviation:
#
#              left (empty)   middle (full)   right (empty)
#   0.10            3.0            49.9            13.8   <- counted as full
#   0.08            0.0            55.0             8.5
#   0.07            0.0            56.0             3.6
#
# That misread said two slots were filled, so the bot never searched for a
# party, pressed Attempt without one, and Attempt does nothing without one.
PARTY_SLOTS = (0.27, 0.50, 0.73)
PARTY_SLOT_Y = 0.45
PARTY_SLOT_HALF_W = 0.07
PARTY_SLOT_MIN_STD = 12.0

# Bottom nav bar, dungeon tab. Fixed, because the bar does not scroll.
NAV_DUNGEON = (0.377, 0.957)

# The OK button of the pop-ups the game opens after logging in. Measured on
# two of them: centred at 0.475 with the button spanning roughly a third of
# the width, at 0.905 down the screen.
#
# Note what this collides with: POS_GIVEUP_Y is 0.90, so recognise() calls
# any blue button below that near the centre a battle's Give Up button, and
# these pop-ups therefore read as BATTLE. That is only safe to act on while
# waking the game up, when no battle can be running yet -- see wake_up.
POPUP_OK_Y = (0.86, 0.95)
POPUP_OK_FX = (0.35, 0.65)
POPUP_OK_MIN_W = 0.15

# The Claim button of the idle-rewards dialog, measured off a real one:
# centred at 0.597, 0.746, with a violet "Extra Rewards" button immediately
# to its left that watches ads for more.
#
# That violet neighbour is not decoration, it is the identification. The
# Notices dialog puts its "Campaigns" tab at 0.476, 0.733 -- same colour,
# same band, near enough the same width -- and an earlier version pressed it
# repeatedly believing it was Claim. No position test separates those two.
# The pair does: Notices has no violet button anywhere.
POS_CLAIM_Y = (0.68, 0.82)
POS_CLAIM_FX = (0.45, 0.85)
POS_CLAIM_MIN_W = 0.12
CLAIM_PAIR_DY = 0.03

# List cards. They all sit centred at relative x 0.49 and have width 0.77,
# measured across both window sizes. Dialogs and the battle screen show
# different widths, so this signature separates the list unambiguously.
CARD_X = 0.49
CARD_X_TOL = 0.05
CARD_W_MIN = 0.72
CARD_W_MAX = 0.85
LIST_MIN_CARDS = 3

# Dungeon names, in the order of the list from top to bottom. The bot does
# not read them, it counts cards. The names only serve the log, so the
# transcript shows what is being played rather than "card 3".
DUNGEON_NAMES = [
    "Apocalymon Wall",
    "Fight! DemiDevimon",
    "Fight! Bakemon",
    "Fight! Digifactory",
    "Network Defense Ops",
    "Metal Sea",
    "Daily changing dungeon",
]


# Short names for the command line, in the same order as DUNGEON_NAMES
DUNGEON_KEYS = ["apocalymon", "demidevimon", "bakemon", "digifactory",
                "network", "metalsea", "daily"]


def dungeon_index(key):
    """Number of a dungeon from its short name. Partial matches are also
    accepted, so 'apo' is enough."""
    key = key.strip().lower()
    if not key:
        return None
    if key.isdigit():
        n = int(key) - 1
        return n if 0 <= n < len(DUNGEON_KEYS) else None
    matches = [i for i, k in enumerate(DUNGEON_KEYS) if k.startswith(key)]
    return matches[0] if len(matches) == 1 else None


def parse_selection(text, total=7):
    """Translate a list of short names into numbers.

    A leading minus excludes, everything else includes. With no argument, all
    are included except the last, which changes daily.

      --only apocalymon,network     nur diese beiden
      --skip apocalymon             alle ausser Apocalymon
    """
    unknown_names = []
    numbers = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        idx = dungeon_index(part)
        if idx is None:
            unknown_names.append(part)
        else:
            numbers.append(idx)
    return numbers, unknown_names


def dungeon_label(index, von_unten=False, total=7, sichtbar=5):
    """Name of an entry. Counted from the bottom, the first visible entry
    sits at total minus sichtbar."""
    pos = (total - sichtbar + index) if von_unten else index
    if 0 <= pos < len(DUNGEON_NAMES):
        return DUNGEON_NAMES[pos]
    return "Eintrag %d" % (pos + 1)

# Ticket badge in the list card. The ticket count sits at the bottom left,
# possibly with a second counter for ad attempts next to it.
BADGE_X = 0.10
BADGE_W = 0.34  # wide enough for the ticket and ad counters side by side
# Distance of the badge from the card's bottom edge, plus its height
BADGE_BOTTOM_OFF = 0.008
BADGE_H = 0.040

# Whether a counter reads 0 can be read from the leading digit, without any
# digit recognition. The zero has a hole in the middle, measured 0.00 against
# 0.33 to 0.93 for all other digits. The digit set from the minigame does not
# fit here, the font is different.
ZERO_HOLE_MAX = 0.15

# Smallest character in a counter, as a share of the badge crop's height.
# Measured over nine cards on two frames, and the spread within each kind is
# under half a percent:
#
#   ticket digits   0.269 - 0.279      ticket slash   0.337 - 0.346
#   ad digits       0.226 - 0.231      ad slash       0.288 - 0.293
#
# This used to be 0.28, which falls between the ticket digits and the ad
# slash -- the worst place there is. It threw away every digit of the counter
# that matters and kept the slash of the one that does not, so the ticket
# count read as unreadable on every card and every dungeon was played
# "unclear, will try it". At 0.20 all four kinds come through; what else
# comes with them is thrown out by the slash rule below.
GLYPH_MIN_H = 0.20

# A slash is narrow and clearly taller than the digits beside it. Measured:
# 71 against 57 in the ticket counter, 60 against 47 in the ad counter, so
# 1.25 and 1.26 -- the same proportion in both, which is what a font does.
SLASH_MIN_RATIO = 1.12
SLASH_MAX_WH = 0.60

# States
LIST = "liste"
DIALOG = "dialog"
DIALOG_PARTY = "dialog_party"
DIALOG_AD = "dialog_werbung"
# What the game is doing while nothing else is: it is an idle game and
# the party clears stages in the background the whole time. The name is
# printed straight into the log, so it says that rather than "kampf".
BATTLE = "battling in stages"
# Confirmation dialogs with two buttons side by side, cancel on the left,
# confirm on the right. Two cases are known and both are dangerous.
#
#   "Exit the game?"                OK closes the game
#   "Disband the party and leave?"  OK disbands the party
#
# Measured, both buttons sit at the same place, OK at 0.59 to 0.64 and Cancel
# at 0.36 to 0.40, same size each. Hence one state for both, leaving is
# always done via the left button.
EXIT = "sicherheitsabfrage"

# THREE dialogs wear this face, and they do not share an answer. Cancel is
# not always the safe choice, and neither is OK.
#
#   "Exit the game?"                 grey Cancel, OK at 0.561 / 0.652.
#                                    Only ever seen on the title screen.
#                                    OK ends the session, so Cancel.
#   "Disband the party and leave?"   pink Cancel, OK at 0.602 / 0.599.
#                                    Cancel keeps the bot stuck in the
#                                    dungeon panel, OK returns to the list.
#                                    Looks the same whether or not there is
#                                    a party in the slots, confirmed by the
#                                    player -- so the pink test holds for
#                                    the solo case too.
#   "Return to the title screen?"    pink Cancel, OK at 0.602 / 0.599.
#                                    What the back key raises in the game
#                                    with nothing open. OK throws the
#                                    session away, so Cancel.
#
# The last two are the same picture. Measured on real frames of both, the
# sample over the Cancel button is identical to the pixel: 0.648 of it in
# hue 140-150 either way. Nothing in the dialog separates them -- only the
# text does, and this bot reads no text so that it works in every language.
#
# So colour answers one question only: is this the game-exit prompt (grey,
# measured 0.000 in that hue band) or one of the two in-game prompts (pink,
# 0.648). Which of the two in-game ones it is has to come from the caller,
# which knows whether it was just trying to leave a dungeon. See
# dismiss_confirm.
EXIT_CANCEL_SAT_MAX = 100
# Hue of the pink Cancel button, in OpenCV's 0-179 scale. Saturation alone
# cannot carry this: the dialog's own background is blue and just as
# saturated, and sampling that instead of the button is how an exit dialog
# came to be read as a party dialog. Pink is a hue; blue is a different one.
#
# The band starts at 135 and not at 150 because the real button measures
# hue 140-150 with saturation 147. At (150, 179) it scored 0.021 against the
# 0.15 the test asks for, so every pink prompt read as the exit prompt, was
# answered with Cancel, and the bot sat in the dungeon panel until it gave
# up. The grey Cancel of the real exit prompt sits at hue 100-110 and scores
# 0.000 in this band, so the margin is the whole range.
PARTY_PINK_HUE = (135, 175)
UNKNOWN = "unknown"

# The game's exit confirmation. It appears when the back key is pressed and
# no dialog is open. Two buttons side by side at about half height, grey
# Cancel on the left at 0.40 and blue OK on the right at 0.59, measured. OK
# would close the game, so this screen must be reliably recognised and left
# via Cancel.
POS_EXIT_OK = 0.61
POS_EXIT_CANCEL = 0.38
EXIT_TOL = 0.07
EXIT_Y = (0.50, 0.75)
EXIT_W = (0.12, 0.24)


# Every fx/fy in this file is a fraction of the *window image*, because that
# is what they were measured on: 805 x 1390 frames from screen capture, with
# LDPlayer's own chrome part of the picture. GAME_IN_WINDOW says where the
# game sat inside that reference window -- left, top, width, height as
# fractions of it -- and so defines what those numbers mean.
#
# Measured by matching a window frame against the ADB frame of the same
# screen, correlation 0.99: the game is 758 x 1348 at 4, 40. A 40 px tab bar
# on top and a 43 px sidebar on the right are therefore inside every fraction
# in this file.
# Measured in capture.py, next to the window class it describes.
GAME_IN_WINDOW = capture.GAME_IN_WINDOW

# The same chrome in pixels: left, top, right, bottom. It does not scale with
# the window, which is why a fraction of the window image is only worth
# anything once the window has been measured -- at 619 wide the sidebar is
# 6.9 % of the width instead of 5.3 %, and a fraction read as if the window
# were still 805 wide lands 18 device pixels off.
WINDOW_CHROME = capture.WINDOW_CHROME

# The chrome above, cross-checked against the one thing that cannot change:
# the game's own aspect. If what is left after taking the chrome off is not
# that shape, this is not the window layout that was measured, and the frame
# is used as it comes rather than on a guess.
CHROME_ASPECT_TOL = 0.01

# How far a frame's aspect may sit from the device's before it is taken for a
# window frame rather than a bare game frame. The two are 0.5625 against
# 0.5791, so anything under half that gap separates them with room to spare.
DEVICE_ASPECT_TOL = 0.008


# ----------------------------------------------------------------------------
def _window_space(x0, y0, gw, gh):
    """The window a game area of this size and place would sit in.

    Returned rather than the game area itself so that one vocabulary covers
    both sources. See GAME_IN_WINDOW for why that vocabulary is the window
    and not the game.
    """
    fx0, fy0, fw, fh = GAME_IN_WINDOW
    ww, wh = gw / fw, gh / fh
    return (int(round(x0 - ww * fx0)), int(round(y0 - wh * fy0)),
            int(round(ww)), int(round(wh)))


def game_rect(img):
    """Reference rect for every fraction in this file, in this frame's pixels.

    Two kinds of frame arrive here and both have to answer with the same
    vocabulary, because the same constants are read off both.

    A frame from ADB is the game area and nothing else, so what comes back is
    wider than the image and starts above and left of it -- the window the
    game would sit in. Checked against the auto button: found at 0.3778 and
    0.7604 of a device frame, which is 0.3607 and 0.7662 of that window,
    against the measured constant 0.361 and 0.766.

    A window frame has the chrome in it. The game area is found by taking
    WINDOW_CHROME off, and is then stretched back to the reference window, so
    that a window of any size answers with the numbers the reference window
    would have given. At 805 x 1390 that is exactly the frame as it comes,
    which is what every constant here was measured against.

    Anything whose shape does not fit the measured layout is used as it comes.
    That is the old behaviour, and it is the right answer for a picture this
    function has no business making assumptions about.
    """
    h, w = img.shape[:2]
    if abs(w / float(h) - DEVICE_ASPECT) <= DEVICE_ASPECT_TOL:
        return _window_space(0, 0, w, h)
    left, top, right, bottom = WINDOW_CHROME
    gw, gh = w - left - right, h - top - bottom
    if gw > 0 and gh > 0 and abs(gw / float(gh) - DEVICE_ASPECT) <= CHROME_ASPECT_TOL:
        return _window_space(left, top, gw, gh)
    fitted = _fitted_game(w, h)
    if fitted is not None:
        return _window_space(*fitted)
    return 0, 0, w, h


def _fitted_game(w, h):
    """The game area in a window that has no sidebar, or None.

    The layout above is LDPlayer with its sidebar out: tab bar on top,
    sidebar on the right, and the game filling the rest exactly. Without the
    sidebar that arithmetic no longer comes out at the game's aspect, and
    what used to happen then was that the whole image was used as it came.
    That works while the window is roughly the shape of the game and drifts
    the moment it is not: the game is then letterboxed inside the window, and
    every fraction in this file slides by however wide the bars are.

    It cost the passive helper a session. Resized to 730 x 1389 -- an aspect
    of 0.5256 where the game wants 0.5625 -- the bars came to 25 pixels top
    and bottom, the hologram counter slid out of the top of its crop, and
    every round for two minutes reported that it could not read a number
    that was plainly on the screen.

    So: take the tab bar off the top, fit the game into what is left keeping
    its own aspect, and centre it. Checked against the auto button, whose
    place in the game is known, over eight frames at five window shapes:

        window        this model    top-aligned instead
        765 x 1390    0 / +2 px     0 / +2 px
        657 x 1198    0 / +2 px     0 / +2 px
        651 x 1195    0 / -0 px     0 / -0 px
        573 x 1056    0 / -0 px     0 / -0 px
        497 x  914    0 / +2 px     0 / +2 px
        730 x 1389    0 / +1 px     0 / -25 px

    The last row is the one that decides it: where the window is the wrong
    shape the bars are real, and they are shared top and bottom.
    """
    space = h - WINDOW_CHROME[1]
    if space <= 0 or w <= 0:
        return None
    gw = min(float(w), space * DEVICE_ASPECT)
    gh = gw / DEVICE_ASPECT
    # A picture this model would read as mostly border is not a window with a
    # game in it, and is better used as it comes.
    if gw < 0.5 * w or gh < 0.5 * h:
        return None
    return (int(round((w - gw) / 2.0)),
            int(round(WINDOW_CHROME[1] + (space - gh) / 2.0)),
            int(round(gw)), int(round(gh)))


def to_pixel(img, fx, fy):
    """Relative position in window pixels."""
    x0, y0, gw, gh = game_rect(img)
    return int(round(x0 + fx * gw)), int(round(y0 + fy * gh))


def find_buttons(img, colour, min_area=0.004, min_y=BUTTON_MIN_Y):
    """Find wide, strongly coloured buttons."""
    x0, y0, gw, gh = game_rect(img)
    mask = cv2.inRange(cv2.cvtColor(img, cv2.COLOR_BGR2HSV), *colour)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 15), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area * gw * gh:
            continue
        # The ad button, at about 7 to 1, is clearly wider than the others.
        # With the old upper bound of 6 it fell through and the bot treated
        # the dialog as unknown.
        if not 1.2 < w / max(h, 1) < 9.0:
            continue
        fx = (x + w / 2.0) / gw
        fy = (y + h / 2.0 - y0) / gh
        if fy < min_y:
            continue
        out.append({"fx": fx, "fy": fy, "fw": w / gw, "fh": h / gh})
    out.sort(key=lambda b: b["fy"])
    return out


def near(value, target, tol=POS_TOLERANCE):
    return abs(value - target) <= tol


def list_cards(img, with_size=False):
    """Vertical centres of the list entries, from top to bottom.

    Detected live instead of read from fixed positions. That way it fits any
    scroll position and any window size. With with_size, the card height is
    included too, needed because the first entry is a taller banner and a
    fixed offset from the centre would not hold for it.
    """
    out = []
    for b in find_buttons(img, BLUE, min_area=0.002, min_y=0.0):
        if not near(b["fx"], CARD_X, CARD_X_TOL):
            continue
        if not CARD_W_MIN <= b["fw"] <= CARD_W_MAX:
            continue
        out.append((b["fy"], b["fh"]))
    out.sort()
    return out if with_size else [fy for fy, _ in out]


def badge_crop(img, fy, fh=None):
    """Crop containing a list card's counters.

    The reference point is the card's bottom edge, not its centre. Cards
    vary in height, the first banner is noticeably taller than the rest. With
    a fixed offset from the centre, the crop missed there.
    """
    x0, y0, gw, gh = game_rect(img)
    fh = fh if fh else 0.118
    bottom_list = fy + fh / 2.0
    y = int(y0 + (bottom_list - BADGE_BOTTOM_OFF - BADGE_H) * gh)
    h = int(BADGE_H * gh)
    x = int(x0 + BADGE_X * gw)
    w = int(BADGE_W * gw)
    return img[max(0, y):y + h, max(0, x):x + w]


def badge_glyphs(img, fy, fh=None, scale=4):
    """Characters in the ticket badge, from left to right."""
    crop = badge_crop(img, fy, fh)
    if crop.size == 0:
        return None, []
    big = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale),
                     interpolation=cv2.INTER_CUBIC)
    mask = cv2.inRange(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), 200, 255)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = [s for s in stats[1:]
           if s[4] > 200 and 0.15 < s[2] / max(s[3], 1) < 1.2
           and s[3] > GLYPH_MIN_H * mask.shape[0]]
    out.sort(key=lambda s: s[0])
    return mask, out


def group_glyphs(glyphs):
    """Characters split into counters, by the gap between them.

    A counter reads n/2 and its characters sit close together; a clear gap
    separates one counter from the next.
    """
    if not glyphs:
        return []
    groups = [[glyphs[0]]]
    for before, now in zip(glyphs, glyphs[1:]):
        gap = now[0] - (before[0] + before[2])
        if gap > 3 * before[2]:
            groups.append([now])
        else:
            groups[-1].append(now)
    return groups


def counter_digits(group):
    """The digits of one counter, or None if this group is not a counter.

    The proof is the slash: narrow, and taller than the digits around it. It
    is what tells a counter from the rest of the artwork in the crop -- the
    Apocalymon card carries a medal and the word "Rose" in the same strip,
    and its letters are the height of a digit. They have no slash, so they
    are not a counter.

    Only what stands to the left of the slash is returned. That is the count;
    to the right is the daily allowance, which is always two.
    """
    if len(group) < 2:
        return None
    tallest = max(group, key=lambda g: g[3])
    others = [g[3] for g in group if g is not tallest]
    if not others:
        return None
    median = sorted(others)[len(others) // 2]
    if tallest[3] < SLASH_MIN_RATIO * median:
        return None
    if tallest[2] / max(tallest[3], 1) > SLASH_MAX_WH:
        return None
    left = [g for g in group if g[0] + g[2] <= tallest[0]]
    return left or None


def is_zero_digit(mask, stat):
    """Is this digit a zero? Measured by the hole in the middle."""
    glyph = mask[stat[1]:stat[1] + stat[3], stat[0]:stat[0] + stat[2]]
    if glyph.size == 0:
        return False
    glyph = cv2.resize(glyph, (20, 28))
    return float((glyph[9:19, 7:13] > 127).mean()) <= ZERO_HOLE_MAX


# How a digit is measured. The glyph is squashed onto a 12 x 16 grid first,
# so a counter reads the same whatever size the emulator window is -- these
# very numbers were taken from two windows, 760 x 1310 and 619 x 1059.
#
# Deliberately no stored pictures of the digits. They would be images taken
# from the game, which is the one thing this program does not ship, and it
# would turn the dungeon bot into a bot that needs setting up. Shapes are
# described by numbers instead, the way every other threshold here is.
#
# Measured on Apocalymon counting down from 46 to 37, which walks the units
# place through all ten digits, plus the tens place giving 4 and 3:
#
#   digit  holes  hole y   ink   top    bottom  right
#     0      1     0.47    0.49  0.42    0.54    0.64
#     1      0      -      0.41  0.33    0.88    0.16
#     2      0      -      0.44  0.50    1.00    0.53
#     3      0      -      0.45  0.54    0.71    0.67
#     4      1     0.45    0.41  0.29    0.17    0.58
#     5      0      -      0.49  0.79    0.67    0.50
#     6      1     0.63    0.53  0.58    0.58    0.53
#     7      0      -      0.35  1.00    0.21    0.30
#     8      2     0.47    0.56  0.58    0.71    0.67
#     9      1     0.33    0.52  0.50    0.54    0.66
#
# The thresholds below sit in the gaps of that table. The two roomiest are
# the 4, whose bottom is empty at 0.17 against 0.54 for every other one-hole
# digit, and the 2, whose bottom bar is solid. The tightest are the hole
# positions that separate 9, 0 and 6, with 0.05 to 0.08 either side; those
# are the ones to widen first if a digit is ever read wrongly.
DIGIT_GRID = (12, 16)
D4_BOTTOM_MAX = 0.35        # 4 against 0, 6, 9
D9_HOLE_MAX = 0.40          # 9 against 4 and 0
D6_HOLE_MIN = 0.55          # 6 against 0
D7_BOTTOM_MAX = 0.35        # 7, the only holeless digit with an empty foot
D1_RIGHT_MAX = 0.25         # 1, which is empty on its right
# ...except where the 1 stands on a serif. The quest card's font draws it
# with a full bar under it, and that bar reaches the right edge: measured
# on "Defeat 12/50", right came to 0.38 over the whole glyph, sailed past
# the test above, and the 1 was then read as a 2 on the next line down
# (bottom 0.92, over D2_BOTTOM_MIN). Six other 1s on the same run of cards
# measured 0.12 to 0.20 and were read correctly, so this is not a
# threshold to widen -- 0.38 is a different shape, not a noisier one.
#
# What no 1 has, serif or not, is ink on its right *above* the foot.
# Measured over the rows between the flag and the bar, the last three
# columns of the grid:
#
#   1 (n=7)                     0.00
#   every other digit (n=65)    0.45 to 0.91
#
# So the floor sits at 0.15: three times under the lowest of the others,
# and above nothing at all, which is what a 1 has there.
D1_ROWS = (2, 13)
D1_RIGHT_COLS = 3
D1_UPPER_RIGHT_MAX = 0.15
D2_BOTTOM_MIN = 0.85        # 2 against 3 and 5

# 5 against 3, and this one was learned the hard way. It went by the top
# band first, on the reasoning that the 5 opens with a solid bar while the 3
# opens with an arc -- 0.79 against 0.54, which looked like room enough. In a
# live window one size smaller the arc of a 3 filled out to 0.75 and it was
# read as a 5, so 34 tickets became 54.
#
# The row below the top says it far more plainly, and it says it about the
# shape rather than about how thickly the shape was drawn: under its opening
# the 5 carries a stem down the left with nothing on the right, and the 3
# carries its bulge on the right with nothing on the left.
#
#   rows 3 to 6      left quarter    right quarter
#     5                  0.75            0.00
#     3                  0.00            0.85
#
# So the test is which flank is heavier, and the gap is the whole width of
# the glyph rather than a tenth of a measurement.
D53_ROWS = (3, 7)


def digit_bitmap(mask, stat):
    """The glyph on a fixed grid, so its size no longer matters."""
    glyph = mask[stat[1]:stat[1] + stat[3], stat[0]:stat[0] + stat[2]]
    if glyph.size == 0:
        return None
    return cv2.resize(glyph, DIGIT_GRID,
                      interpolation=cv2.INTER_AREA) > 127


def _holes(bits):
    """Enclosed background areas, and how far down each one sits."""
    padded = np.pad((~bits).astype(np.uint8), 1, constant_values=1)
    count, labels = cv2.connectedComponents(padded, 4)
    found = []
    for k in range(1, count):
        ys, xs = np.where(labels == k)
        if (0 in ys or 0 in xs
                or labels.shape[0] - 1 in ys or labels.shape[1] - 1 in xs):
            continue                      # that one is the world outside
        found.append(ys.mean() / labels.shape[0])
    return found


def read_digit(mask, stat):
    """Which digit this is, or None if it does not look like one.

    Holes first, because they split the ten into three groups that no
    amount of ink measuring separates as cleanly.
    """
    bits = digit_bitmap(mask, stat)
    if bits is None:
        return None
    holes = _holes(bits)
    bottom = float(bits[-2:].mean())
    right = float(bits[:, -4:].mean())

    if len(holes) >= 2:
        return 8
    if len(holes) == 1:
        if bottom < D4_BOTTOM_MAX:
            return 4
        if holes[0] < D9_HOLE_MAX:
            return 9
        if holes[0] > D6_HOLE_MIN:
            return 6
        return 0
    if bottom < D7_BOTTOM_MAX:
        return 7
    if right < D1_RIGHT_MAX             or float(bits[D1_ROWS[0]:D1_ROWS[1], -D1_RIGHT_COLS:].mean())             < D1_UPPER_RIGHT_MAX:
        return 1
    if bottom >= D2_BOTTOM_MIN:
        return 2
    band = bits[D53_ROWS[0]:D53_ROWS[1]]
    return 5 if band[:, :4].mean() > band[:, -4:].mean() else 3


def read_counter(mask, digits):
    """The number a counter shows, or None if any digit was unreadable.

    All or nothing on purpose. Half a number is worse than no number: 4 read
    out of 46 would have the bot stop after four attempts and call the card
    empty.
    """
    if not digits:
        return None
    value = 0
    for stat in digits:
        one = read_digit(mask, stat)
        if one is None:
            return None
        value = value * 10 + one
    return value


def card_counters(img, fy, fh=None):
    """The counters on a list card: the mask, and one digit list per counter.

    First the tickets, then the ads if the card has them. Apocalymon has only
    the one.
    """
    mask, glyphs = badge_glyphs(img, fy, fh)
    if mask is None or not glyphs:
        return None, []
    found = [digits for digits in
             (counter_digits(g) for g in group_glyphs(glyphs)) if digits]
    return mask, found


# The daily allowance, the number after the slash on both counters. The
# game resets two tickets a day and allows two watched ads a day.
DAILY_ALLOWANCE = 2


def card_budget(img, fy, fh=None):
    """How many attempts this card can still yield today.

    Both counters count down, and both say what is left. 46/2 is forty-six
    tickets in hand, with two more arriving each day; 0/2 on the film symbol
    is no ads left today, out of the two a day gives.

    The film symbol is drawn only while the ticket counter reads 0/2.
    Confirmed both ways: it appears once tickets first run out, and it
    disappears again the moment tickets are above zero for any reason --
    including a repurchase, and regardless of how many ads the symbol had
    been showing right before the purchase. So a card with tickets left
    carries one counter, full stop, and that says nothing whatever about
    its ads: reading the missing symbol as "no ads" is a conclusion the
    card does not support, and it would have the bot stop as the last
    ticket went and walk away from two free attempts. Ads are unknown
    whenever tickets are not at zero.

    Hence the three shapes an answer can have:

      tickets  > 0, (no film symbol, it is hidden while this holds) ->
                    ads unknown, total unknown, at least that many tickets
      tickets == 0, film symbol N  -> N, and that is all there is
      tickets == 0, no film symbol -> 0, this card has no ads to give

    A total of None means "play it, and find out inside". Only a total of 0
    lets a card be skipped without opening it.
    """
    mask, counters = card_counters(img, fy, fh)
    if not counters:
        return {"tickets": None, "ads": None, "total": None}

    tickets = read_counter(mask, counters[0])
    ads = read_counter(mask, counters[1]) if len(counters) > 1 else None

    if tickets is None:
        total = None
    elif ads is not None:
        # Observed only at tickets == 0, per the rule above -- the symbol
        # hides itself otherwise -- but added rather than assumed to be
        # zero, in case that ever stops holding.
        total = tickets + ads
    elif tickets == 0:
        # Tickets gone and still no film symbol: this card has no ads.
        total = 0
    else:
        # Tickets left, so the symbol is hidden and the ads behind it
        # cannot be counted. Unknown, not zero.
        total = None
    return {"tickets": tickets, "ads": ads, "total": total}


def card_has_attempts(img, fy, fh=None):
    """Does this list card still have attempts left?

    Reads whether the ticket counter's leading digit is a zero. Three
    outcomes: tickets present means play, tickets at 0 with no ad counter
    means safe to skip, tickets at 0 with an ad counter means unclear and
    gets tried. The third case costs one open-and-close, after which the bot
    remembers the outcome.

    Returns None if nothing could be read. The card is then played to be
    safe, not skipped.
    """
    mask, counters = card_counters(img, fy, fh)
    if not counters:
        return None
    tickets = counters[0]
    if not is_zero_digit(mask, tickets[0]):
        return True
    return None if len(counters) > 1 else False


def confirm_kind(img, ok_button):
    """Which confirmation dialog is this, 'beenden' (exit) or 'party'.

    Told apart by the left button: grey for the exit dialog, where OK closes
    the game, pink for the party dialog, where OK is the correct answer.

    "Party" has to be proved, and the proof is pink pixels. It used to be
    enough for the sample to be saturated, which the dialog's blue interior
    also is -- and the sample lands on that interior whenever the two buttons
    are not symmetric about the middle of the screen. Measured on a real exit
    dialog: OK at 0.561, Cancel at 0.383, mirror at 0.439, which is the gap
    between them. That read as party, and the answer to party is OK.

    Anything inconclusive is therefore the exit dialog. Being wrong that way
    costs a Cancel that was not needed; being wrong the other way ends the
    session.
    """
    x0, y0, gw, gh = game_rect(img)
    left = 1.0 - ok_button["fx"]
    # Wide enough to cover the button even when the mirror is off by the
    # measured 0.056, which is what happens on a dialog that is not centred.
    x = int(x0 + (left - 0.09) * gw)
    w = int(0.18 * gw)
    y = int(y0 + (ok_button["fy"] - 0.015) * gh)
    h = int(0.03 * gh)
    patch = img[max(0, y):y + h, max(0, x):x + w]
    if patch.size == 0:
        return "beenden"
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    pink = ((hsv[:, :, 0] >= PARTY_PINK_HUE[0])
            & (hsv[:, :, 0] <= PARTY_PINK_HUE[1])
            & (hsv[:, :, 1] > EXIT_CANCEL_SAT_MAX))
    share = float(np.count_nonzero(pink)) / pink.size
    return "party" if share >= 0.15 else "beenden"


def party_slots_filled(img):
    """How many party slots are filled. Returns a count from 0 to 3."""
    x0, y0, gw, gh = game_rect(img)
    filled = 0
    for fx in PARTY_SLOTS:
        x = int(x0 + (fx - PARTY_SLOT_HALF_W) * gw)
        w = int(2 * PARTY_SLOT_HALF_W * gw)
        y = int(y0 + (PARTY_SLOT_Y - 0.05) * gh)
        h = int(0.10 * gh)
        patch = img[max(0, y):y + h, max(0, x):x + w]
        if patch.size == 0:
            continue
        if float(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).std()) >= PARTY_SLOT_MIN_STD:
            filled += 1
    return filled


# Measured on the real "Now Loading ... Connecting 57.6%" screen, against a
# 799x1387 frame of 1.1 M pixels:
#
#   progress bar advancing 2%        79 px   0.007%
#   one more loading dot            324 px   0.029%
#   the small sprite animating     2025 px   0.183%
#
# Everything that moves on it is tiny. A test asking for 0.2% of the frame
# calls all of that stillness, which is how the loop decided a perfectly
# healthy load was a screen it could not get past.
MOVING_SHARE = 0.0002
# "Did my tap do anything?" wants a blunt one, so a blinking icon does not
# count as an answer.
CHANGED_SHARE = 0.01
# How long the picture has to be literally unchanged before this gives up.
# Not "how many taps did nothing": taps during a load do nothing by
# definition, and counting them is what aborted three good runs. A screen
# that has not altered one pixel in this long really is stuck.
#
# Raised from 25 s after a live run gave up here with the loading bar shown
# nearly full -- a load can sit still for a stretch even this close to the
# end, and that is not yet the same thing as being stuck.
FREEZE_WINDOW = 45.0
FREEZE_SHARE = 0.0002
# How long to wait for a moving screen to settle before tapping it anyway.
# Without this an idle animation on the main screen would be waited on for
# ever. Raised alongside FREEZE_WINDOW, for the same reason: a loading bar
# still visibly filling should not get tapped at just because 8 s have
# passed.
MOVING_PATIENCE = 20.0
# Least time between two taps while waking the game up. The menus need a
# moment to react and a burst of clicks arrives before any of them has been
# drawn, which reads as "nothing is happening" and starts the loop guessing.
WAKE_TAP_PAUSE = 1.0


def _same_screen(before, after, min_share=CHANGED_SHARE):
    """Did nothing change? The threshold is the caller's decision, see
    MOVING_SHARE and CHANGED_SHARE."""
    if before is None or after is None or before.shape != after.shape:
        return False
    diff = cv2.absdiff(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY),
                       cv2.cvtColor(after, cv2.COLOR_BGR2GRAY))
    return float(np.count_nonzero(diff > 30)) / diff.size < min_share


def popup_ok(img):
    """A pop-up's OK button, or None.

    Found by colour and rough position, not by a remembered pixel, so a
    slightly different card still works. Deliberately narrow: it has to be a
    wide blue button low down and near the middle.
    """
    for b in find_buttons(img, BLUE, min_y=POPUP_OK_Y[0]):
        if (POPUP_OK_Y[0] <= b["fy"] <= POPUP_OK_Y[1]
                and POPUP_OK_FX[0] <= b["fx"] <= POPUP_OK_FX[1]
                and b["fw"] >= POPUP_OK_MIN_W):
            return b
    return None


def claim_button(img):
    """The idle-rewards Claim button, or None.

    A wide blue button in the lower middle WITH a violet one beside it. The
    violet half is what makes it Claim rather than the Notices dialog's
    Campaigns tab, which is otherwise the same button in the same place.
    """
    def in_band(b):
        return POS_CLAIM_Y[0] <= b["fy"] <= POS_CLAIM_Y[1]

    blue = [b for b in find_buttons(img, BLUE, min_y=POS_CLAIM_Y[0])
            if in_band(b) and b["fw"] >= POS_CLAIM_MIN_W
            and POS_CLAIM_FX[0] <= b["fx"] <= POS_CLAIM_FX[1]]
    violet = [b for b in find_buttons(img, VIOLET, min_y=POS_CLAIM_Y[0])
              if in_band(b)]
    for b in blue:
        for v in violet:
            if abs(v["fy"] - b["fy"]) <= CLAIM_PAIR_DY and v["fx"] < b["fx"]:
                return b
    return None


# The auto button on the main game screen: a blue disc with an A between two
# arrows, below and left of the middle. Pressing it makes the game spend the
# tickets by itself.
#
# Measured on a real frame, 805 x 1390. In the band searched below, the blue
# mask finds four things, and only one of them is this button:
#
#   the panel edge        241 x 12 px            far too wide
#   the sun icon           64 x 62, fill 0.62    a rounded square
#   THE AUTO BUTTON        43 x 43, fill 0.72    a disc, 0.053 of the width
#   a bar right of it      49 x 17               too flat
#
# So width and roundness carry it, not position alone.
#
# Roundness does a second job, and this is the useful part. The game dims
# everything behind a dialog, and a dimmed disc loses its edges out of the
# blue range and breaks up. Measured on the same button, twice:
#
#   main screen clear          43 x 43, area 1331   fill 0.72
#   a dialog open over it      42 x 42, area  754   fill 0.43
#
# So a button found at full fill is evidence of both things a caller needs:
# where to tap, and that nothing is covering the screen. 0.65 keeps its
# distance from the dimmed case, which is the error that matters -- failing
# to find the button costs nothing but a press that does not happen.
# The "Stage Failed..." banner: big red letters across the upper third. It
# appears when the character dies, the stage restarts by itself, and nothing
# needs doing about it -- except that it stays until something is clicked,
# and ANY click dismisses it. A tap on the auto button while it is up is
# swallowed by the banner and the press is lost.
#
# Measured, share of saturated red in the band 0.10 to 0.22 of the height:
#
#   the banner (and dimmed by a dialog on top of it)   0.0584
#   the main screen, its red notification badges       0.0053
#   every other frame there is                         0.0000
#
# 0.02 sits between with an order of magnitude either side, and the measured
# banner was a dimmed one, so an undimmed banner scores higher still.
STAGE_FAILED_BAND = (0.10, 0.22)
STAGE_FAILED_RED = 0.02
STAGE_FAILED_HUE = ((0, 120, 120), (8, 255, 255),
                    (170, 120, 120), (179, 255, 255))

# Red in that band is necessary and is not sufficient, which cost a whole
# feature a run. The stage the player was on, Binary Road, is drawn on a red
# grid: the band measured 0.484 red, twenty-four times the threshold, and the
# passive helper concluded the banner was up and did nothing at all -- for as
# long as that stage lasted. Two other frames say the same in the other
# direction: a dungeon card's artwork scores 0.069 and an orange cave 0.063,
# both above 0.02 and neither a banner.
#
# What the banner has and none of them do is a white outline around the
# letters, which is how this game draws every headline. Measured as the share
# of the band that is red with white within two pixels of it:
#
#   the banner                          0.0236
#   the red stage that broke it         0.0037
#   a dungeon card's red artwork        0.0001
#   an orange cave                      0.0000
#   every ordinary main screen          0.0000 to 0.0002
#
# 0.010 sits a factor of two under the banner and a factor of nearly three
# over the worst impostor. And the two ways of being wrong do not cost the
# same: missing a banner costs one tap, which is what dismisses it anyway,
# while seeing one that is not there stops everything until the screen
# changes. So this test is meant to lean towards "not a banner".
STAGE_FAILED_WHITE = ((0, 0, 200), (179, 60, 255))
STAGE_FAILED_HALO = 0.010

# Its own blue range, a little wider than BLUE: this is an icon, not one of
# the flat buttons BLUE was measured on, and its disc is shaded.
AUTO_BLUE = ((95, 120, 120), (115, 255, 255))
POS_AUTO = (0.361, 0.766)
AUTO_BAND = (0.28, 0.45, 0.72, 0.82)
AUTO_W = (0.040, 0.068)
AUTO_ASPECT = (0.80, 1.25)
AUTO_FILL_MIN = 0.65

def stage_failed(img):
    """Is the red Stage Failed banner up?

    Red letters, and not the words themselves: reading those would be text
    recognition, which this bot does without so that it works in every
    language. What is measured is the shape of how the game draws a
    headline -- saturated red with a white outline around it -- because red
    alone is also a red stage, a red card and a red cave. See the numbers
    above STAGE_FAILED_HALO.
    """
    x0, y0, gw, gh = game_rect(img)
    # Clamped, because on an ADB frame the reference rect starts above and
    # left of the image and a negative index would wrap to the far edge.
    top = max(0, int(y0 + STAGE_FAILED_BAND[0] * gh))
    band = img[top:int(y0 + STAGE_FAILED_BAND[1] * gh),
               max(0, x0):x0 + gw]
    if band.size == 0:
        return False
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    low = cv2.inRange(hsv, np.array(STAGE_FAILED_HUE[0]),
                      np.array(STAGE_FAILED_HUE[1]))
    high = cv2.inRange(hsv, np.array(STAGE_FAILED_HUE[2]),
                       np.array(STAGE_FAILED_HUE[3]))
    red = low | high
    if float(np.count_nonzero(red)) / red.size < STAGE_FAILED_RED:
        return False
    # Red letters, not a red picture: the outline is the difference.
    white = cv2.inRange(hsv, np.array(STAGE_FAILED_WHITE[0]),
                        np.array(STAGE_FAILED_WHITE[1]))
    near = cv2.dilate(white, np.ones((5, 5), np.uint8))
    halo = float(np.count_nonzero(cv2.bitwise_and(red, near))) / red.size
    return halo >= STAGE_FAILED_HALO


def auto_button(img):
    """The auto button on the main screen, or None if it is not plainly there.

    None is also the answer to "is the main screen really in front, with
    nothing over it". Every dialog in this game is drawn across the middle
    and covers this button, so a caller that finds it has evidence for both
    questions at once -- where to tap, and that it is safe to.
    """
    x0, y0, gw, gh = game_rect(img)
    fx0, fx1, fy0, fy1 = AUTO_BAND
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0:
        return None
    mask = cv2.inRange(cv2.cvtColor(sub, cv2.COLOR_BGR2HSV),
                       np.array(AUTO_BLUE[0]), np.array(AUTO_BLUE[1]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not h:
            continue
        fw = w / float(gw)
        if not AUTO_W[0] <= fw <= AUTO_W[1]:
            continue
        if not AUTO_ASPECT[0] <= w / float(h) <= AUTO_ASPECT[1]:
            continue
        if area / float(w * h) < AUTO_FILL_MIN:
            continue
        return {"fx": (left + x + w / 2.0 - x0) / gw,
                "fy": (top + y + h / 2.0 - y0) / gh,
                "fw": fw, "fh": h / float(gh)}
    return None


# The home button: the globe in the middle of the bottom nav bar, and the way
# back to the main screen from every screen that bar is drawn on. That is the
# catch, and it is the reason go_home walks back to the list first -- the bar
# belongs to the list side of the game and is not drawn over a dungeon panel,
# a battle or a dialog.
#
# Found by its glyph, not by its position: the white wireframe globe inside
# the disc. Measured over 49 real frames -- window frames 497 to 805 wide and
# ADB frames of 1080 x 1920, both frame shapes of the same scene -- as shares
# of the reference window:
#
#   the globe        fw 0.0473 to 0.0501   aspect 0.96 to 1.03   fill 0.42 to 0.49
#   next widest white thing in that crop, over every frame there is:
#     a tab's label edge          fw 0.0155
#     a white panel across the bar, on a loading screen or with Special
#     Summon open over the game    fw 0.125, fill 1.00
#
# So the width band below keeps 15 % clear of the globe at either end and
# still leaves a factor of two either way to the nearest wrong thing, and
# fill throws out the solid white panel that width alone would have to argue
# with. Exactly one blob passed on each of the 49 frames, none on any other.
#
# It does the same second job auto_button does: the game dims what is behind
# a dialog, and the dimmed globe leaves the white range entirely -- measured
# on a frame with the leave prompt up, no white blob at all in that crop. So
# a globe found is evidence of both things a caller needs, where to tap and
# that nothing is covering it.
#
# The button's own centre measures 0.481, 0.945, which is 0.104 to the right
# of NAV_DUNGEON and a little higher, as the bar is drawn. It is written down
# here for the record only: what gets tapped is the glyph that was found.
HOME_BAND = (0.41, 0.555, 0.905, 0.985)
HOME_WHITE = ((0, 0, 200), (179, 60, 255))
HOME_W = (0.038, 0.062)
HOME_ASPECT = (0.80, 1.25)
HOME_FILL = (0.30, 0.70)

# How hard go_home tries. One press is all it takes from the list, and the
# second is there because a press sent into an animation is swallowed -- the
# same reason summon.py caps its way out at four. Three is that with a spare;
# past it, whatever is on screen is not what this bot takes it for, and more
# presses into it would be the blind clicking CLAUDE.md warns about. The
# rounds are the looking, and there are more of them than presses because a
# round that finds no bar spends itself waiting rather than tapping.
HOME_PRESSES_MAX = 3
HOME_ROUNDS = 6


def home_button(img):
    """The home button in the bottom nav bar, or None if it is not plainly there.

    None also answers "is the nav bar in front and undimmed", for the same
    reason auto_button answers it: see the numbers above.
    """
    x0, y0, gw, gh = game_rect(img)
    fx0, fx1, fy0, fy1 = HOME_BAND
    # Clamped: on an ADB frame the reference rect starts above and left of
    # the image, and a negative index would wrap to the far edge.
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0:
        return None
    mask = cv2.inRange(cv2.cvtColor(sub, cv2.COLOR_BGR2HSV),
                       np.array(HOME_WHITE[0]), np.array(HOME_WHITE[1]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not h:
            continue
        fw = w / float(gw)
        if not HOME_W[0] <= fw <= HOME_W[1]:
            continue
        if not HOME_ASPECT[0] <= w / float(h) <= HOME_ASPECT[1]:
            continue
        if not HOME_FILL[0] <= area / float(w * h) <= HOME_FILL[1]:
            continue
        return {"fx": (left + x + w / 2.0 - x0) / gw,
                "fy": (top + y + h / 2.0 - y0) / gh,
                "fw": fw, "fh": h / float(gh)}
    return None


def violet_beside(button, violet):
    """Is there a violet button at the same height, to the left of this one?

    That pair is the dungeon panel's Clear Previous Difficulty next to
    Attempt, and no confirmation prompt has it. Measured over real frames of
    all three prompts: none carries a violet button within CLAIM_PAIR_DY of
    its OK, while the panel's pair sits at exactly the same fy.
    """
    return any(abs(v["fy"] - button["fy"]) <= CLAIM_PAIR_DY
               and v["fx"] < button["fx"] for v in violet)


def recognise(img):
    """Which screen is visible and where clicking is allowed."""
    blue = find_buttons(img, BLUE, min_y=0.0)
    violet = find_buttons(img, VIOLET, min_y=0.0)
    cards = list_cards(img)

    # Exit confirmation first. It has a blue button of a size and position
    # nothing else has, and a wrong click next to it would be costly.
    exit_ok = next((b for b in blue
                    if near(b["fx"], POS_EXIT_OK, EXIT_TOL)
                    and EXIT_Y[0] <= b["fy"] <= EXIT_Y[1]
                    and EXIT_W[0] <= b["fw"] <= EXIT_W[1]), None)
    # ... unless a violet button sits beside it. Two dialogs put a blue
    # button where the exit prompt's OK is looked for, and both are told
    # apart by their violet neighbour rather than by another position band:
    # the idle-rewards dialog, whose Extra Rewards would be tapped by the
    # "Cancel" that follows, and the dungeon panel while it is still
    # loading. Measured: a panel whose artwork has not arrived yet draws a
    # narrower Attempt, 0.214 against the loaded 0.251, which slips inside
    # EXIT_W -- and the mirrored Cancel then lands on Clear Previous
    # Difficulty. That happened four times in one live dungeon.
    if (exit_ok and len(cards) < LIST_MIN_CARDS and claim_button(img) is None
            and not violet_beside(exit_ok, violet)):
        return {"state": EXIT, "attempt": None, "party": None, "ad": None,
                "clear": None, "blau": blue, "violett": violet,
                "karten": cards, "giveup": None, "exit_ok": exit_ok,
                "exit_kind": confirm_kind(img, exit_ok)}

    # Check for battle next. During a battle there is game artwork that looks
    # very similar to a button. The Give Up button, centred at the very
    # bottom, is unambiguous by contrast.
    giveup = next((b for b in blue
                   if near(b["fx"], POS_CENTER) and b["fy"] > POS_GIVEUP_Y), None)
    if giveup:
        return {"state": BATTLE, "attempt": None, "party": None, "ad": None,
                "clear": None, "blau": blue, "violett": violet,
                "karten": cards, "giveup": giveup}

    # Only buttons at one of the known positions. Without this restriction, a
    # part of a list card at 0.42 was once mistaken for Attempt.
    usable = [b for b in blue
              if BUTTON_MIN_Y <= b["fy"] <= BUTTON_MAX_Y
              and ATTEMPT_W[0] <= b["fw"] <= ATTEMPT_W[1]
              and (near(b["fx"], POS_CENTER) or near(b["fx"], POS_ATTEMPT))]
    in_range = lambda b: BUTTON_MIN_Y <= b["fy"] <= BUTTON_MAX_Y
    ad = next((b for b in violet if near(b["fx"], POS_CENTER) and in_range(b)), None)
    clear = next((b for b in violet if near(b["fx"], POS_CLEAR) and in_range(b)), None)

    attempt = party = None
    if len(usable) >= 2:
        # two buttons, the right one is Attempt, the centred one is Find a Party
        attempt = next((b for b in usable if near(b["fx"], POS_ATTEMPT)), None)
        party = next((b for b in usable if near(b["fx"], POS_CENTER)), None)
        if attempt is None:
            attempt = usable[0]
    elif len(usable) == 1:
        attempt = usable[0]

    # Clear Previous Difficulty does not count as evidence of a dialog. The
    # failure screen has violet areas at the same position, and a dialog
    # always has either Attempt or the ad button.
    dialog_open = bool(attempt or ad)
    if dialog_open:
        if attempt and party:
            state = DIALOG_PARTY
        elif attempt:
            state = DIALOG
        elif ad:
            state = DIALOG_AD
        else:
            state = DIALOG
    elif len(cards) >= LIST_MIN_CARDS:
        state = LIST
    else:
        state = UNKNOWN

    ergebnis = {"state": state, "attempt": attempt, "party": party, "ad": ad,
                "clear": clear, "blau": blue, "violett": violet,
                "karten": cards, "giveup": None, "party_voll": 0}
    if state == DIALOG_PARTY:
        ergebnis["party_voll"] = party_slots_filled(img)
    return ergebnis


# ----------------------------------------------------------------------------
class DungeonBot:
    # Click origin, overwritten in __init__. A class default because the
    # offline tests build a bot with __new__ and never run __init__.
    origin = (0, 0)

    # States in which a dungeon dialog is open. Kept as a class attribute so
    # it does not get lost when individual methods are refactored.
    DIALOGS = (DIALOG, DIALOG_PARTY, DIALOG_AD)

    def __init__(self, cap, dry_run=True, log=print, entries=7, skip_last=1,
                 use_ads=True, battle_timeout=90.0, tick=1.0, max_minutes=0,
                 max_attempts=6, max_ads=2, min_battle=6.0, swipes=1,
                 survey_first=True, patience=1.5, only=None, skip=None,
                 budgets=None, debugdir="debug_dungeon"):
        self.cap = cap
        self.max_minutes = max_minutes
        self.deadline = None
        # Click targets are computed in device coordinates, not window
        # pixels. Otherwise window capture would need a conversion via the
        # minigame calibration, and that fails in the menu because no game
        # card is visible there. That is why this used to run over the slow
        # ADB path.
        self.origin, self.device = self._device_size()
        self.dry_run = dry_run
        self.log = log
        self.entries = entries
        self.skip_last = skip_last
        self.use_ads = use_ads
        self.battle_timeout = battle_timeout
        self.tick = tick
        self.stats = {"attempts": 0, "fights": 0, "ads": 0,
                      "skipped": 0, "unknown": 0, "declined": 0,
                      "exit_caught": 0, "not_selected": 0}
        self.control = guard.Stop()
        # What the last survey read off each card, so the attempt loop does
        # not have to read it a second time from inside the panel, where the
        # counter is not visible anyway.
        self.counted = {}
        # Attempts already spent per dungeon, across the whole run. The
        # number the player sets is a budget for the run; asked once per
        # round it handed Apocalymon its single attempt again in round two,
        # and again in round three.
        self.spent = {}
        # How many attempts the player allows per dungeon, by position in
        # the list. Empty means the old behaviour, max_attempts for every
        # one of them. A dungeon set to 0 is not played at all -- that is
        # what the checkbox used to say.
        self.budgets = dict(budgets or {})
        # The ceiling when nothing was read from the card. Elapsed time still
        # decides whether a battle really happened: a battle takes 7 to 40
        # seconds, and a dialog returning faster than that means nothing
        # happened.
        self.max_attempts = max_attempts
        # Battles measured take about 20 seconds, short ones about 7. Below
        # this threshold it was not a battle but a rejection.
        self.min_battle = min_battle
        # After Attempt the game needs a moment before the dialog goes away.
        # Measured about 3 seconds at Apocalymon Wall.
        self.start_timeout = 8.0 * patience
        # Hard upper limits. They should never trigger, but are the last
        # safeguard against a loop I did not foresee. Two ads per dungeon per
        # day, each granting exactly one ticket, gives at most four battles
        # per dungeon and day.
        self.max_ads = max_ads
        self.max_loops = 12
        self.survey_first = survey_first
        # All wait times hang off one factor. The animation windows measured
        # take about half a second longer than assumed, so it is set to 1.5.
        self.patience = patience
        self.pause_short = 0.5 * patience
        self.pause_long = 1.0 * patience
        # Dungeons that have demonstrably yielded nothing more this session.
        # The evidence comes from operation, not from the image. Reading
        # digits on the ad button was too unreliable, and by colour an
        # exhausted button looks the same as a usable one, measured both
        # H 125 S 170 V 235.
        self.exhausted = set()
        # How many cards are visible at the bottom is measured during
        # planning and remembered here, so the names from the bottom are
        # mapped correctly.
        self.visible_at_bottom = 5
        # Dungeon selection as numbers from 0, in list order. only wins over
        # skip, so that an explicit selection is not overridden by a stale
        # skip.
        self.only = set(only) if only else None
        self.skip = set(skip) if skip else set()
        self.swipes = swipes
        self.debugdir = debugdir
        self._saved = 0

    # ------------------------------------------------------------------
    def _device_size(self):
        """Reference frame for clicks: its origin and its size.

        game_rect turns whichever picture comes back -- a device frame or a
        window frame -- into the same reference frame, so this needs only
        the one frame the bot is looking at anyway. It used to reach
        through to a HybridCapture's own AdbCapture for a second frame from
        the click side specifically; that mixed mode is gone, image and
        click always come from the same source now.
        """
        try:
            img = self.cap.grab()
        except Exception:
            return (0, 0), (1080, 1920)
        x0, y0, gw, gh = game_rect(img)
        return (x0, y0), (gw, gh)

    def grab(self):
        return self.cap.grab()

    def tap(self, fx, fy, was=""):
        """Click by relative position.

        No image parameter anymore. Clicks go out in device coordinates, the
        image was not needed. It only led to a caller wanting to pass
        info["img"], and not every recognition result provides that key. The
        result was a KeyError in the middle of a run.
        """
        ox, oy = self.origin
        dw, dh = self.device
        x, y = int(round(ox + fx * dw)), int(round(oy + fy * dh))
        if self.dry_run:
            self.log("    [dry run] click %s at rel. %.3f, %.3f, pixel %d,%d" % (was, fx, fy, x, y))
            return
        self.cap.tap(x, y)

    def back(self, only_if_dialog=True, leaving_dungeon=False):
        """Android back key.

        Only press it if a dialog is actually open. If none is open, the game
        answers with "Return to the title screen?", and OK on that throws the
        session away.

        `leaving_dungeon` says what the caller was trying to do, and only a
        caller that was closing a dungeon panel may set it. It is the only
        thing that separates the prompt for that from the one for the title
        screen -- they are the same picture. See dismiss_confirm.
        """
        if only_if_dialog and not self.dry_run:
            state = recognise(self.grab())["state"]
            if state in (LIST, UNKNOWN, BATTLE):
                self.log("    no dialog open, back key not pressed")
                return False
        if self.dry_run:
            self.log("    [Trockenlauf] Zurueck-Taste")
            return
        try:
            self.cap.back()
            time.sleep(self.pause_short)
        except Exception as err:
            self.log("    back key failed: %s" % err)
            return False
        # Check whether we ended up in the exit confirmation
        if not self.dry_run:
            info = recognise(self.grab())
            if info["state"] == EXIT:
                self.dismiss_confirm(info, leaving_dungeon=leaving_dungeon)
                return False
        return True

    def press_auto(self, img=None):
        """Press the auto button once, if the screen plainly allows it.

        Auto makes the game spend its tickets by itself, so it is worth one
        careful press and never a blind one. Everything has to line up: no
        confirmation prompt, no pop-up, no rewards dialog, and the button
        itself sharp and where it belongs -- which cannot be true while
        anything is drawn over the main screen, because the game dims what
        is behind a dialog and the dimmed button fails the roundness test.

        Returns True if it was pressed. The caller must not press again: it
        is a toggle, and a second press turns it back off.
        """
        img = self.grab() if img is None else img
        info = recognise(img)
        if info["state"] in (EXIT, DIALOG, DIALOG_PARTY, DIALOG_AD):
            return False
        if popup_ok(img) is not None or claim_button(img) is not None:
            return False
        if stage_failed(img):
            # Any click at all dismisses this banner, so a press aimed at
            # the auto button would be eaten by it. Leave it: whatever taps
            # next clears it, and the press comes round again.
            self.log("  Stage Failed is up, not pressing auto through it")
            return False
        button = auto_button(img)
        if button is None:
            return False

        before = self._auto_patch(img, button)
        self.log("  pressing the auto button, tickets are spent by the game "
                 "from here")
        self.tap(button["fx"], button["fy"], was="auto")
        if self.dry_run:
            return True
        time.sleep(max(self.pause_long, WAKE_TAP_PAUSE))

        # Say what changed rather than judge it. Whether this button visibly
        # answers a press has not been measured on a real frame yet, so the
        # numbers go in the log and the next run decides the threshold.
        after_img = self.grab()
        found = auto_button(after_img)
        after = self._auto_patch(after_img, found or button)
        self.log("    auto button before %s, after %s" % (before, after))
        return True

    @staticmethod
    def _auto_patch(img, button):
        """Mean colour of the button itself, as three numbers for the log."""
        x0, y0, gw, gh = game_rect(img)
        half = button["fw"] * 0.4
        x = int(x0 + (button["fx"] - half) * gw)
        y = int(y0 + (button["fy"] - half) * gh)
        w = max(1, int(2 * half * gw))
        patch = img[max(0, y):y + w, max(0, x):x + w]
        if patch.size == 0:
            return "nothing"
        return "%d/%d/%d" % tuple(int(v) for v in patch.reshape(-1, 3).mean(0))

    def settled_frame(self, timeout=2.5):
        """A frame the screen has stopped moving in.

        The pre-check reads digits off the list, and digits read while the
        list is still gliding are digits read from a smear -- which returns
        "nothing could be read", which the caller has to treat as "try it".
        Two frames that match is the proof it has come to rest. MOVING_SHARE
        is the threshold for "did anything at all move", which is exactly the
        question here.

        A screen that never settles, because something on it animates,
        returns its last frame rather than waiting for ever.
        """
        previous = self.grab()
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.15)
            current = self.grab()
            if _same_screen(previous, current, MOVING_SHARE):
                return current
            previous = current
        return previous

    def dismiss_confirm(self, info=None, leaving_dungeon=False):
        """Leave a confirmation dialog, differently depending on its kind.

        OK is pressed for exactly one of the three, and only when the caller
        says it was on its way out of a dungeon:

          grey Cancel                     "Exit the game?" -- Cancel, always.
          pink, leaving_dungeon=True      the dungeon's own prompt -- OK,
                                          which is the only way out of the
                                          panel. Cancel leaves the bot in it.
          pink, leaving_dungeon=False     could be "Return to the title
                                          screen?", so Cancel.

        The two pink ones cannot be told apart from the picture, measured
        identical to the pixel, so the caller's intent is the whole of the
        evidence. Being wrong in the cautious direction costs a Cancel that
        was not needed; being wrong the other way costs the session.
        """
        info = info or recognise(self.grab())
        if info["state"] != EXIT:
            return
        ok = info["exit_ok"]
        kind = info.get("exit_kind", "beenden")
        self.stats["exit_caught"] += 1
        if kind == "party" and leaving_dungeon:
            self.log("  leaving the dungeon via OK, back to the list")
            self.tap(ok["fx"], ok["fy"], was="OK, Party verlassen")
        else:
            if kind == "party":
                self.log("  an in-game prompt, but nothing here was leaving "
                         "a dungeon -- Cancel")
            else:
                # Keep the frame. This is the prompt whose OK ends the
                # session, so any surprise about where it came from is worth
                # being able to look at afterwards.
                self.save_unknown(self.grab(), "confirm_beenden")
                self.log("  exit dialog, leaving via Cancel")
            # Cancel sits mirrored relative to OK
            cancel_x = 1.0 - ok["fx"] if ok["fx"] > 0.5 else POS_EXIT_CANCEL
            self.tap(cancel_x, ok["fy"], was="Abbrechen")
        time.sleep(self.pause_long)

    def wait_for(self, states, timeout, was=""):
        """Wait for one of the states. Returns the recognition result or None."""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            info = recognise(self.grab())
            last = info
            if info["state"] in states:
                return info
            time.sleep(self.tick)
        self.log("    Warten auf %s ohne Erfolg%s"
                 % ("/".join(states), (", " + was) if was else ""))
        return None

    # ------------------------------------------------------------------
    def open_list(self):
        """Open the dungeon list and confirm that it is open.

        Without this confirmation, the bot would tap blindly somewhere after
        a failed click on the tab. That is more dangerous in the menu than
        in the minigame, so it stops here rather than guessing.
        """
        img = self.grab()
        if recognise(img)["state"] == LIST:
            self.log("already in the list")
            return True
        self.tap(*NAV_DUNGEON, was="Dungeon-Reiter")
        if self.dry_run:
            return True
        time.sleep(self.pause_long)
        for _ in range(6):
            if recognise(self.grab())["state"] == LIST:
                self.log("list is open")
                return True
            time.sleep(self.pause_short)
        self.log("list not recognised. Am I on the main screen, and does the "
                 "dungeon tab really sit at rel. %.3f, %.3f?"
                 % NAV_DUNGEON)
        return False

    def wake_up(self, timeout=180.0, max_taps=60, claim_rewards=False,
                start_auto=False):
        """From a just-started game to the dungeon list.

        With `start_auto`, the auto button gets one press along the way, at
        the first moment the main screen is unmistakably clear. See
        press_auto for what "clear" is measured against.

        Returns True once the list is open. Deliberately dumb about what it
        is looking at: the screens between a launch and the main menu are the
        part that changes with every game update, so instead of recognising
        them this repeats the taps whose outcome can be checked -- the
        pop-up OK button and the dungeon tab.

        Two rules keep it out of trouble.

        It waits for a moving screen to settle before tapping, because a
        screen in motion is loading and loading is not a problem to be tapped
        at. It gives that up after MOVING_PATIENCE, so an idle animation on
        the main screen cannot stall it for ever.

        And it only concludes it is stuck when the picture has not altered at
        all for FREEZE_WINDOW seconds. Counting taps that achieved nothing
        was the old test, and it aborted three healthy runs: during a load,
        every tap achieves nothing and that is correct behaviour.

        Only for the cold-start path, where nothing else is open.
        """
        deadline = time.time() + timeout
        started = time.time()
        said = 0.0
        taps = 0
        previous = None
        waiting_since = None
        frozen_ref = None
        frozen_since = time.time()
        stalled = False
        # The back key is a loaded gun on this path: with no dialog open it
        # raises "Exit the game?", whose OK ends the session. It gets one
        # chance, and loses it the moment it produces that dialog.
        back_allowed = True
        # A tap high up gets one go per screen as well, so a screen that
        # ignores it is not tapped at for ever.
        neutral_tried = False
        # Claiming leaves a reward window standing over the dialog, and the
        # Claim button stays visible behind it. Once claiming has happened,
        # a Claim button is no longer evidence of a dialog waiting to be
        # closed with the back key -- the window over it says "Tap to close",
        # and a tap is what it wants.
        claimed = False
        # The auto button is pressed at most once, on the main screen, before
        # the dungeon tab is reached. It is a toggle: a second press would
        # turn it off again, so this is set the moment it is pressed and not
        # when the press is confirmed.
        auto_pressed = False
        banner_taps = 0
        self.log("waiting for the game to be ready, up to %d s" % timeout)

        while time.time() < deadline and taps < max_taps:
            if self.control.is_set():
                return False
            # Plain pause wait, not _time_left(): that one tries to find its
            # way back to the list afterwards, and during wake-up there is
            # no list to find yet.
            while self.control.is_paused() and not self.control.is_set():
                time.sleep(0.2)
            if self.control.is_set():
                return False

            img = self.grab()
            state = recognise(img)["state"]
            if state == LIST:
                self.log("dungeon list is open after %d tap(s), %d s"
                         % (taps, time.time() - started))
                return True
            if state == EXIT:
                # Almost certainly this loop's own doing, from a back key
                # pressed with nothing open. Cancel it -- never OK, which
                # closes the game -- and stop using the back key.
                self.log("  exit prompt is open, cancelling it")
                self._cancel_exit(recognise(img))
                back_allowed = False
                stalled = False
                previous = None
                time.sleep(WAKE_TAP_PAUSE)
                continue
            if state in (DIALOG_PARTY, DIALOG_AD):
                # Already inside the game, on something this bot knows how to
                # handle. Hand over rather than tapping past it.
                self.log("game is up, state %s" % state)
                return self.open_list()

            now = time.time()
            waited = now - started
            if waited - said >= 10:
                said = waited
                self.log("  %d s, %d tap(s), screen reads %s"
                         % (waited, taps, state))

            # Has anything at all altered since the last frame kept for this?
            # Any movement resets the clock; only a picture that stays
            # identical runs it down.
            if frozen_ref is None or not _same_screen(frozen_ref, img,
                                                      FREEZE_SHARE):
                frozen_ref = img
                frozen_since = now
            elif now - frozen_since >= FREEZE_WINDOW and taps > 0:
                self.log("nothing on screen has changed for %d s. Something "
                         "is there that neither the OK button nor the "
                         "dungeon tab gets past -- close it by hand and "
                         "start again." % (now - frozen_since))
                # Keep the screen that stopped it. Every round of this so far
                # has been a screen nobody had seen before, and asking for it
                # by hand afterwards costs a whole run.
                self.save_unknown(img, "wake_stuck")
                return False

            # Moving? Then it is loading. Wait, but not indefinitely. The
            # very first frame counts as moving too: tapping a screen nobody
            # has looked at twice is exactly what this avoids.
            first = previous is None
            moving = not first and not _same_screen(previous, img,
                                                    MOVING_SHARE)
            previous = img
            if first or moving:
                if waiting_since is None:
                    waiting_since = now
                if now - waiting_since < MOVING_PATIENCE:
                    time.sleep(self.pause_short or 0.5)
                    continue
            waiting_since = None

            # BATTLE is deliberately not handled above. A login pop-up's OK
            # button sits where Give Up sits and so reads as a battle, and no
            # battle can be running seconds after the game started.
            ok = popup_ok(img)
            claim = claim_button(img)
            if ok is not None:
                self.tap(ok["fx"], ok["fy"], was="pop-up OK")
            elif claim is not None and claim_rewards and not claimed:
                self.log("  claiming the idle rewards, as asked")
                self.tap(claim["fx"], claim["fy"], was="Claim")
                claimed = True
            elif state == DIALOG or (claim is not None and not claimed):
                # Something recognisably a dialog. The back key is what
                # closes those, and for the rewards dialog it is the only
                # answer that does not spend the idle timer.
                self.log("  closing what is in front with the back key")
                self.back(only_if_dialog=False)
                if state != DIALOG:
                    # Only a guess, so it does not get a second go unless it
                    # turns out to have been right.
                    back_allowed = False
            elif (start_auto and not auto_pressed and banner_taps < 2
                    and stage_failed(img)):
                # Clear the way for the press rather than hope something
                # else clears it. Any tap at all dismisses this banner, and
                # in a live run the tap that did it was the dungeon tab --
                # which opened the list, ended the wake-up, and the press
                # never got its turn. Twice at most: a character that keeps
                # dying puts the banner straight back up, and this is not
                # the loop to fight that in.
                self.log("  Stage Failed is up, tapping it away first")
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                banner_taps += 1
            elif (start_auto and not auto_pressed
                    and self.press_auto(img)):
                # Before the stalled branches, not after: a main screen with
                # no battle running does not move, so every tap on it reads
                # as stalled and the press would never get its turn. Its own
                # conditions are the stricter test anyway -- a crisp button
                # means no dialog is dimming the screen and no banner is up.
                auto_pressed = True
            elif stalled and not neutral_tried:
                # Unknown, and the last tap achieved nothing. A tap high up
                # is what the game itself asks for on the screens that say
                # "Tap to close" -- the reward window after claiming, and
                # the red Stage Failed banner that follows it on a cold
                # start. It is tried before the back key because it cannot
                # raise the exit prompt, and the back key can.
                self.log("  tapping high up to close what is in front")
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                neutral_tried = True
            elif stalled and back_allowed:
                self.log("  closing what is in front with the back key")
                self.back(only_if_dialog=False)
                back_allowed = False
            else:
                self.tap(*NAV_DUNGEON, was="touch to start / dungeon tab")
            taps += 1
            if self.dry_run:
                self.log("[dry run] stopping here, nothing was really tapped")
                return True
            # Menus need a moment. A burst of taps lands before the first one
            # has been drawn, and the loop then reads its own impatience as
            # a screen that will not move.
            time.sleep(max(self.pause_long, WAKE_TAP_PAUSE))

            # Did that achieve anything? If not, the next round closes what
            # is in front instead of repeating itself.
            after = self.grab()
            stalled = _same_screen(img, after, CHANGED_SHARE)
            if not stalled:
                # Something moved, so whatever was tried worked; the back key
                # and the tap high up are allowed to be considered again.
                back_allowed = True
                neutral_tried = False

        self.log("gave up waiting for the game after %d tap(s) and %d s."
                 % (taps, time.time() - started))
        if previous is not None:
            self.save_unknown(previous, "wake_timeout")
        return False

    def _cancel_exit(self, info):
        """Press Cancel on the exit prompt. Never OK.

        Separate from dismiss_confirm on purpose: that one also handles the
        party dialog, where OK is right, and the two are told apart by a
        colour test. On this path there is no party to leave -- the game has
        only just started -- so there is nothing to weigh up and no way for a
        misread to close the game.
        """
        ok = info.get("exit_ok") if info else None
        if not ok:
            self.log("    no exit button found, leaving it alone")
            return False
        # Belt and braces: never press the mirrored position when it lands on
        # the idle-rewards dialog's Extra Rewards button.
        if claim_button(self.grab()) is not None:
            self.log("    that is the rewards dialog, not an exit prompt")
            return False
        cancel_x = 1.0 - ok["fx"] if ok["fx"] > 0.5 else POS_EXIT_CANCEL
        self.tap(cancel_x, ok["fy"], was="Cancel, stay in the game")
        time.sleep(max(self.pause_long, WAKE_TAP_PAUSE))
        return True

    def scroll_top(self, swipes=None):
        self._scroll(swipes or self.swipes, up=True)

    def scroll_bottom(self, swipes=None):
        self._scroll(swipes or self.swipes, up=False)

    def _scroll(self, swipes=None, up=True):
        """Scroll the list to the edge.

        One swipe is enough, measured. Then wait half a second, otherwise
        reading happens during the trailing motion and the cards sit at the
        wrong positions.
        """
        swipes = swipes or self.swipes
        ox, oy = self.origin
        dw, dh = self.device
        x = int(ox + 0.5 * dw)
        y_near, y_far = int(oy + 0.30 * dh), int(oy + 0.88 * dh)
        if self.dry_run:
            self.log("    [dry run] scroll list %s"
                     % ("up" if up else "down"))
            return
        for _ in range(swipes):
            if up:
                self._swipe(x, y_near, x, y_far)
            else:
                self._swipe(x, y_far, x, y_near)
            time.sleep(0.5)
        time.sleep(0.5)

    def _swipe(self, x1, y1, x2, y2, ms=300):
        try:
            self.cap.swipe(x1, y1, x2, y2, ms)
        except Exception as err:
            self.log("    swipe failed: %s" % err)

    # ------------------------------------------------------------------
    def return_to_list(self, tries=5):
        """Back to the list, via the tab if necessary.

        Without this, the bot used to get stuck somewhere after a dialog and
        skipped the following cards.
        """
        # back() answers False when the press raised the exit prompt instead
        # of closing anything. Some panels -- the dungeon's own, measured --
        # do not handle the back key at all, and repeating it there only
        # produced the exit prompt three more times in a live run.
        back_allowed = True
        neutral_tried = False
        # Whether the frame before this one showed a dungeon panel. That is
        # the whole evidence for answering the prompt with OK, so it is
        # tracked rather than assumed: a prompt already on screen when this
        # helper was called is none of its doing and gets Cancel.
        panel_before = False
        for i in range(tries):
            info = recognise(self.grab())
            if info["state"] == LIST:
                return True
            if info["state"] == EXIT:
                self.dismiss_confirm(info, leaving_dungeon=panel_before)
                panel_before = False
                continue
            panel_before = info["state"] in self.DIALOGS
            if back_allowed and i < tries - 2 and info["state"] in self.DIALOGS:
                # A dungeon panel is what is open here, so the prompt the
                # back key raises is the dungeon's own and OK is the way out.
                back_allowed = self.back(leaving_dungeon=True)
            elif not neutral_tried:
                # A tap high up, outside whatever panel is in front. In the
                # live run the dungeon's own panel answered the back key
                # with the exit prompt and ignored the dungeon tab, and this
                # is the one remaining way out that cannot do harm.
                self.log("    tapping high up, outside the panel")
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                neutral_tried = True
            else:
                self.tap(*NAV_DUNGEON, was="Dungeon-Reiter")
            time.sleep(self.pause_long)
        self.log("  could not find the way back to the list")
        return False

    def go_home(self, rounds=HOME_ROUNDS):
        """Leave the game on its main screen. True if it is showing.

        Called from run's finally, so it happens on every way out and not
        only the good one: a run that never found the list, one cut short by
        the Stop button, one that threw. Each of those used to leave the game
        wherever it stood -- a dungeon panel, a card, a rewards dialog -- and
        the next thing started then met a screen it did not expect.

        Two things it deliberately does not do. It is not gated on the pause
        or stop flag: by the time this runs that flag is usually already set,
        that being one of the ways a run ends, and a gate would skip the one
        step whose whole point is where the game is left. It is bounded
        instead. And it never taps a position -- the nav bar is drawn only on
        the list side of the game, so if the globe is not on the frame the
        answer is to get back to the list and look again, not to tap where it
        would have been.

        What it checks after pressing is auto_button, not "the globe is gone":
        independent evidence that the main screen is in front and clear.
        """
        pressed, went_back = 0, False
        try:
            for _ in range(rounds):
                img = self.grab()
                if auto_button(img) is not None:
                    if pressed:
                        self.log("back on the main screen")
                    return True
                button = home_button(img)
                if button is None:
                    # No bar on this frame: either something is still open
                    # over it, or it is dimmed by a dialog. return_to_list
                    # is the bot's own way out of both, and it is worth one
                    # go, not one per round.
                    if not went_back:
                        went_back = True
                        self.log("\nnot on a screen with the nav bar, "
                                 "going back to the list first")
                        self.return_to_list()
                        continue
                    time.sleep(self.pause_long)
                    continue
                if pressed >= HOME_PRESSES_MAX:
                    break
                if not pressed:
                    self.log("\npressing the home button")
                self.tap(button["fx"], button["fy"], was="home button")
                pressed += 1
                if self.dry_run:
                    # Nothing was clicked, so nothing will change. Sitting
                    # out the rest would report a failure that never happened.
                    return False
                time.sleep(self.pause_long)
            self.log("could not get back to the main screen -- the game is "
                     "left where it stands")
            self.save_unknown(self.grab(), "no_way_home")
        except Exception as err:
            # This runs in a finally. A run that ended because the capture
            # died would otherwise end with this error instead of its own,
            # and the real one is the one worth reading.
            self.log("the way home failed: %s" % err)
        return False

    def save_unknown(self, img, tag):
        """Save an unknown screen once, so it can be reproduced later.
        Capped, so a long run does not fill the disk."""
        if self._saved >= 6:
            return None
        import os
        os.makedirs(self.debugdir, exist_ok=True)
        path = os.path.join(self.debugdir, "%s_%02d.png" % (tag, self._saved))
        cv2.imwrite(path, img)
        self._saved += 1
        self.log("  unknown screen saved: %s" % path)
        return path

    def dump_badge(self, img, fy, fh, name):
        """Write out one card's counter strip, with what was read from it.

        Only when DGUP_DUMP_BADGES is set. A counter misread live cannot be
        chased with a screenshot taken by hand: what matters is the frame
        the bot itself had, at the moment it had it, at whatever size the
        window happened to be.
        """
        import os
        if not os.environ.get("DGUP_DUMP_BADGES"):
            return
        os.makedirs(self.debugdir, exist_ok=True)
        crop = badge_crop(img, fy, fh)
        if crop.size == 0:
            return
        safe = "".join(c if c.isalnum() else "_" for c in name)[:24]
        budget = card_budget(img, fy, fh)
        path = os.path.join(self.debugdir, "badge_%s_%s_%s.png"
                            % (safe, budget["tickets"], budget["ads"]))
        cv2.imwrite(path, crop)
        self.log("    badge written: %s" % path)

    def global_index(self, index, label):
        """Number within the overall list, regardless of whether counting is
        from the top or the bottom."""
        if label == "unten":
            return self.entries - self.visible_at_bottom + index
        return index

    def is_selected(self, index, label):
        """Is this dungeon selected?"""
        pos = self.global_index(index, label)
        if self.only is not None:
            return pos in self.only
        return pos not in self.skip

    def attempts_for(self, index, label):
        """Attempts this dungeon has left, of what the player allowed."""
        pos = self.global_index(index, label)
        allowed = self.budgets.get(pos, self.max_attempts)
        return max(0, allowed - self.spent.get(pos, 0))

    def note_spent(self, index, label, count):
        """Book what a visit used, so the next round knows about it."""
        if count:
            pos = self.global_index(index, label)
            self.spent[pos] = self.spent.get(pos, 0) + count

    def label_of(self, index, label):
        """Name instead of card number, for the log only. The bot itself
        keeps counting cards; reading names would be text recognition and
        would break on every game update."""
        return dungeon_label(index, von_unten=(label == "unten"),
                            total=self.entries, sichtbar=self.visible_at_bottom)

    def survey(self, positions, label):
        """Read from the list in advance which dungeons still have attempts.

        From the list and not from the dialog, which saves opening and
        closing per dungeon. The Attempt button is not a reliable witness
        anyway, it is visible even at 0 tickets.

        Both counters are read, and what comes out is the number of attempts
        the card can still yield today: tickets plus the ads not yet
        watched. A card at zero is skipped without being opened, which is
        what this pass is for -- before the counters could be read, every
        card answered "unclear" and was opened and closed for nothing.

        A card whose counters cannot be read is still played. Unreadable is
        not the same as empty, and the loop inside the panel stops on its own
        when the attempts run out.
        """
        playable = []
        # Not self.grab(): this runs right after a scroll.
        img = self.settled_frame()
        for index in positions:
            if not self._time_left():
                break
            if not self.is_selected(index, label):
                self.log("  %-22s not selected" % self.label_of(index, label))
                self.stats["not_selected"] += 1
                continue
            if (label, index) in self.exhausted:
                self.log("  %-22s already exhausted this session"
                         % self.label_of(index, label))
                continue
            if self.attempts_for(index, label) <= 0:
                self.log("  %-22s had its %d, done"
                         % (self.label_of(index, label),
                            self.spent.get(self.global_index(index, label), 0)))
                continue
            cards = list_cards(img, with_size=True)
            if index >= len(cards):
                continue
            fy, fh = cards[index]
            budget = card_budget(img, fy, fh)
            self.dump_badge(img, fy, fh, self.label_of(index, label))
            allowed = self.attempts_for(index, label)
            self.counted[(label, index)] = budget

            if budget["total"] == 0:
                reason = "nothing left today"
            elif budget["total"] is not None:
                playable.append(index)
                # Both numbers, because they answer different questions: what
                # the game still owes, and what the player allowed.
                reason = ("%d tickets and %d ad%s, %d possible, playing %d"
                          % (budget["tickets"], budget["ads"],
                             "" if budget["ads"] == 1 else "s",
                             budget["total"],
                             min(budget["total"], allowed)))
            elif budget["tickets"]:
                playable.append(index)
                # The ads are behind a symbol the game has not drawn yet.
                reason = ("%d tickets, ads unknown until they run out, "
                          "playing up to %d" % (budget["tickets"], allowed))
            else:
                playable.append(index)
                reason = "counters unreadable, will try it"
            self.log("  %-22s %s" % (self.label_of(index, label), reason))
        return playable

    def play_entry(self, index, label="", key=None):
        """Open a dungeon and play it until nothing more can be done.

        Reactive loop. Before every action, it checks which screen is
        visible and derives exactly one action from that. The earlier fixed
        sequence broke wherever something unexpected happened in between and
        had to be patched individually. Here, a new screen is one more line.
        """
        key = key if key is not None else (label, index)
        img = self.grab()
        info = recognise(img)
        if not self.dry_run and info["state"] != LIST:
            self.log("  not in the list, state %s" % info["state"])
            self.stats["unknown"] += 1
            self.save_unknown(img, "keine_liste")
            if not self.return_to_list():
                return
            img = self.grab()
            info = recognise(img)

        cards = info["karten"] if info["karten"] else list_cards(img)
        if index >= len(cards):
            self.log("  %s not visible, %d cards recognised"
                     % (self.label_of(index, label), len(cards)))
            self.stats["skipped"] += 1
            return
        self.tap(CARD_X, cards[index], was=self.label_of(index, label))
        if self.dry_run:
            return
        time.sleep(self.pause_short)

        # Two ceilings, and the lower one wins. The player's number says how
        # much of this dungeon they want played; the counted one says how
        # much the game will actually hand out. Neither is known to the
        # other, and either can be the smaller.
        allowed = self.attempts_for(index, label)
        counted = self.counted.get((label, index)) or {}
        limit = allowed
        if counted.get("total") is not None:
            limit = min(allowed, counted["total"])
        # Ads likewise: what the card says is left, or the old blanket cap
        # when the counter could not be read.
        ad_limit = self.max_ads if counted.get("ads") is None else counted["ads"]
        if limit != allowed or ad_limit != self.max_ads:
            self.log("  playing at most %d (allowed %d, counted %s), ads %d"
                     % (limit, allowed, counted.get("total"), ad_limit))

        attempts_done = 0
        ads_used = 0
        party_searches = 0
        steps = 0
        expect_ticket = False
        ads_had_no_effect = False
        reopened = False
        while steps < self.max_loops:
            if not self._time_left():
                break
            steps += 1
            info = self.dialog_settled(tries=2)
            state = info["state"]

            if state == EXIT:
                kind = info.get("exit_kind", "beenden")
                self.dismiss_confirm(info, leaving_dungeon=True)
                if kind == "party":
                    # OK leaves the party and returns to the list. This
                    # dungeon is done with that, continuing to search would
                    # be a loop.
                    self.log("  left the party, dungeon done")
                    return
                continue

            if state == BATTLE:
                self.wait_dialog_back(self.battle_timeout)
                continue

            if state == LIST:
                if reopened or attempts_done == 0:
                    self.log("  back in the list, done")
                    return
                # Finishing an attempt sometimes drops the panel and leaves
                # the list showing, with tickets still on the card. Metal Sea
                # ended a live run that way with one attempt unspent. Open it
                # once more instead of calling the dungeon finished -- if it
                # really is empty the panel says so, and the loop ends on the
                # next pass. Once, so a card the game keeps closing cannot
                # become a loop.
                reopened = True
                here = list_cards(self.grab())
                if index >= len(here):
                    self.log("  back in the list, done")
                    return
                self.log("  back in the list, opening the card once more")
                self.tap(CARD_X, here[index], was=self.label_of(index, label))
                time.sleep(self.pause_long)
                continue

            if state == UNKNOWN:
                # Reward, result, or an intermediate screen. Tap high up,
                # that accepts rewards and does not trigger a party prompt.
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral")
                time.sleep(self.pause_short)
                continue

            if self.is_close_button(info["attempt"]):
                self.log("  reward window, closing")
                self.tap(info["attempt"]["fx"], info["attempt"]["fy"],
                         was="Close")
                time.sleep(self.pause_long)
                continue

            # After an ad, an Attempt button must appear. If the ad button
            # reappears instead, it did not yield a ticket.
            if expect_ticket:
                expect_ticket = False
                if state == DIALOG_AD:
                    ads_had_no_effect = True

            if state == DIALOG_PARTY and info["party_voll"] < 2:
                # Without team-mates, Attempt does nothing. The dialog looks
                # identical with and without a party, both buttons sit at the
                # same place. It can only be told apart by the party slots,
                # measured standard deviation 0.0 when empty against 28 to 48
                # when occupied.
                if party_searches >= 2:
                    self.log("  no party found, moving on")
                    break
                self.log("  searching for a party, %d of 3 slots filled"
                         % info["party_voll"])
                self.tap(info["party"]["fx"], info["party"]["fy"],
                         was="Find a Party")
                party_searches += 1
                time.sleep(self.pause_long * 3)
                continue

            if info["attempt"]:
                if attempts_done >= limit:
                    self.log("  played %d, which is the limit" % limit)
                    break
                self.log("  attempt %d" % (attempts_done + 1))
                t0 = time.time()
                self.tap(info["attempt"]["fx"], info["attempt"]["fy"],
                         was="Attempt")
                attempts_done += 1
                self.stats["attempts"] += 1
                if self.wait_dialog_gone(self.start_timeout):
                    if self.wait_dialog_back(self.battle_timeout):
                        duration = time.time() - t0
                        if duration < self.min_battle:
                            # Too short for a battle. The dialog was only
                            # briefly gone, e.g. because of a message. Do not
                            # count it as a battle, otherwise six missed
                            # clicks would look like six battles in the log.
                            self.log("  only %.0f s, that was no battle" % duration)
                            self.stats["declined"] += 1
                            break
                        self.stats["fights"] += 1
                        self.log("  battle finished after %.0f s" % duration)
                    continue
                # The dialog stayed open. Either rejected, or the click fell
                # inside an animation. The next pass will show which of the
                # two, since then the ad button appears instead of Attempt.
                self.log("  attempt had no effect")
                self.stats["declined"] += 1
                if attempts_done >= 2:
                    break
                continue

            if state == DIALOG_AD and info["ad"]:
                if not self.use_ads:
                    self.log("  no attempts left, ads disabled")
                    break
                if ads_had_no_effect:
                    # An ad that yielded no ticket will not yield one next
                    # time either. The game then reports "Ad viewing limit
                    # reached". Without this rule the bot used to watch six
                    # ads in a row for nothing.
                    self.log("  ads no longer yield a ticket, moving on")
                    self.exhausted.add(key)
                    break
                if ads_used >= ad_limit:
                    self.log("  no ads left, %d watched" % ads_used)
                    self.exhausted.add(key)
                    break
                self.log("  attempts empty, watching an ad")
                self.tap(info["ad"]["fx"], info["ad"]["fy"], was="Werbung")
                ads_used += 1
                self.stats["ads"] += 1
                expect_ticket = True
                time.sleep(self.pause_long)
                continue

            self.log("  nothing to do in state %s" % state)
            break

        if steps >= self.max_loops:
            self.log("  loop limit reached, moving on")
        self.note_spent(index, label, attempts_done)
        self.return_to_list()

    def wait_dialog_gone(self, timeout=8.0):
        """Wait until the dialog disappears.

        This is the evidence that a click had an effect. Before this, I
        measured the time until return and caught the dialog while it had
        not actually gone yet. The result was 0.1 seconds and the false
        report that no battle had happened, even though the battle was
        running.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if recognise(self.grab())["state"] not in self.DIALOGS:
                return True
            time.sleep(0.4)
        return False

    @staticmethod
    def is_close_button(button):
        """Narrow, centred button, so Close and not Attempt."""
        return bool(button) and button["fw"] <= CLOSE_W_MAX

    def dialog_settled(self, tries=3, pause=None):
        """Wait until the dialog has actually settled.

        After a battle, a return animation runs for 2 to 3 seconds. The
        dialog is already visible during that, but not yet interactive. A
        click on Attempt then has no effect, and the bot used to wrongly
        treat that as a rejection due to empty tickets. In a test run that
        cost the second of two battles.

        "Settled" means several consecutive frames show the same state at
        the same button position. Same principle as in the minigame bot, a
        single frame is no proof.
        """
        pause = pause if pause is not None else 0.5 * self.patience
        previous = None
        same_count = 0
        for _ in range(tries * 4):
            info = recognise(self.grab())
            fingerprint = (info["state"],
                       round(info["attempt"]["fy"], 3) if info["attempt"] else None,
                       round(info["ad"]["fy"], 3) if info["ad"] else None)
            if fingerprint == previous:
                same_count += 1
                if same_count >= tries - 1:
                    return info
            else:
                same_count = 0
                previous = fingerprint
            time.sleep(pause)
        return recognise(self.grab())

    def wait_dialog_back(self, timeout):
        """Wait until the dialog is back, tapping away rewards along the way.

        No tapping happens during a battle, that could hit Give Up. Outside
        a battle, tapping accepts the reward, which also applies after the
        ad button, since a reward window appears there too.
        """
        deadline = time.time() + timeout
        taps = 0
        while time.time() < deadline:
            img = self.grab()
            info = recognise(img)
            if info["state"] in self.DIALOGS:
                # Close windows are no longer clicked here, the main loop
                # does that. Otherwise wait_dialog_back would never return
                # such a window and the caller would check against nothing.
                return info
            if info["state"] == BATTLE:
                time.sleep(self.tick)
                continue
            if info["state"] == EXIT:
                # The party prompt arises precisely from tapping somewhere
                # while a party exists. After OK the dungeon is left, so stop
                # here.
                self.dismiss_confirm(info, leaving_dungeon=True)
                return None
            if info["state"] == LIST:
                return None
            if taps and taps % 4 == 0:
                self.back()
            else:
                # Tap high up, outside any dialog. A tap in the middle of the
                # screen can trigger a confirmation prompt; with a party it
                # acts like the back key.
                self.tap(0.5, NEUTRAL_TAP_Y, was="neutral, Belohnung annehmen")
            taps += 1
            time.sleep(self.tick)
        return None

    # ------------------------------------------------------------------
    def plan(self):
        """Two-phase plan, so that without name recognition no entry is
        played twice or not at all.

        The list is longer than the window. The first cards are visible at
        the top, the last ones at the bottom. From the total count and the
        number of cards visible at the bottom follows how many must be
        played from the top, so the two views complement each other exactly.

        Example with seven entries and five visible at the bottom. At the
        bottom that is entries 3 to 7, so 1 and 2 are played from the top.
        The last one is skipped, it changes daily.
        """
        self.scroll_bottom()
        bottom_list = list_cards(self.grab())
        n_bottom = len(bottom_list)
        if not n_bottom:
            self.log("no list cards recognised, am I in the list?")
            return 0, 0
        self.visible_at_bottom = n_bottom
        play_from_top = max(0, self.entries - n_bottom)
        play_from_bottom = max(0, n_bottom - self.skip_last)
        self.log("plan: %d cards visible at the bottom. Play %d from the top, "
                 "%d from the bottom, %d of %d in total"
                 % (n_bottom, play_from_top, play_from_bottom,
                    play_from_top + play_from_bottom, self.entries))
        return play_from_top, play_from_bottom

    def _time_left(self):
        """Checks pause, abort, and the time limit between actions. Never in
        the middle of an action, so no click is left unverified."""
        was_paused = False
        while self.control.is_paused() and not self.control.is_set():
            was_paused = True
            time.sleep(0.2)
        if was_paused and not self.control.is_set() and not self.dry_run:
            # During the pause, you may have been active in the game
            # yourself. So do not just continue blindly; check where things
            # stand first, and find the way back to the list.
            self.log("  resuming, checking the screen first")
            info = recognise(self.grab())
            if info["state"] == EXIT:
                self.dismiss_confirm(info)
            if recognise(self.grab())["state"] != LIST:
                self.log("  not in the list, state %s, returning"
                         % recognise(self.grab())["state"])
                if not self.return_to_list():
                    self.log("  no way back, aborting")
                    self.control.request("no way back to the list")
                    return False
        if self.control.is_set():
            self.log("aborted")
            return False
        if not self.max_minutes:
            return True
        if self.deadline is None:
            self.deadline = time.time() + self.max_minutes * 60
        if time.time() < self.deadline:
            return True
        self.log("time limit of %d minutes reached" % self.max_minutes)
        return False

    def run(self):
        """One pass through the list, top half then bottom half.

        It used to go round and round. The idea was that a lost battle would
        come up again next time instead of the bot getting stuck on it -- but
        this routine has no lost battles to retry: it spends attempts, and an
        attempt spent is spent whatever the outcome. What the rounds actually
        produced was a dungeon set to one attempt being handed one more in
        every round.

        How much each dungeon gets is the number beside it, and the panel
        loop plays that number in the one visit. There is nothing a second
        pass could add.
        """
        try:
            self._play()
        finally:
            self.go_home()
        return self.stats

    def _play(self):
        """One pass through the list. run wraps this, see there."""
        if not self.open_list():
            return
        play_from_top, play_from_bottom = self.plan()
        if self.dry_run:
            self.log("Note: a dry run does not scroll, so the plan is based on "
                     "whatever view is showing and may be off.")

        top_list = [i for i in range(play_from_top) if self.is_selected(i, "oben")]
        bottom_list = [i for i in range(play_from_bottom) if self.is_selected(i, "unten")]
        if self.survey_first:
            self.log("\nPre-check: which dungeons still have attempts")
            self.scroll_top()
            top_list = self.survey(top_list, "oben")
            self.scroll_bottom()
            bottom_list = self.survey(bottom_list, "unten")
            self.log("Playable, top %s, bottom %s"
                     % ([i + 1 for i in top_list] or "none",
                        [i + 1 for i in bottom_list] or "none"))
            self.stats["skipped"] += (play_from_top - len(top_list)
                                            + play_from_bottom - len(bottom_list))
            if not top_list and not bottom_list:
                self.log("nothing left to collect")
                return

        self.scroll_top()
        for index in top_list:
            if not self._time_left():
                break
            self.log("\n%s" % self.label_of(index, "oben"))
            self.play_entry(index, "oben", key=("oben", index))
            self.scroll_top()
        self.scroll_bottom()
        for index in bottom_list:
            if not self._time_left():
                break
            self.log("\n%s" % self.label_of(index, "unten"))
            self.play_entry(index, "unten", key=("unten", index))
            self.scroll_bottom()


# ----------------------------------------------------------------------------
# Label and order for format_summary, kept apart from self.stats so the dict
# itself can stay a plain counter and does not have to carry display text.
SUMMARY_LABELS = [
    ("attempts", "Attempts"),
    ("fights", "Fights"),
    ("ads", "Ads watched"),
    ("skipped", "Skipped"),
    ("not_selected", "Not selected"),
    ("unknown", "Unclear screens"),
    ("declined", "Declined"),
    ("exit_caught", "Exit prompts caught"),
]


def format_summary(stats):
    """The stats dict, laid out for reading rather than printed as a repr.

    `dict.get` rather than a straight lookup, so a caller with an older or
    trimmed stats dict still gets a readable summary instead of a KeyError.
    """
    width = max(len(label) for _, label in SUMMARY_LABELS)
    lines = ["Summary"]
    lines += ["  %-*s %d" % (width, label, stats.get(key, 0))
             for key, label in SUMMARY_LABELS]
    return "\n".join(lines)


def probe(cap, log=print):
    """Shows what is recognised on the current screen. Clicks nothing."""
    img = cap.grab()
    x0, y0, gw, gh = game_rect(img)
    info = recognise(img)
    log("window %d x %d, title bar %d px, game area %d x %d"
        % (img.shape[1], img.shape[0], y0, gw, gh))
    log("state: %s" % info["state"])
    for name in ("attempt", "party", "ad", "clear"):
        b = info[name]
        log("  %-8s %s" % (name, "relativ x %.3f y %.3f, Pixel %d,%d"
                           % (b["fx"], b["fy"], *to_pixel(img, b["fx"], b["fy"]))
                           if b else "not found"))
    log("  all blue buttons:   %s"
        % ", ".join("%.3f/%.3f" % (b["fx"], b["fy"]) for b in info["blau"]) or "none")
    log("  all violet buttons: %s"
        % ", ".join("%.3f/%.3f" % (b["fx"], b["fy"]) for b in info["violett"]) or "none")
    log("\nRecognised list cards: %s"
        % (", ".join("%.3f" % c for c in info["karten"]) or "none"))
    log("\nClick targets the bot would use")
    log("  dungeon tab     pixel %d,%d" % to_pixel(img, *NAV_DUNGEON))
    home = home_button(img)
    log("  home button     %s"
        % ("pixel %d,%d" % to_pixel(img, home["fx"], home["fy"])
           if home else "not on this screen"))
    for i, fy in enumerate(info["karten"]):
        log("  card %d          pixel %d,%d" % (i + 1, *to_pixel(img, CARD_X, fy)))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually click")
    ap.add_argument("--probe", action="store_true", help="only show what is recognised")
    ap.add_argument("--entries", type=int, default=7,
                    help="number of entries in the list")
    ap.add_argument("--skip-last", type=int, default=1,
                    help="skip this many entries at the end, the last one changes daily")
    ap.add_argument("--no-ads", action="store_true")
    ap.add_argument("--battle-timeout", type=float, default=90.0)
    ap.add_argument("--max-minutes", type=int, default=0,
                    help="time limit in minutes, 0 for none")
    # Two tickets plus two ad tickets give four battles per dungeon and day.
    # The limit sits above that, so it only triggers on an actual error.
    ap.add_argument("--max-attempts", type=int, default=6,
                    help="upper limit of Attempt clicks per dungeon and round")
    ap.add_argument("--max-ads", type=int, default=2,
                    help="upper limit of ad clicks per dungeon and round")
    ap.add_argument("--only", default=None,
                    help="only these dungeons, short names separated by commas. "
                         "Available: " + ", ".join(DUNGEON_KEYS))
    ap.add_argument("--skip", default=None,
                    help="skip these dungeons, same short names")
    ap.add_argument("--list-dungeons", action="store_true",
                    help="list the short names and exit")
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames and clicks via adb or via the window and "
                         "mouse. Default: the stored switch (Helpermon's "
                         "window, or DGUP_ADB_MODE)")
    ap.add_argument("--no-survey", action="store_true",
                    help="skip the pre-check, try every dungeon directly")
    ap.add_argument("--min-battle", type=float, default=6.0,
                    help="shorter than this was no battle, so attempts are used up")
    ap.add_argument("--patience", type=float, default=1.5,
                    help="factor on all wait times, higher is more patient")
    ap.add_argument("--swipes", type=int, default=1,
                    help="swipes needed to scroll to the end of the list")
    ap.add_argument("--no-hotkeys", "--no-mouse-guard",
                    action="store_true", dest="no_hotkeys",
                    help="disable the global F7/F8 pause and abort keys "
                         "(--no-mouse-guard is the old name for this)")
    args = ap.parse_args()

    if args.list_dungeons:
        print("Short names for --only and --skip, partial matches are enough\n")
        for i, (key, name) in enumerate(zip(DUNGEON_KEYS, DUNGEON_NAMES)):
            print("  %d  %-12s %s" % (i + 1, key, name))
        print("\nExamples")
        print("  py dungeon.py --go --skip apocalymon")
        print("  py dungeon.py --go --only apo,network")
        return

    only, unknown_o = parse_selection(args.only) if args.only else (None, [])
    skip, unknown_s = parse_selection(args.skip) if args.skip else ([], [])
    if unknown_o or unknown_s:
        print("unknown names: %s" % ", ".join(unknown_o + unknown_s))
        print("py dungeon.py --list-dungeons shows the known names")
        return
    if only is not None and skip:
        print("--only wins, --skip is ignored")
    if only is not None:
        print("Only these dungeons: %s"
              % ", ".join(DUNGEON_NAMES[i] for i in sorted(only)))
    elif skip:
        print("Skipped: %s"
              % ", ".join(DUNGEON_NAMES[i] for i in sorted(skip)))

    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)
    if args.probe:
        probe(cap)
        return

    print("Mode: %s" % ("REAL, it will click" if args.go
                        else "dry run, no clicks"))
    bot = DungeonBot(cap, dry_run=not args.go, entries=args.entries,
                     skip_last=args.skip_last, use_ads=not args.no_ads,
                     battle_timeout=args.battle_timeout,
                     max_minutes=args.max_minutes,
                     max_attempts=args.max_attempts, max_ads=args.max_ads,
                     survey_first=not args.no_survey, patience=args.patience,
                     only=only, skip=skip,
                     min_battle=args.min_battle, swipes=args.swipes)
    print("Reference frame %d x %d" % bot.device)
    _keys(bot)
    control = None if args.no_hotkeys else guard.start(bot.control)
    try:
        stats = bot.run()
    except KeyboardInterrupt:
        stats = bot.stats
        print("\naborted")
    finally:
        if control:
            control.stop()
    print("\n%s" % format_summary(stats))


def _keys(bot):
    """Space pauses, q aborts, console focus only. guard.py additionally
    wires up global F7/F8 hotkeys that work even when the emulator window
    has focus instead of this console."""
    try:
        import msvcrt
    except ImportError:
        return
    import threading

    def loop():
        while not bot.control.is_set():
            ch = msvcrt.getwch()
            if ch == " ":
                paused = bot.control.toggle_pause()
                print("    %s" % ("paused, space resumes"
                                  if paused else "resumed"), flush=True)
            elif ch in ("q", "Q"):
                bot.control.request("key q")
                print("    abort requested", flush=True)

    threading.Thread(target=loop, daemon=True).start()
    print("Keys: space pauses, q aborts (console focus needed)")


if __name__ == "__main__":
    main()
