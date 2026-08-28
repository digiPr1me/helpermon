"""
Digital World Search: getting onto the board from the main screen, and back
there when the run is over.

Three screens, two taps, three checks -- never whether the screen before is
gone, always whether the one after has arrived, and twice running, so an
animation mid-transition is not mistaken for the real thing (CLAUDE.md).

  Main screen   -- tap the Explore tab -->   Explore menu
  Explore menu  -- tap the card        -->   Board
  Board         -- tap the X           -->   Explore menu
  Explore menu  -- tap the globe       -->   Main screen

No image from the game is stored anywhere in this file. Every screen is told
apart by colour, shape and neighbour, the way dungeon.py and summon.py
already do it, and the four recognisers here are built and measured exactly
like theirs -- see PLAN_WORLD_SEARCH_NAV.md section 4 for the numbers.

  py explore.py --probe                 what is recognised on the live game
  py explore.py --probe --file x.png    the same, on a saved picture

There is no --go here. This module has no run of its own; it is driven from
engine.py's Settings.navigate, at the start and end of engine.run.
"""

import argparse
import os
import time

import cv2
import numpy as np

import capture
import dungeon as D
import guard
import userdata


# ----------------------------------------------------------------------------
# explore_tab -- the Explore tab in the bottom nav bar
# ----------------------------------------------------------------------------
# The tab carries a red notification badge that comes and goes, and CLAUDE.md
# is explicit that nothing may hang on it in either direction. It cannot: the
# badge sits on top of the icon, above this band entirely, and it is red,
# outside a mask with no hue term at all.
#
# Found at two things that are never the badge: the globe (dungeon.home_button,
# which also proves nothing is dimming the bar), and the label clump nearest
# NAV_EXPLORE_DX to its right. fy is taken from the globe rather than the
# label -- the label of whichever tab is currently open turns white and
# drifts a little, the globe's height does not.
NAV_LABEL_BAND = (0.955, 0.985)
NAV_LABEL_WHITE = ((0, 0, 215), (179, 235, 255))
NAV_LABEL_MIN_AREA = 3
# Clumps closer than this are one label, not two neighbours. Measured at
# 0.012 gw in PLAN_WORLD_SEARCH_NAV.md 4.1.
NAV_LABEL_GAP = 0.012

# Measured on ws_main_adb.png, PLAN_WORLD_SEARCH_NAV.md 4.1: the Explore
# label sits 0.2350 to the right of the globe, and the nearest neighbour
# (Shop) 0.097 further out. Confirmed on two more frames, ws_menu.png and
# explore-menu.png (the same scene, ADB and window), within 0.0074.
NAV_EXPLORE_DX = 0.235
# Half the distance to the nearest neighbour, so a clump has to be
# unambiguously closer to 0.235 than to anything else out there.
NAV_EXPLORE_TOL = 0.045


def _label_clumps(img, x0, y0, gw, gh):
    """Bright clumps in the tab label row, merged left to right by gap.

    The band starts at 0.955, not the 0.945 PLAN_WORLD_SEARCH_NAV.md 4.1
    measured. At 0.945 the globe's own decorative ring is bright enough to
    pass this mask and close enough to the neighbouring labels that the
    gap-merge below chains three or four tabs into one -- checked on
    ws_main_adb.png, where 0.945 collapses Digimon, Dungeon, the globe and
    Camp into a single clump. 0.955 leaves the ring out and reproduces every
    dx in that section within 0.013, still an order of magnitude inside the
    0.097 gap to the nearest real neighbour.
    """
    top = max(0, int(y0 + NAV_LABEL_BAND[0] * gh))
    bottom = int(y0 + NAV_LABEL_BAND[1] * gh)
    left = max(0, x0)
    right = x0 + gw
    sub = img[top:bottom, left:right]
    if sub.size == 0:
        return []
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(NAV_LABEL_WHITE[0]), np.array(NAV_LABEL_WHITE[1]))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    comps = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < NAV_LABEL_MIN_AREA:
            continue
        comps.append((left + x - x0, left + x + w - x0, area))
    comps.sort()
    if not comps:
        return []
    gap = NAV_LABEL_GAP * gw
    groups = [[comps[0]]]
    for c in comps[1:]:
        prev = groups[-1][-1]
        if c[0] - prev[1] > gap:
            groups.append([c])
        else:
            groups[-1].append(c)
    out = []
    for g in groups:
        xs0 = min(c[0] for c in g)
        xs1 = max(c[1] for c in g)
        out.append({"fx": (xs0 + xs1) / 2.0 / gw, "fw": (xs1 - xs0) / gw,
                    "area": sum(c[2] for c in g)})
    return out


