"""
Skewer bot. Cooking minigame: read the order, build the same skewer, submit.

A third bot, same family as dungeon.py rather than the board minigame: no
scrolling world, no pathfinding, just "recognise the screen, do exactly one
action, verify, repeat" against a fixed layout. See dungeon.py's own module
docstring for the same idea applied to the dungeon list.

Loop, once an order is showing
  1. Read the order strip and confirm it is the SAME on two consecutive
     frames, so a half-drawn order is never acted on.
  2. Click that order's ingredients in turn on the 4x3 grid, counting the
     clicks rather than re-reading the plate.
  3. Abandon and start over if the order changes underneath.
  4. Once as many clicks went out as the order is long, click Complete and
     wait for a different order to appear.

Repeat until the round timer runs out or the "Failed..." dialog / the
gameplay screen itself disappears.

Ingredient icons are not shipped with the program, same policy as the rest
of this project. Learn them from your own screen first:

  py learn_skewer.py              learn the 12 grid icons once
  py skewer.py --probe            shows what is recognised, clicks nothing
                                   (saves to debug_skewer/<timestamp>/,
                                    add --tag NAME to label the run)
  py skewer.py                    dry run, plans but does NOT click
  py skewer.py --go               actually clicks
  py skewer.py --go --rounds 3
  py skewer.py --go --speed 1.1   same, but 10% less waiting between
                                   clicks -- the dial to chase a score
                                   with, raise it gradually
  py skewer.py --go --no-complete debug: build one order, hold before
                                   Complete, then --probe it in another
                                   terminal

Two different recognition strategies are in use, deliberately.

The 4x3 grid is fixed and unscaled, so it is matched at fixed positions by
straight template correlation -- see GRID_COLS_FX/GRID_ROWS_FY. This part
is solid, matches come back 0.9-1.0 against real templates.

The order strip and the plate have neither fixed icon count, nor fixed
spacing, nor even fixed positions -- a short order leaves its ingredients
spread apart along the stick, a long one packs them until they overlap --
so nothing positional works there. They are read in two stages instead:
find the ingredients geometrically, then name each by argmax over all
twelve -- see find_strip_icons and the SKEWER_* comment above it. No match
threshold is involved anywhere in that path, which is the point: the two
earlier threshold-based versions each dropped real ingredients that scored
a hundredth under the cutoff.
"""

import argparse
import os
import time

import cv2
import numpy as np

import capture
import guard
import userdata
from dungeon import game_rect, to_pixel

# ----------------------------------------------------------------------------
# States. Per-frame and stateless, like dungeon.recognise() -- multi-frame
# judgement calls (has this really settled? has the round really ended?)
# live in SkewerBot, not here.
ORDER_VISIBLE = "order_visible"
MISMATCH = "mismatch"
COMPLETE_READY = "complete_ready"
UNKNOWN = "unknown"
# Not a recognise() state, only used as SkewerBot.play_round()'s stop reason.
ROUND_OVER = "round_over"
# solve_current_order()'s return value when --no-complete stops it right
# after the last ingredient instead of clicking Complete.
ORDER_HELD = "order_held"

# ----------------------------------------------------------------------------
# UNCALIBRATED. Guessed from one described screenshot, not measured. Every
# number here needs a --probe round-trip against the real window before it
# can be trusted. All rects are (fx, fy, fw, fh), fx/fy the CENTRE, matching
# the {"fx","fy","fw","fh"} convention dungeon.py already uses for buttons.

POS_LIVES = (0.16, 0.075, 0.20, 0.04)
POS_SCORE = (0.50, 0.045, 0.35, 0.05)
POS_TIMER = (0.50, 0.115, 0.40, 0.03)
POS_ORDER_STRIP = (0.50, 0.26, 0.85, 0.09)
POS_PORTRAITS = (0.50, 0.40, 0.90, 0.16)
POS_COMPLETE = (0.81, 0.55, 0.22, 0.09)

# "Failed..." round-over dialog (Current Record / Best Record / Close).
# Measured against a real, cleanly captured dialog crop (game-area-relative
# fx/fy/fw/fh 0.514/0.503/0.665/0.277, mean HSV ~108/213/110) -- taller and
# lower than the first guess. Blue share on that real crop measured 0.315,
# just under the first guess's 0.35 cutoff, which would have missed it;
# lowered with margin. Confirmed against exactly one real example so far.
POS_FAILED_DIALOG = (0.51, 0.50, 0.67, 0.28)
DIALOG_BLUE_HSV_LOW = (100, 80, 80)
DIALOG_BLUE_HSV_HIGH = (130, 255, 255)
DIALOG_BLUE_SHARE = 0.25

# Close button on the Failed dialog, and Start on the stage-select screen
# behind it (Stage 5 stays selected once chosen). Both measured live: Close
# a round, click through, confirmed Close lands back on stage-select and
# Start begins a fresh round at the same stage.
POS_DIALOG_CLOSE = (0.51, 0.615)
POS_STAGE_START = (0.50, 0.671)

# "Play Game" lantern on the main menu, cold start into the minigame. Only
# ever measured once, live, at a 579x1059 window (270, 880 in raw pixels) --
# not yet confirmed at any other window size, and unlike POS_DIALOG_CLOSE /
# POS_STAGE_START there is no round_over_dialog-style check available first
# to confirm the main menu is actually showing. Verify with --probe at the
# main menu before trusting SkewerBot.enter_from_menu() blind.
POS_MENU_PLAY_GAME = (0.466, 0.831)

# Third draft, and a real architecture change, not just a position tweak.
# Fixed evenly-spaced slots (first two drafts) cannot work here: a real
# 3-icon order and a real 4-icon order had their icons at visibly different,
# more tightly packed positions -- the game spaces/centres icons based on
# how many there are, so no fixed grid of slot positions fits every order
# length. Icons are found by sliding each learned template across the whole
# strip instead (see find_strip_icons below), the way cv2.matchTemplate is
# meant to be used for "is this somewhere in a wider image", rather than by
# assuming where they are.
#
# The current/plate strip is the same idea, over the plate area instead --
# still completely unverified, the plate has been empty in every real
# capture so far.
# Re-measured against the first real capture of a NON-empty plate (five
# ingredients on it). The previous guess sat too low and too wide: its top
# edge cut through the icons about a third of the way down, and its right
# edge reached into the Complete button. Icons measured at x 244..523,
# y 720..819 in a 765x1390 window; this box adds margin for the plate rim
# while stopping short of the button dome at x~550.
POS_CURRENT_STRIP = (0.495, 0.544, 0.422, 0.115)
# Single click point to undo the last ingredient, roughly the plate centre.
POS_PLATE_CLICK = (0.47, 0.575)

