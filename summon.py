"""
Special Summon bot: spends Skill Card, Support Digimon and Crest Summon
tickets, biggest draw every time.

Same principle as dungeon.py and passive.py: no images from the game, no
setup step. Every screen is told apart by colour, shape and neighbour, the
way CLAUDE.md asks for.

  py summon.py --probe      shows what is recognised, clicks nothing
  py summon.py              dry run, plans but does NOT click
  py summon.py --go         actually clicks

F7 pauses/resumes and F8 aborts globally, see guard.py.

The one recognizer everything else hangs off is summon_button: the
brightest, wide, full yellow button on the screen. It moves between the
main screen, the result screen and the Crest confirmation dialog, and is
never read from a stored position -- it is found fresh every time. Where it
sits also answers "may I click the ticket-spending button here", because a
result screen puts a second yellow button on the row and this bot must
never treat that one as the same click as the one that opened it.

Two colour ranges were measured live against the running game on
2026-08-26 (YELLOW, DOT_ORANGE/DOT_INACTIVE, RED) -- see debug_summon/ for
the frames. Everything else (crop positions, widths) is the raw fractions
from PLAN_SUMMONS.md section 4, not yet re-measured on a game_rect-correct
frame: run --probe before a real --go and compare what it prints against
what is on screen, the same way dungeon.py's probe is used to debug a
misread.
"""

import argparse
import os
import time

import cv2
import numpy as np

import capture
import dungeon as D
import guard
import passive as P
import userdata


# ----------------------------------------------------------------------------
# The yellow summon button
# ----------------------------------------------------------------------------
# Measured live on the running game: a live button (main screen, result
# screen, Crest dialog) reads H 8-26 S 211-255 V 235-255; the same button
# dimmed behind an open dialog drops to V 51-108 with its saturation
# unchanged. The range's own floor at V 180 is what keeps the dimmed one
# out -- the same trick dungeon.auto_button uses, so a Crest dialog with two
# yellow buttons on screen (the live dialog one and the dimmed one behind
# it) never finds the wrong one by accident.
YELLOW = ((10, 150, 180), (35, 255, 255))

# Width as a fraction of the game width. Measured in PLAN_SUMMONS.md 4.1:
# the rank badges on a result screen's cards are 0.124 and 0.157 wide, the
# real button 0.245 to 0.266 -- room on both sides.
SUMMON_BUTTON_W = (0.20, 0.30)
# A filled rectangle, not text on a badge: measured live 0.89 for a button
# with a longer label ("10x Summon", dark text eating more of the yellow
# than the plainer buttons) against 0.62 to 0.66 for a rank badge -- still
# room to spare above the badges with the floor here.
SUMMON_BUTTON_FILL_MIN = 0.85


def summon_button(img):
    """The brightest wide, full yellow button on the screen, or None.

    Several yellow blobs can be on screen at once -- a dimmed one is
    filtered out by YELLOW's own brightness floor already; if more than
    one live one is ever found, the brightest is kept, never the first
    found or the one nearest the bottom.
    """
    x0, y0, gw, gh = D.game_rect(img)
    mask = cv2.inRange(cv2.cvtColor(img, cv2.COLOR_BGR2HSV), *YELLOW)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best, best_v = None, -1.0
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not w or not h:
            continue
        fw = w / float(gw)
        if not SUMMON_BUTTON_W[0] <= fw <= SUMMON_BUTTON_W[1]:
            continue
        if area / float(w * h) < SUMMON_BUTTON_FILL_MIN:
            continue
        v = float(cv2.cvtColor(img[y:y + h, x:x + w],
                                cv2.COLOR_BGR2HSV)[:, :, 2].mean())
        if v > best_v:
            best_v = v
            best = {"fx": (x + w / 2.0 - x0) / gw,
                    "fy": (y + h / 2.0 - y0) / gh,
                    "fw": fw, "fh": h / float(gh)}
    return best


# Where the X sits that returns to the mode screen, as a multiple of the
# button's own width to its right. Measured on the result screen: button
# centred at fx 0.638 (raw), X at 0.839, a gap of 0.201 against a button
# width of 0.253 -- 0.79 button-widths. Position only, never colour: a
# white square with a small blue mark does not separate from a busy
# screen by colour the way the button does. The caller verifies the tap
# worked by reading mode_dots afterwards, never by trusting this alone.
X_BESIDE_OFFSET = 0.80


def x_beside_button(button):
    return button["fx"] + X_BESIDE_OFFSET * button["fw"], button["fy"]
# ----------------------------------------------------------------------------
# The X that closes Special Summon
# ----------------------------------------------------------------------------
# The same physical button x_beside_button aims at, found in its own right
# instead of off a yellow button beside it, because the run has to walk out
# of Special Summon from screens that have no button worth measuring from.
#
# It never moves. Measured at fx 0.7934 fy 0.9567 on fifteen frames of six
# window shapes -- 573, 736, 757, 759 and 1080 wide, the last of them the
# ADB frame -- and the whole spread across them is 0.0011 in fx and 0.0002
# in fy. What moves is the summon button: on a result screen the button row
# drops to the bottom and x_beside_button then lands within 0.004 of this
# same X, which is why that route works; on a mode screen the row sits at
# fy 0.885 and the same arithmetic points at empty sky 0.07 above the X.
EXIT_BUTTON_FX = 0.7934
EXIT_BUTTON_FY = 0.9567
# The plate's width. The crop taken below is deliberately smaller than the
# plate -- 0.35 of it either side of the centre, not 0.5 -- so that a window
# shape this was never measured at cannot slide the background into it. That
# is not theoretical: pushed 0.008 gw sideways, a crop of 0.45 drops the
# plate share to 0.677 while one of 0.35 holds 0.720.
EXIT_BUTTON_FW = 0.0785
EXIT_CROP = 0.35
# A near-white plate with a small blue X on it. Neither half tells it from
# the game on its own -- the plate is the same white as half the UI, and the
# main screen reads 0.189 of this very blue at this very spot -- so it is
# the pair that decides, the way CLAUDE.md asks for. Measured over those
# fifteen frames: plate 0.749 to 0.760, mark 0.211 to 0.226. The nearest
# rival among every other frame in debug_summon is the main screen at plate
# 0.000 mark 0.189, and a draw animation at plate 0.292 mark 0.002.
EXIT_PLATE = ((0, 0, 225), (180, 45, 255))
EXIT_MARK = ((98, 110, 140), (118, 220, 255))
# Floors far enough below what they must catch to survive a misaligned crop:
# 0.60 against a worst case of 0.720, 0.12 against 0.187.
EXIT_PLATE_MIN = 0.60
EXIT_MARK_BAND = (0.12, 0.34)


