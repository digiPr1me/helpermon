"""
Check the passive helper offline, no emulator needed.

Two halves. The readers are given painted frames -- a counter, a bond bubble,
the Partner window's button pair -- and have to answer the same way at two
window sizes. The bot itself is given a fake screen and its taps are counted,
which is what catches a toggle being pressed twice or a bubble being tapped
off a single frame.

One honest limit on the painted digits: the glyphs come from OpenCV's own
font, not the game's, and this program ships no picture of the game's. The
shape reader in dungeon.py was measured against the game, and of the ten
OpenCV digits it reads eight -- its 4 and 9 are drawn differently there. So
the numbers below are built from the eight that carry over. What these cases
test is this module's part: the right crop, the right row, the comma thrown
away and the slash found. The digits themselves are dungeon.py's business.
"""

import cv2
import numpy as np

import dungeon as D
import passive as P


# Two window sizes for everything, because a threshold that is really a
# threshold on how thickly something is drawn passes at one size and fails at
# the other. That is not a hypothetical here: it is how a 3 came to be read
# as a 5 in the dungeon bot.
#
# 765 x 1390 and 657 x 1198 are two of the sizes the real screenshots were
# taken at. Smaller than that, OpenCV's own font stops drawing legible
# digits -- the strokes thin out and fall through the mask -- so the counter
# cases stop there while the shapes, which do not depend on a font, go on
# down to 497 x 914.
SIZES = ((765, 1390), (657, 1198))
SHAPE_SIZES = ((765, 1390), (657, 1198), (497, 914))


# ----------------------------------------------------------------------------
# Painting
# ----------------------------------------------------------------------------
def blank(w, h):
    return np.full((h, w, 3), 30, np.uint8)


FONT = cv2.FONT_HERSHEY_DUPLEX