# --- Reading a skewer (the order strip, and the plate) ----------------------
# Third architecture for this, and the first one that is not built on an
# absolute match threshold. The two earlier ones slid ingredient templates
# across the strip and kept every peak above STRIP_ICON_THRESHOLD (0.80).
# Both failed the same way: measured against a real 5-icon order, the five
# correct icons scored 0.87 / 0.80 / 0.93 / 0.80 / 0.86 -- two of them sat
# exactly ON the cutoff. An icon that dips a hundredth under is silently
# dropped rather than reported, which is precisely the "an ingredient got
# skipped" bug seen live. Lowering the cutoff was not a fix either: at a
# neighbouring window size a phantom `tuna` scored 0.82, i.e. above it.
# Threshold-based reading trades dropped icons against invented ones, and
# there is no setting where it does neither.
#
# So: find the icons GEOMETRICALLY first, then name each one by argmax over
# all twelve candidates. argmax cannot drop an icon (something is always the
# best match) and cannot invent one (positions come from pixels, not scores).
# Absolute scores stop mattering; only the ranking does.
#
# Step 1, the run. Inside the white speech bubble (order) or white plate
# (current), a column carrying an icon has visibly more non-background pixel
# height than a column carrying only the bare wooden stick. Measured on a
# real 5-icon capture: bare stick 17-23 px, icon columns 24-55 px, no
# overlap. Deliberately NOT the black outline between icons, which was tried
# first and does not work -- pale ingredients (onion, shrimp) have such thin
# outlines that they read the same as the stick, and dark ones (dark_meat)
# are dark right through their middle so the seams vanish.
# The container the skewer lies on. Measured on a real frame: bubble and
# plate are near-grey (saturation 0-3), while even the palest ingredient
# measured 88, so saturation separates them cleanly where brightness does
# not (that ingredient is brighter than the plate it sits on).
CONTAINER_MAX_SAT = 60
CONTAINER_MIN_VALUE = 150
CONTAINER_PIECE_SHARE = 0.15  # keep container pieces this big, vs. the biggest
#
# The background level is measured per container, never assumed: the speech
# bubble is pure white (255 throughout), while the plate only reaches 236 and
# sits around 223 -- one fixed cutoff cannot serve both, and a bubble-tuned
# 245 made every plate pixel count as content, which read as "no icons here".
SKEWER_BG_PERCENTILE = 90    # brightness inside the container that counts as bare
SKEWER_BG_MARGIN = 0.06      # how much darker than that a pixel must be to be content
SKEWER_RUN_FLOOR = 0.40      # ingredient column, as a share of the tallest one
SKEWER_CLUSTER_GAP = 4       # bare-stick columns that separate two clusters
SKEWER_MIN_ICON_PX = 6       # narrower than this is noise, not an ingredient
SKEWER_MIN_ICON_SHARE = 0.30  # tallest column, as a share of the crop, for "not bare"
#
# Step 2, the icons. Icon count is NOT derived up front -- ordering by
# length and spacing both change with the order, and every attempt to
# recover N geometrically was fragile (equal-slot scoring picks the wrong N;
# silhouette-valley detection over-splits; autocorrelation puts the period
# at 37 px where the true spacing is 34). Instead a narrow window is slid
# across the run and classified at every step, and consecutive identical
# readings are grouped. Each group is one icon, and a group about twice the
# median width is two of the same ingredient in a row. On the real 5-icon
# capture the groups came out clean and well separated (7/6/8/6/9 samples,
# spans 24/20/28/20/32 px) and collapsed to exactly the right order.
SKEWER_WINDOW_OF_ICON = 0.70  # naming window, as a fraction of one ingredient
SKEWER_SINGLE_CLUSTER_FH = 1.2  # cluster this wide, vs band height, holds one item
SKEWER_COUNT_WINDOW_FH = 0.45  # counting window, as a fraction of band height
SKEWER_SLIDE_STEPS = 30       # samples across one cluster when counting
#
# Icon pitch along the skewer, as a fraction of the strip crop's width.
# Measured across seven real captures once the wooden stick is subtracted
# from the run: run width came out 181-188 px in a 650 px crop for five
# ingredients, i.e. a pitch of 36-38 px, and dividing by 37 recovers "5" on
# every one of them (5.0, 5.0, 5.0, 5.1, 4.9, 5.0, 4.9).
#
# ASSUMPTION, and the weakest thing in this file: all seven of those
# captures are FIVE-ingredient orders, so whether the pitch stays put for
# other lengths is untested. The two possibilities are not distinguishable
# from the data at hand -- either the game keeps icons the same size and
# lengthens the skewer (pitch fixed, this is right), or it keeps the skewer
# the same length and shrinks the icons (pitch shrinks, and this reads a
# long order as a five). A note from an earlier session, comparing a 3-icon
# against a 4-icon order, leans toward the second. Verify with a --probe of
# a clearly shorter and a clearly longer order before trusting this.
#
# Counting by classification instead was tried and is worse: it needs each
# ingredient to form its own run of identical readings, and measured over
# the same seven captures it got the count right on only four -- an
# ingredient that reads like its neighbour merges away, and one that reads
# unstably splits in two.

# 4x3 ingredient grid, bottom third. Best-guess names from the screenshot,
# meant to be corrected in learn_skewer.py or the wizard's Skewer step --
# pink_item/brown_item in particular are placeholders, not real names.
#
# KNOWN, measured over 13 real captures: these rows are about 9 thousandths
# too low. The icon sits hard against the TOP edge of its crop (median top
# margin 0.0 px) with ~22 px of dead space below it, so tall icons are
# clipped and every template carries ~6% less of its ingredient than it
# could. Shifting GRID_ROWS_FY by -0.009, to (0.664, 0.771, 0.878), balances
# the margins to 1.0/11.5 px.
#
# Deliberately NOT applied. The fractions are baked into every learned
# template, so changing them means relearning all twelve icons and redoing
# the strip verification -- against a setup that currently measures 0.92-0.99
# in the grid and 42/42 on the strip. Change it when the templates are being
# relearned anyway, not before.
#
# Whether the crop should also be TALLER is untested: measuring that needs an
# oversized crop, and at anything near the row pitch (0.107) the icon blob
# merges with the neighbouring row, so the measurement contradicts itself.
GRID_COLS_FX = (0.21, 0.40, 0.60, 0.80)
GRID_ROWS_FY = (0.673, 0.780, 0.887)
GRID_CELL_FW, GRID_CELL_FH = 0.16, 0.08
INGREDIENT_NAMES = [
    "raw_meat", "dark_meat", "shrimp", "egg",
    "leaf_wrap", "fish_cake", "corn", "tomato",
    "radish", "pink_item", "brown_item", "onion",
]

# Every icon crop (order slot, current slot, grid cell) is resized to this
# before matching, so there is no cell_w-ratio rescaling to solve the way
# vision.py does for the scrolling board -- valid as long as the window
# is not resized between learning and playing.
REF_ICON_SIZE = (64, 64)