def explore_tab(img):
    """The Explore tab, or None if it is not plainly there.

    None also answers "is the bottom nav bar in front and undimmed", the
    same second job dungeon.home_button's own None already does -- this
    function refuses to look any further once that one has.
    """
    home = D.home_button(img)
    if home is None:
        return None
    x0, y0, gw, gh = D.game_rect(img)
    clumps = _label_clumps(img, x0, y0, gw, gh)
    if not clumps:
        return None
    best = min(clumps, key=lambda c: abs(c["fx"] - home["fx"] - NAV_EXPLORE_DX))
    if abs(best["fx"] - home["fx"] - NAV_EXPLORE_DX) > NAV_EXPLORE_TOL:
        return None
    return {"fx": best["fx"], "fy": home["fy"], "fw": best["fw"], "area": best["area"]}


# ----------------------------------------------------------------------------
# explore_menu -- is the Explore menu open
# ----------------------------------------------------------------------------
# The obvious feature is the wrong one. The hellblau EXPLORE header band
# measures 0.708 on this menu against 0.683 on the main screen, which has
# blue sky at the same spot -- 2.5 points is not a threshold, it is a coin
# flip that loses on the next background. What separates them is the dark
# body behind the cards, present only here.
MENU_DARK_BAND = (0.16, 0.86)
MENU_DARK_HUE = ((95, 120, 20), (130, 255, 110))
# Measured, PLAN_WORLD_SEARCH_NAV.md 4.2: the menu itself 0.544 to 0.552
# across three frames and two frame shapes, the nearest real screen (the
# banner-covered board) 0.371. 0.45 sits 18 % under the one and 21 % over
# the other.
MENU_DARK_MIN = 0.45


def _dark_body_share(img, x0, y0, gw, gh):
    top = max(0, int(y0 + MENU_DARK_BAND[0] * gh))
    bottom = int(y0 + MENU_DARK_BAND[1] * gh)
    left = max(0, x0)
    sub = img[top:bottom, left:x0 + gw]
    if sub.size == 0:
        return 0.0
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(MENU_DARK_HUE[0]), np.array(MENU_DARK_HUE[1]))
    return float(np.count_nonzero(mask)) / mask.size


def explore_menu(img):
    """The Digital World Search card's tap target, or None if this is not
    the Explore menu.

    Not None only when both hold: the dark body behind the cards, and the
    card itself found by world_search_card. Same shape as
    summon.general_tab -- the screen counts as recognised once what is
    needed on it has been found on it, not before.
    """
    x0, y0, gw, gh = D.game_rect(img)
    if _dark_body_share(img, x0, y0, gw, gh) < MENU_DARK_MIN:
        return None
    return world_search_card(img)


# ----------------------------------------------------------------------------
# world_search_card -- the card in the Explore menu
# ----------------------------------------------------------------------------
# The Digital World Search card carries a magenta pixel-device screen, and
# it is the largest magenta thing in the menu by a wide margin -- measured
# ratio 9.9 (window) and 9.7 (ADB) against the next largest, a training
# card's own artwork. 0.006 of the reference area is the same order of
# magnitude the summon bot's General tab measured, and that one threshold
# disagreed by a wrong direction between window and ADB frames (CLAUDE.md).
# So this decides by ratio to the runner-up, not by an absolute area.
# Measured over five frames of the menu in both frame shapes: every real
# magenta thing on it -- the card's screen, its own pink seam, the Training
# card, the fourth card -- sits at H 146 to 150. The old upper bound of 175
# was a round number, never measured against anything it had to refuse, and
# it reached far enough into red to swallow a brick wall (H 173) out of the
# scene behind the header. 160 is 10 units above what it must catch and 13
# below what it must not.
CARD_HUE = ((140, 90, 120), (160, 255, 255))
# A floor against dust only, a factor of 12 under the real card.
CARD_MIN_SHARE = 0.0005
# What counts as a different card rather than this one's own pink seam.
# Measured: the seam sits 0.072 away (Euclidean, in fx/fy), the nearest
# real rival 0.62 to 0.64 away.
CARD_FOREIGN_GAP = 0.17
# Half the measured ratio, room on both sides.
CARD_RATIO_MIN = 3.0
# The device screen sits in the upper part of the card; the tile's own
# centre -- what should be tapped -- is measured 0.072 further down.
CARD_TAP_DY = 0.072


