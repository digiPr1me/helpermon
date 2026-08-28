"""
Check the Digital World Search navigation offline, no emulator needed.

Two halves, the same shape as test_summon_flow.py. The four recognisers are
given painted frames, built with the same _bgr helper so the colours are the
exact HSV numbers explore.py's own comments were measured against. The Nav
flow cases (open_board, leave_board, and engine.run's finally) are scripted
instead: a queue of plain dicts, each recognizer patched to read one field
off it, and the taps counted -- what is under test there is the order of
steps and how many times each one retries, not the pixel readers again.

leave_board hands off to dungeon.go_home partway through (explore.py has no
code of its own for that step), so the Nav flow cases build a real
dungeon.DungeonBot with dungeon.home_button and dungeon.auto_button patched
the same way, rather than a stub -- go_home is exercised for real here, not
assumed.
"""

import cv2
import numpy as np

import dungeon as D
import explore as X


# ----------------------------------------------------------------------------
# Painting
# ----------------------------------------------------------------------------
BACKGROUND = (40, 35, 30)


def blank(w, h):
    return np.full((h, w, 3), BACKGROUND, np.uint8)


def _bgr(h, s, v):
    """One HSV triple, OpenCV's own scale, converted to BGR for painting --
    so every painted colour is the exact number this module's comments
    measured, not a guess at what a colour looks like in BGR."""
    px = np.uint8([[[h, s, v]]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


CARD_C = _bgr(148, 170, 190)      # the card's own screen, measured H 148
# The scene behind the currency bar, measured on a live frame: a dark red
# brick wall on an orange stage, H 173. Red enough to have fallen inside the
# old CARD_HUE, which reached to 175.
HEADER_RED_C = _bgr(173, 115, 144)
CLOSE_PLATE_C = _bgr(110, 55, 180)     # inside explore.CLOSE_PLATE
CLOSE_MARK_C = _bgr(110, 95, 125)      # inside explore.CLOSE_MARK
CLOSE_SKY_C = _bgr(60, 200, 250)       # outside both -- too green, too bright
DARK_BODY_C = _bgr(112, 180, 65)       # inside explore.MENU_DARK_HUE


def globe_tile(side):
    """The globe glyph on a fixed grid, the same shape dungeon.home_button
    was measured against (copied from test_dungeon_flow.py's paint_home, a
    circle with a meridian and two parallels)."""
    big = 8 * side
    tile = np.zeros((big, big), np.uint8)
    c, g = big // 2, big // 2 - 1
    t = max(1, int(big * 0.055))
    cv2.circle(tile, (c, c), g, 255, t)
    cv2.ellipse(tile, (c, c), (int(g * 0.45), g), 0, 0, 360, 255, t)
    cv2.line(tile, (c - g, c), (c + g, c), 255, t)
    cv2.ellipse(tile, (c, c), (g, int(g * 0.52)), 0, 0, 360, 255, t)
    small = cv2.resize(tile, (side, side), interpolation=cv2.INTER_AREA)
    return small >= 110


def paint_globe(img):
    x0, y0, gw, gh = D.game_rect(img)
    cx, cy = int(x0 + 0.481 * gw), int(y0 + 0.945 * gh)
    r = int(0.081 * gw / 2)
    cv2.circle(img, (cx, cy), r, (210, 140, 60), -1)
    cv2.circle(img, (cx, cy), int(r * 0.62), (90, 40, 20), -1)
    side = int(round(0.0485 * gw))
    tile = globe_tile(side)
    x, y = cx - side // 2, cy - side // 2
    img[y:y + side, x:x + side][tile] = (255, 255, 255)
    return img


def paint_label(img, fx, w=0.05):
    """A bright clump in the tab label row, at fx."""
    x0, y0, gw, gh = D.game_rect(img)
    top = int(y0 + (X.NAV_LABEL_BAND[0] + 0.003) * gh)
    bottom = int(y0 + (X.NAV_LABEL_BAND[1] - 0.003) * gh)
    left = int(x0 + (fx - w / 2.0) * gw)
    right = int(x0 + (fx + w / 2.0) * gw)
    cv2.rectangle(img, (left, top), (right, bottom), (255, 255, 255), -1)
    return img


def paint_card(img, fx, fy, w=0.06, h=0.05, colour=CARD_C):
    x0, y0, gw, gh = D.game_rect(img)
    ww, hh = int(w * gw), int(h * gh)
    x, y = int(x0 + fx * gw - ww / 2), int(y0 + fy * gh - hh / 2)
    cv2.rectangle(img, (x, y), (x + ww, y + hh), colour, -1)
    return img


def paint_dark_body(img, share=0.9):
    x0, y0, gw, gh = D.game_rect(img)
    fy0, fy1 = X.MENU_DARK_BAND
    top = int(y0 + fy0 * gh)
    bottom = int(y0 + fy0 * gh + (fy1 - fy0) * gh * share)
    cv2.rectangle(img, (max(0, x0), top), (x0 + gw, bottom), DARK_BODY_C, -1)
    return img


def paint_close_x(img, fx=None, fy=None, plate=True, mark=True):
    x0, y0, gw, gh = D.game_rect(img)
    fx = X.CLOSE_FX if fx is None else fx
    fy = X.CLOSE_FY if fy is None else fy
    half = int(0.5 * X.CLOSE_FW * gw)
    cx, cy = int(x0 + fx * gw), int(y0 + fy * gh)
    cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half),
                  CLOSE_PLATE_C if plate else CLOSE_SKY_C, -1)
    if mark:
        arm = int(0.42 * half)
        thick = max(1, int(0.18 * half))
        cv2.line(img, (cx - arm, cy - arm), (cx + arm, cy + arm),
                 CLOSE_MARK_C, thick)
        cv2.line(img, (cx - arm, cy + arm), (cx + arm, cy - arm),
                 CLOSE_MARK_C, thick)
    return img