# Starting points only, borrowed from vision.DEFAULT_THRESHOLD for the same
# "match one of N small icons" problem shape. Need their own measurement.
ICON_THRESHOLD = 0.62
ICON_MIN_MARGIN = 0.05

# How many consecutive gameplay-UI-absent reads before SkewerBot.play_round
# declares the round over, instead of treating it as the ~1-2 s gap between
# orders. Pure guess, no screenshot evidence of either transition yet.
ROUND_OVER_ABSENT_READS = 3

# Red-symbol-around-the-character heuristic for a wrong/late submission.
# Logging only in v1, does not stop the bot by itself (see module docstring
# on why round-over is detected by the dialog/UI-absence instead of a
# mistake count). Measured against a real portraits.png crop with NO mistake
# showing, the warm restaurant background alone already scored 0.071-0.081
# red share -- the 0.08 first guess was sitting right on top of that noise
# floor. Raised well above it; still unverified against an actual mistake.
MISTAKE_RED_SHARE = 0.16

# Bounds on --speed. The lower one keeps the dial from stalling the bot
# entirely; the upper one, together with MIN_TICK, keeps it from turning
# into a machine gun that taps faster than the emulator can redraw. MIN_TICK
# is a floor and not a target: one frame of recognition costs ~21 ms, so
# anything below about 40 ms per click means clicking on a screen this
# program has not actually looked at yet.
MIN_SPEED, MAX_SPEED = 0.25, 4.0
MIN_TICK = 0.04


# ----------------------------------------------------------------------------
def crop_rel(img, fx, fy, fw, fh):
    """Crop of the game area, fx/fy the centre, fw/fh the size, all relative."""
    x0, y0, gw, gh = game_rect(img)
    cx, cy = to_pixel(img, fx, fy)
    w, h = int(round(fw * gw)), int(round(fh * gh))
    x, y = cx - w // 2, cy - h // 2
    return img[max(0, y):y + h, max(0, x):x + w]


# ----------------------------------------------------------------------------
# Templates. Own small store, separate from vision.py's, because there is no
# board/cell_w scaling concept here -- just fixed on-screen icon crops
# normalised to one reference size.
#
# ONE style is learned, the clean grid-button crop, and it serves both the
# grid and the skewers. There used to be a second, separately learned
# "strip" set (skewerstrip_*.png) on the theory that an icon on a skewer is
# too unlike its grid-button self to match. That set is gone: its templates
# were hand-cropped in learn_skewer.py and, looked at directly, turned out
# to frame only the TOP HALF of each icon plus a slice of speech-bubble
# border and background -- which is a large part of why strip matching
# never scored better than ~0.8 and behaved differently on the plate (a
# different background) than in the order strip.
#
# What replaced it is not a better template but a background-independent
# comparison: a masked hue/saturation histogram (see _colour_signature).
# Pixel correlation is dominated by the background -- a grid template sits
# on a dark button, a skewer icon on a white plate, and TM_CCOEFF_NORMED
# between the two scores near zero even when it is plainly the same
# ingredient. Masking the background away and comparing colour instead
# scored the same five real icons 0.97 / 0.90 / 0.68 / 0.61 / 0.96 against
# their correct grid templates, each a clear winner over the runner-up
# (0.43 / 0.19 / 0.42 / 0.33 / 0.47) -- which is all argmax needs.
_ICON_CACHE = None
_SIGNATURE_CACHE = None


def save_ingredient_template(name, crop):
    """Save one learned ingredient icon, grid-button style. Called by
    learn_skewer.py."""
    tpl = cv2.resize(crop, REF_ICON_SIZE, interpolation=cv2.INTER_AREA)
    cv2.imwrite(userdata.template_path("skewer_" + name), tpl)
    forget_ingredient_templates()


def _load_named_templates(prefix, cache):
    if cache is not None:
        return cache
    out = {}
    directory = userdata.templates_dir(create=False)
    if os.path.isdir(directory):
        for fname in os.listdir(directory):
            if fname.startswith(prefix) and fname.endswith(".png"):
                img = cv2.imread(os.path.join(directory, fname))
                if img is not None:
                    out[fname[len(prefix):-len(".png")]] = img
    return out


def load_ingredient_templates(force=False):
    """Learned-dir grid-style templates, cached. Scans for any skewer_*.png
    rather than a fixed name list, so a name typed differently in
    learn_skewer.py is still picked up."""
    global _ICON_CACHE
    if force:
        _ICON_CACHE = None
    _ICON_CACHE = _load_named_templates("skewer_", _ICON_CACHE)
    return _ICON_CACHE


def _colour_signature(tpl, mask):
    """Masked hue/saturation/value histogram of one icon. Background-
    independent by construction, which is the whole point -- see the note
    above `_ICON_CACHE`.

    Value gets only 4 bins against hue's 24, deliberately. Brightness is the
    channel that shifts most between the lit grid button an ingredient is
    learned from and the flat bubble or plate it is read on, so it is not
    trustworthy as a primary cue -- but as a coarse tiebreaker it is exactly
    what separates the pale ingredients from each other. Measured over four
    real order captures (20 ingredients): hue+saturation alone read 19,
    losing a mushroom to shrimp on a near-tie (0.550 against 0.517); adding
    coarse value read all 20. Giving value a fine 6 bins instead drops it to
    17, so this is a narrow window, not a free improvement -- re-measure
    before widening it.
    """
    hsv = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], mask, [24, 8, 4],
                        [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()


def _grid_icon_mask(tpl):
    """Foreground of a grid-button template: the button behind the icon is
    dark and grey, the ingredient is either brighter or actually coloured.
    Both tests are needed -- dark_meat is dark enough to fail the brightness
    test on its own, but it is a saturated brown, not grey."""
    gray = cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV)[:, :, 1]
    return ((gray > 60) | (sat > 70)).astype(np.uint8)


def _skewer_icon_mask(sub):
    """Foreground of an icon cut out of a skewer: everything darker than the
    bright bubble or plate behind it. The background cutoff comes from this
    crop's own brightest pixels rather than a fixed number, because bubble
    white (255) and plate white (~223) differ.

    The wooden stick is deliberately NOT subtracted, although it does cross
    every icon. Subtracting it by colour was tried and is actively harmful:
    measured on a real capture, the bare stick sits at hue 16 / sat 104 /
    grey 170, and the pale ingredients sit right on top of it -- mushroom
    18 / 99 / 208, egg 17 / 62 / 212, onion 16 / 131 / 181. A rule tight
    enough to catch the stick removed 78% of a real mushroom and 58% of a
    real egg, gutting exactly the ingredients that were already hardest to
    tell apart. The stick is separated by HEIGHT instead, where the margin
    is large and unambiguous -- see SKEWER_RUN_FLOOR.
    """
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    background = float(np.percentile(gray, 97))
    return (gray < background * (1.0 - SKEWER_BG_MARGIN)).astype(np.uint8)


