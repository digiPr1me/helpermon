"""
The passive helper: the bond token, and Auto Spend for Hologram Tickets.

Two small jobs on the game's main screen, done over and over while Helpermon
is open rather than in a run of its own:

  - the bond token. The partner Digimon shows a speech bubble with a food
    symbol in it; the token is collected by tapping **the figure**, not the
    bubble. Tapping the figure with no token there opens the Partner window
    instead, which is why the bubble has to be found first: it is the only
    evidence that a tap will collect something.
  - Auto Spend. The blue (A) disc at the hologram device makes the game spend
    its hologram tickets by itself. It is a toggle, it switches itself off
    when the tickets run out, and the counter under the device is what says
    whether it is running.

This module reads and taps. The one thing it closes is the Partner window its
own tap opened, within seconds of opening it; anything else the player has on
screen is left where it is -- the chat window included, which is why nothing
here ever aims at the chat line. It does not own a loop. The caller ticks it,
so that one thread in the launcher can pause it while a real bot is playing.

Everything visual is borrowed from dungeon.py: game_rect for the coordinate
vocabulary, auto_button both as a target and as the proof that nothing is
drawn over the main screen, and the digit reader, which carries no stored
pictures of digits and so needs no setup step.
"""

import os
import time

import cv2
import numpy as np

import dungeon as D


# ----------------------------------------------------------------------------
# The bond bubble
# ----------------------------------------------------------------------------
# What is looked for is the bubble's frame, not what is in it: the food symbol
# changes -- bread, apple, meat -- while the frame does not. It is a white
# rounded square with a tail at the bottom, and inside the white there is a
# cyan ring, drawn as two corner brackets facing each other across the
# symbol: one at the upper left and one at the lower right, or the other way
# round.
#
# **The cyan is the anchor, not the white.** For a long time this went the
# other way round -- a white blob of about the right size with cyan somewhere
# against it -- and it worked until the game drew a stage in pale stone. On
# Haunted House the walls measure inside the same white range as the bubble,
# the bubble's white ran into the wall behind it, and what came back was a
# 69 x 96 blob that fell straight through the width filter. The player sent a
# screenshot of a bubble plainly on the screen that the helper could not see;
# a second frame, on pale purple, had been sitting unread in the collection
# since the feature was built. White is the game's most common colour and
# tells the bubble from nothing.
#
# The cyan does. In the whole band there is nothing else of that hue drawn
# that thinly, and the two brackets are a **pair**, which is the rule this
# program already leans on everywhere else: a thing is identified by its
# neighbour, not by its own measurements. Their midpoint is the bubble's
# centre, to three thousandths on every frame there is.
#
# Measured on six frames -- five window shapes and one ADB frame, two of
# them the pale stages the white reader lost:
#
#   one bracket   fw 0.0320 to 0.0446   fill 0.23 to 0.29
#   the pair      centres dx 0.33 to 0.71 of a bracket width
#                          dy 0.56 to 1.14 of a bracket height
#                 areas within 0.88 of each other
#   white in a bubble-sized box at their midpoint   0.43 to 0.48
#
# and against that, everything else in the band that got as far as being
# paired: white 0.02 to 0.14, except one mis-pairing of the real bubble's own
# brackets with a stray, which sat at dx 1.07.
#
# The band. The player: the token can only be in the middle of the picture
# and nowhere else, which the frames bear out -- six sightings between fx
# 0.487 and 0.514, fy 0.317 and 0.401, and five older ones inside the same
# window. So the search is the middle of the field with a fifth of air on
# every side, and the two columns of side icons are nowhere near it. That
# matters: the Daily Bonus wheel is new in the inner column at fx 0.694 and
# it is a white and cyan disc -- the old band ended at 0.68, two per cent
# away, and the player reported the wheel being taken for the token. Its
# cyan quarters are solid, filling 0.64 of their boxes against a bracket's
# 0.29, so the pair test refuses it as well wherever it is drawn.
BUBBLE_BAND = (0.40, 0.62, 0.26, 0.50)
BUBBLE_WHITE = ((0, 0, 200), (179, 45, 255))
BUBBLE_CYAN = ((86, 90, 160), (100, 255, 255))
# One bracket: thin, and about half the bubble across.
BUBBLE_ARM_W = (0.024, 0.058)
BUBBLE_ARM_FILL = (0.15, 0.42)
# The pair, in units of a bracket's own width and height. A bracket that is
# not part of a ring has nothing sitting diagonally beside it.
BUBBLE_PAIR_DX = 0.85
BUBBLE_PAIR_DY = (0.40, 1.30)
# Two arcs of the same ring are drawn the same. 0.88 at worst, and the one
# mis-pairing that got this far scored 0.87 -- so this is a second opinion,
# not the thing that decides.
BUBBLE_PAIR_RATIO = 0.70
# The bubble is still white, and this is where that is asked: over a
# bubble-sized box at the pair's midpoint. 0.43 to 0.48 against 0.14 for the
# best impostor, a factor of 1.4 either way -- and it holds on the pale
# stages, where the wall only adds white to a box that is mostly white
# already.
BUBBLE_WHITE_MIN = 0.30
# How big the box is that white share is taken over: the bubble's own width,
# measured 0.0535 to 0.0610 across the ring plus its border.
BUBBLE_SIDE = 0.056

# Where the figure is, seen from the bubble.
#
# Corrected after a live run. The first version aimed at the level badge and
# from there at the big Digimon standing over it -- which is a figure, and
# the wrong one. The badge belongs to the team's lead; the bubble belongs to
# the small one standing down and to the right of it, and tapping the lead
# only opens its info window. The player named it: "the figure below and to
# the right of the one so far".
#
# Measured again on three frames at three window sizes, bubble to the middle
# of the figure that owns it, and once more after game_rect learned to find
# the game inside a sidebar-less window:
#
#   651 x 1195   a pink dragon        -0.0710 gw   +0.0756 gh
#   657 x 1198   a small orange one   -0.0709 gw   +0.0754 gh
#   497 x  914   a golden bird        -0.0707 gw   +0.0766 gh
#
# Three ten-thousandths of spread, where the smallest of the three figures is
# about 0.07 gw across. Checked by marking the point on each frame: it lands
# on the body every time.
BOND_TAP_OFF = (-0.071, 0.076)
# The play area, as a last check on that arithmetic. A tap computed outside
# this is not a figure and is not sent.
BOND_TAP_LIMITS = (0.12, 0.88, 0.18, 0.62)