# ----------------------------------------------------------------------------
# The flow harness -- no pixels, plain dicts
# ----------------------------------------------------------------------------
TAB = {"fx": 0.7119, "fy": 0.9429}
MENU_FOUND = {"fx": 0.293, "fy": 0.286}
CLOSE_FOUND = {"fx": X.CLOSE_FX, "fy": X.CLOSE_FY}
HOME_FOUND = {"fx": 0.481, "fy": 0.945}


def F(**kw):
    base = {"tab": None, "menu": None, "close": None, "home": None,
            "main_clear": False, "failed": False}
    base.update(kw)
    return base


class Screen:
    """A queue of frames; grab() pops one and keeps repeating the last once
    the queue runs dry -- the same shape as test_summon_flow.py's Screen,
    for the same reason: a settled screen keeps looking the same on every
    further read."""

    def __init__(self):
        self.queue = []
        self.last = None
        self.taps = []

    def push(self, *frames):
        self.queue.extend(frames)
        return self

    def grab(self):
        if self.queue:
            self.last = self.queue.pop(0)
        return self.last


def install():
    saved = (X.explore_tab, X.explore_menu, X.close_button,
             D.stage_failed, D.auto_button, D.home_button)
    X.explore_tab = lambda img: img["tab"]
    X.explore_menu = lambda img: img["menu"]
    X.close_button = lambda img: img["close"]
    D.stage_failed = lambda img: img["failed"]
    D.auto_button = (lambda img: {"fx": 0.361, "fy": 0.766}
                     if img["main_clear"] else None)
    D.home_button = lambda img: img["home"]
    return saved


def restore(saved):
    (X.explore_tab, X.explore_menu, X.close_button,
     D.stage_failed, D.auto_button, D.home_button) = saved


