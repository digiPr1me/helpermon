"""
The quest loop: working through the game's own row of repeating quests.

The game offers a fixed routine of 15 quests, one at a time, on a card at the
right edge of the battle screen. It repeats after the last one. This module
reads that card, decides what the current quest needs, and either claims it
or plays it -- using the existing dungeon and summon bots, never a new one.

The routine itself cannot be told apart by its numbers alone: the target
count on the card (37/50) repeats six times over the 15 steps, so the
routine below is a script of what usually comes next, not a menu to search.
The card's own counter is the independent check CLAUDE.md asks for --
"never click blindly" -- and where the script and the card disagree, the
loop resyncs forward through the script rather than trusting either one
blindly. See _handle_mismatch.

The counter alone is not that check, and a run proved it: started while
the game was showing "Clear Fight! Bakemon 0/2", the loop read a target of
2, found a target of 2 in the step it happened to remember, and played
DemiDevimon. **The routine does not start where the bot was left; it
starts wherever the game is.** So the word in front of the number is read
too -- counted, not read as text, because 7 characters and 11 are all it
takes to keep those two apart and counting needs no stored letters. See
NAME_H_MIN, and ROUTINE's "chars", which is filled in only for the cards
somebody has actually counted.

Everything visual is borrowed from dungeon.py, the same way passive.py and
summon.py already borrow it: game_rect for the coordinate vocabulary,
auto_button as the proof that the main screen is clear, stage_failed so the
red banner is never tapped through, and the digit reader, which carries no
stored pictures and so needs no setup step.

The quest card itself is translucent (measured: S 6-25 inside it against
68-113 on the game art beside it) and so is never searched for as a coloured
block. What is searched for is its counter -- a slash between two numbers,
exactly the shape dungeon.py and passive.py already read counters by -- and
the card is found *around* the counter, not the other way round. A longer
quest name centres differently and pushes the counter's own x sideways by as
much as 0.026 of the game's width; the card's own position barely moves at
all (three thousandths across a window frame and an ADB frame of the same
screen). So the counter's position is read fresh every time, and the card's
tap target is a near-constant offset from wherever the counter turned out to
be, never a stored x.

A finished card is a different picture, and that had to be measured
rather than assumed: the ist digit is redrawn **green** the moment the
count reaches the target, and the card grows an animated green border.
Read in white and red alone it had nothing left of its slash at all, so
the counter went unreadable at exactly the moment it was worth tapping
and no finished quest was ever claimed. See QUEST_GREEN.

debug_quest/quest-loop-finished-quest.png, the ADB frame this module was
checked against, is the reward window itself: everything behind it,
including the next quest's own card, is dimmed dark enough that no reader
in this file can read it -- measured, the grayscale crop tops out at 125
against the 200 this file's white threshold asks for. That is not a gap:
auto_button finds nothing on that frame either, and tick()'s own gate on
auto_button is what keeps every reader in this file from ever being asked
to read a dimmed screen at all. What that frame proves is the gate, not
the counter -- see quest_claimable's caller in tick().
"""

import time

import cv2
import numpy as np

import dungeon as D
import passive as P


# ----------------------------------------------------------------------------
# The quest counter, and the card around it
# ----------------------------------------------------------------------------
# Where to look. Wide enough to hold the counter wherever a longer or shorter
# quest name has pushed it, narrow enough to leave out the two other slashes
# on the same screen: the XP bar's counter near the top of the window and the
# hologram counter near the bottom, both well outside this band, and the
# Summon icon's own badge, which sits inside the band but carries no slash at
# all and so never survives the row search below.
QUEST_BAND = (0.55, 0.95, 0.45, 0.75)
QUEST_SCALE = 4
QUEST_WHITE = (200, 255)
# The ist side of the counter is red, not white (PLAN_QUEST_LOOP.md 3.3) --
# a grayscale threshold alone loses it entirely, since red converts to a
# fairly dark grey. Measured on the real card: H median 173, S median 244,
# V median 232. Kept apart from the game's pink "!" report badges, which
# measure H median 163 -- ten hue units away, the same gap CLAUDE.md already
# warns is too close for colour alone to decide anything. It does not have
# to decide anything here: what makes a glyph the ist digit is never its own
# colour, only that it sits directly left of the slash on the row (see
# _quest_row) -- this range only has to be wide enough to bring the glyph
# into the mask at all, with margin on both sides of the ten-unit gap.
#
# Two ranges, not one: OpenCV's hue wraps at 179/0, and the reddest pixels
# at the centre of the stroke measured H 0-1 -- inside a single range ending
# at 179 that core was cut out of every stroke, and a solid "0" came back as
# a hollow ring with a second ring of background running right through the
# middle of it, which read_digit saw as an extra hole and called an "8".
QUEST_RED_LOW = ((0, 120, 120), (8, 255, 255))
QUEST_RED_HIGH = ((158, 120, 120), (179, 255, 255))
# And **green once the quest is finished**. Red is "not there yet"; the
# moment the count reaches the target the same digit is redrawn in green,
# and the card grows an animated green border that runs around it like a
# snake. Missing this cost the whole feature its point: the card went
# unreadable at exactly the moment it was worth tapping, because nothing
# stood left of the slash in either of the two masks above -- so a
# finished quest was never claimed, and the failure came back as "could
# not read the quest card after the action", about a card that was
# plainly on the screen.
#
# Measured on debug_quest/loop-finished-quest-green-border.png, at
# QUEST_SCALE, all four off the same frame:
#
#                              size      fill    H      S     V
#   the green "2"              31x45     0.64    66    250   207
#   the animated border       334x348    0.08    57    151   255
#   the emerald reward chip   102x107    0.46    59    144   245
#   the card's own panel         -         -    99-108
#
# So the range only has to be a green, twenty hue units clear of the
# panel behind it. What keeps the border and the chip out of the counter
# is not their colour and was never going to be: the border is a thin
# outline and dies on QUEST_FILL_MIN, 0.08 against 0.15; the chip sits a
# whole text row lower and dies on the row test; and both are far outside
# the digit height band around the slash. Three separate reasons, none of
# them a hue.
QUEST_GREEN = ((40, 120, 120), (85, 255, 255))

# The glyph filter. Measured on the counter's own characters -- see the
# module docstring's table in PLAN_QUEST_LOOP.md 3.3: the slash is the
# tallest character at 14 px, the digits either side measure 11 to 12,
# 0.79 to 0.86 of the slash. Kept relative to the slash, never to the crop:
# CLAUDE.md already carries two counters that went unreadable the other way.
QUEST_MIN_H = 0.02          # crop-relative, a noise floor only
QUEST_ASPECT = (0.15, 1.20)
QUEST_FILL_MIN = 0.15
QUEST_SLASH_WH = 0.55        # width over height, ceiling for a slash candidate
QUEST_DIGIT_H_MIN = 0.65     # of the slash's own height
QUEST_DIGIT_H_MAX = 0.95
QUEST_ROW_TOL = 0.25
# How far a character may sit from its neighbour and still belong to the
# same number, as a share of the slash's height.
#
# This was 1.0 and it was far too generous -- measured against 28 real
# cards from one full turn of the routine, 19 of them were read wrong,
# and every one of them the same way: the word next to the number was
# swallowed into it. "Defeat 12/50" came back as 522/50, the "t" of
# "Defeat" read as a digit; "Draw 0/30 Skill Card Summons" came back as
# 0/305122, the letters of "Skill" strung onto the target; "0/50 times"
# as 0/505. Nothing but the two dungeon quests survived, and only because
# "Bakemon" and "DemiDevimon" happen to end in a short letter.
#
# Measured on those cards, in slash heights:
#
#   between two characters of the same number   0.13 to 0.27
#   between a number and the word beside it     0.55 to 0.95
#
# 0.40 sits between them, 1.5 times above the widest gap inside a number
# and 1.4 times below the narrowest space beside one. A letter is never
# told from a digit by its height here -- an ascender ("t", "k", "l", a
# capital) measures 0.75 to 0.85 of the slash and so does every digit.
# It is the space that separates them, and on the ist side the colour
# does it as well (see below).
QUEST_GAP_MAX = 0.40
# An absolute floor under QUEST_MIN_H, in the frame's own real pixels before
# scaling. QUEST_MIN_H alone would never trigger it: it is a share of this
# band's own crop height, and the digits stay roughly that same share of the
# crop whatever the window size, because the crop is itself a fraction of
# the game (PLAN_QUEST_LOOP.md 4.2's table). What actually shrinks with a
# smaller window is the absolute pixel count digit_bitmap has to work with
# -- 12.2 px at the reference window, 7.2 px at 440x806 -- and every digit
# reader in this program resizes onto a fixed grid that stops meaning
# anything once the source is only a handful of pixels tall. Six is below
# every window size this program's other readers were ever measured at
# and above what a handful of pixels of anti-aliasing noise could produce.
QUEST_MIN_PX = 6