# The chat line, which is not a place to tap.
#
# The game writes the world chat across the bottom of the field, over the
# scenery and over whoever is standing there: a translucent bar with the last
# message in it, a round chat symbol at its left and a collapse arrow left of
# that. A tap anywhere on it opens the chat window -- reported from a live
# session, twice, with the window then swallowing the taps of the rounds that
# followed.
#
# There is no reading to be done here. The bar is where it is, and the fix is
# simply not to aim into it:
#
#   the bar, over three frames at three shapes, window and ADB
#       top     0.5853 to 0.5873      bottom  0.6136 to 0.6140
#       left    0.1045 (collapse arrow)
#       right   0.5921 to 0.6026, growing with the length of the message
#
# The zone below covers that with about three per cent of air on every side,
# because it is a place to stay out of and being too large costs nothing. On
# the other side of it, the taps a real bubble has ever asked for run from
# 0.393 to 0.477, a fifth of the picture above the zone. Only the very bottom
# of the search band can reach it at all -- 0.50 there plus the figure's
# 0.076 comes to 0.576 -- so this guard is a fence at the end of a field
# nobody walks in. It stays because that is what a fence is for.
#
# The helper does not close the chat window either, and that is deliberate:
# it cannot tell its own tap from the player's hand, and closing a window
# somebody just opened is worse than leaving one open. With nothing aiming
# into the bar there is nothing to close -- and while a window is up,
# screen_is_clear says the screen is not clear and every round does nothing,
# which is the right answer whoever opened it.
CHAT_ROW = (0.06, 0.64, 0.570, 0.630)


def on_chat_row(fx, fy):
    """Would a tap here land on the chat line?"""
    x0, x1, y0, y1 = CHAT_ROW
    return x0 <= fx <= x1 and y0 <= fy <= y1