def make_nav(screen, dry_run=False, control=None):
    """A Nav wired to screen, with a real dungeon.DungeonBot underneath --
    not a stub. leave_board hands off to that bot's own go_home partway
    through, and go_home is exercised for real here rather than assumed."""
    nav = X.Nav.__new__(X.Nav)
    nav.cap = None
    nav.dry_run = dry_run
    nav.log = lambda t: None
    nav.control = control if control is not None else D.guard.Stop()
    nav.patience = 0.0
    nav.debugdir = "debug_explore"

    bot = D.DungeonBot.__new__(D.DungeonBot)
    bot.dry_run = dry_run
    bot.log = lambda t: None
    bot.pause_short = bot.pause_long = bot.tick = 0.0
    bot.origin = (0, 0)
    bot.device = (1080, 1920)
    bot.control = D.guard.Stop()
    bot.debugdir = "debug_explore"
    bot._saved = 0
    bot.save_unknown = lambda img, tag: None
    bot.return_to_list = lambda tries=5: True
    bot.grab = screen.grab

    def tap(fx, fy, was=""):
        if not dry_run:
            screen.taps.append((round(fx, 3), round(fy, 3), was))
    bot.tap = tap

    nav.bot = bot
    return nav


class FlipControl:
    """A Stop that reports itself paused exactly once, then resumed --
    standing in for a human pressing resume mid-wait, without an actual
    sleep loop for the test to sit through."""

    def __init__(self):
        self.paused_once = False

    def is_set(self):
        return False

    def wait_while_paused(self, emit=None, tick=0.15):
        if not self.paused_once:
            self.paused_once = True
            return True, True
        return True, False