def _card_blobs(img):
    """The magenta clumps in the menu body, biggest first and its rival.

    Only the body. The header above it is the currency bar, and the game
    draws the player's current scene behind it at whatever colour that
    scene happens to be -- an orange stage put a dark red brick wall there
    measuring 0.00566 against the card's own 0.00601, and the ratio rule,
    which is what this recogniser rests on, collapsed to 1.1. The cards are
    drawn in the body and nowhere else, so that is where they are looked
    for; MENU_DARK_BAND already says where the body is.

    Judged by the clump's centre rather than by cropping the image: a crop
    cuts whatever straddles its edge, and a clump that lost half its pixels
    to the crop would be compared against a rival that kept all of its own.
    """
    x0, y0, gw, gh = D.game_rect(img)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(CARD_HUE[0]), np.array(CARD_HUE[1]))
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    blobs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        share = area / float(gw * gh)
        if share < CARD_MIN_SHARE:
            continue
        fy = (y + h / 2.0 - y0) / gh
        if not MENU_DARK_BAND[0] <= fy <= MENU_DARK_BAND[1]:
            continue
        blobs.append({"fx": (x + w / 2.0 - x0) / gw, "fy": fy,
                      "share": share})
    if not blobs:
        return None, None
    biggest = max(blobs, key=lambda b: b["share"])
    foreign = max((b for b in blobs if b is not biggest
                   and ((b["fx"] - biggest["fx"]) ** 2
                        + (b["fy"] - biggest["fy"]) ** 2) ** 0.5 >= CARD_FOREIGN_GAP),
                  key=lambda b: b["share"], default=None)
    return biggest, foreign


def world_search_card(img):
    """The Digital World Search card's tap target, or None.

    None both when no magenta clump clears CARD_MIN_SHARE at all, and when
    the biggest one found is not convincingly the largest -- a menu with a
    different layout, or no menu at all.
    """
    biggest, foreign = _card_blobs(img)
    if biggest is None:
        return None
    if foreign is not None and biggest["share"] < CARD_RATIO_MIN * foreign["share"]:
        return None
    return {"fx": biggest["fx"], "fy": biggest["fy"] + CARD_TAP_DY}


# ----------------------------------------------------------------------------
# close_button -- the X that closes the board
# ----------------------------------------------------------------------------
# Built like summon.exit_button: a fixed plate plus a mark on it, in a crop
# smaller than the plate itself so a window shape this was never measured on
# cannot slide the background into it. Measured, PLAN_WORLD_SEARCH_NAV.md
# 4.4, on ws_board.png and ws_banner.png, ADB only -- no window frame of the
# board exists to measure this against, which is why the floors sit well
# below what was actually caught (0.60 against 0.799, not 0.70).
#
# summon.exit_button sits 0.006/0.008 away at almost the same spot on
# screen, and the two cannot be confused: it needs a near-white plate
# (V >= 225, S <= 45) and finds nothing at all on either of these frames.
CLOSE_FX = 0.7990
CLOSE_FY = 0.9490
CLOSE_FW = 0.0846
CLOSE_CROP = 0.35
CLOSE_PLATE = ((95, 40, 155), (125, 75, 205))
CLOSE_MARK = ((95, 78, 105), (125, 115, 150))
CLOSE_PLATE_MIN = 0.60
CLOSE_MARK_BAND = (0.10, 0.30)