def _cyan_arms(img, x0, y0, gw, gh):
    """The corner brackets in the middle of the field, left to right.

    Everything of the bubble's cyan that is drawn as thinly as the bubble
    draws it. What comes back is the raw stats rows, in the crop's own
    pixels, with the crop's corner so the caller can put them back.
    """
    fx0, fx1, fy0, fy1 = BUBBLE_BAND
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0 or sub.shape[0] < 2 or sub.shape[1] < 2:
        return left, top, []
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, np.array(BUBBLE_CYAN[0]), np.array(BUBBLE_CYAN[1]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(cyan, 8)
    arms = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not w or not h:
            continue
        if not BUBBLE_ARM_W[0] <= w / float(gw) <= BUBBLE_ARM_W[1]:
            continue
        fill = area / float(w * h)
        if not BUBBLE_ARM_FILL[0] <= fill <= BUBBLE_ARM_FILL[1]:
            continue
        arms.append((x, y, w, h, area))
    arms.sort(key=lambda s: s[0])
    return left, top, arms


def _white_share(img, cx, cy, gw):
    """How much of a bubble-sized box at this point is white.

    Taken from the frame rather than from the band's crop, so that a bubble
    near the edge of the band is measured over the same box as one in the
    middle of it.
    """
    side = max(4, int(BUBBLE_SIDE * gw))
    top, left = int(cy - side / 2), int(cx - side / 2)
    box = img[max(0, top):top + side, max(0, left):left + side]
    if box.size == 0:
        return 0.0
    hsv = cv2.cvtColor(box, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array(BUBBLE_WHITE[0]), np.array(BUBBLE_WHITE[1]))
    return float(white.mean()) / 255.0


def bond_bubble(img):
    """The bond bubble, or None if the screen is not showing one.

    The cyan ring is what is looked for, as a pair of brackets, and the white
    is only asked about afterwards -- see the block above for why round that
    way. Returns the same shape as dungeon.auto_button: fx, fy, fw, fh as
    fractions of the reference window, plus the white share that won.
    """
    x0, y0, gw, gh = D.game_rect(img)
    left, top, arms = _cyan_arms(img, x0, y0, gw, gh)
    best = None
    for i, one in enumerate(arms):
        for other in arms[i + 1:]:
            wide = (one[2] + other[2]) / 2.0
            tall = max((one[3] + other[3]) / 2.0, 1.0)
            dx = abs((one[0] + one[2] / 2.0) - (other[0] + other[2] / 2.0)) / wide
            dy = abs((one[1] + one[3] / 2.0) - (other[1] + other[3] / 2.0)) / tall
            if dx > BUBBLE_PAIR_DX:
                continue
            if not BUBBLE_PAIR_DY[0] <= dy <= BUBBLE_PAIR_DY[1]:
                continue
            if (min(one[4], other[4]) / float(max(one[4], other[4]))
                    < BUBBLE_PAIR_RATIO):
                continue
            cx = left + ((one[0] + one[2] / 2.0) + (other[0] + other[2] / 2.0)) / 2.0
            cy = top + ((one[1] + one[3] / 2.0) + (other[1] + other[3] / 2.0)) / 2.0
            share = _white_share(img, cx, cy, gw)
            if share < BUBBLE_WHITE_MIN:
                continue
            if best is not None and share <= best["white"]:
                continue
            # The box the two brackets span, which is the bubble to within
            # its own border: 0.054 to 0.061 of the window across, against
            # the 0.0535 to 0.0593 the white reader used to report.
            ring_w = (max(one[0] + one[2], other[0] + other[2])
                      - min(one[0], other[0]))
            ring_h = (max(one[1] + one[3], other[1] + other[3])
                      - min(one[1], other[1]))
            best = {"fx": (cx - x0) / gw, "fy": (cy - y0) / gh,
                    "fw": ring_w / float(gw), "fh": ring_h / float(gh),
                    "white": share}
    return best


def aim_at_figure(bubble):
    """Where this bubble says the figure is, wherever that falls."""
    return (bubble["fx"] + BOND_TAP_OFF[0], bubble["fy"] + BOND_TAP_OFF[1])


def figure_from_bubble(bubble):
    """Where to tap for the token, or None if that is not a place to tap.

    Two ways of being no place: outside the field, which means the bubble was
    never a bubble, and on the chat line, which means the figure is standing
    behind it. Both end the round the same way and the caller says which it
    was.
    """
    fx, fy = aim_at_figure(bubble)
    x0, x1, y0, y1 = BOND_TAP_LIMITS
    if not (x0 <= fx <= x1 and y0 <= fy <= y1):
        return None
    if on_chat_row(fx, fy):
        return None
    return fx, fy


# ----------------------------------------------------------------------------
# The Partner window
# ----------------------------------------------------------------------------
# What opens when the figure is tapped and no token is there. The picture in
# it is a different Digimon every time, and the name and skills are text, so
# neither can be what identifies it. Its two buttons can: a violet
# Encyclopedia and a blue Move, side by side, the same size. That is the pair
# rule the dungeon bot already leans on -- a button is identified by its
# neighbour, not by its own position.
#
# Measured on three frames of it, two window sizes:
#
#   violet  fx 0.325 - 0.329   fy 0.732 - 0.734   fw 0.229 - 0.230
#   blue    fx 0.620 - 0.623   fy 0.732 - 0.734   fw 0.229 - 0.230
#
# and on the main screen there is no violet button at all.
PARTNER_VIOLET_X = 0.327
PARTNER_BLUE_X = 0.622
PARTNER_Y = 0.733
PARTNER_TOL = 0.04

# Whose window is it? This is the whole of what was missing, and leaving it
# out closed windows the player had just opened for themselves -- reported
# from a live session, and once for a window that was not even this one, so
# the pair above matches more than the three frames it was measured on.
#
# The helper knows its own: it taps the figure only when it has seen a
# bubble, and a Partner window is what that tap opens when the token turns
# out to have been collected already. So a window is the helper's for this
# long after its own tap on the figure, and nobody else's ever.
#
# Fifteen seconds against a round of two: the window is seen on the next
# round, and two taps and the back key all fall well inside it. It does not
# get extended, not even by a round that could not tap because the mouse was
# in use -- an ownership that can be pushed forward is one that drifts onto
# whatever is on screen when the player finally lets go, which is the bug
# itself in slower motion. Miss the fifteen seconds and the window waits to
# be closed by hand, which is the safe way round.
PARTNER_OWN = 15.0

# How it is closed: a tap above it, not the back key.
#
# The back key was the first answer and it is a loaded gun in this game. With
# no dialog open it raises "Return to the title screen?", and in one live run
# it did exactly that three times in three minutes -- the window had closed
# by itself between the frame and the key. Nothing was lost, because back()
# recognises that prompt and cancels it, but a tap cannot raise it at all.
#
# 0.15 of the height is above the panel, whose top edge measured 0.199 over
# three frames, and what sits there is the stage banner: a label, not a
# button. So the tap either closes the window or does nothing.
PARTNER_CLOSE = (0.50, 0.15)
# After this many taps that changed nothing, the back key gets its turn after
# all. Better a prompt that gets cancelled than a helper stuck behind a
# window it opened itself.
PARTNER_TAPS = 2


def partner_menu(img):
    """The Partner window's button pair, or None.

    A yes or no. The answer is the violet button, and nothing uses it -- the
    window is closed by a tap above the panel, at a fixed place.

    Not proof of whose window it is. One live report has this matching a
    screen that was not the Partner window at all, so the caller decides by
    what the helper itself did, not by what this recognised.
    """
    violets = [b for b in D.find_buttons(img, D.VIOLET, min_area=0.004, min_y=0.0)
               if D.near(b["fx"], PARTNER_VIOLET_X, PARTNER_TOL)
               and D.near(b["fy"], PARTNER_Y, PARTNER_TOL)]
    if not violets:
        return None
    blues = [b for b in D.find_buttons(img, D.BLUE, min_area=0.004, min_y=0.0)
             if D.near(b["fx"], PARTNER_BLUE_X, PARTNER_TOL)
             and D.near(b["fy"], PARTNER_Y, PARTNER_TOL)]
    if not blues:
        return None
    return violets[0]


# ----------------------------------------------------------------------------
# The hologram counter
# ----------------------------------------------------------------------------
# The number under the hologram device, "77,605 / 10". The left side is what
# is left, the right side is Items per Activation from the device's own
# settings and is not read.
#
# Measured again after game_rect learned to find the game inside a window
# that has no sidebar. Every fraction in this file moved a little when that
# landed, and this band is the tightest one there is -- the old numbers put
# its edge through the tops of the digits, and a window resized to a
# different shape then slid them out of it altogether.
#
# Over nine frames at six window shapes, from 497 x 914 to 765 x 1390, the
# counter's own box now measures:
#
#   left edge of the first digit   0.4109 - 0.4129
#   top edge of the row            0.8617 - 0.8648
#   bottom edge of the row         0.8729 - 0.8755
#
# A spread of two thousandths across every shape, which is what a stable
# coordinate vocabulary looks like. The band keeps a full digit height of
# air above and below, so nothing sits on an edge.
HOLO_BAND = (0.36, 0.62, 0.845, 0.895)
HOLO_SCALE = 4
HOLO_WHITE = (200, 255)
# The glyph filter, all of it relative to the crop so that the window size
# does not matter. Measured over the same four frames, as a share of the
# scaled crop's height:
#
#   digits          0.278 - 0.300
#   the slash       0.343 - 0.369
#   the comma       0.111 - 0.125
#   what else is in the band (XP numbers, the device's rim) is wider than it
#   is tall, 1.4 to 7.9, where a digit measures 0.58 to 0.78
#
# The comma is the new one against the dungeon's card counters, and it is the
# one glyph that must never reach read_digit -- it would come back as a digit
# and turn 1,000 into 10000. dungeon.GLYPH_MIN_H at 0.20 already parts it
# from the digits with room on both sides, so it is reused rather than a
# second number invented.
HOLO_ASPECT = (0.15, 1.20)
HOLO_FILL_MIN = 0.15
# A noise floor and nothing more. It used to be a real threshold, set against
# the crop's height -- and then the crop was made taller to survive a resized
# window, every proportion to it shrank, and the comma dropped through. With
# no comma the number lost the rule that says three digits follow one, and a
# counter that had been read for days went unreadable.
#
# The lesson is the one CLAUDE.md already carries: measure the shape against
# something that belongs to the thing itself. Here that is the slash, and
# every proportion that decides anything is taken against it further down.
# What is left here is only "too small to be a character at all": the comma
# measures 0.07 of the crop at its smallest, single-pixel noise far less.
HOLO_MIN_H = 0.04
# The slash, and the row it stands in.
#
# dungeon.group_glyphs splits a badge into counters by the gaps between
# characters, which is right for a strip that holds nothing else. This crop
# does hold something else: the XP numbers the device throws up sit directly
# above the counter and are white, the same size and the same shape as a
# digit. Split by gaps alone they join the number and 77,105 reads as
# 7,727,375 -- measured, on bond-5.
#
# So the row is what selects here, and the slash defines it. Measured over
# four frames:
#
#   slash, width over height   0.45 - 0.46
#   digits, width over height  0.58 - 0.78
#   digit height over slash    0.78 - 0.81
#   comma height over slash    0.33 - 0.34
#   digit centre off the slash centre   2 to 4 px of a 51 px slash
#
# The XP numbers sit a whole row higher, 60 px off that centre, and that is
# what throws them out.
HOLO_SLASH_WH = 0.52
HOLO_DIGIT_H_MIN = 0.60
# Digits are shorter than the slash beside them, measured 0.78 to 0.85 of it.
# The upper bound is what stops a row of digits from being taken for the
# slash of some other row.
HOLO_DIGIT_H_MAX = 0.95
HOLO_ROW_TOL = 0.25
# The comma, as a share of the slash: short, and sitting low. Measured on the
# four frames, and the two numbers cluster tightly -- height 0.32 to 0.34 of
# the slash, centre 0.29 to 0.33 of a slash height below the row's own
# centre, where a digit sits within 0.06 of it.
#
# Tight on purpose. The device's rim throws off specks: one of them measured
# 0.25 and 0.54 and a window loose enough to hold it made bond-1 read as a
# number with two commas, which the grouping below then threw away whole.
HOLO_COMMA_H = (0.28, 0.40)
HOLO_COMMA_DROP = (0.22, 0.42)
# The digits of one number are all the same height, and a digit that is not
# is a digit something is drawn over. That is not a rare case here: the XP
# numbers rising off the device clip the tops of the digits under them, and a
# clipped digit does not come back as unreadable, it comes back as another
# digit. On bond-5 a clipped 1 and 0 read as 2 and 3, and 77,105 became
# 77,235 -- a number that looks perfectly reasonable and is wrong, which is
# the worst kind.
#
# Measured, shortest digit of a number over the tallest:
#
#   the four clean frames   0.958, 0.968, 0.976, 1.000
#   bond-5, two clipped     0.878
#
# So an uneven row is thrown away whole, and the next tick reads it again.
HOLO_DIGIT_EVEN = 0.93

# Two structural checks on top, because a clipped digit does not always come
# back shorter -- sometimes it does not come back at all, and a number that
# has quietly lost a digit still looks like a number. 77,605 reading as 7,605
# would be a fall of seventy thousand that never happened.
#
#   The commas. The game writes thousands separators, so the digits after a
#   comma are exactly three, and a number of four digits or more without one
#   is not a number that was read properly.
#
#   The spacing. Measured between neighbouring characters of the counter,
#   including the comma: 11 to 16 pixels where a digit is 27 wide. A missing
#   digit leaves a hole of 41. One digit width is the line between them, with
#   room on both sides.
HOLO_GROUP = 3
HOLO_GAP_MAX = 1.0


def _holo_mask(img):
    """The counter's crop, scaled up and reduced to its white text."""
    x0, y0, gw, gh = D.game_rect(img)
    fx0, fx1, fy0, fy1 = HOLO_BAND
    left = max(0, int(x0 + fx0 * gw))
    top = max(0, int(y0 + fy0 * gh))
    sub = img[top:int(y0 + fy1 * gh), left:int(x0 + fx1 * gw)]
    if sub.size == 0 or sub.shape[0] < 2 or sub.shape[1] < 2:
        return None
    big = cv2.resize(sub, (sub.shape[1] * HOLO_SCALE, sub.shape[0] * HOLO_SCALE),
                     interpolation=cv2.INTER_CUBIC)
    return cv2.inRange(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY),
                       HOLO_WHITE[0], HOLO_WHITE[1])