# The card is translucent, and over a bright background its own panel
# comes through coloured. Measured on the "Draw 0/30 Skill Card Summons"
# card over an orange scene: the pink wash in the gap between the "w" of
# "Draw" and the red 0 measured H 160, S 140 -- inside QUEST_RED_HIGH by
# two hue units -- and formed a blob 70x88 at fill 0.38, the size and
# shape of a digit, right beside the real one. It was read as a 3, and
# "Draw 0/30" came back as 30/30: a finished quest, on a card that had
# not started.
#
# Colour cannot throw it out (it is inside the range), position cannot
# (0.23 of a slash off the row against 0.17 for real characters, too
# close), and neither can fill (0.38 against a real minimum of 0.41).
# Brightness can, and by a factor of two: text on this card is drawn
# bright whatever its colour, and the panel behind it is dim -- the plan
# measured the panel itself at V 114 to 121 (PLAN_QUEST_LOOP.md 3.2).
#
#   the upper quartile of V inside the box
#     the 72 counter characters read off 25 real cards   239 to 255
#     the pink wash that was read as a 3                 126
#
# 180 sits a third of the way from either, and well above the panel.
QUEST_BRIGHT_PCT = 75
QUEST_BRIGHT_MIN = 180

# -- the quest's own name, and why it is counted rather than read -----------
# The target number does not say which quest is on the card: 2 stands for
# both dungeon steps, 30 for both summon steps, 50 for six steps between
# them. The script says what usually comes next, and a remembered position
# is not evidence of anything -- a loop started on a day that opened at
# "Clear Fight! Bakemon" played DemiDevimon instead, because the target
# matched and nobody looked at the word beside it.
#
# What is on the card is a word, and this program has no letter shapes
# stored anywhere and is not getting any: they would be images out of the
# game, and the quest loop would inherit a setup step. What it can do
# without them is *count* the letters, which is enough for the only
# question being asked -- "Bakemon" is 7 characters and "DemiDevimon" is
# 11, and no reading of either can be mistaken for the other.
#
# Measured on debug_quest/dailies-battle-stages.png, the counter row of
# the real Bakemon card, at QUEST_SCALE:
#
#   the seven letters of "Bakemon"    h 32 to 45   (0.59 to 0.83 of the slash)
#   the slash                         h 54
#   the dot over an "i" (same card,
#   the line above, "Fight!")         h 6          (0.11 of the slash)
#
# So a floor at 0.35 of the slash keeps every letter body and drops every
# dot and every speck -- a factor of three either way, which is what
# CLAUDE.md asks for and what a threshold at 0.5 would not have given.
NAME_H_MIN = 0.35
# How much of its own height a letter must share with the slash's rows to
# count as standing on the counter's line. Half, which a descender ("g",
# "p") still clears and a line above or below cannot.
NAME_OVERLAP = 0.5
# The card's own width, in game fractions (PLAN_QUEST_LOOP.md 3.1). Only
# ever used to bound the name: the crop reaches further left than the card
# does, and the game art out there draws bright shapes of its own.
CARD_W = 0.264
# The card's height, same table. Only the dump uses it, and it takes this
# much above *and* below the card's middle -- twice the card, so a crop
# taken to be looked at by hand shows its edges and the reward chip under
# it rather than cutting the thing it is meant to explain.
CARD_H = 0.068
DUMP_DIR = "debug_quest"
# How far a counted name may sit from the length written into the routine
# and still be that quest. Two: a pair of letters merging costs one, a
# speck of card edge surviving the floor costs one the other way.
#
# The two lengths that have to stay apart are 7 and 11, and at a tolerance
# of two their bands meet at exactly 9 -- a reading of 9 would fit both
# and identify neither. That is not the failure it looks like: a card that
# fits two steps is a card that has said nothing, and _matches then leaves
# the script where it is, which is what the whole loop did before any word
# was counted. What must never happen is the other way round -- a clean 7
# fitting the eleven-letter step -- and four apart with a tolerance of two
# it cannot.
NAME_TOL = 2


def _run_touching(glyphs, edge, unit, grow_left):
    """Glyphs that reach `edge` in a contiguous chain, within QUEST_GAP_MAX
    * unit of each other. Everything past the first wide gap is a quest
    name or other artwork, not the counter."""
    glyphs = sorted(glyphs, key=lambda s: s[0])
    if grow_left:
        glyphs = list(reversed(glyphs))
    run = []
    for g in glyphs:
        gap = (edge - (g[0] + g[2])) if grow_left else (g[0] - edge)
        if gap > QUEST_GAP_MAX * unit:
            break
        run.append(g)
        edge = g[0] if grow_left else g[0] + g[2]
    run.sort(key=lambda s: s[0])
    return run


def _bright_enough(value, stat):
    """Is this shape drawn text, or the card's own panel showing through?

    See QUEST_BRIGHT_MIN. The one question a hue cannot answer here.
    """
    x, y, w, h = stat[0], stat[1], stat[2], stat[3]
    box = value[y:y + h, x:x + w]
    if box.size == 0:
        return False
    return np.percentile(box, QUEST_BRIGHT_PCT) >= QUEST_BRIGHT_MIN


def _name_run(stats, slash, x_to, x_from, value=None):
    """The quest's own letters on the counter's row, between two edges.

    Counted, never read -- see NAME_H_MIN. Called twice: once for what
    stands in front of the number, bounded by the card's left edge and the
    number's own, and once for what stands behind it, bounded by the
    number's right edge and the card's. Both bounds matter: the crop
    reaches past the card into the game art on one side, and the number
    itself must never be counted as part of a word on the other.
    """
    out = []
    for s in stats:
        x, y, w, h = s[0], s[1], s[2], s[3]
        if not h or h < NAME_H_MIN * slash[3]:
            continue
        # A letter is never a hairline. The card's own bright edge runs
        # down the right side of the row as a component 1 px wide and 138
        # tall, and it was counted as a word behind the number on the
        # Bakemon card -- 7/1 instead of 7/0. The same aspect floor the
        # counter's own characters go through, twenty times under it.
        if w < QUEST_ASPECT[0] * h:
            continue
        if x < x_from or x + w > x_to:
            continue
        shared = min(y + h, slash[1] + slash[3]) - max(y, slash[1])
        if shared < NAME_OVERLAP * h:
            continue
        if value is not None and not _bright_enough(value, s):
            continue
        out.append(s)
    out.sort(key=lambda s: s[0])
    return out

# The card's tap target, as an offset from the counter row rather than a
# stored position. Measured on both frame shapes of the same real screen
# (PLAN_QUEST_LOOP.md 3.1, 3.6):
#
#             window 732x1341   ADB 1080x1920
#   card mid       0.7510/0.5987     0.7493/0.6008
#   counter row     0.7838/0.5887     0.8099/0.5889
#
# The card's own x barely moves (three thousandths) while the row's x moves
# by 0.026 between "Bakemon 0/2" and "DemiDevimon 0/2" -- a longer name
# pushes the centred text sideways inside a card that does not move. So the
# card's x is the constant below, never the row's own x; only its y tracks
# the row, by the small, near-identical offset measured both ways (0.0100,
# 0.0121).
CARD_MID_FX = 0.750
CARD_FY_ROW_OFFSET = 0.011

# The dead spot that closes the reward window. Player-checked in the game
# itself: a tap here opens nothing on the plain main screen. Left edge, half
# height -- outside passive.BOND_TAP_LIMITS, so it is provably not a figure,
# and far from the "Tap to close" label itself (0.5, 0.82), which sits over
# the hologram device on the screen behind the window and would open that
# instead if the window had already closed by itself. See
# PLAN_QUEST_LOOP.md 5.1 and debug_quest/quest-loop-dead-tap.png.
DEAD_TAP = (0.04, 0.47)