def close_button(img):
    """The X that closes the board, or None.

    None also answers "is the board (or whatever it left up) in front" --
    every other screen on this path measures 0.000 on both halves.
    """
    x0, y0, gw, gh = D.game_rect(img)
    r = CLOSE_CROP * CLOSE_FW * gw
    cx, cy = x0 + CLOSE_FX * gw, y0 + CLOSE_FY * gh
    top, bottom = int(cy - r), int(cy + r)
    left, right = int(cx - r), int(cx + r)
    if top < 0 or left < 0 or bottom > img.shape[0] or right > img.shape[1]:
        return None
    hsv = cv2.cvtColor(img[top:bottom, left:right], cv2.COLOR_BGR2HSV)
    if hsv.size == 0:
        return None
    n = float(hsv.shape[0] * hsv.shape[1])
    plate = cv2.inRange(hsv, np.array(CLOSE_PLATE[0]), np.array(CLOSE_PLATE[1])).sum() / 255.0 / n
    mark = cv2.inRange(hsv, np.array(CLOSE_MARK[0]), np.array(CLOSE_MARK[1])).sum() / 255.0 / n
    if plate < CLOSE_PLATE_MIN:
        return None
    if not CLOSE_MARK_BAND[0] <= mark <= CLOSE_MARK_BAND[1]:
        return None
    return {"fx": CLOSE_FX, "fy": CLOSE_FY, "plate": plate, "mark": mark}


# ----------------------------------------------------------------------------
# The navigator
# ----------------------------------------------------------------------------
# Same numbers as dungeon.go_home, same reason: one tap is enough from a
# settled screen, the rest exist because a tap sent into an animation is
# swallowed, and a look that finds nothing spends itself waiting rather than
# tapping again.
NAV_TAPS_MAX = 3
NAV_ROUNDS = 6

# The X pops one screen only, the Explore menu, never further -- unlike
# Special Summon's up to two. Kept at summon.py's own numbers regardless:
# the reasoning is the same (a tap during an animation is eaten) and a run
# that gives up on the way out is worse than one that tried a few times too
# many.
EXIT_ROUNDS = 20
EXIT_TAPS_MAX = 4
EXIT_ROUND = 0.6