def _holo_glyphs(mask):
    """Characters in the counter crop, from left to right.

    The same job as dungeon.badge_glyphs, with one difference that matters:
    the area filter there is an absolute number of pixels, and this crop is
    a good deal smaller than a dungeon card's badge. At 497 px window width
    the slash measures 150 pixels against that filter's 200, so it would be
    thrown away and with it the only thing that says where the number ends.
    Everything here is therefore relative to the crop.
    """
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not h or h < HOLO_MIN_H * mask.shape[0]:
            continue
        if not HOLO_ASPECT[0] <= w / float(h) <= HOLO_ASPECT[1]:
            continue
        if area / float(w * h) < HOLO_FILL_MIN:
            continue
        out.append(stats[i])
    out.sort(key=lambda s: s[0])
    return out


def holo_counter(img):
    """How many hologram tickets are left, or None if it cannot be read.

    All or nothing, like dungeon.read_counter: half a number would be read as
    a fall that never happened and would have the bot press a button that is
    already doing its job.

    None is the answer on any screen that is not the clear main screen. The
    game dims what is behind a dialog and the dimmed digits drop out of the
    white mask -- checked on two frames of the Partner window, where this
    finds no glyphs at all.
    """
    mask = _holo_mask(img)
    if mask is None:
        return None
    digits = _counter_row(_holo_glyphs(mask))
    if not digits:
        return None
    return D.read_counter(mask, digits)