# ----------------------------------------------------------------------------
def main():
    ok = total = 0

    def check(name, good, detail=""):
        nonlocal ok, total
        total += 1
        ok += bool(good)
        print("%-62s %-28s %s" % (name, detail, "ok" if good else "FAILED"))

    # -- explore_tab, painted -----------------------------------------------
    img = blank(759, 1387)
    check("explore_tab is None when home_button is None",
          X.explore_tab(img) is None)

    for w, h in ((759, 1387), (1080, 1920)):
        img = blank(w, h)
        paint_globe(img)
        home = D.home_button(img)
        paint_label(img, home["fx"] + X.NAV_EXPLORE_DX)
        found = X.explore_tab(img)
        good = (found is not None
                and abs(found["fx"] - home["fx"] - X.NAV_EXPLORE_DX) < 0.01
                and abs(found["fy"] - home["fy"]) < 0.001)
        check("explore_tab sits right of the globe at %dx%d" % (w, h), good,
              "%s" % found)

    # -- explore_menu, painted -----------------------------------------------
    img = blank(759, 1387)
    paint_dark_body(img)
    paint_card(img, 0.30, 0.22)
    found = X.explore_menu(img)
    check("explore_menu finds the menu (dark body and card, both)",
          found is not None, "%s" % found)

    img = blank(759, 1387)  # the main screen: no dark body, no card
    check("explore_menu rejects the main screen",
          X.explore_menu(img) is None)

    img = blank(759, 1387)
    paint_card(img, 0.30, 0.22)  # a card with no dark body behind it
    check("explore_menu rejects a card without the dark body",
          X.explore_menu(img) is None)

    # -- world_search_card, painted ------------------------------------------
    img = blank(759, 1387)
    paint_card(img, 0.30, 0.22)
    found = X.world_search_card(img)
    check("world_search_card finds the biggest clump",
          found is not None and abs(found["fx"] - 0.30) < 0.01
          and abs(found["fy"] - (0.22 + X.CARD_TAP_DY)) < 0.01,
          "%s" % found)

    # The ratio rule, the case an absolute area floor would get wrong: the
    # runner-up is only half the size of the biggest, not a third of it.
    img = blank(759, 1387)
    paint_card(img, 0.30, 0.22, w=0.08, h=0.07)
    paint_card(img, 0.70, 0.70, w=0.06, h=0.05)
    found = X.world_search_card(img)
    check("world_search_card rejects a menu with no clear biggest clump",
          found is None, "%s" % found)

    # Not refuted by the card's own seam, close by and not small either.
    img = blank(759, 1387)
    paint_card(img, 0.30, 0.22, w=0.08, h=0.07)
    paint_card(img, 0.30, 0.29, w=0.06, h=0.04)  # the seam, 0.07 away
    found = X.world_search_card(img)
    check("world_search_card is not refuted by the same card's own seam",
          found is not None and abs(found["fx"] - 0.30) < 0.01,
          "%s" % found)

    # The header is not the menu, and the scene behind it is whatever the
    # player is standing in. Measured on a live frame: an orange stage put a
    # dark red brick wall behind the currency bar at fy 0.064, H 173,
    # covering 0.00566 of the reference area against the card's own 0.00601.
    # The ratio fell to 1.1, the card went unfound, and the run failed twice
    # over -- on the way in and again on the way back. Painted here bigger
    # than the card on purpose: it must lose on where it is and on what
    # colour it is, not on being small.
    for w, h in ((759, 1387), (1080, 1920)):
        img = blank(w, h)
        paint_card(img, 0.30, 0.22, w=0.08, h=0.07)
        paint_card(img, 0.54, 0.064, w=0.21, h=0.07, colour=HEADER_RED_C)
        found = X.world_search_card(img)
        check("a brick wall behind the header does not hide the card, %d x %d"
              % (w, h),
              found is not None and abs(found["fx"] - 0.30) < 0.01,
              "%s" % found)

    # And the same wall, painted in the card's own colour, still loses --
    # this one is the band alone doing the work.
    for w, h in ((759, 1387), (1080, 1920)):
        img = blank(w, h)
        paint_card(img, 0.30, 0.22, w=0.08, h=0.07)
        paint_card(img, 0.54, 0.064, w=0.21, h=0.07)
        found = X.world_search_card(img)
        check("a magenta thing above the menu body is not a card, %d x %d"
              % (w, h),
              found is not None and abs(found["fx"] - 0.30) < 0.01,
              "%s" % found)

    # -- close_button, painted -----------------------------------------------
    for w, h in ((805, 1390), (1080, 1920)):
        img = paint_close_x(blank(w, h))
        found = X.close_button(img)
        check("close_button is found at %d x %d" % (w, h),
              found is not None and abs(found["fx"] - X.CLOSE_FX) < 0.001
              and abs(found["fy"] - X.CLOSE_FY) < 0.001,
              "found" if found else "missed")

    plate_only = paint_close_x(blank(805, 1390), mark=False)
    check("a plate with no X on it is not the close button",
          X.close_button(plate_only) is None)
    mark_only = paint_close_x(blank(805, 1390), plate=False)
    check("a blue X with no plate under it is not the close button",
          X.close_button(mark_only) is None)

    # -- every recogniser against an empty screen -----------------------
    img = blank(759, 1387)
    check("no recogniser raises or fires on an empty screen",
          X.explore_tab(img) is None and X.explore_menu(img) is None
          and X.world_search_card(img) is None and X.close_button(img) is None)

    # -- the flow, scripted --------------------------------------------------
    saved = install()
    try:
        # -- open_board -------------------------------------------------
        screen = Screen()
        screen.push(F(close=CLOSE_FOUND))
        nav = make_nav(screen)
        got = nav.open_board()
        check("open_board taps nothing when the board is already open",
              got is True and not screen.taps,
              "%s, %d tap(s)" % (got, len(screen.taps)))

        screen = Screen()
        screen.push(F(main_clear=False))
        nav = make_nav(screen)
        got = nav.open_board()
        check("open_board aborts before the first tap with no main screen",
              got is False and not screen.taps,
              "%s, %d tap(s)" % (got, len(screen.taps)))

        # The menu appears on the third look within one tap's wait, so no
        # second tap of the Explore tab should follow.
        screen = Screen()
        screen.push(F(main_clear=True, tab=TAB))
        screen.push(F(menu=None), F(menu=None), F(menu=MENU_FOUND), F(menu=MENU_FOUND))
        screen.push(F(close=CLOSE_FOUND), F(close=CLOSE_FOUND))
        nav = make_nav(screen)
        got = nav.open_board()
        tab_taps = [t for t in screen.taps if t[2] == "Explore tab"]
        check("open_board waits rather than tapping the tab again",
              got is True and len(tab_taps) == 1,
              "%s, %d tab tap(s)" % (got, len(tab_taps)))

        # The menu never comes: at most NAV_TAPS_MAX taps of the tab, then
        # False. Screen keeps repeating the last frame, so one push covers
        # every remaining round.
        screen = Screen()
        screen.push(F(main_clear=True, tab=TAB))
        screen.push(F(menu=None))
        nav = make_nav(screen)
        got = nav.open_board()
        tab_taps = [t for t in screen.taps if t[2] == "Explore tab"]
        check("open_board gives up after NAV_TAPS_MAX taps of the tab",
              got is False and len(tab_taps) == X.NAV_TAPS_MAX,
              "%s, %d tab tap(s)" % (got, len(tab_taps)))

        # A stop mid-wait ends it at once. One tap has already gone out --
        # the wait is checked after the tap, not before it -- but no
        # further one follows.
        screen = Screen()
        screen.push(F(main_clear=True, tab=TAB))
        control = D.guard.Stop()
        control.request("test")
        nav = make_nav(screen, control=control)
        got = nav.open_board()
        tab_taps = [t for t in screen.taps if t[2] == "Explore tab"]
        check("a stop mid-wait ends open_board with no further tap",
              got is False and len(tab_taps) == 1,
              "%s, %d tab tap(s)" % (got, len(tab_taps)))

        # A pause mid-wait, then resumed, runs to the end.
        screen = Screen()
        screen.push(F(main_clear=True, tab=TAB))
        screen.push(F(menu=MENU_FOUND), F(menu=MENU_FOUND))
        screen.push(F(close=CLOSE_FOUND), F(close=CLOSE_FOUND))
        nav = make_nav(screen, control=FlipControl())
        got = nav.open_board()
        check("a pause mid-wait, then resumed, runs open_board to the end",
              got is True, "%s" % got)

        # -- leave_board --------------------------------------------------
        # Taps the X, sees the Explore menu, does not tap the X again, and
        # hands off to dungeon.go_home -- which taps the globe once and
        # confirms with auto_button, run for real here.
        screen = Screen()
        screen.push(F(menu=None, close=CLOSE_FOUND))
        screen.push(F(menu=MENU_FOUND, home=HOME_FOUND))
        screen.push(F(home=HOME_FOUND))
        screen.push(F(main_clear=True))
        nav = make_nav(screen)
        got = nav.leave_board()
        x_taps = [t for t in screen.taps if t[2] == "X to close the Digital World Search"]
        home_taps = [t for t in screen.taps if t[2] == "home button"]
        check("leave_board taps the X once, then goes to the globe",
              got is True and len(x_taps) == 1 and len(home_taps) == 1,
              "%s, %d X tap(s), %d home tap(s)"
              % (got, len(x_taps), len(home_taps)))

        # Already home: not a single tap.
        screen = Screen()
        screen.push(F(main_clear=True))
        nav = make_nav(screen)
        got = nav.leave_board()
        check("leave_board taps nothing when already on the main screen",
              got is True and not screen.taps,
              "%s, %d tap(s)" % (got, len(screen.taps)))

        # An unknown screen sits over the X for two rounds; nothing is
        # tapped until close_button answers again.
        screen = Screen()
        screen.push(F(), F())
        screen.push(F(close=CLOSE_FOUND))
        screen.push(F(menu=MENU_FOUND, home=HOME_FOUND))
        screen.push(F(home=HOME_FOUND))
        screen.push(F(main_clear=True))
        nav = make_nav(screen)
        got = nav.leave_board()
        x_taps = [t for t in screen.taps if t[2] == "X to close the Digital World Search"]
        check("leave_board taps nothing while the X is not recognised",
              got is True and len(x_taps) == 1,
              "%s, %d X tap(s)" % (got, len(x_taps)))

        # The rounds run out on a screen this bot does not know, but the
        # nav bar is on it. The globe is the second way home, and it is the
        # one that was missing when a red brick wall stopped explore_menu
        # from recognising the Explore menu: the branch above was the only
        # route to go_home, and the player was left sitting in the menu with
        # the globe plainly on the frame the run saved as it gave up.
        screen = Screen()
        screen.push(*[F(home=HOME_FOUND) for _ in range(X.EXIT_ROUNDS + 1)])
        screen.push(F(main_clear=True))
        nav = make_nav(screen)
        got = nav.leave_board()
        x_taps = [t for t in screen.taps if t[2] == "X to close the Digital World Search"]
        home_taps = [t for t in screen.taps if t[2] == "home button"]
        check("an unknown screen with the nav bar still gets home by the globe",
              got is True and not x_taps and len(home_taps) == 1,
              "%s, %d X tap(s), %d home tap(s)"
              % (got, len(x_taps), len(home_taps)))

        # And with no way home at all it says so rather than tapping about.
        screen = Screen()
        screen.push(F())
        nav = make_nav(screen)
        got = nav.leave_board()
        check("a screen with nothing on it ends leave_board with no tap",
              got is False and not screen.taps,
              "%s, %d tap(s)" % (got, len(screen.taps)))

        # The stop flag does not gate leave_board -- it still taps.
        screen = Screen()
        screen.push(F(menu=None, close=CLOSE_FOUND))
        screen.push(F(menu=MENU_FOUND, home=HOME_FOUND))
        screen.push(F(home=HOME_FOUND))
        screen.push(F(main_clear=True))
        control = D.guard.Stop()
        control.request("test")
        nav = make_nav(screen, control=control)
        got = nav.leave_board()
        x_taps = [t for t in screen.taps if t[2] == "X to close the Digital World Search"]
        check("leave_board taps despite the stop flag being set",
              got is True and len(x_taps) == 1,
              "%s, %d X tap(s)" % (got, len(x_taps)))

        # A dry run clicks nothing and reports no failure that never
        # happened.
        screen = Screen()
        screen.push(F(menu=None, close=CLOSE_FOUND))
        said = []
        nav = make_nav(screen, dry_run=True)
        nav.log = said.append
        got = nav.leave_board()
        check("a dry run of leave_board clicks nothing",
              got is False and not screen.taps
              and not any("could not get back" in line for line in said),
              "%s, %d tap(s), %s" % (got, len(screen.taps), said))
    finally:
        restore(saved)

    # -- engine.run's finally --------------------------------------------
    import engine

    class FakeNav:
        def __init__(self, cap, dry_run=False, log=None, control=None, patience=1.5):
            calls.append("init")

        def open_board(self):
            calls.append("open")
            return True

        def leave_board(self):
            calls.append("leave")
            return True

    class FakeControl:
        def stop(self):
            calls.append("hotkeys stopped")

    saved_nav, saved_loop, saved_cap, saved_guard_start = (
        engine.explore.Nav, engine._run_loop, engine.open_capture, engine.guard.start)
    engine.explore.Nav = FakeNav
    engine._run_loop = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    engine.open_capture = lambda settings, emit: object()
    engine.guard.start = lambda stop, log=None: FakeControl()
    try:
        calls = []
        settings = engine.Settings(navigate=True, hotkeys=True)
        stop = engine.Stop()
        threw = False
        try:
            engine.run(settings, lambda e: None, stop)
        except RuntimeError:
            threw = True
        check("engine.run calls leave_board even when _run_loop throws",
              threw and calls == ["init", "open", "leave", "hotkeys stopped"],
              "%s" % calls)

        # And when open_board itself fails: this is where
        # PLAN_WORLD_SEARCH_NAV.md 5.4's own sketch returns before its
        # finally runs at all, which would skip leave_board and leave the
        # global hotkeys registered. open_board is inside the try here
        # instead, precisely so this case does not do that.
        calls = []
        engine.explore.Nav.open_board = lambda self: (calls.append("open"), False)[1]
        settings = engine.Settings(navigate=True, hotkeys=True, dry_run=False)
        stop = engine.Stop()
        result = engine.run(settings, lambda e: None, stop)
        check("engine.run still cleans up when open_board itself fails",
              result is None and calls == ["init", "open", "leave", "hotkeys stopped"],
              "%s" % calls)
    finally:
        (engine.explore.Nav, engine._run_loop, engine.open_capture,
         engine.guard.start) = (saved_nav, saved_loop, saved_cap, saved_guard_start)

    print("\n%d of %d cases as expected%s"
          % (ok, total, "" if ok == total else "   <-- SOMETHING FAILED"))


if __name__ == "__main__":
    main()