def exit_button(img):
    """The X that closes one Special Summon screen, or None.

    None also answers "is a Special Summon screen in front at all": every
    tab and every result screen carries this X, and a dialog drawn over it
    dims the plate out of the white mask the same way dungeon.auto_button's
    disc loses its edges. So a caller that finds it has evidence that a tap
    there will land on something, not only where to send it.
    """
    x0, y0, gw, gh = D.game_rect(img)
    r = EXIT_CROP * EXIT_BUTTON_FW * gw
    cx, cy = x0 + EXIT_BUTTON_FX * gw, y0 + EXIT_BUTTON_FY * gh
    top, bottom = int(cy - r), int(cy + r)
    left, right = int(cx - r), int(cx + r)
    if top < 0 or left < 0 or bottom > img.shape[0] or right > img.shape[1]:
        return None
    hsv = cv2.cvtColor(img[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    if hsv.size == 0:
        return None
    n = float(hsv.shape[0] * hsv.shape[1])
    plate = cv2.inRange(hsv, *EXIT_PLATE).sum() / 255.0 / n
    mark = cv2.inRange(hsv, *EXIT_MARK).sum() / 255.0 / n
    if plate < EXIT_PLATE_MIN:
        return None
    if not EXIT_MARK_BAND[0] <= mark <= EXIT_MARK_BAND[1]:
        return None
    return {"fx": EXIT_BUTTON_FX, "fy": EXIT_BUTTON_FY,
            "plate": plate, "mark": mark}


# ----------------------------------------------------------------------------
# Which mode is selected
# ----------------------------------------------------------------------------
# Measured live: the active dot's orange reads H 8-12 S 143-255 V 240-255,
# well clear of the sky-blue background behind it. The two inactive dots do
# not separate from that background by hue or saturation at all -- both
# measure H 108-115 S 56-118, and the plain sky right beside a dot measures
# the same H108 S60. What does separate them is brightness: the sky there
# is a flat, textureless V 255, while the dot -- being a filled, shaded
# disc -- dips to V 118-235. Without the upper bound on V the inactive mask
# swallows the whole sky into one component 140,000 pixels large and the
# two real dots vanish inside it.
DOT_ORANGE = ((4, 130, 150), (20, 255, 255))
DOT_INACTIVE = ((95, 40, 100), (125, 140, 235))
# Raw fraction from a screenshot not taken through grab_screen.py: the dot
# row sat at fy 0.26-0.28 there, between the mode banners above and the
# ticket counter below. Widened for safety until re-measured on a
# game_rect-correct frame.
DOT_Y_BAND = (0.18, 0.38)
# Measured live: the real dots are about 9-10 px square at 607 px game
# width, area 62-76 -- comfortably above this, with room below for a
# smaller window.
DOT_MIN_AREA = 0.00003
DOT_ASPECT = (0.5, 2.0)
# The three dots sit close together, not spread across the screen -- used
# to reject stray same-coloured artwork rather than trusting the band
# alone.
DOT_Y_TOL = 0.006
DOT_X_SPREAD_MAX = 0.16
# Three rules that say "these three blobs are the dot row" rather than
# "these three blobs happen to be near each other". Without them the
# reader took the first orange blob that had two companions of any size at
# any spacing, and on the Buddy tab -- one banner, one dot -- it found a
# row in the banner artwork and reported mode 2 for a screen that has no
# modes at all.
#
# Measured on ADB-shaped frames of all three mode screens, the real dots:
#
#   skill    orange 17 x 17   inactive 20 x 18, 20 x 18
#   support  orange 16 x 17   inactive 20 x 18, 20 x 18
#   crest    orange 17 x 17   inactive 20 x 18, 20 x 18
#
# and the false row on the Buddy tab: 54 x 27, 111 x 70, 12 x 16. The real
# rows spread 20/16 = 1.25 across their members, the false one 111/12 =
# 9.25. 1.6 sits between with room either side.
DOT_SIZE_RATIO_MAX = 1.6
# Same story for the gaps. Real dots are evenly spaced -- 19 px and 19 px
# on the skill screen -- while the false row measured 62 and 46, a ratio
# of 1.35.
DOT_GAP_RATIO_MAX = 1.25
# And the baseline: the three real dots share one cy exactly, the false
# row spread 21 px. The old tolerance of 0.02 gh was 28 px and let that
# through; 0.006 gh is 8 px on a window frame and 12 on an ADB one.


def _dot_blobs(mask, gw, gh):
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not w or not h or area < DOT_MIN_AREA * gw * gh:
            continue
        if not DOT_ASPECT[0] <= w / float(h) <= DOT_ASPECT[1]:
            continue
        out.append({"cx": x + w / 2.0, "cy": y + h / 2.0, "w": w, "h": h})
    return out


def _looks_like_a_row(row):
    """True if these three blobs are the dot row and not three coincidences.

    Same size and evenly spaced. Either test alone would have caught the
    Buddy tab; both are cheap and they fail differently, so both stay.
    """
    widths = [b["w"] for b in row]
    heights = [b["h"] for b in row]
    for side in (widths, heights):
        if max(side) > DOT_SIZE_RATIO_MAX * max(1.0, min(side)):
            return False
    gaps = [row[i + 1]["cx"] - row[i]["cx"] for i in range(len(row) - 1)]
    if min(gaps) <= 0:
        return False
    return max(gaps) <= DOT_GAP_RATIO_MAX * min(gaps)


def mode_dots(img):
    """Which of the three mode banners is selected -- 1, 2 or 3 -- or None.

    Found by colour and count, not by position, because the row is centred
    under the banners and a dot's own x drifts with the window. What does
    not drift: there are three of them, close together, and exactly one is
    orange. Counted from the left, per CLAUDE.md's own instruction for this
    reader rather than read off the orange one's own position.
    """
    x0, y0, gw, gh = D.game_rect(img)
    top = max(0, int(y0 + DOT_Y_BAND[0] * gh))
    bottom = int(y0 + DOT_Y_BAND[1] * gh)
    sub = img[top:bottom, max(0, x0):x0 + gw]
    if sub.size == 0:
        return None
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    oranges = _dot_blobs(cv2.inRange(hsv, *DOT_ORANGE), gw, gh)
    inactives = _dot_blobs(cv2.inRange(hsv, *DOT_INACTIVE), gw, gh)
    for o in oranges:
        row = [o] + [c for c in inactives
                      if abs(c["cy"] - o["cy"]) <= DOT_Y_TOL * gh
                      and abs(c["cx"] - o["cx"]) <= DOT_X_SPREAD_MAX * gw]
        if len(row) != 3:
            continue
        row.sort(key=lambda b: b["cx"])
        if not _looks_like_a_row(row):
            continue
        return row.index(o) + 1
    return None


# ----------------------------------------------------------------------------
# General, and the neighbour banner
# ----------------------------------------------------------------------------
# Buddy's green, measured live: H 76-77 S 166-221 V 215-221.
GREEN = ((65, 90, 140), (90, 255, 255))
TAB_Y_TOL = 0.04

# The area floor for the two tabs, and the reason this bot could not open
# Special Summon at all on its first live run.
#
# It stood at 0.006 of the reference window, and that is what the tabs
# themselves measure. On a window frame General covers 6,821 px of a
# 803 x 1386 window space, which is 0.00613 -- over the line by 2 %. On the
# ADB frame the bot actually runs on, the same tab covers 13,092 px of a
# 1147 x 1980 window space, which is 0.00577 -- under the line by 4 %, and
# Buddy misses by 1 %. The frames the suite paints are clean and generous,
# so every test passed while the live run timed out on the entry screen
# twice in a row.
#
# The two do not agree because min_area is taken against the window space,
# which is larger than the image and by a different factor on each source
# (1.060 against 1.096), and because an anti-aliased edge loses a different
# share of its pixels at each scale. A 3 % margin cannot survive either.
# This is CLAUDE.md's own trap, the one the glyph filter fell into at 0.28
# against digits measuring 0.274.
#
# 0.003 leaves a factor of two below the smallest real measurement. What
# keeps the lower floor from letting anything else in is not the area at
# all -- it is the pair below.
TAB_MIN_AREA = 0.003
# Both tabs are the same size, measured 0.242 to 0.245 wide on window and
# ADB frames alike. The bottom row's blue buttons measure 0.172 to 0.236,
# so width alone would not separate them -- but they have no green tab
# beside them, and that is what does.
TAB_FW = (0.18, 0.32)
TAB_FW_TOL = 0.06


def general_tab(img):
    """The blue General tab, identified by the green Buddy tab beside it.

    Position will not do here: General sits at rel. x 0.17 on the entry
    screen and blue buttons of roughly the same shape turn up at other x
    positions on every mode screen afterwards (15x Summon). The green
    neighbour at the same height, and of the same width, is what is unique
    to this one screen.
    """
    blues = D.find_buttons(img, D.BLUE, min_area=TAB_MIN_AREA, min_y=0.0)
    greens = D.find_buttons(img, GREEN, min_area=TAB_MIN_AREA, min_y=0.0)
    for b in blues:
        if not TAB_FW[0] <= b["fw"] <= TAB_FW[1]:
            continue
        for g in greens:
            if not D.near(g["fy"], b["fy"], TAB_Y_TOL):
                continue
            if g["fx"] <= b["fx"]:
                continue
            if abs(g["fw"] - b["fw"]) > TAB_FW_TOL:
                continue
            return b
    return None


# Raw fractions from PLAN_SUMMONS.md 4.6: the banner row's own fy, and the
# neighbour banner's centre to either side of the selected one.
BANNER_FY = 0.20
NEIGHBOUR_FX_RIGHT = 0.80
NEIGHBOUR_FX_LEFT = 0.13

# Where the Summon icon sits on the game's main screen. fx confirmed by
# passive.py's own measurement (0.822); fy confirmed live on 2026-08-26 by
# a real tap that opened Special Summon.
SUMMON_ICON_FX = 0.80
SUMMON_ICON_FY = 0.54


# ----------------------------------------------------------------------------
# The ticket / crest counter, top right
# ----------------------------------------------------------------------------
# White digits on a dark badge, the same shape dungeon.badge_glyphs reads --
# confirmed live on both screens this counter appears on. Two positions
# rather than one: fy about 0.23-0.33 on the mode's own main screen, about
# 0.01-0.10 on the result screen; fx is the same narrow column on both,
# confirmed live. A single band wide enough to cover both merged the badge
# into the surrounding artwork and text -- one connected blob 350,000
# pixels large -- so each position gets its own narrow crop instead, and
# whichever one actually holds a badge is the one that parses.
TICKET_BANDS = ((0.63, 0.87, 0.23, 0.33), (0.63, 0.87, 0.01, 0.10))
TICKET_SCALE = 4
TICKET_WHITE = (200, 255)
# Measured live on "4,734": the four digits are 31-35 px wide by 46-47
# tall, aspect 0.65-0.82; the ticket icon beside them, caught by the same
# mask because its own centre is a white shape, is 80 x 81, aspect 0.99.
# The upper bound sits between the two with margin either side.
TICKET_ASPECT = (0.15, 0.95)
TICKET_FILL_MIN = 0.15
# The comma is short -- 20 px against a 46 px digit, well under half. A
# height floor high enough to keep it out a title banner drifting into the
# crop above the badge would keep the comma out too, so height alone
# cannot be the filter; _ticket_row below anchors on the tallest glyph
# instead and reads everything near its own row, comma included.
#
# This floor is only there to throw away one- and two-pixel dirt. It must
# NOT be asked to separate a comma from a speck, because it is a fraction
# of the crop, and CLAUDE.md already records what happens then: a
# threshold measured against the crop moves when the crop does.
TICKET_MIN_H = 0.012
# What actually separates them, measured against the digits themselves.
#
# This is the bug that made the first live run unreadable. The ticket icon
# beside the number has a small white mark inside it, and on the frame
# kept as debug_summon/stalled_00.png it came out 14 x 20 next to digits
# of 87 to 88 -- over the crop-relative floor of 0.03 (16.9 px) by three
# pixels. It joined the row as a sixth character, "2,739" parsed as six
# glyphs, and the whole counter went unread. Three rounds of that and the
# mode gave up, while the number sat plainly on the screen.
#
# Every glyph as a share of the tallest one in the same crop, over every
# frame in debug_summon/ that actually holds a badge:
#
#   digits             0.72 - 1.00
#   the comma          0.42   (22 x 37 against 87, on three separate frames)
#   icon marks, dirt   0.02 - 0.23
#
# 0.32 sits 24 % below the comma and 39 % above the worst speck. Anything
# nearer than that to either is the mistake this replaces.
TICKET_MIN_REL_H = 0.32

# How many characters a crop must hold before it is believed to be the
# badge at all.
#
# One is not enough, and that is not a guess: on the Crest result screen a
# single stray 29 x 46 mark in the main-screen band parsed as "1" and was
# returned, while the band beside it held a clean "446" and was never
# tried, because the first band that parses wins. On the draw animation --
# where there is no badge on the screen at all -- a lone 18 x 20 blob
# parsed as "7". A made-up number is worse than an admitted None: the loop
# compares this reading with the one before it to decide what happened.
#
# The cost of asking for two is that a genuine one-digit count reads as
# None. That costs nothing here. Every price is 10 or 30, so a single
# digit always means "stop", and the red price says so independently --
# the counter is only ever the cross-check for it (PLAN_SUMMONS.md 0).
#
# Counted in DIGITS, not in row members, and that distinction is the
# second half of the same bug. The row is split into digits and commas by
# height further down, so a row of two whose shorter member is taken for a
# comma yields a one-digit number after all -- which is how a lone "7"
# from the Reward banner's artwork still got returned from a crop that had
# passed a two-member check.
TICKET_MIN_DIGITS = 2

# And how tall a character of the counter is, as a share of the game's own
# height. This is what finally separates the badge from everything else
# that is white and roughly digit-shaped.
#
# The badge is a fixed piece of interface, so this hardly varies at all.
# Measured over every frame in debug_summon/ whose reading is known to be
# right -- 2199, 2642, 2739, 398, 496, 4734, 5299, 24, 54, 446, on window
# and ADB frames alike:
#
#   every correct reading      0.0107 - 0.0112
#   wrong ones, below          0.0018  0.0048  0.0052  0.0053  0.0067
#                              0.0069  0.0087  0.0091
#   wrong ones, above          0.0165  0.0167  0.0169  0.0171  0.0274
#                              0.0326  0.0331
#
# The band below leaves 16 % to the nearest wrong reading underneath and
# 27 % to the nearest above, with the real span sitting in the middle of
# it. This is what would have stopped the live run's false abort: two
# stray 5-pixel marks in the result band read as "77" at 0.0048, the run
# took it for the count, and the next perfectly good 2,199 looked like the
# number going up.
TICKET_H_OF_GAME = (0.009, 0.013)


def _ticket_mask(img, band):
    x0, y0, gw, gh = D.game_rect(img)
    fx0, fx1, fy0, fy1 = band
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0 or sub.shape[0] < 2 or sub.shape[1] < 2:
        return None
    big = cv2.resize(sub, (sub.shape[1] * TICKET_SCALE,
                            sub.shape[0] * TICKET_SCALE),
                      interpolation=cv2.INTER_CUBIC)
    return cv2.inRange(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), *TICKET_WHITE)


def _ticket_glyphs(mask):
    """Characters in the badge, left to right.

    Two passes, and the order is the point. The crop-relative floor only
    clears away dirt; what decides whether something is a character is its
    height against the tallest character found, never against the crop.
    See TICKET_MIN_REL_H for the frame this got wrong.
    """
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not h or h < TICKET_MIN_H * mask.shape[0]:
            continue
        if not TICKET_ASPECT[0] <= w / float(h) <= TICKET_ASPECT[1]:
            continue
        if area / float(w * h) < TICKET_FILL_MIN:
            continue
        out.append(stats[i])
    if not out:
        return []
    tallest = max(s[3] for s in out)
    out = [s for s in out if s[3] >= TICKET_MIN_REL_H * tallest]
    out.sort(key=lambda s: s[0])
    return out


def _ticket_row(glyphs):
    """Glyphs belonging to the counter, anchored on its tallest one.

    There is no slash to anchor on here, unlike dungeon's card badges or
    passive's hologram counter, so the tallest surviving glyph stands in
    for it -- always a digit, since the aspect filter above already took
    the ticket icon out and a comma is shorter than a digit by design.
    Everything else within a generous reach of its row, comma included,
    joins it; a title banner drifting into the crop above the badge sits
    nowhere near that row and is left out.
    """
    if not glyphs:
        return []
    tallest = max(g[3] for g in glyphs)
    anchor_cy = next(g[1] + g[3] / 2.0 for g in glyphs if g[3] == tallest)
    return [g for g in glyphs
            if abs((g[1] + g[3] / 2.0) - anchor_cy) <= 0.9 * tallest]


def ticket_counter(img):
    """Remaining tickets or crests, top right, or None if unreadable.

    All or nothing, like dungeon.read_counter: a number missing a digit
    reads as a number that looks perfectly fine and is wrong, which is
    worse than admitting nothing was read. Tried against each known badge
    position in turn -- only one of them ever actually holds a badge.
    """
    gh = D.game_rect(img)[3]
    for band in TICKET_BANDS:
        mask = _ticket_mask(img, band)
        if mask is None:
            continue
        row = _ticket_row(_ticket_glyphs(mask))
        if not row:
            continue
        tallest = max(g[3] for g in row)
        # Is this the badge at all, or something else white in the crop?
        share = tallest / float(TICKET_SCALE) / float(gh)
        if not TICKET_H_OF_GAME[0] <= share <= TICKET_H_OF_GAME[1]:
            continue
        digits = sorted((g for g in row if g[3] >= 0.75 * tallest),
                         key=lambda g: g[0])
        commas = [g for g in row if g[3] < 0.75 * tallest]
        if len(digits) < TICKET_MIN_DIGITS:
            continue
        if not P._commas_hold(digits, commas):
            continue
        value = D.read_counter(mask, digits)
        if value is not None:
            return value
    return None


# ----------------------------------------------------------------------------
# The price, and whether it is red
# ----------------------------------------------------------------------------
# Measured live on a result screen with an unaffordable draw: the red "30"
# reads H 0 S 255 V 103-255 over a tight crop, against 0 red pixels in a
# same-sized crop of the white "15" beside it. The pink "!" corner badge
# sits near hue 150 (per CLAUDE.md's own measurement of that same pink on a
# different dialog) and falls well outside this band either way.
RED = ((0, 150, 90), (8, 255, 255))
RED_HIGH = ((172, 150, 90), (179, 255, 255))
# Measured live: a red "30" over the generous crop below scores 0.008, a
# white "15" over the same crop scores 0.0 -- the whole gap is margin.
PRICE_RED_MIN = 0.003
# The price sits directly above the button, roughly on its own column.
# Cropped relative to the found button rather than from a fixed position,
# so it lands right on the main screen, the result screen and the Crest
# dialog alike. Measured live: the digits themselves sit 0.014 to 0.033 of
# the game height above the button's own top edge -- a wider reach caught
# the card artwork above it on the main screen, which is red often enough
# (a fire-type Digimon) to read as the abort condition on a full wallet.
PRICE_ABOVE = (0.045, 0.008)
PRICE_HALF_W = 0.55


def _price_crop(img, button):
    x0, y0, gw, gh = D.game_rect(img)
    cx = x0 + button["fx"] * gw
    top_of_button = y0 + (button["fy"] - button["fh"] / 2.0) * gh
    half_w = PRICE_HALF_W * button["fw"] * gw
    top = int(top_of_button - PRICE_ABOVE[0] * gh)
    bottom = int(top_of_button - PRICE_ABOVE[1] * gh)
    left, right = int(cx - half_w), int(cx + half_w)
    return img[max(0, top):max(0, bottom), max(0, left):right]


def price_is_red(img, button):
    """Is the price above this button drawn red -- the abort condition?"""
    crop = _price_crop(img, button)
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, *RED) | cv2.inRange(hsv, *RED_HIGH)
    return float(np.count_nonzero(red)) / red.size >= PRICE_RED_MIN