def _counter_row(glyphs):
    """The digits of the counter, or None if none of the crop is one.

    Every narrow character is tried as the slash, and the one that turns out
    to have a proper number written to its left wins. Taking the tallest and
    hoping was the first version, and it worked only while the crop was cut
    so tightly around the counter that nothing else could get in -- which is
    exactly the tightness that lost the counter altogether when the player
    resized the window. A crop with air in it holds the device's own icons,
    and those are taller than the slash: measured 0.33 and 0.49 of the crop
    against the slash's 0.25.

    So the anchor has to prove itself instead. The proof is the number: even
    digits, evenly spaced, three of them after every comma. Junk does not
    have that, and the one row that does is the counter wherever it sits.

    All of it exists to avoid returning a number that has quietly lost a
    digit. Such a number reads perfectly well and is simply wrong, which is
    the one failure this bot cannot notice by itself -- it would look like
    the fall it is watching for.
    """
    best = None
    for slash in glyphs:
        if slash[2] / float(max(slash[3], 1)) > HOLO_SLASH_WH:
            continue
        digits = _digits_left_of(glyphs, slash)
        if not digits:
            continue
        # A counter reads "so many out of so many", so there is a number on
        # the other side of the slash as well. Requiring it is what stops a
        # stray pair of specks from passing as a one digit counter: on one
        # frame whose real row was damaged, junk read as 7 -- and a wrong
        # small number is far worse than none, it looks like the whole stock
        # spent in a single round.
        if not _digits_beside(glyphs, slash, right=True):
            continue
        if best is None or len(digits) > len(best):
            best = digits
    return best


def _digits_beside(glyphs, slash, right=False):
    """Characters of digit height in the slash's own row, on one side."""
    middle = slash[1] + slash[3] / 2.0
    out = []
    for s in glyphs:
        if s is slash:
            continue
        if right and s[0] < slash[0] + slash[2]:
            continue
        if not right and s[0] + s[2] > slash[0]:
            continue
        if not (HOLO_DIGIT_H_MIN * slash[3] <= s[3]
                <= HOLO_DIGIT_H_MAX * slash[3]):
            continue
        if abs((s[1] + s[3] / 2.0) - middle) > HOLO_ROW_TOL * slash[3]:
            continue
        out.append(s)
    return out


def _digits_left_of(glyphs, slash):
    """The number written left of this character, or None if there is none."""
    middle = slash[1] + slash[3] / 2.0
    digits, commas = [], []
    for s in glyphs:
        if s is slash or s[0] + s[2] > slash[0]:
            continue                       # the allowance, right of the slash
        off = (s[1] + s[3] / 2.0) - middle
        if (HOLO_DIGIT_H_MIN * slash[3] <= s[3] <= HOLO_DIGIT_H_MAX * slash[3]
                and abs(off) <= HOLO_ROW_TOL * slash[3]):
            digits.append(s)
        elif (HOLO_COMMA_H[0] * slash[3] <= s[3] <= HOLO_COMMA_H[1] * slash[3]
              and HOLO_COMMA_DROP[0] * slash[3] <= off
              <= HOLO_COMMA_DROP[1] * slash[3]):
            commas.append(s)
    if not digits:
        return None
    tallest = max(s[3] for s in digits)
    if min(s[3] for s in digits) < HOLO_DIGIT_EVEN * tallest:
        return None
    if not _spacing_holds(digits + commas):
        return None
    if not _commas_hold(digits, commas):
        return None
    return digits