def load_icon_signatures(force=False):
    """Colour signature per ingredient, derived from the grid templates and
    cached alongside them."""
    global _SIGNATURE_CACHE
    if force:
        _SIGNATURE_CACHE = None
    if _SIGNATURE_CACHE is None:
        _SIGNATURE_CACHE = {
            name: _colour_signature(tpl, _grid_icon_mask(tpl))
            for name, tpl in load_ingredient_templates(force).items()}
    return _SIGNATURE_CACHE


def forget_ingredient_templates():
    global _ICON_CACHE, _SIGNATURE_CACHE
    _SIGNATURE_CACHE = None
    _ICON_CACHE = None


def match_icon(crop, templates):
    """Best matching ingredient name for one crop, or None if nothing scores
    above threshold with a clear margin over the runner-up. Never guessed."""
    if crop is None or crop.size == 0 or not templates:
        return None, 0.0
    probe = cv2.resize(crop, REF_ICON_SIZE, interpolation=cv2.INTER_AREA)
    scores = sorted(
        ((float(cv2.matchTemplate(probe, tpl, cv2.TM_CCOEFF_NORMED).max()), name)
         for name, tpl in templates.items()),
        reverse=True)
    best_val, best_name = scores[0]
    second_val = scores[1][0] if len(scores) > 1 else -1.0
    if best_val < ICON_THRESHOLD or best_val - second_val < ICON_MIN_MARGIN:
        return None, best_val
    return best_name, best_val