class Nav:
    """Opens the Digital World Search board from the main screen, and
    returns there when the run is done.

    Borrows a DungeonBot for tapping, pausing and dungeon.go_home, the same
    way summon.SummonBot does -- both carry the device-coordinate origin
    and the measured pause times already, and go_home is reused whole
    rather than rewritten (PLAN_WORLD_SEARCH_NAV.md 5.2).
    """

    def __init__(self, cap, dry_run=True, log=print, control=None,
                 patience=1.5, debugdir="debug_explore"):
        self.cap = cap
        self.dry_run = dry_run
        self.log = log
        self.control = control if control is not None else guard.Stop()
        self.patience = patience
        self.debugdir = debugdir
        self.bot = D.DungeonBot(cap, dry_run=dry_run, log=self._quiet)

    def _quiet(self, text):
        pass

    def grab(self):
        return self.bot.grab()

    def tap(self, fx, fy, was=""):
        self.bot.tap(fx, fy, was=was)

    def _pause_gate(self):
        """False when the run must not go on.

        wait_while_paused alone answers only the pause question, and
        returns "go on" the instant the bot is not paused -- whether or
        not a stop was requested. Checking is_set() beside it is what the
        Stop button in the launcher cost summon.py before this was fixed
        there; every bot with a wait loop needs both.
        """
        if self.control.is_set():
            return False
        go_on, _ = self.control.wait_while_paused()
        return go_on

    def _dump(self, img, tag):
        try:
            os.makedirs(self.debugdir, exist_ok=True)
            path = os.path.join(self.debugdir, "%s.png" % tag)
            cv2.imwrite(path, img)
            self.log("    kept what it saw in %s" % path)
        except Exception as err:
            self.log("    could not keep the frame: %s" % err)

    def _wait_for(self, recognizer):
        """Wait for recognizer to answer twice running, at most NAV_ROUNDS
        rounds. Twice and not once: a frame mid-animation can show a state
        briefly that has not really arrived yet (CLAUDE.md)."""
        confirmed_once = False
        for _ in range(NAV_ROUNDS):
            if not self._pause_gate():
                return None
            img = self.grab()
            if recognizer(img) is not None:
                if confirmed_once:
                    return img
                confirmed_once = True
            else:
                confirmed_once = False
            time.sleep(self.bot.pause_long)
        return None

    def _tap_until(self, target, recognizer, was):
        """Tap target, wait for recognizer, retap up to NAV_TAPS_MAX times
        if it does not come. Never checks whether the screen tapped from is
        gone, only whether the one tapped towards has arrived."""
        for _ in range(NAV_TAPS_MAX):
            self.tap(target["fx"], target["fy"], was=was)
            if self.dry_run:
                return None
            img = self._wait_for(recognizer)
            if img is not None:
                return img
            if self.control.is_set():
                return None
        return None

    # ------------------------------------------------------------------
    def open_board(self):
        """Main screen -> Explore menu -> board. True once the board is up.

        If the board is already open, nothing is tapped at all -- that is
        the normal case for anyone who already starts this way today, and
        the reason this change takes nothing from them.
        """
        img = self.grab()
        if close_button(img) is not None:
            self.log("the board is already open")
            return True
        if D.stage_failed(img):
            self.log("the Stage Failed banner is up, tapping it away first")
            self.tap(0.5, D.NEUTRAL_TAP_Y, was="dismiss Stage Failed")
            time.sleep(self.bot.pause_long)
            img = self.grab()
        if D.auto_button(img) is None:
            self.log("not the plain main screen, cannot open the Digital "
                     "World Search")
            self._dump(img, "not_main_screen")
            return False
        tab = explore_tab(img)
        if tab is None:
            self.log("the Explore tab was not found")
            self._dump(img, "no_explore_tab")
            return False
        img = self._tap_until(tab, explore_menu, "Explore tab")
        if img is None:
            if not self.control.is_set():
                self.log("the Explore menu did not open")
                self._dump(self.grab(), "no_explore_menu")
            return False
        # explore_menu already found the card; asking again would be the
        # same search twice for no reason, and would fail differently than
        # the check that just passed.
        card = explore_menu(img)
        img = self._tap_until(card, close_button, "Digital World Search card")
        if img is None:
            if not self.control.is_set():
                self.log("the board did not open")
                self._dump(self.grab(), "no_board")
            return False
        return True

    # ------------------------------------------------------------------
    def leave_board(self):
        """Tap the X, then the globe. True once the main screen is back.

        Not gated on the pause or stop flag: by the time this runs, that
        flag is usually already set -- one of the ways a run ends -- and a
        gate here would skip the one step whose whole point is where the
        game is left. Bounded instead, the same shape as
        summon.leave_summons.
        """
        taps = 0
        for _ in range(EXIT_ROUNDS):
            img = self.grab()
            if D.auto_button(img) is not None:
                if taps:
                    self.log("back on the main screen")
                return True
            if explore_menu(img) is not None:
                # The X has landed. The second step is exactly
                # dungeon.go_home, no code of its own: it looks for the
                # globe, taps it at most three times, confirms with
                # auto_button.
                return self.bot.go_home()
            x = close_button(img)
            if x is None:
                # Mid-animation, or a screen this bot did not open. Nothing
                # here is worth tapping blindly at.
                time.sleep(EXIT_ROUND * self.patience)
                continue
            if taps >= EXIT_TAPS_MAX:
                break
            if not taps:
                self.log("\nleaving the Digital World Search")
            self.tap(x["fx"], x["fy"], was="X to close the Digital World Search")
            taps += 1
            if self.dry_run:
                # Nothing was clicked, so nothing will change; sitting out
                # the remaining rounds would only report a failure that
                # never happened.
                return False
            time.sleep(EXIT_ROUND * self.patience)

        # The rounds ran out. Whatever is on the screen, this bot does not
        # know it -- but the nav bar is drawn across most of the game's list
        # side, so the globe is worth one honest try before giving up
        # (PLAN_WORLD_SEARCH_NAV.md 5.3). It is not a blind tap: go_home
        # taps only a globe it has found and confirms with auto_button.
        #
        # This is not theory. When world_search_card could not see the card
        # behind a red brick wall, explore_menu answered None, the branch
        # above was the only route to the globe, and the player was left
        # sitting in the Explore menu -- with the globe plainly on the
        # frame the run saved as it gave up.
        if not self.dry_run and self.bot.go_home():
            return True
        self.log("could not get back to the main screen -- the game is "
                 "left where it stands")
        self._dump(self.grab(), "no_way_back")
        return False