def paint_counter(img, text, clip=False, junk=False):
    """The hologram counter where the game draws it.

    The comma is drawn by hand rather than typed. OpenCV's own comma is a
    speck at this size, and the comma is not decoration here -- how tall it
    is and how far it sits below the row is what tells it from a digit and
    from the specks off the device's rim. Painted at the proportions
    measured on the real frames: a third of the slash's height, a third of
    that height below the middle of the row.

    `clip` cuts the top off one digit, the way the XP numbers rising out of
    the device do. `junk` paints those numbers as a second row above the
    counter.
    """
    x0, y0, gw, gh = D.game_rect(img)
    height = 0.0083 * gh
    # Sized so the painted digits come out the height the game's are, 12
    # pixels at a 1390 tall window: OpenCV's cap height is about 0.71 of what
    # getTextSize reports, and everything the reader measures -- the comma
    # against the slash, the row against the crop -- is a proportion of that.
    scale = 0.60 * (gh / 1390.0)
    left = int(x0 + 0.411 * gw)
    base = int(y0 + 0.8626 * gh + height)
    if junk:
        cv2.putText(img, "888", (left + int(0.02 * gw), base - int(1.8 * height)),
                    FONT, scale, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(img, text, (left, base), FONT, scale, (255, 255, 255), 1,
                cv2.LINE_AA)
    if "," in text:
        before = cv2.getTextSize(text.split(",")[0], FONT, scale, 1)[0][0]
        # The rendered glyph is about 0.71 of what getTextSize calls the
        # height, and the comma is 0.41 of a digit, sitting on the baseline.
        # Counted in rows rather than worked out from fractions: at these
        # sizes it is three pixels tall, and rounding a fraction twice put it
        # at four, which is a comma no longer.
        digit = 0.71 * cv2.getTextSize("0", FONT, scale, 1)[0][1]
        rows = max(2, int(round(0.41 * digit)))
        width = max(1, int(round(0.09 * height)))
        cv2.rectangle(img, (left + before, base - rows + 1),
                      (left + before + width - 1, base), (255, 255, 255), -1)
    if clip:
        # The top half of the digit after the comma, cut away.
        cut = left + cv2.getTextSize(text.split(",")[0] + ",", FONT, scale,
                                     1)[0][0]
        cv2.rectangle(img, (cut, base - int(height)),
                      (cut + int(0.6 * height), base - int(0.45 * height)),
                      (30, 30, 30), -1)
    return img


CYAN = (230, 200, 60)                          # BGR, hue about 93


def paint_bubble(img, fx=0.51, fy=0.34):
    """A white square with the bubble's cyan ring inside it.

    The ring is what the reader looks for, and it is not one shape but two:
    a corner bracket at the upper left and another at the lower right,
    facing each other across the food symbol. Painted at the proportions
    measured on the game's own frames -- each bracket 0.62 of the ring
    across, its stroke 0.14 of that again, which comes out at a fill of
    0.23 to 0.27 and a pair 0.61 of a bracket apart in both directions.

    Painted as one L instead, or as a filled square with a cyan edge, this
    case would pass a reader that cannot find the real thing. That is the
    warning CLAUDE.md carries about painted pictures, and this reader was
    written because the last painted bubble was prettier than the game's.
    """
    x0, y0, gw, gh = D.game_rect(img)
    side = int(P.BUBBLE_SIDE * gw)
    x = int(x0 + fx * gw - side / 2)
    y = int(y0 + fy * gh - side / 2)
    cv2.rectangle(img, (x, y), (x + side, y + side), (255, 255, 255), -1)
    # The ring, inside the white border.
    edge = max(1, int(0.06 * side))
    ring = side - 2 * edge
    arm = max(4, int(0.62 * ring))
    thick = max(2, int(0.14 * arm))
    for corner in (0, 1):
        # 0: the upper left bracket, 1: the lower right one.
        left = x + edge if not corner else x + side - edge - arm
        top = y + edge if not corner else y + side - edge - arm
        cv2.rectangle(img, (left, top if not corner else top + arm - thick),
                      (left + arm, (top + thick) if not corner else top + arm),
                      CYAN, -1)
        cv2.rectangle(img, (left if not corner else left + arm - thick, top),
                      ((left + thick) if not corner else left + arm, top + arm),
                      CYAN, -1)
    # The food symbol, in the middle where the brackets leave room.
    cv2.circle(img, (x + side // 2, y + side // 2), int(side * 0.18),
               (60, 60, 200), -1)
    return img


def paint_wheel(img, fx=0.694, fy=0.279, solid=False):
    """The Daily Bonus wheel, the icon that was taken for a bubble.

    White and cyan quarters around a cyan hub, inside a blue rim, drawn at
    the size and the place the game draws it: the inner of the two columns
    of side icons, at fx 0.694, with the coloured disc 0.045 of the window
    across.

    `solid` paints it with every quarter white. That is not what the game
    draws, and it is exactly the shape a spin or a dimmed frame could leave
    behind. Neither version has anything drawn as thinly as the bubble's
    brackets: a quarter of a disc fills 0.78 of its own box and the hub
    fills it altogether, where a bracket fills 0.23 to 0.29.
    """
    x0, y0, gw, gh = D.game_rect(img)
    cx, cy = int(x0 + fx * gw), int(y0 + fy * gh)
    disc = max(6, int(0.0226 * gw))            # radius, 17 px at 751 wide
    cv2.circle(img, (cx, cy), int(disc * 1.18), (200, 90, 20), -1)   # the rim
    cv2.circle(img, (cx, cy), disc, (255, 255, 255), -1)
    if not solid:
        # Two quarters facing each other, the way the wheel is drawn.
        for a in (0, 180):
            cv2.ellipse(img, (cx, cy), (disc, disc), a, 0, 90, CYAN, -1)
    cv2.circle(img, (cx, cy), int(disc * 0.38), CYAN, -1)            # the hub
    return img


def paint_auto_button(img):
    """The blue disc that says the main screen is in front and clear."""
    x0, y0, gw, gh = D.game_rect(img)
    radius = int(0.053 * gw / 2)
    cv2.circle(img, (int(x0 + 0.361 * gw), int(y0 + 0.765 * gh)), radius,
               (230, 140, 50), -1)
    return img


def paint_partner(img):
    """The Partner window's pair: violet Encyclopedia, blue Move."""
    x0, y0, gw, gh = D.game_rect(img)
    for fx, colour in ((P.PARTNER_VIOLET_X, (220, 47, 105)),
                       (P.PARTNER_BLUE_X, (220, 125, 30))):
        w, h = int(0.242 * gw), int(0.045 * gh)
        x = int(fx * gw - w / 2)
        y = int(y0 + P.PARTNER_Y * gh - h / 2)
        cv2.rectangle(img, (x, y), (x + w, y + h), colour, -1)
    return img


def main_screen(w, h, counter="77,605 / 10", bubble=False):
    img = paint_auto_button(blank(w, h))
    if counter:
        paint_counter(img, counter)
    if bubble:
        paint_bubble(img)
    return img


# ----------------------------------------------------------------------------
# A fake screen for the bot
# ----------------------------------------------------------------------------
class Screen:
    """What the bot sees, and what it did about it."""

    def __init__(self, holo=None, bubble=None, partner=False, clear=True,
                 failed=False):
        self.holo = holo
        self.bubble = bubble
        self.partner = partner
        self.clear = clear
        self.failed = failed
        self.taps = []
        self.presses = 0
        self.backs = 0
        self.messages = []
        self.clock = 1000.0

    # the readers, patched over the module's own
    def install(self):
        self.saved = (P.holo_counter, P.bond_bubble, P.partner_menu,
                      D.stage_failed)
        P.holo_counter = lambda img: self.holo
        P.bond_bubble = lambda img: self.bubble
        P.partner_menu = lambda img: {"fx": 0.35} if self.partner else None
        D.stage_failed = lambda img: self.failed

    def restore(self):
        (P.holo_counter, P.bond_bubble, P.partner_menu,
         D.stage_failed) = self.saved

    def bot(self, **kw):
        bot = P.PassiveBot.__new__(P.PassiveBot)
        bot.log = self.messages.append
        bot.dry_run = False
        bot.do_bond = kw.get("do_bond", True)
        bot.do_auto = kw.get("do_auto", True)
        bot.verbose = False
        bot.may_tap = kw.get("may_tap", True)
        bot.now = lambda: self.clock
        bot.auto_state = "unknown"
        bot.last_value = None
        bot.last_change = None
        bot.presses = 0
        bot.next_press = 0.0
        bot.bond_tries = 0
        bot.next_bond = 0.0
        bot.partner_tries = 0
        bot.opened_partner = 0.0
        bot.last_heartbeat = 0.0
        bot.said = None
        bot.cap = kw.get("cap")
        # No frames are kept in the suite: DUMP_MAX at zero closes that door
        # rather than trusting a temp folder to be writable.
        bot._dumps = P.DUMP_MAX
        bot._next_dump = 0.0
        bot._blind_since = None
        screen = self

        class Inner:
            def grab(self):
                return "frame"

            def tap(self, fx, fy, was=""):
                # The auto button is tapped like anything else; what makes
                # it a press rather than a tap is where it went.
                if was == "auto spend":
                    screen.presses += 1
                else:
                    screen.taps.append((round(fx, 3), round(fy, 3), was))

            def back(self, only_if_dialog=True, leaving_dungeon=False):
                screen.backs += 1
                return True

        bot.bot = Inner()
        # screen_is_clear is the auto button; here it is a yes or no.
        bot.screen_is_clear = lambda img: ({"fx": 0.38, "fy": 0.766}
                                           if self.clear else None)
        return bot


# ----------------------------------------------------------------------------
def main():
    ok = total = 0

    def check(name, good, detail=""):
        nonlocal ok, total
        total += 1
        ok += bool(good)
        print("%-52s %-22s %s" % (name, detail, "ok" if good else "FAILED"))

    # -- the counter ---------------------------------------------------
    for w, h in SIZES:
        got = P.holo_counter(main_screen(w, h, "12,305 / 10"))
        check("counter read at %dx%d" % (w, h), got == 12305, "read %s" % got)

    got = P.holo_counter(main_screen(765, 1390, "1,000 / 10"))
    check("the comma is not a digit", got == 1000,
          "read %s, not 10000" % got)

    got = P.holo_counter(main_screen(765, 1390, "0 / 10"))
    check("a counter at zero reads as zero", got == 0, "read %s" % got)

    got = P.holo_counter(main_screen(765, 1390, "77,605 / 20"))
    check("the allowance is not read", got == 77605, "read %s" % got)

    img = paint_auto_button(blank(765, 1390))
    paint_counter(img, "12,305 / 10", junk=True)
    got = P.holo_counter(img)
    check("a second row does not join the number", got == 12305,
          "read %s" % got)

    img = paint_auto_button(blank(765, 1390))
    paint_counter(img, "12,305 / 10", clip=True)
    got = P.holo_counter(img)
    check("a clipped digit is refused whole", got is None, "read %s" % got)

    got = P.holo_counter(paint_auto_button(blank(765, 1390)))
    check("no counter, no number", got is None, "read %s" % got)

    # -- the bubble ----------------------------------------------------
    for w, h in SHAPE_SIZES:
        found = P.bond_bubble(main_screen(w, h, bubble=True))
        good = found is not None and abs(found["fx"] - 0.51) < 0.02
        check("bubble found at %dx%d" % (w, h), good,
              "at %.3f/%.3f" % (found["fx"], found["fy"]) if found else "-")

    check("no bubble on a plain screen",
          P.bond_bubble(main_screen(765, 1390)) is None)

    outside = paint_bubble(paint_auto_button(blank(765, 1390)), fx=0.90, fy=0.34)
    check("a bubble outside the band is not one",
          P.bond_bubble(outside) is None)

    # -- the Daily Bonus wheel -----------------------------------------
    # The icon that cost a live session. Both frame shapes, because a size
    # floor lands differently on an ADB frame and a window frame and a suite
    # that paints its own pictures will not say so by itself: 1080 x 1920 is
    # what the bot actually runs on.
    for w, h in SHAPE_SIZES + ((1080, 1920),):
        wheel = paint_wheel(paint_auto_button(blank(w, h)))
        check("the wheel is not a bubble at %dx%d" % (w, h),
              P.bond_bubble(wheel) is None,
              "%s" % (P.bond_bubble(wheel),))

    # And not where it stands either. A band keeps out an impostor whose
    # place is known and says nothing about one that turns up somewhere
    # else, so the same icon is painted in the middle of the field.
    for w, h in SHAPE_SIZES + ((1080, 1920),):
        wheel = paint_wheel(paint_auto_button(blank(w, h)), fx=0.50, fy=0.34)
        check("nor in the middle of the band at %dx%d" % (w, h),
              P.bond_bubble(wheel) is None,
              "%s" % (P.bond_bubble(wheel),))
        solid = paint_wheel(paint_auto_button(blank(w, h)), fx=0.50, fy=0.34,
                            solid=True)
        check("nor with every quarter white at %dx%d" % (w, h),
              P.bond_bubble(solid) is None,
              "%s" % (P.bond_bubble(solid),))

    # -- where the figure is -------------------------------------------
    target = P.figure_from_bubble({"fx": 0.51, "fy": 0.34})
    check("the figure sits below and left of the bubble",
          target is not None and abs(target[0] - 0.439) < 0.001
          and abs(target[1] - 0.416) < 0.001,
          "tap at %.3f/%.3f" % target if target else "-")
    check("a bubble at the left edge yields no tap",
          P.figure_from_bubble({"fx": 0.19, "fy": 0.34}) is None)

    # -- the chat line -------------------------------------------------
    # The game writes the world chat across the bottom of the field, and a
    # tap on it opens the chat window. A figure standing behind it is a
    # figure that does not get tapped: the token waits, and the window the
    # helper must not close stays shut.
    low = {"fx": 0.51, "fy": 0.52}
    aim = P.aim_at_figure(low)
    check("a figure behind the chat line yields no tap",
          P.figure_from_bubble(low) is None,
          "would have tapped %.3f/%.3f" % aim)
    check("the chat line covers where the game draws it",
          P.on_chat_row(0.30, 0.5853) and P.on_chat_row(0.30, 0.6140)
          and P.on_chat_row(0.1045, 0.60) and P.on_chat_row(0.6026, 0.60))
    check("and nothing above it",
          not P.on_chat_row(0.439, 0.532) and not P.on_chat_row(0.30, 0.50),
          "the lowest real tap is 0.532")

    # -- the Partner window --------------------------------------------
    for w, h in SHAPE_SIZES:
        check("Partner window recognised at %dx%d" % (w, h),
              P.partner_menu(paint_partner(blank(w, h))) is not None)
    check("no Partner window on the main screen",
          P.partner_menu(main_screen(765, 1390)) is None)

    # -- auto spend, the state machine ---------------------------------
    # A falling counter is a running Auto Spend, and a running Auto Spend
    # must never be pressed: the button is a toggle and the press would
    # switch it off.
    screen = Screen(holo=77605)
    screen.install()
    try:
        bot = screen.bot()
        for value in (77605, 77595, 77585, 77575):
            screen.holo = value
            screen.clock += P.TICK
            bot.tick()
        check("a falling counter is left alone", screen.presses == 0,
              "%d press(es)" % screen.presses)

        # A counter that stands still is a button that is off -- but not
        # before STALL_AFTER, because a run of unchanged readings is what a
        # slow activation looks like from outside.
        screen.presses = 0
        bot = screen.bot()
        screen.holo = 5000
        start = screen.clock
        bot.tick()
        while screen.clock + P.TICK < start + P.STALL_AFTER:
            screen.clock += P.TICK
            bot.tick()
        check("nothing is pressed before the stall is certain",
              screen.presses == 0, "%d press(es)" % screen.presses)
        screen.clock += P.TICK
        bot.tick()
        check("a counter that stopped gets a press", screen.presses == 1,
              "%d press(es)" % screen.presses)

        # And then it waits. Both the gap and another stall window have to
        # pass, so this is not a press per tick -- which is the thing that
        # would leave a toggle wherever the last tap happened to put it.
        pressed_at = screen.clock
        for _ in range(int(P.PRESS_GAPS[0] / P.TICK)):
            screen.clock += P.TICK
            bot.tick()
        check("no second press inside the first gap", screen.presses == 1,
              "%d press(es)" % screen.presses)
        while screen.clock + P.TICK <= pressed_at + P.STALL_AFTER:
            screen.clock += P.TICK
            bot.tick()
        check("the second press comes once the gap is out",
              screen.presses == 2, "%d press(es)" % screen.presses)

        # A round that could not read the counter has no evidence and must
        # not press. The XP numbers cover the digits for seconds at a time,
        # and a live run pressed twice into a perfectly healthy Auto Spend
        # because unreadable was counted as unchanged.
        screen.presses = 0
        bot = screen.bot()
        screen.holo = 5000
        bot.tick()
        screen.holo = None
        for _ in range(int(3 * P.STALL_AFTER / P.TICK)):
            screen.clock += P.TICK
            bot.tick()
        check("an unreadable counter is not a stall", screen.presses == 0,
              "%d press(es)" % screen.presses)

        # Nothing left to spend: the game switches Auto Spend off by
        # itself, so there is nothing to press for either.
        screen.presses = 0
        bot = screen.bot()
        screen.holo = 0
        bot.tick()
        for _ in range(12):
            screen.clock += P.TICK
            bot.tick()
        check("an empty device is not pressed", screen.presses == 0,
              "%d press(es)" % screen.presses)

        # -- the bond token --------------------------------------------
        screen.presses = 0
        screen.taps = []
        bot = screen.bot()
        screen.holo = None
        screen.bubble = {"fx": 0.51, "fy": 0.34}
        bot.tick()
        # No waiting for a second frame: the character can die with the
        # bubble up, and then there is nothing left to collect.
        check("the first sighting already taps the figure",
              len(screen.taps) == 1 and screen.taps[0][0] == 0.439,
              "at %s" % (screen.taps[0][:2],) if screen.taps else "-")
        screen.bubble = None
        screen.clock += P.TICK
        bot.tick()
        # Two seconds between rounds is faster than the game clears the
        # bubble, so a tap is not repeated straight away -- that would be a
        # tap at a token already collected, and it opens the info window.
        screen.taps = []
        bot = screen.bot()
        screen.bubble = {"fx": 0.51, "fy": 0.34}
        bot.tick()
        screen.clock += P.TICK
        bot.tick()
        check("no second tap before the game has answered",
              len(screen.taps) == 1, "%d tap(s) in %.0f s"
              % (len(screen.taps), P.TICK))
        screen.clock += P.BOND_RETRY
        bot.tick()
        check("and one again once it has had its moment",
              len(screen.taps) == 2, "%d tap(s)" % len(screen.taps))

        screen.taps = []
        bot = screen.bot()
        screen.bubble = {"fx": 0.51, "fy": 0.34}
        bot.tick()
        screen.bubble = None
        screen.clock += P.TICK
        bot.tick()
        check("the bubble gone counts as collected",
              any("collected" in m for m in screen.messages))

        # A bubble that survives its taps is given up on rather than
        # hammered -- and it drifts a pixel or two between frames, so the
        # counting must not start over every time it moves.
        screen.taps = []
        bot = screen.bot()
        for n in range(20):
            screen.bubble = {"fx": 0.51 + 0.004 * (n % 3),
                             "fy": 0.34 - 0.004 * (n % 2)}
            screen.clock += max(P.TICK, P.BOND_RETRY)
            bot.tick()
        check("a bubble that will not go is left alone",
              len(screen.taps) == P.BOND_TRIES,
              "%d tap(s)" % len(screen.taps))

        # The chat line, from the bot's side. A bubble low enough that the
        # figure stands behind the bar buys nothing but an open chat window
        # -- and this helper does not close windows the player might have
        # opened, so the one it must not open is the one it must not aim at.
        screen.taps = []
        screen.messages = []
        bot = screen.bot()
        for _ in range(8):
            screen.bubble = {"fx": 0.51, "fy": 0.52}
            screen.clock += max(P.TICK, P.BOND_RETRY)
            bot.tick()
        check("the chat line is never tapped", not screen.taps,
              "%d tap(s)" % len(screen.taps))
        said = [m for m in screen.messages if "behind the chat line" in m]
        check("and the log says why", len(said) == 1,
              "%s" % (said[0].strip() if said else "not said"))

        # -- one tap a round -------------------------------------------
        # A bubble to collect and a counter that has stopped, both in the
        # same round. Two things to do, one tap: the second would be aimed
        # with a picture taken before the first one landed.
        bot = screen.bot()
        screen.holo = 5000
        screen.bubble = None
        bot.tick()
        screen.clock += P.STALL_AFTER + P.TICK
        screen.taps, screen.presses = [], 0
        screen.bubble = {"fx": 0.51, "fy": 0.34}
        bot.tick()
        check("a round taps at most once",
              len(screen.taps) + screen.presses == 1,
              "%d tap(s), %d press(es)" % (len(screen.taps), screen.presses))

        # -- screens that must not be touched --------------------------
        # The back key counts here as much as the taps do. This helper used
        # to close the Partner window for itself, by a tap above it and then
        # by the back key, and it could not tell its own stray window from
        # one the player had just opened -- so it closed theirs as well.
        # Nothing may reach a screen that is not the clear main screen now,
        # by any means, and an open window is one of those screens.
        for name, kw in (("a window over the screen", {"clear": False}),
                         ("the red banner up", {"failed": True})):
            screen.taps, screen.presses, screen.backs = [], 0, 0
            probe = Screen(holo=5000, bubble={"fx": 0.51, "fy": 0.34}, **kw)
            probe.install()
            bot = probe.bot()
            for _ in range(8):
                probe.clock += P.TICK
                bot.tick()
            check("nothing is touched with %s" % name,
                  not probe.taps and not probe.presses and not probe.backs,
                  "%d tap(s), %d press(es), %d back key(s)"
                  % (len(probe.taps), probe.presses, probe.backs))
        screen.install()

        # Whose window is it? The helper opens one itself now and then --
        # it taps a bubble off a single frame, and the token is sometimes
        # already collected -- and that one it must clear away, or it stands
        # behind it for the rest of the day. Any other is the player's, and
        # closing those is what this rule exists to stop: it happened in a
        # live session, once to a window that was not even this one.
        probe = Screen(partner=True)
        probe.install()
        bot = probe.bot()
        for _ in range(8):
            probe.clock += P.TICK
            bot.tick()
        check("a window this did not open is left alone",
              not probe.taps and not probe.presses and not probe.backs
              and any("did not open" in m for m in probe.messages),
              "%d tap(s), %d back key(s)" % (len(probe.taps), probe.backs))

        # ... and the one it did open is tapped away from above. Not with
        # the back key: with no dialog open that key raises "Return to the
        # title screen?", and in a live run it did, three times.
        probe = Screen(bubble={"fx": 0.51, "fy": 0.34})
        probe.install()
        bot = probe.bot()
        bot.tick()                       # taps the figure, may open a window
        probe.taps = []
        probe.bubble, probe.partner = None, True
        probe.clock += P.TICK
        bot.tick()
        check("the window its own tap opened is tapped away",
              probe.backs == 0 and len(probe.taps) == 1
              and probe.taps[0][1] == P.PARTNER_CLOSE[1],
              "%d back key(s), %d tap(s)" % (probe.backs, len(probe.taps)))

        # ... and only a window that will not go gets the back key.
        for _ in range(P.PARTNER_TAPS + 1):
            probe.clock += P.TICK
            bot.tick()
        check("a window that will not go gets the back key at last",
              probe.backs >= 1, "%d back key(s)" % probe.backs)

        # Ownership runs out, and it is not extended by anything. A window
        # that turns up long after the helper's own tap is somebody else's,
        # whatever the recogniser makes of it.
        probe = Screen(bubble={"fx": 0.51, "fy": 0.34})
        probe.install()
        bot = probe.bot()
        bot.tick()
        probe.taps = []
        probe.bubble, probe.partner = None, True
        probe.clock += P.PARTNER_OWN + P.TICK
        for _ in range(4):
            probe.clock += P.TICK
            bot.tick()
        check("ownership runs out, and a late window is left alone",
              not probe.taps and not probe.backs,
              "%d tap(s), %d back key(s)" % (len(probe.taps), probe.backs))
        screen.install()

        # A counter that stays unreadable on a screen that looks right is a
        # bug in the reading, and a kept picture is the only way to look into
        # it afterwards. Finding the last one took a hand-made screenshot.
        probe = Screen(holo=None)
        probe.install()
        bot = probe.bot()
        for _ in range(int(2 * P.BLIND_AFTER / P.TICK)):
            probe.clock += P.TICK
            bot.tick()
        check("an unreadable counter eventually says so",
              any("not been readable" in m for m in probe.messages))
        screen.install()

        # A covered emulator window is named as such. Window capture reads
        # the screen where the window sits, so anything in front of it is
        # what the helper gets -- and "not the plain main screen" is a
        # useless thing to say about a browser.
        class Covered:
            def obscured(self):
                return True

        probe = Screen(clear=False)
        probe.install()
        bot = probe.bot(cap=Covered())
        bot.tick()
        check("a covered emulator window is named",
              any("another window is over the emulator" in m
                  for m in probe.messages))

        # And never on a guess: a capture that cannot tell says nothing.
        class Cannot:
            def obscured(self):
                return None

        probe = Screen(clear=False)
        probe.install()
        bot = probe.bot(cap=Cannot())
        bot.tick()
        check("no claim about the window when it cannot be told",
              not any("another window is over" in m for m in probe.messages))
        screen.install()

        # A blocked round says why it did nothing, and keeps saying so
        # once a minute. Silence is what made the red-background bug look
        # like a helper that had stopped.
        probe = Screen(holo=5000, failed=True)
        probe.install()
        bot = probe.bot()
        for _ in range(int(2 * P.HEARTBEAT / P.TICK)):
            probe.clock += P.TICK
            bot.tick()
        beats = [m for m in probe.messages if "still watching" in m]
        check("a blocked round keeps saying why", len(beats) >= 2,
              "%d line(s) in %d s" % (len(beats), 2 * P.HEARTBEAT))
        screen.install()

        # The counter belongs to the page, not to the Auto Spend box. It
        # used to be read only when that box was ticked, so a player who
        # wanted the bond token alone got "holograms could not be read this
        # round" for every round of the day, on a screen where the game was
        # plainly drawing the number.
        probe = Screen(holo=5000)
        probe.install()
        bot = probe.bot(do_auto=False)
        for _ in range(int(2 * P.STALL_AFTER / P.TICK)):
            probe.clock += P.TICK
            bot.tick()
        check("the counter is read with auto spend off",
              any("holograms 5,000" in m for m in probe.messages),
              "said: %s" % (probe.messages[0] if probe.messages else "nothing"))
        # ... and reading it is all that happens: a stalled counter with the
        # box off must not reach for the button.
        check("and a stalled counter is not pressed for",
              not probe.presses and not probe.taps,
              "%d press(es), %d tap(s)" % (probe.presses, len(probe.taps)))
        # Nor does the helper report on something it is not watching.
        check("and auto spend is not judged with the box off",
              "auto spend not watched" in bot.status()
              and not any("auto spend looks off" in m
                          for m in probe.messages),
              bot.status())
        screen.install()

        # The mouse belongs to whoever is holding it.
        probe = Screen(holo=5000, bubble={"fx": 0.51, "fy": 0.34})
        probe.install()
        bot = probe.bot(may_tap=False)
        for _ in range(10):
            probe.clock += P.TICK
            bot.tick()
        check("with the mouse in use it reads but does not tap",
              not probe.taps and not probe.presses
              and any("holograms" in m for m in probe.messages),
              "%d tap(s), %d press(es)" % (len(probe.taps), probe.presses))
    finally:
        screen.restore()

    print("\n%d of %d cases as expected%s"
          % (ok, total, "" if ok == total else "   <-- SOMETHING FAILED"))


if __name__ == "__main__":
    main()