def _bright_container(crop):
    """Mask of the speech bubble (order strip) or the plate (current strip)
    inside a crop, with whatever the skewer covers filled back in.

    Everything else keys off this. Without it the vertical measurement runs
    straight past the container into the background -- which is not
    background-coloured, so it reads as content and stretches the icon band
    to the full crop height, leaving the slide window far too wide to
    resolve single icons.

    Found by LOW SATURATION rather than by brightness. Brightness alone does
    not separate the two: the palest ingredients (onion, egg) are bright
    enough to pass any white test that the plate itself passes, so they get
    absorbed into the container and chop it into fragments -- measured, the
    plate broke into 46 pieces that way. Every ingredient is at least
    somewhat coloured though (the palest measured sat 88) while bubble and
    plate are near-grey (sat 0-3).

    The skewer still splits the container into a band above and a band
    below, so the large pieces are unioned before taking their convex hull.
    Both containers are convex, so the hull costs nothing and restores
    whatever the icons cover, however wide the run is. A morphological close
    cannot promise that -- its kernel is a fixed size, so a long order makes
    an icon run wider than the kernel can bridge and punches a hole straight
    through the container. Eroding at the end drops its own border and rim.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ch, cw = gray.shape
    bare = ((hsv[:, :, 1] < CONTAINER_MAX_SAT) & (gray > CONTAINER_MIN_VALUE)
            ).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(bare, 8)
    if count <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = 1 + np.where(areas >= areas.max() * CONTAINER_PIECE_SHARE)[0]
    points = cv2.findNonZero(np.isin(labels, keep).astype(np.uint8))
    if points is None or len(points) < 3:
        return None
    mask = np.zeros_like(bare)
    cv2.fillConvexPoly(mask, cv2.convexHull(points), 1)
    trim = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (max(3, cw // 60) | 1, max(3, ch // 12) | 1))
    return cv2.erode(mask, trim)


def _skewer_clusters(crop):
    """Where the ingredients sit inside a strip crop, as
    (y_top, y_bottom, [(x_start, x_end), ...]) -- one entry per group of
    ingredients that touch each other. None if the skewer is bare.

    Several clusters, not one run, because a short order does NOT pack its
    ingredients together: a real 2-ingredient order draws them apart with
    bare stick showing between, while a 5-ingredient one has them
    overlapping. Treating the whole thing as a single run made a 2-item
    order measure wider than a 5-item one, since the run then stretched
    from the stick's handle to its tip.

    The stick is separated from the ingredients by HEIGHT, which is a large
    and stable margin: measured across ten real captures the bare stick is
    17 px tall in every single one, while the tallest ingredient column runs
    59-71 px. Separating it by COLOUR was tried first and is a trap -- see
    _skewer_icon_mask.
    """
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ch, cw = gray.shape
    if ch < 8 or cw < 8:
        return None
    inside = _bright_container(crop)
    if inside is None:
        return None
    bare = gray[inside > 0]
    if bare.size == 0:
        return None
    background = float(np.percentile(bare, SKEWER_BG_PERCENTILE))
    # Icon pixels: meaningfully darker than the container behind them, and
    # on the container rather than on the background around it. The stick is
    # left in here and removed by height further down.
    content = ((gray < background * (1.0 - SKEWER_BG_MARGIN)) & (inside > 0))

    height = content.sum(axis=0)
    if not height.any():
        return None
    # Is there anything on the skewer at all? Without this a BARE skewer
    # reads as one ingredient: the cutoff below is a share of the tallest
    # column, and with nothing on the stick the stick itself is the tallest
    # thing there is. Measured over ten real captures the bare stick is a
    # steady 0.14 of the crop height while the tallest ingredient column
    # runs 0.48-0.58, so this gate sits in open space between them.
    if height.max() < ch * SKEWER_MIN_ICON_SHARE:
        return None
    # Ingredient columns are the tall ones. This cutoff is a share of the
    # tallest column rather than an absolute number so it survives a resized
    # window; measured, the stick sits at 0.24-0.29 of the tallest
    # ingredient column, well under it.
    tall = np.where(height > height.max() * SKEWER_RUN_FLOOR)[0]
    if tall.size == 0:
        return None

    rows = np.where(content[:, tall.min():tall.max() + 1].sum(axis=1) > 0)[0]
    if rows.size == 0:
        return None
    y_top, y_bottom = int(rows[0]), int(rows[-1]) + 1

    clusters = []
    breaks = np.where(np.diff(tall) > SKEWER_CLUSTER_GAP)[0]
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [tall.size - 1]))
    for first, last in zip(starts, ends):
        x_start, x_end = int(tall[first]), int(tall[last]) + 1
        if x_end - x_start > SKEWER_MIN_ICON_PX:
            clusters.append((x_start, x_end))
    if not clusters:
        return None
    return y_top, y_bottom, clusters


def classify_skewer_icon(sub, signatures):
    """Name for one icon cut out of a skewer, by argmax over every known
    ingredient. Returns (name, score). Never returns None for a non-empty
    crop -- picking the best of twelve is the entire point, see the
    SKEWER_* note. The score is reported so callers can log how clear the
    win was, not so they can threshold on it."""
    if sub is None or sub.size == 0 or not signatures:
        return None, 0.0
    probe = cv2.resize(sub, REF_ICON_SIZE, interpolation=cv2.INTER_AREA)
    signature = _colour_signature(probe, _skewer_icon_mask(probe))
    best_name, best_val = None, -2.0
    for name, known in signatures.items():
        val = float(cv2.compareHist(signature, known, cv2.HISTCMP_CORREL))
        if val > best_val:
            best_name, best_val = name, val
    return best_name, best_val


def _count_in_cluster(band, x_start, x_end, signatures):
    """How many ingredients are inside one touching cluster.

    Slides a window across the cluster and counts how many times the reading
    CHANGES. That works because naming is reliable once the stick is left in
    the crop (see _skewer_icon_mask) -- it was not, while the stick was being
    masked out by colour, and counting this way failed on three of seven
    captures back then. Two of the same ingredient side by side still read as
    one; no real capture has shown that case yet.
    """
    width = x_end - x_start
    # A cluster no wider than the skewer is tall holds a single ingredient,
    # and sliding over it only invites its own edges to read as neighbours.
    # The two cases are far apart in practice, so the boundary is not
    # delicate: measured over ten real captures, a lone ingredient's cluster
    # runs 0.5-0.7 of the band height, while any cluster holding more than
    # one runs 2.2 or above.
    if width < band.shape[0] * SKEWER_SINGLE_CLUSTER_FH:
        return 1
    window = max(6, int(band.shape[0] * SKEWER_COUNT_WINDOW_FH))
    if width <= window:
        return 1
    step = max(1, width // SKEWER_SLIDE_STEPS)
    seen = []
    for left in range(x_start, x_end - window + 1, step):
        name, _ = classify_skewer_icon(band[:, left:left + window], signatures)
        if name and (not seen or seen[-1] != name):
            seen.append(name)
    return max(1, len(seen))


def find_strip_icons(img, rect, signatures):
    """Ingredients on the skewer in `rect`, left to right.

    Finds the ingredients by geometry and names each by argmax -- see the
    SKEWER_* comment block for why this is not a threshold search, and what
    measured failure it replaces. A bare skewer reads as [], which is what
    the plate shows before the first ingredient goes on.

    Measured against ten real order captures covering 2-, 3- and
    5-ingredient orders, 42 ingredients in total: counts 10/10, names 42/42.

    Both halves of that came from removing a single wrong idea, not from
    tuning. While the wooden stick was being masked out by colour, it took
    58-78% of the pale ingredients with it (they are the same hue); naming
    then failed on every `egg`, and counting failed on three captures
    because the sliding read could not tell one ingredient from the next.
    Leaving the stick in the crop and separating it by height instead fixed
    both at once.

    Still untested against real pixels: an order holding the same
    ingredient twice SIDE BY SIDE. _count_in_cluster counts changes in the
    sliding read, so such a pair reads as one. No capture has shown that
    case (110400 repeats raw_meat, but with tuna between them, and reads
    correctly).

    The PLATE is read by the same code and is less reliable there -- it
    tends to lose the leftmost ingredient, because the plate is an oval and
    near its ends there is much less of it above and below the stick. The
    bot does not use the plate reading (see solve_current_order), so this is
    a known gap rather than a live problem.
    """
    crop = crop_rel(img, *rect)
    if crop is None or crop.size == 0 or not signatures:
        return []
    found = _skewer_clusters(crop)
    if found is None:
        return []
    y_top, y_bottom, clusters = found
    band = crop[y_top:y_bottom, :]

    out = []
    for x_start, x_end in clusters:
        count = _count_in_cluster(band, x_start, x_end, signatures)
        # Each ingredient is then named once, from a window centred on its
        # own share of the cluster, so no neighbour dominates the crop.
        spacing = (x_end - x_start) / float(count)
        window = max(6, int(spacing * SKEWER_WINDOW_OF_ICON))
        for i in range(count):
            centre = x_start + int(spacing * (i + 0.5))
            left = max(x_start, min(centre - window // 2, x_end - window))
            name, _ = classify_skewer_icon(band[:, left:left + window], signatures)
            if name:
                out.append(name)
    return out


def _read_mistake_flash(img):
    """Cheap colour heuristic for the red symbols near the character on a
    wrong/late submission. HSV numbers are returned raw so they can be
    read off during a --probe run and the threshold tuned from real data."""
    crop = crop_rel(img, *POS_PORTRAITS)
    if crop is None or crop.size == 0:
        return False, (0.0, 0.0, 0.0), 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    red = (cv2.inRange(hsv, (0, 120, 90), (10, 255, 255))
           | cv2.inRange(hsv, (170, 120, 90), (179, 255, 255)))
    red_share = float((red > 0).mean())
    mean_hsv = (float(hsv[:, :, 0].mean()), float(hsv[:, :, 1].mean()),
                float(hsv[:, :, 2].mean()))
    return red_share > MISTAKE_RED_SHARE, mean_hsv, red_share


def _read_failed_dialog(img):
    """Rough colour check for the 'Failed...' round-over dialog. Seen once
    in a real screenshot, not yet confirmed against a live probe crop of
    the dialog itself -- see POS_FAILED_DIALOG."""
    crop = crop_rel(img, *POS_FAILED_DIALOG)
    if crop is None or crop.size == 0:
        return False, 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, DIALOG_BLUE_HSV_LOW, DIALOG_BLUE_HSV_HIGH)
    share = float((blue > 0).mean())
    return share > DIALOG_BLUE_SHARE, share


# ----------------------------------------------------------------------------
def recognise(img):
    """What is on screen right now. Bare module-level function, not a
    method, so tests can swap it out process-wide the way test_dungeon_flow
    swaps dungeon.recognise -- see test_skewer_flow.py."""
    templates = load_ingredient_templates()
    signatures = load_icon_signatures()
    order = find_strip_icons(img, POS_ORDER_STRIP, signatures)
    current = find_strip_icons(img, POS_CURRENT_STRIP, signatures)

    grid = []
    for fy in GRID_ROWS_FY:
        for fx in GRID_COLS_FX:
            name, val = match_icon(crop_rel(img, fx, fy, GRID_CELL_FW, GRID_CELL_FH),
                                   templates)
            grid.append({"name": name, "val": val, "fx": fx, "fy": fy})

    mistake_flash, mistake_hsv, mistake_red_share = _read_mistake_flash(img)
    round_over_dialog, dialog_blue_share = _read_failed_dialog(img)

    grid_hits = sum(1 for c in grid if c["name"] is not None)
    # Gameplay UI counts as visible once at least a couple of grid buttons
    # are confidently recognised. Below that, either nothing is learned yet
    # or the round-over/menu screen is showing -- SkewerBot.play_round()
    # decides which, across several reads, not this per-frame function.
    gameplay_visible = grid_hits >= 2

    # find_strip_icons never returns a None placeholder for an unconfident
    # position, it just omits it -- so unlike the grid there is no explicit
    # "uncertain" marker here, only "found" or "not found". An order strip
    # that reads empty while the grid is confidently visible most likely
    # means the match missed everything on it, not that the order really
    # is empty; state falls to UNKNOWN either way, forcing a re-read rather
    # than acting on a guess.
    if not gameplay_visible or not order:
        state = UNKNOWN
    elif current == order:
        state = COMPLETE_READY
    elif len(current) < len(order) and current == order[:len(current)]:
        state = ORDER_VISIBLE
    else:
        state = MISMATCH

    next_ingredient = order[len(current)] if state == ORDER_VISIBLE else None

    return {
        "state": state,
        "gameplay_visible": gameplay_visible,
        "order": order,
        "current": current,
        "next_ingredient": next_ingredient,
        "grid": grid,
        "complete_button": {"fx": POS_COMPLETE[0], "fy": POS_COMPLETE[1]},
        "plate_click": {"fx": POS_PLATE_CLICK[0], "fy": POS_PLATE_CLICK[1]},
        "mistake_flash": mistake_flash,
        "mistake_hsv": mistake_hsv,
        "mistake_red_share": mistake_red_share,
        "round_over_dialog": round_over_dialog,
        "dialog_blue_share": dialog_blue_share,
    }


# ----------------------------------------------------------------------------
class SkewerBot:
    # Click origin, overwritten in __init__. A class default because the
    # offline tests build a bot with __new__ and never run __init__.
    origin = (0, 0)

    # The round itself is only 60 s and scored by meals served, so the click
    # loop is tuned for speed over caution: a short tick and just one repeat
    # to settle (two agreeing reads, not three) instead of the more patient
    # defaults elsewhere in this project.
    #
    # Full pace is 330 ms per click, and it used to be 180. The player asked
    # for 45 % off the speed after watching it play: at 180 ms it was
    # reaching for a grid the emulator had not finished redrawing, which
    # costs an order rather than saving time. 180 / 0.55 is 327, rounded to
    # 330.
    #
    # `speed` is the dial to turn when chasing a higher score. Where the time
    # actually goes, measured: recognising one frame costs ~21 ms (order
    # strip 5, plate 4, twelve grid cells 10), so all but a twentieth of each
    # click is spent waiting on purpose. Dividing the waits is therefore the
    # only lever that matters -- there is little to win by making the
    # recognition faster. What limits it is the game, not this program:
    # clicking faster than the emulator redraws means tapping a grid that has
    # not finished updating. Raise it a little at a time and watch a real
    # round.
    #
    # `speed` deliberately does NOT touch `patience`, which governs the waits
    # for the GAME to do something -- the next order to be drawn, a dialog to
    # settle, a round to start. Those are paced by the game and shortening
    # them buys nothing: an earlier version divided them by speed too, and
    # that made the bot more likely to act on a half-drawn order, which is
    # the one failure this loop must not have. Turn `patience` up on its own
    # if a slow machine needs the game given more room.
    def __init__(self, cap, dry_run=True, log=print, tick=0.33,
                 round_seconds=60.0, settle_tries=2, patience=1.0,
                 debugdir="debug_skewer", no_complete=False, speed=1.0):
        self.cap = cap
        self.origin, self.device = self._device_size()
        self.dry_run = dry_run
        self.log = log
        self.speed = max(MIN_SPEED, min(MAX_SPEED, speed))
        self.tick = max(MIN_TICK, tick / self.speed)
        self.round_seconds = round_seconds
        self.settle_tries = settle_tries
        self.patience = patience
        self.debugdir = debugdir
        # Debug aid: hold right after the last ingredient instead of
        # clicking Complete, so the built skewer and its order stay on
        # screen for --probe / a screenshot instead of disappearing into
        # the next order. See ORDER_HELD.
        self.no_complete = no_complete
        self.control = guard.Stop()
        self.stats = {"orders_done": 0, "mistakes_seen": 0,
                      "undo_clicks": 0, "unknown_reads": 0,
                      "round_over_reason": ""}
        # Hard upper limit on iterations per round, independent of proper
        # round-over detection -- same safety-valve role as
        # DungeonBot.max_loops.
        self.max_loops = 400

    # ------------------------------------------------------------------
    def _device_size(self):
        """Reference frame for clicks: its origin and its size.

        With ADB the frame IS the device screen and the origin is 0,0. In
        window mode the frame carries the emulator's title bar on top, which
        is Windows chrome and not part of the game area. Every fx/fy in this
        file is relative to the game area, so a click has to start from the
        game area's origin -- without that it lands title_bar * (1 - fy)
        pixels too high, measured 14 px at fy 0.550 in a 1051 px window.

        game_rect handles both: on an ADB frame the device aspect matches
        exactly, so it returns the whole image and the origin is 0,0. It
        used to reach through a HybridCapture to its own AdbCapture for a
        second, unmixed frame; that mixed mode is gone, so the one frame
        the bot is looking at is always the right one to measure.
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
        ox, oy = self.origin
        dw, dh = self.device
        x, y = int(round(ox + fx * dw)), int(round(oy + fy * dh))
        if self.dry_run:
            self.log("    [dry run] click %s at rel. %.3f, %.3f, pixel %d,%d"
                     % (was, fx, fy, x, y))
            return
        self.cap.tap(x, y)

    def _wait_if_paused(self):
        go_on, _ = self.control.wait_while_paused(
            emit=lambda ev: self.log("    %s" % ev["text"]))
        return go_on

    # ------------------------------------------------------------------
    def settle(self, tries=None):
        """Wait until consecutive reads agree on state/order/current.

        Same "a single frame is no proof" rule as dungeon.dialog_settled().
        """
        tries = tries or self.settle_tries
        previous = None
        same = 0
        info = None
        for _ in range(tries * 3):
            info = recognise(self.grab())
            fingerprint = (info["state"], tuple(info["order"]), tuple(info["current"]))
            if fingerprint == previous:
                same += 1
                if same >= tries - 1:
                    return info
            else:
                same = 0
                previous = fingerprint
            time.sleep(self.tick)
        return info or recognise(self.grab())

    # ------------------------------------------------------------------
    def click_ingredient(self, name, info):
        cell = next((c for c in info["grid"] if c["name"] == name), None)
        if cell is None:
            self.log("  ingredient %s not currently found on the grid" % name)
            return False
        before = list(info["current"])
        self.tap(cell["fx"], cell["fy"], was="add:%s" % name)
        if self.dry_run:
            return True
        after = self.settle()
        ok = (len(after["current"]) == len(before) + 1
              and after["current"][:len(before)] == before
              and after["current"][-1] == name)
        if not ok:
            self.log("  click on %s had no clear effect, current now %s"
                     % (name, after["current"]))
        return ok

    def click_undo(self, info):
        before = list(info["current"])
        target = info["plate_click"]
        self.tap(target["fx"], target["fy"], was="undo")
        self.stats["undo_clicks"] += 1
        if self.dry_run:
            return True
        after = self.settle()
        ok = (len(after["current"]) == max(0, len(before) - 1)
              and after["current"] == before[:len(after["current"])])
        if not ok:
            self.log("  undo had no clear effect, current now %s" % after["current"])
        return ok

    def click_complete(self, info):
        before_order = list(info["order"])
        button = info["complete_button"]
        self.tap(button["fx"], button["fy"], was="complete")
        self.stats["orders_done"] += 1
        if self.dry_run:
            return True
        deadline = time.time() + 3.0 * self.patience
        while time.time() < deadline:
            after = recognise(self.grab())
            if after["gameplay_visible"] and after["order"] and after["order"] != before_order:
                return True
            time.sleep(self.tick)
        self.log("  complete: no new order appeared, unclear whether it was accepted")
        return False

    def settled_order(self, tries=None):
        """The order strip, confirmed identical on two consecutive reads.
        Returns (order, info) -- the info being the read that confirmed it,
        so the caller can act on it instead of immediately reading again.
        `order` is None if it never settled, or ROUND_OVER if the round
        ended while looking.

        This exists because of a real failure: an order was acted on from a
        SINGLE frame, caught mid-transition while the next order was still
        being drawn into the bubble. Only part of it had appeared, the bot
        built that part, decided the skewer was finished and submitted it --
        "clicked before the order appeared", and a life gone. One frame is
        never proof here, exactly as everywhere else in this project.

        Costs two reads (~40 ms) per order, not per click, so it is cheap
        next to the clicking that follows.
        """
        tries = tries or self.settle_tries
        previous = None
        info = None
        for _ in range(tries * 3):
            info = recognise(self.grab())
            if info["round_over_dialog"] or not info["gameplay_visible"]:
                return ROUND_OVER, info
            order = info["order"]
            if order and order == previous:
                return order, info
            previous = order
            time.sleep(self.tick)
        self.log("  order never settled, not clicking")
        return None, info

    # ------------------------------------------------------------------
    def solve_current_order(self, max_steps=20):
        """One order, start to finish. Returns True on a completed order,
        False if it had to give up, None if the screen stopped looking like
        gameplay at all (round-over is decided by play_round(), not here).

        Tracks its own click count (`built`) as "how far into the order am
        I", instead of re-deriving that from a fresh image read of the
        current/plate strip on every step the way an earlier version did.
        That was forced at the time: plate reading was broken outright, and
        a live run showed `current` never once registering a successful
        add, so per-click verification looped on the first ingredient
        forever. Each grid tap is trusted once its cell is matched, the
        same trust already placed in the grid everywhere else in this file.

        Plate reading has since been rebuilt and does now work -- against
        the first real capture of a populated plate it read all five
        ingredients correctly (see the SKEWER_* block). Re-enabling
        click_ingredient/click_undo here, so every tap is verified against
        the plate again, is therefore back on the table, but it is a
        behavioural change that costs a read per click and has not been
        tried live yet; it is left alone deliberately rather than by
        oversight. Those methods stay on the class and stay tested.
        """
        target, pending = self.settled_order()
        if target is ROUND_OVER:
            return None
        if target is None:
            self.stats["unknown_reads"] += 1
            return False

        built = 0
        unknown_seen = 0
        for _ in range(max_steps):
            if not self._wait_if_paused() or self.control.is_set():
                return False
            # The read that confirmed the order is still current on the first
            # pass, so use it rather than grabbing the same screen twice.
            info, pending = pending or recognise(self.grab()), None
            if info["round_over_dialog"] or not info["gameplay_visible"]:
                return None

            if info["mistake_flash"]:
                self.stats["mistakes_seen"] += 1
                self.log("  mistake flash seen, hsv %s, red share %.2f"
                         % (info["mistake_hsv"], info["mistake_red_share"]))

            # The order must not move under us mid-build. If it does, `built`
            # counts clicks against an order that is no longer on screen, and
            # submitting on that count serves a wrong skewer. Hand back and
            # let the caller start again on whatever is showing now.
            if info["order"] and info["order"] != target:
                self.log("  order changed while building, starting over")
                self.stats["unknown_reads"] += 1
                return False

            if not info["order"]:
                unknown_seen += 1
                self.stats["unknown_reads"] += 1
                if unknown_seen >= 6:
                    self.log("  stuck on an unreadable order, giving up")
                    return False
                time.sleep(self.tick)
                continue
            unknown_seen = 0

            if built >= len(target):
                if self.no_complete:
                    self.log("  order built, holding before Complete (--no-complete)")
                    return ORDER_HELD
                return self.click_complete(info)

            name = target[built]
            cell = next((c for c in info["grid"] if c["name"] == name), None)
            if cell is None:
                unknown_seen += 1
                self.stats["unknown_reads"] += 1
                if unknown_seen >= 6:
                    self.log("  %s not found on the grid, giving up on this order" % name)
                    return False
                time.sleep(self.tick)
                continue
            unknown_seen = 0

            self.tap(cell["fx"], cell["fy"], was="add:%s" % name)
            built += 1
            time.sleep(self.tick)

        self.log("  order loop safety cap reached")
        return False

    def play_round(self, seconds=None):
        seconds = seconds if seconds is not None else self.round_seconds
        deadline = time.time() + seconds + 5.0  # small grace over the in-game timer
        absent_reads = 0
        reason = "step limit reached"
        for _ in range(self.max_loops):
            if not self._wait_if_paused() or self.control.is_set():
                reason = self.control.reason or "aborted"
                break
            if time.time() > deadline:
                reason = "time limit reached"
                break
            info = recognise(self.grab())
            if info["round_over_dialog"]:
                reason = "round over (Failed dialog)"
                break
            if not info["gameplay_visible"]:
                absent_reads += 1
                if absent_reads >= ROUND_OVER_ABSENT_READS:
                    reason = "round over (UI absent)"
                    break
                time.sleep(self.tick)
                continue
            absent_reads = 0
            if self.solve_current_order() == ORDER_HELD:
                reason = "held before Complete (--no-complete)"
                break
        self.log("round finished: %s" % reason)
        self.stats["round_over_reason"] = reason
        return dict(self.stats)

    def restart_round(self):
        """Get from a just-ended round back to a startable stage-select
        screen, and start the next one. Close only if the Failed dialog is
        actually showing (a round can also end by time limit, with no
        dialog); Start is always tapped after, since stage-select shows it
        either way once Close is done. Positions measured live against one
        real Failed -> stage-select -> gameplay transition, not yet
        confirmed for a round that ends by time running out instead."""
        info = recognise(self.grab())
        if info["round_over_dialog"]:
            self.tap(*POS_DIALOG_CLOSE, was="close_failed_dialog")
            time.sleep(1.0 * self.patience)
        self.tap(*POS_STAGE_START, was="start_stage")
        time.sleep(1.5 * self.patience)

    def enter_from_menu(self):
        """Cold start: main menu -> "Play Game" lantern -> stage-select ->
        Start, then a fixed pause before play_round begins. Open-loop taps,
        no state check first -- unlike restart_round() there is no
        round_over_dialog to confirm against, only the caller's word that
        we are actually starting from the main menu. See POS_MENU_PLAY_GAME
        for how unverified that tap position still is."""
        self.tap(*POS_MENU_PLAY_GAME, was="play_game")
        time.sleep(1.5 * self.patience)
        self.tap(*POS_STAGE_START, was="start_stage")
        time.sleep(3.0 * self.patience)

    def run(self, rounds=1, from_menu=False):
        if from_menu:
            self.enter_from_menu()
        for i in range(rounds):
            if self.control.is_set():
                break
            self.log("\n=== Round %d of %d" % (i + 1, rounds))
            self.play_round()
            if i < rounds - 1 and not self.control.is_set():
                self.restart_round()
        return dict(self.stats)