# ----------------------------------------------------------------------------
# View Ads and its counter
# ----------------------------------------------------------------------------
def view_ads_button(img, button=None):
    """The View Ads button, or None -- also the answer for Crest, which has
    none. Found relative to the yellow button rather than at a fixed
    position: View Ads, 15x Summon and 35x Summon all sit at the same
    height as it, and View Ads is the leftmost of the row.
    """
    button = button if button is not None else summon_button(img)
    if button is None:
        return None
    row = sorted((b for b in D.find_buttons(img, D.BLUE, min_area=0.003,
                                             min_y=0.0)
                  if D.near(b["fy"], button["fy"], 0.04)),
                 key=lambda b: b["fx"])
    return row[0] if len(row) >= 2 else None


def _adaptive_text_mask(gray):
    """Binary text mask, dark-on-light or light-on-dark alike.

    The ad counter is drawn dark on a light background, unlike the white-
    on-dark ticket badge -- the same split CLAUDE.md notes for the price.
    Otsu splits the crop into its two halves; the smaller one is the text,
    a crop like this being mostly background either way.
    """
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    if cv2.countNonZero(mask) > mask.size // 2:
        mask = cv2.bitwise_not(mask)
    return mask


# Measured live, the same way as the price above: a wider reach above the
# button caught a hover-animation arrow well clear of the counter, and its
# x happened to line up with the first digit closely enough that
# dungeon.group_glyphs -- which groups by x-gap only, not by row -- pulled
# it into the same group as "2 /2" and the slash search inside it failed.
ADS_ABOVE = (0.05, 0.005)
ADS_HALF_W = 0.55
ADS_SCALE = 4
# Measured live: the film icon beside the counter is roughly square,
# aspect 1.05, against 0.46 to 0.69 for the digits and slash -- the upper
# bound sits between the two so the icon never joins dungeon.group_glyphs'
# x-based grouping and swallows the slash search with its own height.
ADS_ASPECT = (0.15, 0.85)
ADS_FILL_MIN = 0.15
ADS_MIN_H = 0.06