def _spacing_holds(row):
    """Are the characters evenly spaced, with no hole where one is missing?"""
    row = sorted(row, key=lambda s: s[0])
    width = sorted(s[2] for s in row)[len(row) // 2]
    for before, now in zip(row, row[1:]):
        if now[0] - (before[0] + before[2]) > HOLO_GAP_MAX * width:
            return False
    return True


def _commas_hold(digits, commas):
    """Three digits after every comma, and a comma for every thousand."""
    digits = sorted(digits, key=lambda s: s[0])
    if not commas:
        return len(digits) <= HOLO_GROUP
    edges = sorted(c[0] for c in commas)
    groups = []
    rest = digits
    for edge in edges:
        groups.append([s for s in rest if s[0] < edge])
        rest = [s for s in rest if s[0] > edge]
    groups.append(rest)
    if not all(groups):
        return False
    if not 1 <= len(groups[0]) <= HOLO_GROUP:
        return False
    return all(len(g) == HOLO_GROUP for g in groups[1:])


# ----------------------------------------------------------------------------
# The bot
# ----------------------------------------------------------------------------
# How fast Auto Spend spends: one activation every 3 to 4 seconds, taking 1 to
# 20 tickets depending on what the player set in the device. So a counter that
# has not moved for STALL_AFTER seconds has missed five activations at worst,
# and the button is off.
#
# The other way round matters too: the game switches Auto Spend off by itself
# once the tickets are gone. A counter standing at zero is therefore not a
# button to press, it is a day's work finished, and pressing at that point
# would only toggle an empty device on and off.
# How often to look. Two seconds, because the bubble does not wait: the
# character can die with it up and take it along, and a round missed is a
# token missed.
#
# Measured, per round on a 765 x 1390 frame:
#
#   the whole round, every reader in it        7 ms
#   of which the Partner window's button pair  5 ms
#   window capture, the frame itself          24 ms
#   ADB capture, the frame itself            380 to 450 ms
#
# So on window frames a round costs about 31 ms and this asks for 1.5 % of
# one core. On ADB the frame is the whole cost and it comes to a fifth of
# the time -- still fine while nothing else is playing, which is the only
# time this runs at all.
TICK = 2.0
STALL_AFTER = 20.0
# After a press the counter answers within 3 to 5 seconds, so this is when to
# look, not a guess at how long the game needs.
PRESS_CHECK = 5.0
# A press that changed nothing gets another go, but not at once. The button is
# a toggle: if the press did switch Auto Spend on and the tickets are simply
# empty, hammering it would leave it in whichever state the last tap chose.
# Growing gaps, and the check after every press is what makes even a wrong
# press self-correcting -- it is seen and taken back one round later.
PRESS_GAPS = (15.0, 30.0, 60.0)
# Tapped on the first sighting, not confirmed over two frames. That is the
# opposite of what this program does everywhere else, and the reason is the
# player's: the character can die while the bubble is up, and the bubble
# goes with it. A second frame costs five seconds and loses tokens. What
# makes it affordable here is that a wrong tap is cheap -- it opens the
# Partner window, which the next round knows to be the helper's own and
# closes again.
#
# After a tap on the figure, how long to leave the bubble alone before
# tapping again. The game needs a moment to take the token and clear the
# bubble -- measured once at under five seconds -- and at a two second pace
# the next round would otherwise tap a token that is already collected,
# which opens the info window for nothing.
BOND_RETRY = 4.0
# How often a tap is repeated while the bubble is still there. If three have
# not made it go away, something is wrong with the aim and more will not fix
# it.
BOND_TRIES = 3
# When the screen cannot be read, keep a picture of what was there instead.
# A helper that runs all day cannot be watched, so the one thing it can do
# for a player who reports "it does nothing" is show them what it was
# looking at. Rate limited hard: this is a diagnosis, not a habit, and every
# one of these files is a picture of the game screen -- the folder is in
# .gitignore for that reason.
DUMP_DIR = "debug_passive"
DUMP_MAX = 5
DUMP_EVERY = 300.0
# How long the counter may be unreadable on a clear screen before a frame is
# kept. Long enough that the XP numbers rising off the device, which cover
# the digits for a few seconds at a time, never trigger it.
BLIND_AFTER = 60.0

# A line a minute on a screen where nothing is happening, and on a screen
# where something is in the way. Both matter: a log that says one thing and
# then goes silent for twenty minutes cannot be told from a log that stopped,
# and that is exactly how the red-background bug looked in the window.
HEARTBEAT = 60.0


class PassiveBot:
    """Reads the main screen and does the two small jobs on it.

    It borrows a DungeonBot for tapping, the back key and press_auto rather
    than growing its own: those carry the guards that were measured against
    real frames, and there must not be two versions of them.
    """

    def __init__(self, cap, log=print, dry_run=False, do_bond=True,
                 do_auto=True, verbose=False, now=time.time):
        self.cap = cap
        self.log = log
        self.dry_run = dry_run
        self.do_bond = do_bond
        self.do_auto = do_auto
        self.verbose = verbose
        self.now = now
        self.bot = D.DungeonBot(cap, dry_run=dry_run, log=self._quiet)
        # Auto Spend, as seen from outside: "unknown" until two readings
        # exist, then "running" or "stalled".
        self.auto_state = "unknown"
        self.last_value = None
        self.last_change = None
        self.presses = 0
        self.next_press = 0.0
        # A bubble that survives its taps is given up on until it goes.
        self.bond_tries = 0
        self.next_bond = 0.0
        self.partner_tries = 0
        # When the helper last tapped the figure, which is the only way it
        # can open a Partner window at all. See PARTNER_OWN.
        self.opened_partner = 0.0
        self.last_heartbeat = 0.0
        self.said = None
        self._dumps = 0
        self._next_dump = 0.0
        # When the counter first went unreadable while the screen was clear.
        # A number that cannot be read for a minute on a screen that is
        # plainly the right one is a bug in the reading, and the only way to
        # look into it afterwards is to have kept the picture.
        self._blind_since = None
        # Set from outside, once per round. False means read and log but
        # touch nothing -- which is what a tap through the real mouse has to
        # do while somebody's hand is on that mouse.
        self.may_tap = True

    # -- logging -------------------------------------------------------
    def _quiet(self, text):
        """The borrowed DungeonBot's own log, kept for the verbose mode."""
        if self.verbose:
            self.log(text)

    def _once(self, key, text):
        """Say this only when it is not what was said last time.

        A passive bot ticks all day. "another bot is running" belongs in the
        log the first time and not four hundred times after it.
        """
        if self.said != key:
            self.said = key
            self.log(text)

    def _say(self, text):
        self.said = None
        self.log(text)

    # -- the screen ----------------------------------------------------
    def screen_is_clear(self, img):
        """Is the plain main screen in front, with nothing drawn over it?

        The auto button answers this. The game dims what is behind a dialog
        and a dimmed disc loses its edges out of the colour mask, so a button
        found at full roundness is proof of both things at once: the screen
        is clear, and here is where to tap it. Measured 0.72 fill on a clear
        screen against 0.43 with a dialog over it.

        popup_ok is deliberately not asked. It answers True on a perfectly
        ordinary main screen -- checked on four of them -- and would veto
        every round.
        """
        return D.auto_button(img)

    def _why_not_clear(self):
        """A better sentence than "not the main screen", where there is one.

        Window capture reads the screen where the emulator sits, so another
        window in front of it becomes the frame. That is the normal state of
        affairs for a helper meant to run while the player does something
        else, and "not the plain main screen" is a useless thing to say
        about it.
        """
        ask = getattr(self.cap, "obscured", None)
        if ask is None:
            return None
        try:
            covered = ask()
        except Exception:
            covered = None
        if not covered:
            return None
        return ("another window is over the emulator. Window capture reads "
                "the screen where it sits, so the frame is a picture of "
                "whatever is in front. Leave the emulator uncovered, or "
                "switch ADB on -- over ADB it does not matter")

    def _dump(self, img, tag):
        """Keep one frame that could not be read, for a bug report."""
        if self._dumps >= DUMP_MAX or self.now() < self._next_dump:
            return
        try:
            os.makedirs(DUMP_DIR, exist_ok=True)
            # Named by the clock, not by a counter. The counter starts over
            # every time the switch is turned off and on, and the second run
            # of an evening was writing over the evidence from the first.
            path = os.path.join(DUMP_DIR, "%s_%s.png"
                                % (tag, time.strftime("%H%M%S")))
            cv2.imwrite(path, img)
            self._dumps += 1
            self._next_dump = self.now() + DUMP_EVERY
            self.log("    kept what it saw in %s" % path)
        except Exception as err:
            self.log("    could not keep the frame: %s" % err)

    # -- one round -----------------------------------------------------
    def tick(self, img=None):
        """One pass over the screen. Taps at most once.

        Never twice: the second tap would be aimed with a picture taken
        before the first one landed.
        """
        img = self.bot.grab() if img is None else img
        seen = {"clear": False, "holo": None, "bubble": None, "did": None}

        if D.stage_failed(img):
            # Any click at all dismisses this banner, so a tap meant for the
            # figure or the button would be eaten by it.
            self._once("failed", "  the Stage Failed banner is up, not "
                                 "tapping through it")
            self._heartbeat(blocked="the Stage Failed banner is up")
            return seen
        if partner_menu(img) is not None:
            return self._partner_round(seen)
        self.partner_tries = 0
        button = self.screen_is_clear(img)
        if button is None:
            why = self._why_not_clear()
            self._once("busy", "  not the plain main screen, nothing done "
                               "this round" + (": " + why if why else ""))
            if why is None:
                self._dump(img, "unclear")
            self._heartbeat(blocked=why or "not the plain main screen")
            return seen
        seen["clear"] = True

        # Read it whatever the options say. The counter is what the player
        # came to this page to see, and it was tied to the Auto Spend box
        # for no better reason than that pressing the button needs it: with
        # the box off every round reported a counter it had never looked at,
        # on a screen where the number was plainly drawn.
        value = holo_counter(img)
        seen["holo"] = value
        self._note_counter(value, img)

        if self.do_bond:
            bubble = bond_bubble(img)
            seen["bubble"] = bubble
            if self._bond_round(bubble):
                seen["did"] = "collected the bond token"
                return seen

        if self.do_auto and self._auto_round(button, value):
            seen["did"] = "pressed auto spend"
            return seen

        self._heartbeat(value, seen["bubble"])
        return seen

    def _partner_round(self, seen):
        """A Partner window is up. Close it if this helper opened it.

        Whose it is decides everything here. The helper's own is the price
        of tapping a bubble off a single frame -- it opens when the token
        was collected a moment earlier -- and leaving it there stops the
        helper for the rest of the day. The player's own is theirs, and a
        helper that closes windows out from under somebody using the game is
        worse than one that does nothing at all.
        """
        if self.now() - self.opened_partner > PARTNER_OWN:
            self._once("theirs", "  a window is open that this did not open, "
                                 "leaving it alone")
            self._heartbeat(blocked="a window is open that this did not open")
            return seen
        if not self.may_tap:
            self._once("hands", "  the Partner window is open, but the "
                                "mouse is in use, leaving it")
            self._heartbeat(blocked="the Partner window is open and the "
                                    "mouse is in use")
            return seen
        self.partner_tries += 1
        if self.partner_tries <= PARTNER_TAPS:
            self._say("  the Partner window is open, tapping above it")
            self.bot.tap(PARTNER_CLOSE[0], PARTNER_CLOSE[1],
                         was="beside the Partner window")
        else:
            self._say("  the Partner window will not go, using the back key")
            self.bot.back()
        seen["did"] = "closed the partner window"
        return seen

    # -- the counter ---------------------------------------------------
    def _note_counter(self, value, img=None):
        """Remember what the counter says, and say what changed."""
        now = self.now()
        if value is None:
            if self.verbose:
                self.log("  holograms could not be read this round")
            if self._blind_since is None:
                self._blind_since = now
            elif now - self._blind_since >= BLIND_AFTER and img is not None:
                self._say("  the counter has not been readable for %.0f s on "
                          "a screen that looks right" % (now - self._blind_since))
                self._dump(img, "counter")
                self._blind_since = now
            return
        self._blind_since = None
        if self.last_value is None:
            self.last_value = value
            self.last_change = now
            self._say("  holograms %s, first reading" % _num(value))
            return
        if value != self.last_value:
            fell = self.last_value - value
            span = now - (self.last_change or now)
            self._say("  holograms %s (%+d in %.0f s)%s"
                      % (_num(value), -fell, span,
                         ", auto spend is running" if self.do_auto else ""))
            self.last_value = value
            self.last_change = now
            self.auto_state = "running"
            self.presses = 0
            self.next_press = 0.0
        elif self.verbose:
            self.log("  holograms %s, unchanged" % _num(value))

    def _auto_round(self, button, value):
        """Press the auto button if the counter says it is not running.

        `value` is what this round read, and None means it read nothing. A
        round that could not read the counter must not press: it has no
        evidence either way, and treating it as "unchanged" is how a live
        run came to press twice while Auto Spend was working perfectly. The
        XP numbers rising off the device cover the digits for a few seconds
        at a time, and the stall would then be nothing but that animation.

        Returns True if a press went out.

        The press is made here rather than through DungeonBot.press_auto,
        which is the same tap with different guards. One of those guards is
        popup_ok, and popup_ok answers yes on an ordinary main screen: it
        looks for a wide blue button low down and near the middle, and that
        is also LDPlayer-sized description of the game's own bottom bar.
        Measured over every frame in the collection, six hits, all of them
        the bar at the full width of the window and not one of them a
        pop-up. Routed through there this would have refused to press, round
        after round, and said so in a way nobody could act on.

        What is left is not weaker. tick() has already established that the
        auto button is drawn sharply, which no dialog allows, and that the
        red banner is not up, which is the other thing that eats a tap.
        """
        now = self.now()
        if value is None or self.last_value is None:
            return False
        if self.last_value == 0:
            # The game switches Auto Spend off by itself when the tickets run
            # out. Nothing to press for, and a press here would only toggle
            # an empty device.
            self._once("empty", "  no hologram tickets left, auto spend has "
                                "nothing to do")
            return False
        if now - (self.last_change or now) < STALL_AFTER:
            return False
        if self.auto_state != "stalled":
            self.auto_state = "stalled"
            self._say("  holograms %s, unchanged for %.0f s"
                      % (_num(self.last_value), now - self.last_change))
        if now < self.next_press:
            return False
        if not self.may_tap:
            self._once("hands", "  auto spend looks off, but the mouse is "
                                "in use, not pressing")
            return False
        self._say("  auto spend looks off, pressing the button")
        self.bot.tap(button["fx"], button["fy"], was="auto spend")
        gap = PRESS_GAPS[min(self.presses, len(PRESS_GAPS) - 1)]
        self.presses += 1
        # Look again once the game has had its 3 to 5 seconds, and do not
        # press again before the gap is up.
        self.next_press = now + max(gap, PRESS_CHECK)
        self.last_change = now
        return True

    # -- the token -----------------------------------------------------
    def _bond_round(self, bubble):
        """Tap the figure the bubble belongs to. True if tapped.

        No waiting for a second frame: see BOND_TRIES. The counter of tries
        is not tied to where the bubble was, because it drifts a little from
        frame to frame -- it counts rounds in which one was up, and clears
        the moment none is.
        """
        if bubble is None:
            if self.bond_tries:
                self._say("    bubble gone, token collected")
            self.bond_tries = 0
            return False
        if self.bond_tries >= BOND_TRIES:
            self._once("stuck", "  the bubble is still there after %d taps, "
                                "leaving it alone until it goes" % BOND_TRIES)
            return False
        if self.now() < self.next_bond:
            return False
        if not self.may_tap:
            self._once("hands", "  a bubble is up, but the mouse is in use, "
                                "not tapping the figure")
            return False
        target = figure_from_bubble(bubble)
        if target is None:
            aim = aim_at_figure(bubble)
            if on_chat_row(*aim):
                # The figure is standing behind the chat line. Nothing to be
                # done about it this round and nothing to be gained by
                # aiming somewhere else: the token waits, the figure moves,
                # and the chat window stays shut.
                self._once("chatrow", "  bubble at %.3f/%.3f, but the figure "
                                      "is behind the chat line, not tapping "
                                      "-- that would open the chat"
                                      % (bubble["fx"], bubble["fy"]))
            else:
                self._once("offfield", "  bubble at %.3f/%.3f, but the figure "
                                       "would be off the field, not tapping"
                                       % (bubble["fx"], bubble["fy"]))
            return False
        self.bond_tries += 1
        self.next_bond = self.now() + BOND_RETRY
        self._say("  bond bubble at %.3f/%.3f, tapping the figure at "
                  "%.3f/%.3f" % (bubble["fx"], bubble["fy"],
                                 target[0], target[1]))
        self.bot.tap(target[0], target[1], was="the partner figure")
        # From here the helper owns whatever window this opens, for as long
        # as PARTNER_OWN says and no longer.
        self.opened_partner = self.now()
        return True

    # -- the quiet rounds ----------------------------------------------
    def _heartbeat(self, value=None, bubble=None, blocked=None):
        """One line a minute, whether or not anything is happening.

        `blocked` is for the rounds that end early. Those say their reason
        once and then fall silent, which is right for a log that runs all
        day and wrong for anyone trying to tell a waiting helper from a dead
        one -- so the reason comes round again every minute.
        """
        now = self.now()
        if now - self.last_heartbeat < HEARTBEAT:
            return
        self.last_heartbeat = now
        if blocked:
            self.log("  still watching, nothing done: %s" % blocked)
            return
        self.log("  still watching: holograms %s, %s, %s"
                 % (_num(value) if value is not None else "unreadable",
                    self._auto_words(),
                    "a bubble is up" if bubble else "no bubble"))

    def _auto_words(self):
        """How this round would describe Auto Spend.

        "not judged yet" is a promise that a judgement is coming, and with
        the box off none ever is: nothing calls _auto_round, so auto_state
        never leaves "unknown". Saying so beats a line that looks like a
        helper still making up its mind.
        """
        if not self.do_auto:
            return "auto spend not watched"
        return {"running": "auto spend running",
                "stalled": "auto spend looks off",
                "unknown": "auto spend not judged yet"}[self.auto_state]

    def status(self):
        """One line for the window, not for the log."""
        if self.last_value is None:
            return "watching, no counter read yet"
        return "watching -- holograms %s, %s" % (_num(self.last_value),
                                                 self._auto_words())


def _num(value):
    """77605 as 77,605, the way the game writes it."""
    return "{:,}".format(value)


# ----------------------------------------------------------------------------
def probe(cap, log=print, rounds=0, dry_run=True):
    """Watch and say what is seen, clicking nothing.

    py passive.py --probe
    """
    bot = PassiveBot(cap, log=log, dry_run=dry_run, verbose=True)
    log("passive helper, %s" % ("dry run, nothing is clicked" if dry_run
                                else "live"))
    n = 0
    while not rounds or n < rounds:
        n += 1
        bot.tick()
        time.sleep(TICK)


def main():
    import argparse
    import capture
    import userdata

    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="watch and log, click nothing")
    ap.add_argument("--go", action="store_true", help="really tap")
    ap.add_argument("--rounds", type=int, default=0)
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames and clicks via adb or via the window and "
                         "mouse. Default: the stored switch (Helpermon's "
                         "window, or DGUP_ADB_MODE)")
    args = ap.parse_args()

    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)
    probe(cap, rounds=args.rounds, dry_run=not args.go)


if __name__ == "__main__":
    main()