# ----------------------------------------------------------------------------
def probe(cap, log=print, tag=""):
    """Shows what is recognised on the current screen. Clicks nothing.

    Every run writes into its own timestamped subdirectory, so probing a
    second order never overwrites the captures of the first -- comparing
    two real orders against each other is the main way anything in the
    strip recognition gets measured, and a flat set of fixed filenames
    made that impossible without copying files by hand between runs.
    """
    img = cap.grab()
    x0, y0, gw, gh = game_rect(img)
    templates = load_ingredient_templates()
    log("window %d x %d, title bar %d px, game area %d x %d"
        % (img.shape[1], img.shape[0], y0, gw, gh))
    log("ingredient templates learned: %d of %d (%s)"
        % (len(templates), len(INGREDIENT_NAMES), ", ".join(sorted(templates)) or "none"))

    info = recognise(img)
    log("\nstate: %s   gameplay_visible: %s   round_over_dialog: %s"
        % (info["state"], info["gameplay_visible"], info["round_over_dialog"]))
    log("order:           %s" % info["order"])
    log("current:         %s" % info["current"])
    log("next ingredient: %s" % info["next_ingredient"])
    log("mistake flash:   %s   hsv %s   red share %.3f"
        % (info["mistake_flash"], info["mistake_hsv"], info["mistake_red_share"]))
    log("failed dialog:   %s   blue share %.3f"
        % (info["round_over_dialog"], info["dialog_blue_share"]))

    log("\nGrid cells")
    for i, cell in enumerate(info["grid"]):
        px = to_pixel(img, cell["fx"], cell["fy"])
        log("  %2d  %-14s val %.2f   rel %.3f/%.3f   pixel %d,%d"
            % (i + 1, cell["name"] or "?", cell["val"], cell["fx"], cell["fy"], *px))

    log("\nClick targets the bot would use")
    log("  complete    pixel %d,%d" % to_pixel(img, *POS_COMPLETE[:2]))
    log("  undo/plate  pixel %d,%d" % to_pixel(img, *POS_PLATE_CLICK))

    stamp = time.strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join("debug_skewer", stamp + ("_" + tag if tag else ""))
    os.makedirs(outdir, exist_ok=True)
    # Full frame too, not just the crops: re-deriving a rect that turned out
    # to be mispositioned is impossible from the crop it produced, since the
    # crop cannot show what it cut off.
    cv2.imwrite(os.path.join(outdir, "frame.png"), img)
    for name, rect in (("order_strip", POS_ORDER_STRIP), ("current_strip", POS_CURRENT_STRIP),
                       ("portraits", POS_PORTRAITS), ("timer", POS_TIMER),
                       ("lives", POS_LIVES), ("failed_dialog", POS_FAILED_DIALOG)):
        cv2.imwrite(os.path.join(outdir, name + ".png"), crop_rel(img, *rect))
    for i, cell in enumerate(info["grid"]):
        cv2.imwrite(os.path.join(outdir, "grid_%02d.png" % (i + 1)),
                   crop_rel(img, cell["fx"], cell["fy"], GRID_CELL_FW, GRID_CELL_FH))
    # What was actually read, alongside the pixels it was read from -- a
    # capture is only useful later if the reading it produced is kept with it.
    with open(os.path.join(outdir, "read.txt"), "w", encoding="utf-8") as fh:
        fh.write("state:   %s\norder:   %s\ncurrent: %s\n"
                 % (info["state"], info["order"], info["current"]))
    log("\ncrops saved to %s/" % outdir.replace("\\", "/"))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually click")
    ap.add_argument("--probe", action="store_true", help="only show what is recognised")
    ap.add_argument("--tag", default="",
                    help="label appended to the --probe output directory "
                         "name, e.g. --tag five_icons")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--from-menu", action="store_true",
                    help="start from the main menu: click Play Game, then "
                         "Start, before the first round")
    ap.add_argument("--no-complete", action="store_true",
                    help="debug aid: build one order but never click "
                         "Complete, then stop -- gives time to run --probe "
                         "or take a screenshot against the frozen order")
    ap.add_argument("--round-seconds", type=float, default=60.0,
                    help="expected round length, used as a safety deadline")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="click-loop speed dial, higher is faster (e.g. 1.1, "
                         "1.5). Divides the wait between clicks, which is "
                         "most of the loop. Clamped to "
                         + "%g-%g" % (MIN_SPEED, MAX_SPEED))
    ap.add_argument("--patience", type=float, default=1.0,
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
    if args.no_complete and args.rounds != 1:
        print("--no-complete stops after the first order; ignoring --rounds %d, using 1"
              % args.rounds)
        args.rounds = 1

    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)
    if args.probe:
        probe(cap, tag=args.tag)
        return

    print("Mode: %s" % ("REAL, it will click" if args.go else "dry run, no clicks"))
    bot = SkewerBot(cap, dry_run=not args.go, round_seconds=args.round_seconds,
                    patience=args.patience, no_complete=args.no_complete,
                    speed=args.speed)
    print("Reference frame %d x %d" % bot.device)
    if bot.speed != args.speed:
        print("Speed %.2f is outside %g-%g, using %.2f"
              % (args.speed, MIN_SPEED, MAX_SPEED, bot.speed))
    print("Speed %.2f, %.0f ms between clicks" % (bot.speed, bot.tick * 1000))
    # An ADB frame costs roughly 400 ms, measured in PLAN_ADB_ONLY.md
    # (not shipped publicly). A tick below that is a promise --speed cannot
    # keep -- each round still waits for its frame -- so it is said here
    # rather than left to look like the setting is doing nothing.
    if not cap.moves_mouse and bot.tick * 1000 < 400:
        print("Note: an ADB frame costs roughly 400 ms, above this tick. "
              "The actual pace is bounded by that, not by --speed.")
    _keys(bot)
    control = None if args.no_hotkeys else guard.start(bot.control)
    try:
        stats = bot.run(args.rounds, from_menu=args.from_menu)
    except KeyboardInterrupt:
        stats = bot.stats
        print("\naborted")
    finally:
        if control:
            control.stop()
    print("\nSummary: %s" % stats)


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