def ads_left(img, button=None):
    """Free ads left to watch, read from the "n /2" counter above View Ads.

    Both numbers count down, confirmed the hard way on the dungeon's cards
    (CLAUDE.md): "2 /2" is two still to watch, not two watched.
    """
    ads_button = view_ads_button(img, button)
    if ads_button is None:
        return None
    x0, y0, gw, gh = D.game_rect(img)
    cx = x0 + ads_button["fx"] * gw
    top_of_button = y0 + (ads_button["fy"] - ads_button["fh"] / 2.0) * gh
    half_w = ADS_HALF_W * ads_button["fw"] * gw
    top = int(top_of_button - ADS_ABOVE[0] * gh)
    bottom = int(top_of_button - ADS_ABOVE[1] * gh)
    left, right = int(cx - half_w), int(cx + half_w)
    crop = img[max(0, top):max(0, bottom), max(0, left):right]
    if crop.size == 0 or crop.shape[0] < 2 or crop.shape[1] < 2:
        return None
    big = cv2.resize(crop, (crop.shape[1] * ADS_SCALE, crop.shape[0] * ADS_SCALE),
                      interpolation=cv2.INTER_CUBIC)
    mask = _adaptive_text_mask(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    glyphs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not h or h < ADS_MIN_H * mask.shape[0]:
            continue
        if not ADS_ASPECT[0] <= w / float(h) <= ADS_ASPECT[1]:
            continue
        if area / float(w * h) < ADS_FILL_MIN:
            continue
        glyphs.append(stats[i])
    glyphs.sort(key=lambda s: s[0])
    for group in D.group_glyphs(glyphs):
        digits = D.counter_digits(group)
        if digits:
            return D.read_counter(mask, digits)
    return None


# ----------------------------------------------------------------------------
# The bot
# ----------------------------------------------------------------------------
SKILL, SUPPORT, CREST = 1, 2, 3
MODE_ORDER = (SKILL, SUPPORT, CREST)
MODE_NAMES = {SKILL: "Skill Card Summon", SUPPORT: "Support Digimon Summon",
              CREST: "Crest Summon"}
# The fixed cost of the biggest draw in each mode -- 35x for Skill and
# Support, 10x for Crest. Known from the game rather than read off the
# screen: the price is drawn in a different colour and a different polarity
# on every screen it appears on (4.4), while the number itself never
# changes. Used as the cross-check against the ticket count, which the plan
# calls for ("Gegenprobe: Restbestand oben rechts < Preis").
MODE_PRICE = {SKILL: 30, SUPPORT: 30, CREST: 10}
MODE_HAS_ADS = {SKILL: True, SUPPORT: True, CREST: False}
# Whether a tap on the yellow button raises a confirmation dialog before
# anything is drawn. Only Crest does, and this table exists to keep the
# animation-hurrying taps away from it: the dialog takes a moment to be
# drawn, and during that moment there is no button on screen, so a tap
# meant for an animation lands beside the dialog and closes it again. That
# cost three Crest draws in a live run -- the count sat at 388 for three
# rounds and the mode gave up, while every round looked like a click that
# achieved nothing.
#
# The price is that a Crest draw's animation is not hurried along. That is
# a few seconds each on a few dozen draws, against several hundred for
# Skill and Support where the hurrying stays.
MODE_HAS_CONFIRM = {SKILL: False, SUPPORT: False, CREST: True}

# How long the summon button may be gone: an animation, a rare single-card
# reveal, or (for the ad phase) a whole video.
SPAM_TIMEOUT = 25.0
AD_TIMEOUT = 90.0
# Grace period before the first "tap the upper half" attempt at clearing a
# knopflose Einzelenthuellung -- not on the very first missing frame, which
# would fire off in the middle of a perfectly ordinary animation.
NEUTRAL_TAP_FY = 0.10
# Whether to tap while waiting for the button to come back, and how often.
#
# The draw animation runs about 5 seconds and a tap anywhere ends it at
# once, so tapping through it is most of the run's speed. The earlier
# attempt fired three taps straight after the summon tap and they landed
# after the animation had finished on its own -- taps sent before the
# animation is on screen are simply early. Tapping from inside the wait
# fixes that: it only happens on a frame that has just been looked at and
# has no button on it.
#
# And "no button on the frame" is what makes it safe, rather than a
# position band. summon_button finds the Crest confirmation dialog's own
# yellow button, so a frame showing that dialog never reaches this branch
# and the dialog is never tapped away. What does reach it is the
# animation, the rare single-card reveal, and the loading between them --
# none of which has a button to hit.
REVEAL_TAP_EVERY = 0.6
# Frames without a button before the first hurrying tap. One is not
# proof of an animation -- it is also what a screen looks like while
# it is changing into something else.
HURRY_AFTER_MISSING = 2
# Walking back out: how long to keep at it, how long to leave between
# rounds, and how many taps are worth sending at all.
#
# The X pops one screen, so the deepest the bot can ever be is two: a
# result screen, then the mode screen, then the game. Four is that doubled,
# because a tap that lands during an animation is eaten and has to be sent
# again -- and it is a cap, not a target: once four taps have gone out
# without auto_button appearing, whatever is on screen is not what this
# bot thinks it is, and more taps into it would be exactly the blind
# clicking CLAUDE.md warns about.
EXIT_TAPS_MAX = 4
# Rounds, not a deadline. back_to_main counts rounds for the same reason:
# patience is a factor on the waiting, and a deadline built out of it
# collapses to "no rounds at all" the moment patience is zero.
EXIT_ROUNDS = 20
EXIT_ROUND = 0.6


def _num(value):
    return "{:,}".format(value)


class SummonBot:
    """Opens Special Summon, spends each enabled mode's tickets, moves on.

    Borrows a DungeonBot for tapping and pausing rather than growing its
    own -- same reasoning as passive.py: those carry the guards already
    measured against real frames.
    """

    def __init__(self, cap, dry_run=True, log=print, enabled=None,
                 watch_ads_first=True, max_per_mode=0, patience=1.5,
                 stall_limit=3, blind_limit=3, debugdir="debug_summon"):
        self.cap = cap
        self.dry_run = dry_run
        self.log = log
        self.enabled = dict(enabled) if enabled else {m: True for m in MODE_ORDER}
        self.watch_ads_first = watch_ads_first
        self.max_per_mode = max_per_mode
        self.patience = patience
        self.stall_limit = stall_limit
        # A different question from stall_limit, so a different number:
        # "the count is not moving" and "there is no count on this screen"
        # are not the same thing, and CLAUDE.md asks for one threshold per
        # question. See spam for what the second one is really counting.
        self.blind_limit = blind_limit
        self.debugdir = debugdir
        self.bot = D.DungeonBot(cap, dry_run=dry_run, log=self._quiet)
        self.control = self.bot.control
        self._aborted_said = False
        self.stats = {"summons": 0, "ads": 0, "modes_done": 0,
                      "modes_skipped": 0}
        self._dumps = 0

    def _quiet(self, text):
        pass

    def grab(self):
        return self.bot.grab()

    def tap(self, fx, fy, was=""):
        self.bot.tap(fx, fy, was=was)

    def _pause_gate(self):
        """False when the run must not go on.

        `wait_while_paused` answers only the pause question: it returns
        True the moment the bot is not paused, whether or not a stop has
        been requested, and reports the abort only if it happened to be
        waiting out a pause when the flag was set. Checking it alone is
        why the Stop button in the launcher did nothing -- it sets the
        flag, and nothing here ever looked at it. Every other bot in this
        program checks is_set() beside it; this one now does too.
        """
        if self.control.is_set():
            self._say_aborted()
            return False
        go_on, _ = self.control.wait_while_paused()
        if not go_on:
            self._say_aborted()
        return go_on

    def _say_aborted(self):
        # Once, however many nested loops notice it on the way out.
        if not self._aborted_said:
            self._aborted_said = True
            self.log("aborted")

    def _dump(self, img, tag):
        if self._dumps >= 5:
            return
        try:
            os.makedirs(self.debugdir, exist_ok=True)
            path = os.path.join(self.debugdir, "%s_%02d.png" % (tag, self._dumps))
            cv2.imwrite(path, img)
            self._dumps += 1
            self.log("    kept what it saw in %s" % path)
        except Exception as err:
            self.log("    could not keep the frame: %s" % err)

    # -- getting in -----------------------------------------------------
    def open_summons(self):
        """Icon -> Special Summon -> General. False if it cannot be reached."""
        img = self.grab()
        if D.stage_failed(img):
            self.log("the Stage Failed banner is up, tapping it away first")
            self.tap(0.5, NEUTRAL_TAP_FY, was="dismiss Stage Failed")
            time.sleep(self.bot.pause_long)
            img = self.grab()
        if D.auto_button(img) is None:
            self.log("not the plain main screen, cannot open Special Summon")
            self._dump(img, "not_main_screen")
            return False
        self.tap(SUMMON_ICON_FX, SUMMON_ICON_FY, was="Summon icon")
        time.sleep(self.bot.pause_long)
        img = self._wait_for(general_tab, timeout=8.0)
        if img is None:
            if self.control.is_set():
                return False
            self.log("Special Summon did not open, giving up")
            # Kept because this branch has two very different causes -- the
            # tap missed the icon, or the screen is up and General was not
            # recognised on it -- and the log alone cannot tell them apart.
            # The first live failure cost a round of screenshots to answer
            # exactly that question.
            self._dump(self.grab(), "no_general_tab")
            return False
        general = general_tab(img)
        self.tap(general["fx"], general["fy"], was="General")
        time.sleep(self.bot.pause_long)
        img = self._wait_for(mode_dots, timeout=8.0)
        if img is None:
            if self.control.is_set():
                return False
            self.log("no mode banners found after General, giving up")
            return False
        return True

    def _wait_for(self, recognizer, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._pause_gate():
                return None
            img = self.grab()
            if recognizer(img) is not None:
                return img
            time.sleep(0.5 * self.patience)
        return None

    # -- switching mode ---------------------------------------------------
    def goto_mode(self, target):
        img = self.grab()
        current = mode_dots(img)
        if current is None:
            self.log("  mode banners not found, cannot navigate")
            return False
        while current != target:
            if not self._pause_gate():
                return False
            fx = NEIGHBOUR_FX_RIGHT if target > current else NEIGHBOUR_FX_LEFT
            moved = False
            for attempt in range(3):
                self.tap(fx, BANNER_FY, was="neighbour banner")
                time.sleep(self.bot.pause_long)
                new = mode_dots(self.grab())
                if new is not None and new != current:
                    current = new
                    moved = True
                    break
                self.log("  tap had no effect, trying again")
            if not moved:
                self.log("  the banner would not switch after 3 tries, "
                         "skipping this mode")
                return False
        return True

    # -- getting back to the mode's own main screen ----------------------
    def back_to_main(self, img=None):
        img = img if img is not None else self.grab()
        button = summon_button(img)
        if button is None:
            return False
        fx, fy = x_beside_button(button)
        self.tap(fx, fy, was="X back to the mode screen")
        for _ in range(6):
            time.sleep(0.4 * self.patience)
            if mode_dots(self.grab()) is not None:
                return True
        self.log("  tapping the X did not bring the mode screen back")
        return False

    # -- getting back out -------------------------------------------------
    def leave_summons(self):
        """Tap the X until the plain main screen is back. True if it is.

        Deliberately not gated on _pause_gate. By the time this runs the
        stop flag is often already set -- that is one of the ways a run
        ends -- and a gate that returns False on a stop would skip the
        one step whose whole point is to leave the game somewhere the
        next run can start from. It is bounded instead, so Stop still
        ends the session promptly.

        The X pops one screen, not all of them: from a result screen it
        goes back to the mode screen, and only from there to the game.
        So this taps, looks, and taps again, and what it looks for is
        dungeon.auto_button -- independent evidence that the main screen
        is in front with nothing over it, never "the X is gone now".
        """
        taps = 0
        for _ in range(EXIT_ROUNDS):
            img = self.grab()
            if D.auto_button(img) is not None:
                if taps:
                    self.log("back on the main screen")
                return True
            x = exit_button(img)
            if x is None:
                # Mid-animation, or a screen this bot did not open. Either
                # way there is nothing here worth tapping blindly at.
                time.sleep(EXIT_ROUND * self.patience)
                continue
            if taps >= EXIT_TAPS_MAX:
                break
            if not taps:
                self.log("\nleaving Special Summon")
            self.tap(x["fx"], x["fy"], was="X to close Special Summon")
            taps += 1
            if self.dry_run:
                # Nothing was clicked, so nothing will change; sitting out
                # the remaining rounds would only report a failure that
                # never happened.
                return False
            time.sleep(EXIT_ROUND * self.patience)
        self.log("could not get back to the main screen -- the game is left "
                 "where it stands")
        self._dump(self.grab(), "no_way_back")
        return False

    # -- waiting for the button to come back -----------------------------
    def _wait_button_back(self, timeout, hurry=True):
        """Wait until summon_button is found again, at a settled position.

        With `hurry`, every frame without a button is tapped in the upper
        area -- never the lower, where the button row sits. That both ends
        the draw animation early, which is most of the run's speed, and
        clears a knopflose Einzelenthuellung (a rare single-card reveal).
        See REVEAL_TAP_EVERY for why tapping here is safe and tapping
        straight after the summon was not.

        The ad phase passes hurry=False, and that is not caution for its
        own sake: what is on screen during an ad is somebody else's
        creative, and a tap into it can follow a link to a store page
        rather than skip anything. Only the game's own animation is ours
        to hurry along.
        """
        deadline = time.time() + timeout
        last, same, taps, last_tap, missing = None, 0, 0, 0.0, 0
        while time.time() < deadline:
            if not self._pause_gate():
                return None
            img = self.grab()
            button = summon_button(img)
            if button is not None:
                fp = (round(button["fx"], 3), round(button["fy"], 3))
                missing = 0
                if fp == last:
                    same += 1
                    if same >= 1:
                        return img
                else:
                    last, same = fp, 0
            else:
                last, same = None, 0
                missing += 1
                now = time.time()
                # Never on the first frame without a button. A screen in
                # the middle of changing has no button on it either, and a
                # tap sent into that gap lands on whatever arrives next.
                if (hurry and missing >= HURRY_AFTER_MISSING
                        and now - last_tap >= REVEAL_TAP_EVERY):
                    if not taps:
                        self._quiet("  no button on screen, tapping the "
                                    "animation along")
                    self.tap(0.5, NEUTRAL_TAP_FY, was="hurry the animation")
                    taps += 1
                    last_tap = now
            time.sleep(0.5 * self.patience)
        self.log("  the summon button did not come back within %.0f s" % timeout)
        self._dump(self.grab(), "button_timeout")
        return None

    # -- watching the free ads -------------------------------------------
    def watch_ads(self, mode):
        if not self.watch_ads_first or not MODE_HAS_ADS[mode]:
            return
        img = self.grab()
        remaining = ads_left(img)
        if not remaining:
            self.log("  no free ads to watch (or the counter could not be "
                     "read)")
            return
        self.log("  %d free ad%s to watch first"
                 % (remaining, "" if remaining == 1 else "s"))
        while remaining > 0:
            if not self._pause_gate():
                return
            img = self.grab()
            button = view_ads_button(img)
            if button is None:
                self.log("  the View Ads button is gone, stopping the ad "
                         "phase")
                return
            self.tap(button["fx"], button["fy"], was="View Ads")
            img = self._wait_button_back(timeout=AD_TIMEOUT, hurry=False)
            if img is None:
                self.log("  stopping the ad phase, the screen did not "
                         "settle")
                return
            # Never the yellow button here -- it is a live 35x Summon on the
            # result screen the ad just opened, and pressing it would spend
            # 30 real tickets on top of a free round.
            self.back_to_main(img)
            now = ads_left(self.grab())
            if now is None or now >= remaining:
                self.log("  the ad counter did not fall, stopping the ad "
                         "phase")
                return
            self.stats["ads"] += 1
            remaining = now
        self.log("  ads done")

    # -- spending the tickets ---------------------------------------------
    def spam(self, mode):
        price = MODE_PRICE[mode]
        limit = self.max_per_mode
        stalls, blind, done = 0, 0, 0
        # The last count actually read, carried across rounds rather than
        # re-read as "before" each time. The Crest confirmation dialog dims
        # the badge behind it out of the white mask, so the frame in the
        # middle of a Crest draw genuinely has no count on it -- measured
        # on debug_summon/Screenshot 2026-08-25 213248.png and 213301.png,
        # both of which read None and should. Comparing each round against
        # its own "before" made that step look like a stall, and three of
        # them in a row ended the mode while it was drawing perfectly well.
        last_seen = None
        while True:
            if not self._pause_gate():
                return done
            img = self.grab()
            button = summon_button(img)
            if button is None:
                time.sleep(0.5 * self.patience)
                continue
            before = ticket_counter(img)
            if before is not None:
                last_seen = before
            red = price_is_red(img, button)
            underfunded = before is not None and before < price
            if before is not None and red != underfunded:
                self.log("  price colour and ticket count disagree (red=%s, "
                         "%s tickets against a price of %d) -- reading "
                         "error, trusting the ticket count"
                         % (red, _num(before), price))
            if red or underfunded:
                self.log("  %s done, %d summon%s"
                         % (MODE_NAMES[mode], done, "" if done == 1 else "s"))
                return done
            if limit and done >= limit:
                self.log("  limit of %d reached" % limit)
                return done
            self.tap(button["fx"], button["fy"], was="summon")
            img = self._wait_button_back(
                timeout=SPAM_TIMEOUT,
                hurry=not MODE_HAS_CONFIRM[mode])
            if img is None:
                self.log("  stopping, the screen did not settle after the "
                         "tap")
                return done
            after = ticket_counter(img)
            if after is None:
                # Not a stall. This is what the Crest confirmation dialog
                # looks like from here: it dims the badge behind it, so
                # there is nothing to read, and the next round's tap on the
                # dialog's own yellow button is what spends the crests. The
                # count is picked up again on the result screen and
                # compared against last_seen, so the draw is still counted
                # and still checked -- just one round later.
                blind += 1
                self.log("  no count on this screen (%d/%d), most likely a "
                         "step in between" % (blind, self.blind_limit))
                if blind >= self.blind_limit:
                    self.log("  stopping, no count has been readable %d "
                             "times running" % blind)
                    self._dump(img, "no_counter")
                    return done
                continue
            blind = 0
            if last_seen is None:
                # Nothing to compare with yet, so nothing can be concluded.
                last_seen = after
                continue
            if after > last_seen:
                self.log("  tickets went up (%s -> %s), stopping: wrong "
                         "screen or a misread"
                         % (_num(last_seen), _num(after)))
                self._dump(img, "tickets_rose")
                return done
            if after < last_seen:
                if last_seen - after != price:
                    self.log("  tickets %s -> %s, a fall of %d against the "
                             "expected %d -- counted anyway"
                             % (_num(last_seen), _num(after),
                                last_seen - after, price))
                else:
                    self.log("  tickets %s -> %s"
                             % (_num(last_seen), _num(after)))
                done += 1
                self.stats["summons"] += 1
                stalls = 0
            else:
                stalls += 1
                self.log("  tickets unchanged (%d/%d)"
                         % (stalls, self.stall_limit))
            last_seen = after
            if stalls >= self.stall_limit:
                self.log("  stopping, the ticket count has not moved %d "
                         "times running" % stalls)
                self._dump(img, "stalled")
                return done

    # -- the whole run ------------------------------------------------------
    def run(self):
        """Spend every enabled mode, then leave the game on the main screen.

        The walk back out is in a finally because it has to happen on every
        way out of here, not only the good one. A run that never found
        General, one stopped halfway through a draw, one that threw --
        each of those used to leave Special Summon standing open over the
        game, and the next thing to be started then met a screen it did
        not recognise. That is what open_summons refusing on
        "not the plain main screen" looks like from the other end, and
        debug_summon/not_main_screen_00.png is a picture of it: the Buddy
        tab, left behind by the run before.
        """
        try:
            self._spend()
        finally:
            self.leave_summons()
        return self.stats

    def _spend(self):
        if not self.open_summons():
            return
        for mode in MODE_ORDER:
            if not self._pause_gate():
                return
            if not self.enabled.get(mode, True):
                self.log("\n%s: switched off, skipping" % MODE_NAMES[mode])
                continue
            self.log("\n%s" % MODE_NAMES[mode])
            if not self.goto_mode(mode):
                self.stats["modes_skipped"] += 1
                continue
            self.watch_ads(mode)
            self.spam(mode)
            # A mode cut short by the Stop button is not a mode done. Nor is
            # there any point stepping back to the mode screen for a run
            # that is over -- leave_summons walks out from wherever this
            # leaves off, result screen included.
            if self.control.is_set():
                return
            self.stats["modes_done"] += 1
            self.back_to_main()

    def status(self):
        return ("%d summons, %d ads, %d mode(s) done, %d skipped"
                % (self.stats["summons"], self.stats["ads"],
                   self.stats["modes_done"], self.stats["modes_skipped"]))


def format_summary(stats):
    return ("Summary\n  Summons      %d\n  Ads watched  %d\n  Modes done   %d\n"
            "  Modes skipped %d"
            % (stats.get("summons", 0), stats.get("ads", 0),
               stats.get("modes_done", 0), stats.get("modes_skipped", 0)))


# ----------------------------------------------------------------------------
def _short(button):
    if not button:
        return "not found"
    return "fx %.3f fy %.3f fw %.3f" % (button["fx"], button["fy"], button["fw"])


def probe(cap, log=print):
    """Shows what is recognised on the current screen. Clicks nothing."""
    img = cap.grab()
    x0, y0, gw, gh = D.game_rect(img)
    log("window %d x %d, game area %d x %d, top-left offset %d,%d"
        % (img.shape[1], img.shape[0], gw, gh, x0, y0))
    button = summon_button(img)
    log("summon button   %s" % _short(button))
    dots = mode_dots(img)
    log("mode            %s" % (MODE_NAMES.get(dots) if dots
                                else "not on a mode screen"))
    tickets = ticket_counter(img)
    log("tickets/crests  %s" % (_num(tickets) if tickets is not None
                                else "not read"))
    general = general_tab(img)
    log("General tab     %s" % _short(general))
    x = exit_button(img)
    log("exit X          %s" % ("fx %.3f fy %.3f, plate %.3f mark %.3f"
                                % (x["fx"], x["fy"], x["plate"], x["mark"])
                                if x else "not on this screen"))
    if button:
        log("price is red    %s" % price_is_red(img, button))
        ads_button = view_ads_button(img, button)
        log("View Ads button %s" % _short(ads_button))
        if ads_button:
            n = ads_left(img, button)
            log("ads left        %s" % (n if n is not None else "not read"))
    return {"button": button, "mode": dots, "tickets": tickets, "exit": x}


def _keys(bot):
    """Space pauses, q aborts, console focus only. See dungeon.py's _keys."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="only show what is recognised")
    ap.add_argument("--go", action="store_true", help="actually click")
    ap.add_argument("--no-skill", action="store_true")
    ap.add_argument("--no-support", action="store_true")
    ap.add_argument("--no-crest", action="store_true")
    ap.add_argument("--no-ads", action="store_true",
                    help="skip the free ads, go straight to spending")
    ap.add_argument("--max", type=int, default=0,
                    help="at most this many summons per mode, 0 for "
                         "unbounded -- try 2 for a first real run")
    ap.add_argument("--patience", type=float, default=1.5,
                    help="factor on all wait times, higher is more patient")
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames and clicks via adb or via the window and "
                         "mouse. Default: the stored switch (Helpermon's "
                         "window, or DGUP_ADB_MODE)")
    ap.add_argument("--no-hotkeys", "--no-mouse-guard",
                    action="store_true", dest="no_hotkeys",
                    help="disable the global F7/F8 pause and abort keys "
                         "(--no-mouse-guard is the old name for this)")
    args = ap.parse_args()

    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)
    if args.probe:
        probe(cap)
        return

    print("Mode: %s" % ("REAL, it will click" if args.go
                        else "dry run, no clicks"))
    enabled = {SKILL: not args.no_skill, SUPPORT: not args.no_support,
               CREST: not args.no_crest}
    bot = SummonBot(cap, dry_run=not args.go, enabled=enabled,
                    watch_ads_first=not args.no_ads, max_per_mode=args.max,
                    patience=args.patience)
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


if __name__ == "__main__":
    main()