# ----------------------------------------------------------------------------
def _short(target):
    if not target:
        return "not found"
    return "fx %.4f fy %.4f" % (target["fx"], target["fy"])


def probe(img, log=print):
    """Shows what is recognised in this picture. Clicks nothing, and grabs
    nothing itself -- the caller decides whether that came from the live
    game or a saved file."""
    x0, y0, gw, gh = D.game_rect(img)
    # Tested against the raw picture, not against gw/gh: game_rect's own
    # window-space arithmetic does not preserve the device aspect, so
    # checking its output here said "window" for every ADB frame handed to
    # it, including the ones this file's own comments call ADB throughout.
    iw, ih = img.shape[1], img.shape[0]
    shape = ("adb" if abs(iw / float(ih) - D.DEVICE_ASPECT) <= D.DEVICE_ASPECT_TOL
             else "window")
    log("game_rect        x0 %d y0 %d gw %d gh %d, %s frame"
        % (x0, y0, gw, gh, shape))

    home = D.home_button(img)
    log("home button      %s"
        % ("fx %.4f fy %.4f fw %.4f" % (home["fx"], home["fy"], home["fw"])
           if home else "not on this screen"))

    tab = explore_tab(img)
    if tab is None:
        log("explore tab      not found")
    else:
        log("explore tab      fx %.4f, dx %.4f to the globe, area %d"
            % (tab["fx"], tab["fx"] - home["fx"], tab["area"]))

    dark = _dark_body_share(img, x0, y0, gw, gh)
    log("explore menu     dark-body %.3f against %.2f" % (dark, MENU_DARK_MIN))

    biggest, foreign = _card_blobs(img)
    if biggest is None:
        log("world search     no clump found")
    else:
        ratio = biggest["share"] / foreign["share"] if foreign else float("inf")
        log("world search     biggest %.5f at fx %.3f fy %.3f, foreign %s, "
            "ratio %s"
            % (biggest["share"], biggest["fx"], biggest["fy"],
               "%.5f" % foreign["share"] if foreign else "none",
               "%.1f" % ratio if foreign else "n/a"))

    x = close_button(img)
    log("close button     plate %.3f mark %.3f"
        % (x["plate"], x["mark"]) if x else "close button     not on this screen")

    try:
        import vision
        calib = vision.calibrate(img)
        if vision.banner_visible(img, calib):
            board = "calib ok, banner covering the board"
        else:
            templates = vision.load_templates()
            if not templates:
                board = "calib ok, no templates to check the figure with"
            else:
                figure = vision.find_figure(img, calib, templates)
                board = "calib ok, figure %s" % ("found" if figure else "not found")
    except Exception as err:
        board = "calib failed: %s" % err
    log("board            %s" % board)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="only show what is recognised")
    ap.add_argument("--file", default=None,
                    help="a saved picture instead of the live game")
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames via adb or via the window. Default: the "
                         "stored switch (Helpermon's window, or "
                         "DGUP_ADB_MODE)")
    args = ap.parse_args()

    if not args.probe:
        print("explore.py has no run mode of its own -- it is driven from "
              "engine.py's Settings.navigate. Use --probe to check "
              "recognition.")
        return

    if args.file:
        img = cv2.imread(args.file)
        if img is None:
            raise SystemExit("could not read %s" % args.file)
    else:
        adb = userdata.adb_mode() if args.input is None else args.input == "adb"
        img = capture.open_for(adb).grab()
    probe(img)


if __name__ == "__main__":
    main()