def _quest_row(img):
    """The counter's digits and where they sit, or None if none is found.

    Every narrow, tall character in the band is tried as the slash; the one
    that turns out to have a valid number on each side wins, the same proof
    passive._counter_row uses. A slash with digits on only one side is
    thrown away rather than guessed at -- the Summon icon's own badge sits
    in this band with no slash at all, and the game's own "!" report badges
    carry no slash either, so nothing here needs to know their colour.
    """
    x0, y0, gw, gh = D.game_rect(img)
    fx0, fx1, fy0, fy1 = QUEST_BAND
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    right = int(x0 + fx1 * gw)
    bottom = int(y0 + fy1 * gh)
    sub = img[top:bottom, left:right]
    if sub.size == 0 or sub.shape[0] < 2 or sub.shape[1] < 2:
        return None
    big = cv2.resize(sub, (sub.shape[1] * QUEST_SCALE, sub.shape[0] * QUEST_SCALE),
                     interpolation=cv2.INTER_CUBIC)
    white = cv2.inRange(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), *QUEST_WHITE)
    hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array(QUEST_RED_LOW[0]), np.array(QUEST_RED_LOW[1])) \
        | cv2.inRange(hsv, np.array(QUEST_RED_HIGH[0]), np.array(QUEST_RED_HIGH[1]))
    green = cv2.inRange(hsv, np.array(QUEST_GREEN[0]), np.array(QUEST_GREEN[1]))
    value = hsv[:, :, 2]
    # Kept as two masks, not merged into one. A red glyph's anti-aliased
    # edge brushes the white threshold too, and OR-ing the two together
    # left a second, thinner ring just outside the real one with a gap of
    # background between them -- which is a second hole to read_digit, and
    # a clean "0" came back as "8". Read alone, the red mask draws the ist
    # digit as cleanly as the white one draws everything else, so each
    # glyph is read from whichever mask it was actually found in. The
    # green mask joins them on the same terms and for the same reason: on
    # a finished card it is the ist digit, and nothing else on that row.
    glyphs, source, coloured = [], {}, set()
    unfiltered = []
    for mask in (white, red, green):
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        unfiltered.extend(stats[1:])
        for i in range(1, n):
            stat = stats[i]
            x, y, w, h, area = stat
            if not h or h < QUEST_MIN_H * mask.shape[0]:
                continue
            if not QUEST_ASPECT[0] <= w / float(h) <= QUEST_ASPECT[1]:
                continue
            if area / float(w * h) < QUEST_FILL_MIN:
                continue
            if not _bright_enough(value, stat):
                continue
            glyphs.append(stat)
            source[id(stat)] = mask
            if mask is not white:
                coloured.add(id(stat))

    def _read(stats_list):
        value = 0
        for s in stats_list:
            d = D.read_digit(source[id(s)], s)
            if d is None:
                return None
            value = value * 10 + d
        return value

    best = None
    for slash in glyphs:
        if slash[3] < QUEST_MIN_PX * QUEST_SCALE:
            continue
        if slash[2] / float(max(slash[3], 1)) > QUEST_SLASH_WH:
            continue
        middle = slash[1] + slash[3] / 2.0
        left_g, right_g = [], []
        for g in glyphs:
            if g is slash:
                continue
            if not (QUEST_DIGIT_H_MIN * slash[3] <= g[3] <= QUEST_DIGIT_H_MAX * slash[3]):
                continue
            if abs((g[1] + g[3] / 2.0) - middle) > QUEST_ROW_TOL * slash[3]:
                continue
            if g[0] + g[2] <= slash[0]:
                # The ist side is never white. It is red while the quest
                # is running and green once it is done, and the quest's
                # own words are white -- so on this side the colour alone
                # keeps "Defeat" out of "Defeat 12/50", with no threshold
                # involved at all. Measured on all 28 cards of one turn
                # of the routine: every ist digit red or green, every
                # letter beside it white.
                if id(g) in coloured:
                    left_g.append(g)
            else:
                right_g.append(g)
        if not left_g or not right_g:
            continue
        # Only the run that actually touches the slash is the counter's own
        # number. A quest name shares the row's height and can still sit
        # well to its left -- "Bakemon" and the digit are both digit-height
        # and both left of the slash, and only the gap between them (five
        # times the digit-to-slash gap, in the frame this was measured on)
        # tells them apart. The same shape of trap as VIOLET against the
        # prompt's pink: a threshold on the row alone was not enough there
        # either, and needed a neighbour to decide.
        left_run = _run_touching(left_g, slash[0], slash[3], grow_left=True)
        right_run = _run_touching(right_g, slash[0] + slash[2], slash[3],
                                  grow_left=False)
        if not left_run or not right_run:
            continue
        ist = _read(left_run)
        ziel = _read(right_run)
        if ist is None or ziel is None:
            continue
        span = right_run[-1][0] + right_run[-1][2] - left_run[0][0]
        if best is None or span > best["span"]:
            all_stats = left_run + right_run + [slash]
            row_top = min(s[1] for s in all_stats)
            row_bottom = max(s[1] + s[3] for s in all_stats)
            row_left = left_run[0][0]
            row_right = right_run[-1][0] + right_run[-1][2]
            row_cx = left + (row_left + row_right) / 2.0 / QUEST_SCALE
            row_cy = top + (row_top + row_bottom) / 2.0 / QUEST_SCALE
            card_left = (x0 + (CARD_MID_FX - CARD_W / 2.0) * gw - left) \
                * QUEST_SCALE
            card_right = (x0 + (CARD_MID_FX + CARD_W / 2.0) * gw - left)                 * QUEST_SCALE
            name = _name_run(unfiltered, slash, row_left, card_left, value)
            after = _name_run(unfiltered, slash, card_right, row_right, value)

            best = {"ist": ist, "ziel": ziel, "span": span,
                    "row_fx": (row_cx - x0) / gw, "row_fy": (row_cy - y0) / gh,
                    # A count, and zero is one of them: the hologram
                    # card carries no word in front of its number at all,
                    # and the stage card none on either side. Both are
                    # measurements, not the absence of one. None is what
                    # a caller hands _matches when nothing was counted,
                    # and no reading here is ever that.
                    "name_len": len(name),
                    # And what stands *behind* the number. The word in
                    # front is not always there: measured across one full
                    # turn of the routine, "0/50 times" has nothing at all
                    # in front of it and "Draw 0/30 Skill" has a word on
                    # each side. The pair is what tells the quests apart
                    # -- see ROUTINE's "chars".
                    "after_len": len(after),
                    # The word's own width, in slash heights, so it means
                    # the same on a window frame and on an ADB one. Nothing
                    # decides anything by it yet -- it is what --probe and
                    # the card dump print, and what a second quest's card
                    # will be measured against.
                    "name_w": ((name[-1][0] + name[-1][2] - name[0][0])
                              / float(slash[3])) if name else 0.0}
    return best


def quest_progress(img):
    """(ist, ziel) on the quest card, or None if no counter is found.

    All or nothing, the same rule as dungeon.read_counter: a made-up number
    is worse than an admitted None, because the loop compares this reading
    against the one before it to decide whether an action worked at all.
    """
    row = _quest_row(img)
    if row is None:
        return None
    return row["ist"], row["ziel"]


def quest_card(img, row=None):
    """The quest card's tap target, plus what its counter says, or None.

    Found over the counter, not the card: see the module docstring. The
    card itself is never searched for as a coloured shape, because it is
    translucent and what it measures depends on whatever background sits
    behind it (PLAN_QUEST_LOOP.md 3.2).

    `row` is a reading of the same frame that has already been done -- the
    loop reads the row once per tick and hands it on, rather than putting
    the same picture through the same reader twice.
    """
    row = _quest_row(img) if row is None else row
    if row is None:
        return None
    return {"fx": CARD_MID_FX, "fy": row["row_fy"] + CARD_FY_ROW_OFFSET,
            "ist": row["ist"], "ziel": row["ziel"],
            "row_fx": row["row_fx"], "row_fy": row["row_fy"],
            "name_len": row["name_len"], "name_w": row["name_w"],
            "after_len": row["after_len"]}


def quest_claimable(img):
    """Is the current quest done? ist >= ziel, and nothing else.

    No colour, no glow, no third reader. PLAN_QUEST_LOOP.md 4.3: the game
    writes the number itself, and a finished quest sits and waits for the
    tap rather than resolving on its own, so this is both cheaper and safer
    than any feature that would first need calibrating against an unfinished
    card of the same scene.

    A finished card does say so in colour as well -- the ist digit turns
    green and a green border runs around the card -- and that is still not
    what is asked here. The border is animated, so which part of it is
    green depends on the moment the frame was taken, and the digit's own
    colour is already doing a job one step earlier: it is what puts the
    digit in the mask at all (QUEST_GREEN), which is what makes the number
    readable, which is what this answers with. Reading the same evidence
    twice is not a second opinion.
    """
    progress = quest_progress(img)
    if progress is None:
        return False
    ist, ziel = progress
    return ist >= ziel


# ----------------------------------------------------------------------------
# The stage number
# ----------------------------------------------------------------------------
# "Stage: 7,308", centred under the location banner. Measured on
# debug_quest/dailies-battle-stages.png: the word "Stage:" and the number
# sit on one centred line, so a longer number pushes the whole line, "Stage:"
# included, sideways -- there is no fixed x for either part. What is fixed
# enough to anchor on is the gap: the space after the colon measured about
# 2.3 times the widest digit-to-digit gap within the number itself, on that
# one frame. So the number is found as the right-most run of evenly spaced,
# digit-sized characters in a band wide enough to hold "Stage: NNNN" at any
# length, cut off wherever a gap that wide turns up.
STAGE_BAND = (0.30, 0.70, 0.168, 0.196)
STAGE_SCALE = 4
STAGE_WHITE = (190, 255)
STAGE_MIN_H = 0.06
STAGE_ASPECT = (0.15, 1.20)
STAGE_FILL_MIN = 0.15
# Gap over the row's own median glyph width. The comma itself is too short
# to pass STAGE_MIN_H and never joins the glyph list, so the gap either side
# of it merges into one -- measured 1.48 of a digit's width on the real
# frame, against 2.39 for the space after the colon. The split sits at
# their geometric mean, two full digit widths, a margin of about 1.2 either
# way.
STAGE_GAP_SPLIT = 2.0
# A comma is short beside a digit. Measured 0.36 of a digit's height on the
# one frame this was checked against; digits themselves are even, so
# anything under half a digit's height is the comma, never a digit.
STAGE_COMMA_MAX = 0.6


def stage_number(img):
    """The stage number under the location banner, or None.

    Nothing taps because of this. It exists only to say why a "clear this
    stage" step is still waiting -- PLAN_QUEST_LOOP.md 4.4 -- so if this
    reader is ever wrong, the cost is a worse log line and nothing else: the
    quest card's own ist/ziel counter is what actually decides the claim,
    the same as every other step.
    """
    x0, y0, gw, gh = D.game_rect(img)
    fx0, fx1, fy0, fy1 = STAGE_BAND
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0 or sub.shape[0] < 2 or sub.shape[1] < 2:
        return None
    big = cv2.resize(sub, (sub.shape[1] * STAGE_SCALE, sub.shape[0] * STAGE_SCALE),
                     interpolation=cv2.INTER_CUBIC)
    mask = cv2.inRange(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY), *STAGE_WHITE)
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    glyphs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not h or h < STAGE_MIN_H * mask.shape[0]:
            continue
        if not STAGE_ASPECT[0] <= w / float(h) <= STAGE_ASPECT[1]:
            continue
        if area / float(w * h) < STAGE_FILL_MIN:
            continue
        glyphs.append(stats[i])
    if not glyphs:
        return None
    glyphs.sort(key=lambda s: s[0])
    widths = sorted(s[2] for s in glyphs)
    median_w = widths[len(widths) // 2] or 1

    # The trailing run: walk backwards from the right-most glyph, stop at
    # the first gap wider than the split. That is the number, whatever
    # "Stage:" happened to be in front of it.
    run = [glyphs[-1]]
    for g in reversed(glyphs[:-1]):
        gap = run[0][0] - (g[0] + g[2])
        if gap > STAGE_GAP_SPLIT * median_w:
            break
        run.insert(0, g)
    if len(run) < 2:
        return None

    tallest = max(s[3] for s in run)
    is_digit = [s[3] >= (1 - STAGE_COMMA_MAX) * tallest for s in run]
    digits = [s for s, keep in zip(run, is_digit) if keep]
    commas = [s for s, keep in zip(run, is_digit) if not keep]
    if not P._commas_hold(digits, commas):
        return None
    return D.read_counter(mask, sorted(digits, key=lambda s: s[0]))


# ----------------------------------------------------------------------------
# The way out of a screen the loop did not open
# ----------------------------------------------------------------------------
# Everything in this file waits for the plain main screen and does nothing
# without it, which is right until the game stops going back there by
# itself. A live run parked step 6 on "tapping the card did not open the
# reward window" and then said "not the plain main screen" for as long as
# anybody watched: the frame the passive helper kept at 09:24:59 was the
# Special Summon reward screen, with the game's own X plainly drawn in the
# corner. Waiting was never going to end that, because nothing was going to
# happen. One tap would have.
#
# Neither X is new. summon.exit_button is the white plate that closes a
# Special Summon screen and explore.close_button the violet one that closes
# the Digital World Search board, both measured where they were built. What
# is new is asking for them here, and what makes that safe was measured
# across all 249 stored frames of nine debug folders, both frame shapes
# from 573 x 1056 to 1080 x 1920:
#
#   the white X fires on 30 of them, the violet on 25, never both on one
#   frame, and -- the number this rests on -- **not one frame in the whole
#   collection carries an X and a crisp auto button at once.**
#
# So an X can only ever be found on a screen that is already not the main
# screen, which is the only place this is asked. The pair is wider than the
# two screens they were built for, too: the same white plate reads 0.760
# plate / 0.226 mark on the summon reward screen and on the PvP screen, to
# the fourth decimal, because it is one piece of artwork the game reuses.
def close_x(img):
    """The X that closes whatever is in front, or None.

    Asked in one place only -- a screen that has already failed the auto
    button -- and answered by the two recognisers that already exist. The
    white one first: it is the commoner of the two by a little and the one
    the summon steps leave behind.

    Imported here rather than at the top of the file, the way the summon
    steps already import summon.py, so that reading a quest card still
    costs nothing but dungeon.py.
    """
    import summon as S
    import explore as X

    found = S.exit_button(img)
    if found is not None:
        return dict(found, which="the white X")
    found = X.close_button(img)
    if found is not None:
        return dict(found, which="the violet X")
    return None


# ----------------------------------------------------------------------------
# The routine, as a script
# ----------------------------------------------------------------------------
# What the game itself hands out, in this order, repeating after the last
# one. See PLAN_QUEST_LOOP.md 2 for how the player read it off the game.
# "target" is the only machine-readable property of a step -- and it is not
# unique: 2 appears twice, 30 four times, 50 six times. Only the order tells
# them apart, which is the whole reason the loop keeps a remembered position
# rather than picking a step by its numbers (PLAN_QUEST_LOOP.md 2.1).
#
# Step 9, "clear stage ####", is assumed to carry the same 0/1-shaped
# counter as every other step -- unmeasured directly, but the only reading
# that keeps quest_progress/quest_claimable uniform across all 15 steps
# rather than needing a special case. stage_number exists to explain the
# wait, not to gate the claim; see its own docstring.
DUNGEON, SUMMON, HOLO, ENEMIES, STAGE = "dungeon", "summon", "holo", "enemies", "stage"

# Positions in dungeon.DUNGEON_KEYS: apocalymon 0, demidevimon 1, bakemon 2.
DEMIDEVIMON, BAKEMON = 1, 2
# summon.SKILL, summon.SUPPORT -- written as their own numbers here so this
# module does not have to import summon.py just for two constants that are
# never anything but 1 and 2.
SKILL, SUPPORT = 1, 2

# "chars" is the pair of word lengths on the counter's own row: how many
# letters stand in front of the number, and how many behind it. It is the
# one thing on the card that says *which* quest this is rather than how
# far along it is, and it needs no stored letter shapes -- see NAME_H_MIN.
#
# Measured across one full turn of the routine, 23 readable cards
# (debug_quest/, DGUP_DUMP_QUEST=1). Every one of them fell on exactly
# these numbers, with no spread at all:
#
#   the card says                 in front   behind   n
#   "DemiDevimon 0/2"                11        -      2
#   "Bakemon 0/2"                     7        -      2
#   "Defeat 12/50", "Defeat 0/100"    6        -      8
#   "Draw 0/30 Skill"                 4        5      3
#   "Draw 0/30"                       4        -      3
#   "0/50 times"                      -        5      4
#   "605/605"                         -        -      1
#
# A dash is "nothing on that side", counted as zero when it is compared.
# The pair is what separates the two quests that share a target: 4/5
# against 4/0 for the two summon steps, where the word in front is "Draw"
# on both and only what follows the number differs. None instead of a
# pair means nobody has counted that card yet, and then the target
# decides alone, the way it did before any word was read.
ROUTINE = [
    {"target": 2, "kind": DUNGEON, "arg": DEMIDEVIMON, "chars": (11, None),
     "name": "Clear Fight! DemiDevimon, 2x"},
    {"target": 2, "kind": DUNGEON, "arg": BAKEMON, "chars": (7, None),
     "name": "Clear Fight! Bakemon, 2x"},
    {"target": 50, "kind": HOLO, "arg": None, "chars": (None, 5),
     "name": "Activate the Hologram Device, 50x"},
    {"target": 50, "kind": ENEMIES, "arg": None, "chars": (6, None),
     "name": "Defeat 50 enemies"},
    {"target": 30, "kind": SUMMON, "arg": SKILL, "chars": (4, 5),
     "name": "Draw 30 Skill Card Summons"},
    {"target": 30, "kind": SUMMON, "arg": SUPPORT, "chars": (4, None),
     "name": "Draw 30 Support Summons"},
    {"target": 50, "kind": HOLO, "arg": None, "chars": (None, 5),
     "name": "Activate the Hologram Device, 50x"},
    {"target": 100, "kind": ENEMIES, "arg": None, "chars": (6, None),
     "name": "Defeat 100 enemies"},
    # The stage step names a stage rather than a count, and the number
    # goes up every time round -- by five or ten, the player says, and it
    # names the stage the game wants reached. It is far behind: 605 on the
    # turn this was watched, against a player standing at stage 8,154. So
    # the card arrives already finished, 605/605, and is there to be
    # claimed rather than played, and will stay that way for a very long
    # time. target None means "whatever number it shows"; a step like that
    # is never matched on its target and always on its word pair, which
    # for this card is the only one in the routine with nothing on either
    # side of the number.
    {"target": None, "kind": STAGE, "arg": None, "chars": (None, None),
     "name": "Clear the stage"},
    {"target": 50, "kind": HOLO, "arg": None, "chars": (None, 5),
     "name": "Activate the Hologram Device, 50x"},
    {"target": 50, "kind": ENEMIES, "arg": None, "chars": (6, None),
     "name": "Defeat 50 enemies"},
    {"target": 30, "kind": SUMMON, "arg": SKILL, "chars": (4, 5),
     "name": "Draw 30 Skill Card Summons"},
    {"target": 30, "kind": SUMMON, "arg": SUPPORT, "chars": (4, None),
     "name": "Draw 30 Support Summons"},
    {"target": 50, "kind": HOLO, "arg": None, "chars": (None, 5),
     "name": "Activate the Hologram Device, 50x"},
    {"target": 100, "kind": ENEMIES, "arg": None, "chars": (6, None),
     "name": "Defeat 100 enemies"},
]


# ----------------------------------------------------------------------------
# The loop
# ----------------------------------------------------------------------------
TICK = 2.0
# How long a park lasts before the same step is tried again. Long enough that
# a switched-off box or an empty ticket stock is not hammered every two
# seconds; short enough that turning the box back on is noticed within a
# couple of minutes rather than needing a restart.
PARK_RETRY = 60.0
# The same, for a step that is out of attempts until the game's daily
# reset. Nothing is going to change about an empty ticket counter within
# the minute, and every retry is a whole trip through the dungeon list --
# opened, scrolled, surveyed, closed -- with the emulator taken off the
# passive helper for the duration. Long enough not to hammer it, short
# enough that tickets bought by hand are noticed within a quarter hour.
PARK_RETRY_EMPTY = 900.0
CLAIM_OPEN_TIMEOUT = 8.0
# Closing the reward window: how many taps at the dead spot, and how long
# each one is given before the next.
#
# It was two taps of eight seconds, and a live run found the shape of that
# wrong rather than the total. Four windows closed on the first tap; the
# fifth, opened 25 seconds after the one before it, swallowed both -- and
# eight seconds of waiting in between bought nothing, because a window
# that is going to close does it within a second. What a swallowed tap
# needs is another tap, not more patience.
#
# The dead spot opens nothing on the plain main screen (PLAN_QUEST_LOOP.md
# 5.1, player-checked), so a tap too many costs nothing at all -- which is
# what makes five of them cheaper than two.
CLAIM_CLOSE_TAPS = 5
CLAIM_CLOSE_STEP = 3.0
BLIND_AFTER = 60.0
# How long the card is given to come back after a bot has played. The
# dungeon bot returns while the game is still closing its result screens,
# and the first frame after a run is regularly a window rather than the
# main screen -- see _row_once_settled. Long enough for that, short enough
# that a game genuinely stuck somewhere else is still parked on within
# half a minute.
SETTLE_TIMEOUT = 30.0

# The hologram device, for the one step that can be played with a single
# tap: "Activate the Hologram Device 0/50 times". With Auto Spend running
# the game does this by itself and the loop touches nothing -- watched over
# a full turn of the routine, the counter went to 50/50 twice without a
# single tap from here. This is the fallback for a run with Auto Spend
# switched off, which is otherwise a step the loop can only park on.
#
# Never a stored position. The device is found from the auto button, which
# every reader here already has to find anyway, and which sits at its
# left. Measured on two window shapes of the same screen:
#
#                        the auto button      the device
#   732 x 1341            0.362 / 0.766      0.477 / 0.816
#   674 x 1238            0.370 / 0.765      0.485 / 0.815
#
# The offset holds to a thousandth across both, and the target it lands on
# is the glass cylinder itself, checked by eye on both frames.
HOLO_TAP_OFF = (0.115, 0.050)
# How long the game is given to count an activation. The device runs an
# animation of a few seconds and the quest counter only moves once it has
# finished, so a tap judged straight away always looks like a failure.
HOLO_COUNT_WAIT = 12.0

# Getting out of a screen that is not the main screen -- see close_x.
#
# How long the screen is given to come back by itself before an X is
# reached for. Longer than SETTLE_TIMEOUT on purpose: the 30 s there is
# what a bot's own result screens take to finish closing, and this must
# not start pressing things while that is still going on. It is also
# longer than any animation the game plays, and it is not a hurry -- a
# screen nobody is going to close is just as stuck in a minute as it is
# now.
STUCK_AFTER = 45.0
# Between taps once it has started, and how many before it gives up. A
# swallowed tap wants another tap rather than more patience
# (CLAIM_CLOSE_TAPS learned that the hard way), and a screen can be two
# deep -- the summon reward over the summon menu -- so six taps is room
# for every layer the game has ever put up plus swallowed ones.
STUCK_TAP_EVERY = 3.0
STUCK_TAPS_MAX = 6


def _words_said(words):
    """The word pair, said in a log line."""
    if not words or not any(words):
        return "no word beside the number"
    before, after = words
    return "%s in front of the number, %s behind it" % (
        ("%d characters" % before) if before else "nothing",
        ("%d" % after) if after else "nothing")


class QuestLoop:
    """One tick reads the card and does at most one thing about it.

    Emulator ownership is asked for through two callbacks rather than
    reached for directly, so this class stays usable offline: a caller like
    the launcher wires reserve_emulator/release_emulator to its own worker
    thread and quest_busy flag (PLAN_QUEST_LOOP.md 6), and the tests wire
    fakes that just say yes.
    """

    def __init__(self, cap, log=print, dry_run=False, now=time.time,
                 do_dungeon=True, do_summon=True, claim_only=False,
                 auto_spend_on=True, step=0,
                 save_step=None, reserve_emulator=None, release_emulator=None,
                 start_guard=None, stop_guard=None):
        self.cap = cap
        self.log = log
        self.dry_run = dry_run
        self.now = now
        self.do_dungeon = do_dungeon
        self.do_summon = do_summon
        self.claim_only = claim_only
        self.auto_spend_on = auto_spend_on
        self.bot = D.DungeonBot(cap, dry_run=dry_run, log=self._quiet)
        self.step = step % len(ROUTINE)
        self.save_step = save_step
        self.reserve_emulator = reserve_emulator or (lambda: True)
        self.release_emulator = release_emulator or (lambda: None)
        self.start_guard = start_guard
        self.stop_guard = stop_guard
        # Set from outside, once per round -- the same convention passive.py
        # uses. False means read and log but touch nothing, for the moments
        # a real (non-ADB) mouse is in somebody's hand.
        self.may_tap = True

        self.last_progress = None
        self.last_words = None
        self.parked_because = None
        self.park_retry_at = 0.0
        self._mismatch = None
        self._retried_step = None
        self.current_control = None
        self.said = None
        self._blind_since = None
        # A claim whose taps all landed but whose counter did not fall gets
        # exactly one more try on the very next tick before it counts as a
        # park -- PLAN_QUEST_LOOP.md 5.1's "faellt nicht -> kein Fortschritt,
        # und beim zweiten Mal wird geparkt". Only that specific failure
        # gets the second try; a reward window that never opened or closed
        # is a structural failure and parks the ordinary way, at once.
        self._claim_stall_step = None
        self._holo_dead = 0
        self._dumped = set()
        # Since when the screen has not been the plain main screen, and
        # what has been done about it -- see _stuck.
        self._stuck_since = None
        self._stuck_taps = 0
        self._stuck_tap_at = 0.0

    # -- logging ---------------------------------------------------------
    def _quiet(self, text):
        pass

    def _once(self, key, text):
        if self.said != key:
            self.said = key
            self.log(text)

    def _say(self, text):
        self.said = None
        self.log(text)

    def _park(self, reason, retry_in=PARK_RETRY):
        self.parked_because = reason
        self.park_retry_at = self.now() + retry_in
        self._once("park:" + reason, "  parked on step %d (%s): %s"
                   % (self.step + 1, ROUTINE[self.step]["name"], reason))

    def _advance(self, new_step):
        self.step = new_step % len(ROUTINE)
        self.parked_because = None
        self._retried_step = None
        self._claim_stall_step = None
        self._holo_dead = 0
        self.said = None
        if self.save_step:
            self.save_step(self.step)

    # -- one round ---------------------------------------------------------
    def tick(self, img=None):
        """One pass. Claims at most one quest or plays at most one action.

        Never both, and never a second tap this round on top of either: the
        second would be aimed with a picture taken before the first landed
        -- the same rule passive.tick follows.
        """
        img = self.bot.grab() if img is None else img
        result = {"claimed": False, "acted": False}

        if D.stage_failed(img):
            self._once("failed", "  the Stage Failed banner is up, not "
                                 "tapping through it")
            return result
        if D.auto_button(img) is None:
            self._stuck(img)
            return result
        self._back_again()

        row = _quest_row(img)
        if row is None:
            self._blind(img)
            return result
        self._blind_since = None
        ist, ziel = row["ist"], row["ziel"]
        self.last_progress = (ist, ziel)
        words = (row["name_len"], row["after_len"])
        self.last_words = words
        self._dump_card(img, row)

        # The card decides which step this is, not the remembered position.
        # The position is only a tie-breaker between steps the card itself
        # cannot tell apart -- see _matches.
        if not self._matches(self.step, ziel, words):
            self._handle_mismatch(ist, ziel, words)
            return result

        self._mismatch = None
        if self.parked_because and self.now() < self.park_retry_at:
            return result

        if ist >= ziel:
            card = quest_card(img, row)
            if card is None:
                self._park("the card looked claimable, but could not be "
                          "read again")
                return result
            claimed, fell = self._claim(card)
            if claimed:
                result["claimed"] = True
                self._advance(self.step + 1)
            elif fell is False:
                if self._claim_stall_step == self.step:
                    self._park("claimed, but the counter did not fall, "
                              "twice in a row")
                else:
                    self._claim_stall_step = self.step
                    self._say("  claimed, but the counter did not fall -- "
                             "trying again next round")
            return result

        kind = ROUTINE[self.step]["kind"]
        if self.claim_only:
            self._once("claimonly", "  step %d needs playing (%s), but "
                                    "'claim only' is on"
                                    % (self.step + 1, ROUTINE[self.step]["name"]))
            return result
        if kind == HOLO and not self.auto_spend_on:
            if self._run_holo_step(ist, ziel):
                result["acted"] = True
            return result
        if kind in (HOLO, ENEMIES, STAGE):
            self.parked_because = None
            return result
        if not self._identified():
            # Not a park and not a refusal: the loop still plays the step,
            # the same as it always has. It says so once because this is
            # the one line that names a card nobody has counted yet, and
            # DGUP_DUMP_QUEST turns that line into a picture.
            self._once("unnamed:%d" % self.step,
                      "  nothing on this card says it is step %d (%s) "
                      "rather than another with the same target -- playing "
                      "it anyway" % (self.step + 1, ROUTINE[self.step]["name"]))
        if kind == DUNGEON:
            if not self.do_dungeon:
                self._park("the dungeon-quests switch is off")
                return result
            self._run_dungeon_step(ist, ziel)
            result["acted"] = True
            return result
        if kind == SUMMON:
            if not self.do_summon:
                self._park("the summon-quests switch is off")
                return result
            self._run_summon_step(ist, ziel)
            result["acted"] = True
            return result
        return result

    def _keep_frame(self, tag):
        """Keep one whole frame when a step fails on something unread.

        Not the card crop -- whatever went wrong is outside it. Once per
        tag per run, and without any switch to remember: a failure nobody
        photographed is a failure nobody can fix, and the passive helper
        keeps its unreadable frames on the same terms (passive._dump).
        """
        import os
        if tag in self._dumped:
            return
        self._dumped.add(tag)
        try:
            os.makedirs(DUMP_DIR, exist_ok=True)
            path = os.path.join(DUMP_DIR, "%s_%s.png"
                                % (tag, time.strftime("%H%M%S")))
            cv2.imwrite(path, self.bot.grab())
            self._say("    kept what it saw in %s" % path)
        except Exception as err:
            self._say("    could not keep the frame: %s" % err)

    def _dump_card(self, img, row):
        """Write the card out, with what was counted on it.

        Only when DGUP_DUMP_QUEST is set, and only once per (count, target)
        pair, so a day at the same quest does not fill a folder. This is
        how the empty "chars" entries in ROUTINE get filled: the quest that
        is on the screen writes its own card into debug_quest/ with the
        number of characters in the file name, and the same card read by
        hand says which quest that number belongs to. dungeon.dump_badge
        works the same way and for the same reason -- a card misread live
        cannot be chased with a screenshot taken afterwards by hand.
        """
        import os
        if not os.environ.get("DGUP_DUMP_QUEST"):
            return
        key = (row["name_len"], row["after_len"], row["ziel"])
        if key in self._dumped:
            return
        self._dumped.add(key)
        x0, y0, gw, gh = D.game_rect(img)
        fy = row["row_fy"] + CARD_FY_ROW_OFFSET
        left = int(x0 + (CARD_MID_FX - CARD_W / 2.0) * gw)
        right = int(x0 + (CARD_MID_FX + CARD_W / 2.0) * gw)
        top = int(y0 + (fy - CARD_H) * gh)
        bottom = int(y0 + (fy + CARD_H) * gh)
        crop = img[max(0, top):bottom, max(0, left):right]
        if crop.size == 0:
            return
        os.makedirs(DUMP_DIR, exist_ok=True)
        path = os.path.join(DUMP_DIR, "card_%s-%s_%d_of_%d.png"
                            % (row["name_len"] or 0, row["after_len"] or 0,
                               row["ist"], row["ziel"]))
        cv2.imwrite(path, crop)
        self._say("  card written: %s (%s)"
                  % (path, _words_said((row["name_len"], row["after_len"]))))

    def _stuck(self, img):
        """Not the plain main screen. Wait, then look for an X to get out.

        Nothing at all for the first STUCK_AFTER seconds: the screen the
        loop is looking at is most often one of its own on the way out, or
        an animation, or the player's, and every one of those ends by
        itself. What does not end by itself is a screen the loop tapped
        open and could not close -- a live run sat on the Special Summon
        reward screen for as long as anybody watched, saying this same
        line, with the game's own X drawn in the corner of every frame.

        Then, and only then, the X. Never a tap at a remembered corner:
        close_x has to find one, and if it does not this says so and keeps
        the frame instead of guessing. One tap per round, checked by the
        next round's auto button rather than by another look at the picture
        that aimed it -- the same rule the rest of tick() follows.
        """
        now = self.now()
        if self._stuck_since is None:
            self._stuck_since = now
        waited = now - self._stuck_since
        if waited < STUCK_AFTER:
            self._once("busy", "  not the plain main screen, nothing done "
                               "this round")
            return
        x = close_x(img)
        if x is None:
            self._once("noway", "  not the plain main screen for %.0f s, and "
                                "no X on it to get out with -- leaving it "
                                "alone" % waited)
            self._keep_frame("no-x-to-get-out-with")
            return
        if not self.may_tap:
            self._once("hands", "  a screen is in the way and %s could close "
                                "it, but the mouse is in use, not tapping"
                                % x["which"])
            return
        if self._stuck_taps >= STUCK_TAPS_MAX:
            self._once("xstuck", "  %s is still there after %d taps -- "
                                 "leaving it alone"
                                 % (x["which"], self._stuck_taps))
            self._keep_frame("x-would-not-close")
            return
        if now - self._stuck_tap_at < STUCK_TAP_EVERY:
            return
        self._stuck_taps += 1
        self._stuck_tap_at = now
        self._say("  not the plain main screen for %.0f s -- tapping %s at "
                  "%.3f/%.3f to get out (%d of %d)"
                  % (waited, x["which"], x["fx"], x["fy"], self._stuck_taps,
                     STUCK_TAPS_MAX))
        self.bot.tap(x["fx"], x["fy"], was="the X, to leave a screen the "
                                           "loop cannot work on")

    def _back_again(self):
        """The main screen is back. Forget how long it was gone.

        Said out loud only where an X was actually tapped, because that is
        the one case where the loop did something about it and the player
        has a line saying so hanging in the log.
        """
        if self._stuck_taps:
            self._say("  the main screen is back after %d tap(s) on the X"
                      % self._stuck_taps)
        self._stuck_since = None
        self._stuck_taps = 0

    def _blind(self, img):
        now = self.now()
        if self._blind_since is None:
            self._blind_since = now
        elif now - self._blind_since >= BLIND_AFTER:
            self._say("  the quest counter has not been readable for %.0f s "
                      "on a screen that looks right" % (now - self._blind_since))
            self._blind_since = now

    def status(self):
        """One line for the window."""
        step = ROUTINE[self.step]
        text = "Step %d of %d -- %s" % (self.step + 1, len(ROUTINE), step["name"])
        if self.last_progress:
            text += ", %d/%d" % self.last_progress
        if self.last_words and step["chars"] is None:
            # Only where the routine has no words for this step yet: that
            # pair is what has to be written into ROUTINE["chars"], and
            # the window is where somebody will see it.
            text += " (%s)" % _words_said(self.last_words)
        if self.parked_because:
            text += " -- parked: %s" % self.parked_because
        return text

    # -- what the card says this step is ------------------------------------
    def _matches(self, i, ziel, words):
        """Could the card in front of us be step `i`?

        Two questions, and the card answers as much of each as it can. The
        target has to be the step's target -- that one has always been
        asked. The words either side of the number have to be the step's
        words, wherever they have been counted: without them, a run that
        opened on "Bakemon" played DemiDevimon, because 2 is 2 and nothing
        else was looked at.

        A step whose card nobody has counted yet ("chars": None) is
        matched on its target alone, the way every step was before. That
        is not a gap in the check, it is the check saying what it does not
        know -- and the "other candidate, once" rule in _after_action is
        still underneath it.

        A step with no fixed target -- the stage one, whose number is a
        stage rather than a count -- is the other way round: never matched
        on the number, always on the words.
        """
        q = ROUTINE[i]
        if q["target"] is None:
            # A step with no target of its own takes the numbers no other
            # step claims. Without that, a card whose words went unread
            # would land here -- (0, 0) is what an empty reading looks
            # like as well -- and the loop would sit on a step that plays
            # nothing while the game showed something else entirely.
            if any(o["target"] == ziel for o in ROUTINE):
                return False
        elif q["target"] != ziel:
            return False
        if q["chars"] is None or words is None or None in words:
            return q["target"] is not None
        return all(abs((a or 0) - (b or 0)) <= NAME_TOL
                   for a, b in zip(q["chars"], words))

    def _identified(self):
        """Is the step we are on the only one the card could be?"""
        q = ROUTINE[self.step]
        if q["chars"] is None:
            return False
        others = [i for i in range(len(ROUTINE))
                  if i != self.step and ROUTINE[i]["target"] == q["target"]
                  and (ROUTINE[i]["kind"], ROUTINE[i]["arg"])
                  != (q["kind"], q["arg"])]
        return not others or all(ROUTINE[i]["chars"] is not None
                                 for i in others)

    # -- resync ------------------------------------------------------------
    def _handle_mismatch(self, ist, ziel, words):
        """Script and card disagree. Wait for a second frame, then resync.

        PLAN_QUEST_LOOP.md 2.1: a single mismatched frame is not proof of
        anything -- it could be the tail end of the very claim that is about
        to advance the step. Only a mismatch that survives two rounds in a
        row is trusted, and even then nothing is clicked: the step jumps
        forward to the next script entry the card could actually be -- by
        its target, and by the length of the word in front of it wherever
        that word has been counted.
        """
        if self._mismatch == (self.step, ziel, words):
            candidates = self._forward_candidates(ziel, words)
            if candidates:
                old = self.step
                self._advance(candidates[0])
                self._say("  the card is not step %d (%s): it shows "
                          "%d/%d, %s -- going to step %d (%s)"
                          % (old + 1, ROUTINE[old]["name"], ist, ziel,
                             _words_said(words), self.step + 1,
                             ROUTINE[self.step]["name"]))
            else:
                self._once("nomatch:%s:%s" % (ziel, words),
                          "  the card shows %d/%d, %s, and no step in the "
                          "routine looks like that -- parked"
                          % (ist, ziel, _words_said(words)))
                self.parked_because = "the card and the script disagree"
            self._mismatch = None
        else:
            self._mismatch = (self.step, ziel, words)

    def _forward_candidates(self, ziel, words):
        n = len(ROUTINE)
        order = [(self.step + i) % n for i in range(1, n + 1)]
        return [i for i in order if self._matches(i, ziel, words)]

    def _other_candidate(self, ziel, words=None):
        """A different step with the same target, for one retry.

        PLAN_QUEST_LOOP.md 2.1's third rule: two attempts that did not move
        the counter mean the wrong quest was played, and there is exactly
        one designed case of that -- DemiDevimon and Bakemon both asking
        for 2. Matched on kind as well as target, and on a different `arg`,
        so a stalled Skill Summon step is not "retried" against a Support
        one that merely shares its target by coincidence.

        And never against a step the card itself rules out: with both
        dungeon names counted, a stalled Bakemon step has no other
        candidate at all any more, and the loop parks instead of playing
        the wrong dungeon a second time.
        """
        cur = ROUTINE[self.step]
        for i, q in enumerate(ROUTINE):
            if i != self.step and q["target"] == ziel and q["kind"] == cur["kind"] \
                    and q["arg"] != cur["arg"] \
                    and self._matches(i, ziel, words):
                return i
        return None

    # -- claiming ------------------------------------------------------------
    def _wait_for(self, pred, timeout):
        deadline = self.now() + timeout
        while self.now() < deadline:
            if pred(self.bot.grab()):
                return True
            time.sleep(0.3)
        return False

    def _row_once_settled(self, timeout=SETTLE_TIMEOUT):
        """The card, once the screen is back to the plain main screen.

        The bot that just played comes back the moment *it* is finished,
        which is not the moment the game is: the dungeon's own result
        screens are still closing, and the very first frame after a run is
        as likely to be a reward window as a main screen. One reading of
        that frame is not a measurement -- taken as one, it parked a whole
        run on "could not read the quest card after the action" two
        seconds before the card was plainly readable again.

        So the same two gates tick() uses, and then the card: no banner, a
        crisp auto button, a counter that reads. None only after the
        timeout, which is then a real answer rather than a race.
        """
        deadline = self.now() + timeout
        while True:
            img = self.bot.grab()
            if not D.stage_failed(img) and D.auto_button(img) is not None:
                row = _quest_row(img)
                if row is not None:
                    return row
            if self.now() >= deadline:
                return None
            time.sleep(0.5)

    def _claim(self, card):
        """Tap the card, wait for the reward, close it, check the fall.

        No back key anywhere in here -- PLAN_QUEST_LOOP.md 5.1. The reward
        window is closed with a tap at a fixed, checked-empty spot, and the
        proof the claim really happened is the ist side falling, never the
        target: on the wrap from step 15 to step 1 the target itself changes
        too, but on every other step it does not, and a caller that waited
        for that would wait forever.

        Returns (claimed, fell). `fell` is None for a structural failure --
        the window never opened or never closed, already parked here on the
        spot -- and True/False once every tap landed and the only open
        question is whether the number actually moved; the caller gives
        that one case a single extra try before it counts as a park.
        """
        if not self.may_tap:
            self._once("hands", "  a quest is ready to claim, but the mouse "
                               "is in use, not tapping")
            return False, None
        before_ist, before_ziel = card["ist"], card["ziel"]
        self._say("  step %d ready (%d/%d), claiming"
                  % (self.step + 1, card["ist"], card["ziel"]))
        self.bot.tap(card["fx"], card["fy"], was="quest card")
        if self.dry_run:
            return False, None
        if not self._wait_for(lambda im: D.auto_button(im) is None,
                              CLAIM_OPEN_TIMEOUT):
            self._park("tapping the card did not open the reward window")
            return False, None
        for attempt in range(CLAIM_CLOSE_TAPS):
            self.bot.tap(DEAD_TAP[0], DEAD_TAP[1], was="dead spot, closing "
                                                        "the reward")
            if self._wait_for(lambda im: D.auto_button(im) is not None,
                              CLAIM_CLOSE_STEP):
                break
        else:
            self._keep_frame("reward-window-stuck")
            self._park("the reward window did not close after %d taps"
                      % CLAIM_CLOSE_TAPS)
            return False, None
        progress = quest_progress(self.bot.grab())
        if progress is None:
            return False, False
        ist, ziel = progress
        # Proof that the claim landed is the card being a *different* card,
        # and the ist side falling is only the usual way that shows. On the
        # step where the routine hands over to one with another target it
        # does not fall at all: 100/100 was claimed and the next card read
        # 610/610, which is not "the counter did not fall", it is the next
        # quest. Judged on the ist side alone that came back as a failed
        # claim and cost the loop a retry on a card it had already
        # collected.
        if ziel == before_ziel and ist >= before_ist:
            return False, False
        self._say("  claimed, next is %d/%d" % progress)
        return True, True

    # -- playing -------------------------------------------------------------
    def _reserve(self):
        if self.reserve_emulator():
            return True
        self._once("ownership", "  another bot owns the emulator, waiting")
        return False

    def _after_action(self, before_ist, before_ziel, blocked=None):
        """Did the action move the counter? Advance, retry once, or park.

        PLAN_QUEST_LOOP.md 2.1's third rule and 5.2's last step. A quest
        that did not move after a real attempt is not a loss to retry --
        CLAUDE.md 2.3, there are no lost rounds in this game -- it is the
        wrong quest, and the fix is to try the one other step the script
        could have meant, once, and park if that does not move it either.

        `blocked` is that rule's exception, and it comes from the bot that
        just ran: a reason why there was no real attempt at all. A counter
        standing still is then explained, so it is no longer evidence of
        the wrong quest -- the other candidate is not played, because that
        would spend the other dungeon's tickets on a guess the card has
        already answered -- and the park says what the bot saw instead of
        the counter it could not have moved.
        """
        park_in = PARK_RETRY_EMPTY if blocked else PARK_RETRY
        row = self._row_once_settled()
        if row is None:
            self._park(blocked or "could not read the quest card after the "
                                  "action", retry_in=park_in)
            return
        ist, ziel = row["ist"], row["ziel"]
        if ziel != before_ziel:
            # Something else moved the routine on already; the next tick
            # re-reads the script against this card fresh.
            return
        if ist > before_ist:
            self._say("  progress: %d/%d -> %d/%d" % (before_ist, before_ziel,
                                                       ist, ziel))
            return
        if not blocked and self._retried_step != self.step:
            self._retried_step = self.step
            alt = self._other_candidate(
                ziel, (row["name_len"], row["after_len"]))
            if alt is not None:
                self._say("  no progress after the action, trying the other "
                          "step with the same target instead")
                self._advance(alt)
                return
        self._park(blocked or "an action did not move the counter (still "
                              "%d/%d)" % (ist, ziel), retry_in=park_in)

    def _run_holo_step(self, ist, ziel):
        """Activate the hologram device once, and prove the quest counted it.

        One activation per round, not fifty in a loop: every tap is aimed
        with a frame taken after the last one landed and is checked against
        the quest's own counter, the same rule the rest of this file
        follows. Fifty of them take a few minutes, which is the cheapest
        part of this whole routine.

        Returns True if a tap went out.
        """
        if not self.may_tap:
            self._once("hands", "  the hologram device needs a tap, but the "
                               "mouse is in use")
            return False
        auto = D.auto_button(self.bot.grab())
        if auto is None:
            return False
        self._once("holo", "  auto spend is off -- activating the hologram "
                          "device from here, %d to go" % (ziel - ist))
        self.bot.tap(auto["fx"] + HOLO_TAP_OFF[0],
                     auto["fy"] + HOLO_TAP_OFF[1], was="hologram device")
        if self.dry_run:
            return True
        deadline = self.now() + HOLO_COUNT_WAIT
        while self.now() < deadline:
            time.sleep(0.5)
            frame = self.bot.grab()
            if D.stage_failed(frame) or D.auto_button(frame) is None:
                continue
            row = _quest_row(frame)
            if row is None or row["ziel"] != ziel:
                continue
            if row["ist"] > ist:
                self._holo_dead = 0
                self.last_progress = (row["ist"], row["ziel"])
                return True
        # The device has nothing to spend, or the tap missed. Either way a
        # second dead tap is the answer, not a fiftieth.
        self._holo_dead += 1
        if self._holo_dead >= 2:
            self._park("the hologram device was tapped twice and the quest "
                      "did not count either one -- out of tickets?")
        return True

    def _run_dungeon_step(self, ist, ziel):
        if not self._reserve():
            return
        step = ROUTINE[self.step]
        watcher = None
        bot = None
        try:
            self._say("  step %d: %s -- playing the dungeon"
                      % (self.step + 1, step["name"]))
            bot = D.DungeonBot(self.cap, dry_run=self.dry_run, log=self._quiet,
                               only=[step["arg"]], budgets={step["arg"]: 2},
                               survey_first=True)
            self.current_control = bot.control
            if self.start_guard:
                watcher = self.start_guard(bot)
            bot.run()
        finally:
            if watcher and self.stop_guard:
                self.stop_guard(watcher)
            self.current_control = None
            self.release_emulator()
        self._after_action(ist, ziel, blocked=self._dungeon_blocked(bot))

    def _dungeon_blocked(self, bot):
        """What the dungeon bot read off the card, said out loud.

        The bot surveys both counters from the list before it opens
        anything and skips a card that has nothing left -- but this loop
        hands it a silenced log and then never asked what it had found. An
        empty DemiDevimon therefore came back as "an action did not move
        the counter (still 1/2)", once a minute, with nothing anywhere
        saying that the tickets were gone: the player could see it on the
        card and the bot, which had read the very same number, could not.
        A reading thrown away is a reading nobody took.

        Returns a park reason where the card says the day is over on this
        dungeon, None wherever there was something to play -- the quest
        counter is the witness again then, the way it is everywhere else.
        """
        if bot is None:
            return None
        # only=[...] picks a single card, so the survey holds exactly one
        # budget. None means the list never opened at all, which is not
        # something a ticket count can be read out of.
        budget = next(iter(bot.counted.values()), None)
        if budget is None:
            return None
        tickets, ads, total = budget["tickets"], budget["ads"], budget["total"]
        if total == 0:
            self._say("  the dungeon card reads 0 tickets and no ads left")
            return "the dungeon is out of tickets and ads until tomorrow"
        if total is not None:
            self._say("  the dungeon card reads %d ticket%s and %d ad%s"
                      % (tickets, "" if tickets == 1 else "s",
                         ads, "" if ads == 1 else "s"))
        elif tickets:
            # The film symbol is drawn only at 0 tickets, so above zero
            # the ads are simply unknown -- CLAUDE.md, and the reason a
            # card with tickets left never counts as empty here.
            self._say("  the dungeon card reads %d ticket%s, ads unknown "
                      "until they run out"
                      % (tickets, "" if tickets == 1 else "s"))
        else:
            self._say("  the counters on the dungeon card could not be read")
        return None

    def _enter_summon_by_card(self, summon_bot, mode):
        """Tap the quest card straight into Special Summon. True if it did.

        The shortcut PLAN_QUEST_LOOP.md 5.3 asks for: confirmed by
        mode_dots, never assumed. A tap that lands somewhere else is not
        chased further here -- the caller falls back to open_summons() and
        goto_mode(), the way that runs every day already.
        """
        import summon as S
        img = self.bot.grab()
        card = quest_card(img)
        if card is None:
            return False
        summon_bot.tap(card["fx"], card["fy"], was="quest card, into "
                                                    "Special Summon")
        if self.dry_run:
            return False
        time.sleep(summon_bot.bot.pause_long)
        return S.mode_dots(summon_bot.grab()) == mode

    def _run_summon_step(self, ist, ziel):
        import summon as S

        step = ROUTINE[self.step]
        mode = step["arg"]
        # No counting before the menu is open. Both numbers this step needs
        # -- the ticket badge and the "n /2" over View Ads -- are drawn on
        # the summon screen and nowhere else, so asked of the main screen
        # they can only answer None. Asked there anyway, they parked the
        # step on "not enough tickets for a summon, and no free ads left
        # today" every single time, with a full stock of tickets and
        # without the menu ever having been opened. A reader is allowed to
        # say None; a caller is not allowed to read that as a number.
        if not self._reserve():
            return
        watcher = None
        try:
            self._say("  step %d: %s -- opening Special Summon"
                      % (self.step + 1, step["name"]))
            bot = S.SummonBot(self.cap, dry_run=self.dry_run, log=self._quiet,
                              enabled={S.SKILL: True, S.SUPPORT: True,
                                       S.CREST: False},
                              watch_ads_first=True, max_per_mode=1)
            self.current_control = bot.control
            if self.start_guard:
                watcher = self.start_guard(bot)
            try:
                if not self._enter_summon_by_card(bot, mode):
                    if not (bot.open_summons() and bot.goto_mode(mode)):
                        self._park("could not reach the summon menu")
                        return
                # Now there is something to count, and it is worth saying
                # out loud: this is the number the step lives or dies on.
                tickets = S.ticket_counter(bot.grab())
                ads = S.ads_left(bot.grab())
                self._say("  on the summon screen: %s tickets, %s free ad(s), "
                          "a draw costs %d"
                          % ("could not read" if tickets is None else tickets,
                             "could not read" if ads is None else ads,
                             S.MODE_PRICE[mode]))
                # The ads first, because they are free. No reading of the
                # quest card in between: it is not on this screen at all,
                # and the check that used to sit here was reading the
                # summon menu for a card that is behind it. Two free ads
                # cannot finish a quest that wants thirty draws anyway --
                # what finishes it is the one draw of 35 below.
                before = bot.stats["ads"]
                bot.watch_ads(mode)
                drawn = bot.spam(mode)
                if not drawn and bot.stats["ads"] == before:
                    self._park("nothing to draw with: %s tickets against a "
                              "price of %d, and no free ads left"
                              % ("an unreadable count of" if tickets is None
                                 else tickets, S.MODE_PRICE[mode]))
                    return
            finally:
                bot.leave_summons()
        finally:
            if watcher and self.stop_guard:
                self.stop_guard(watcher)
            self.current_control = None
            self.release_emulator()
        self._after_action(ist, ziel)


# ----------------------------------------------------------------------------
def probe(cap, log=print, rounds=1):
    """Read and say, click nothing. py quest.py --probe"""
    bot = D.DungeonBot(cap, dry_run=True, log=lambda t: None)
    for _ in range(max(1, rounds)):
        img = bot.grab()
        card = quest_card(img)
        stage = stage_number(img)
        log("auto_button: %s" % ("found" if D.auto_button(img) else "None"))
        log("stage_failed: %s" % D.stage_failed(img))
        if card is None:
            log("quest card: not found")
        else:
            log("quest card: tap %.3f/%.3f, counter row %.3f/%.3f, %d/%d "
               "(claimable: %s)" % (card["fx"], card["fy"], card["row_fx"],
                                    card["row_fy"], card["ist"], card["ziel"],
                                    card["ist"] >= card["ziel"]))
        if card is not None:
            words = (card["name_len"], card["after_len"])
            probe_loop = QuestLoop.__new__(QuestLoop)
            fits = [i + 1 for i in range(len(ROUTINE))
                    if probe_loop._matches(i, card["ziel"], words)]
            log("quest words: %s -- fits step(s) %s"
               % (_words_said(words),
                  ", ".join(str(i) for i in fits) or "none"))
        log("stage number: %s" % stage)
        if rounds > 1:
            time.sleep(TICK)


def main():
    import argparse

    import capture
    import userdata

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="read and log once, click nothing")
    ap.add_argument("--go", action="store_true", help="run for real")
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--input", choices=["adb", "mouse"], default=None)
    args = ap.parse_args()

    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)

    if args.probe or not args.go:
        probe(cap, rounds=max(1, args.rounds))
        return

    # No persistence here: the standalone CLI has no access to the
    # launcher's own state file, and starts the routine from step 1 every
    # time. The launcher's own use of QuestLoop (app.py) wires save_step to
    # that file; this is a probe tool, not the way this bot is meant to run
    # for a whole day.
    loop = QuestLoop(cap, dry_run=False)
    n = 0
    while not args.rounds or n < args.rounds:
        n += 1
        loop.tick()
        time.sleep(TICK)


if __name__ == "__main__":
    main()
