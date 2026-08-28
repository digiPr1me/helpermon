"""
Check the Special Summon bot offline, no emulator needed.

Same shape as test_passive_flow.py: painted frames for the readers, a fake
screen for the bot. The readers here lean more on colour than on shape --
the yellow button, the orange mode dot, red versus white price -- so the
paint helpers build small HSV patches and convert them to BGR rather than
picking colours by eye, the same numbers this module's own comments were
measured against.

The bot-level cases (spam, watch_ads, goto_mode) do not paint pixels at
all. A frame there is a plain dict the patched readers hand straight back;
what is under test is the state machine -- stalls, the limit, the Crest
double tap, never pressing the yellow button mid-ad -- not the pixel
readers again.
"""

import cv2
import numpy as np

import dungeon as D
import guard
import summon as S


# ----------------------------------------------------------------------------
# Painting
# ----------------------------------------------------------------------------
BACKGROUND = (235, 225, 210)


def blank(w, h):
    return np.full((h, w, 3), BACKGROUND, np.uint8)


def _bgr(h, s, v):
    """One HSV triple, OpenCV's own scale, converted to BGR for painting.

    So every painted colour is the exact number this module's comments
    measured, not a guess at what "yellow" or "red" looks like in BGR.
    """
    px = np.uint8([[[h, s, v]]])
    b, g, r = cv2.cvtColor(px, cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


YELLOW_LIVE = _bgr(20, 220, 245)
YELLOW_DIM = _bgr(20, 220, 80)
DOT_ORANGE_C = _bgr(10, 200, 250)
DOT_INACTIVE_C = _bgr(112, 90, 180)
RED_C = _bgr(3, 220, 200)
WHITE_C = (235, 235, 235)
BLUE_C = _bgr(100, 200, 220)
GREEN_C = _bgr(78, 200, 220)


def paint_button(img, fx, fy, fw=0.25, fh=0.048, dim=False, half_fill=False):
    x0, y0, gw, gh = D.game_rect(img)
    w, h = int(fw * gw), int(fh * gh)
    x, y = int(x0 + fx * gw - w / 2), int(y0 + fy * gh - h / 2)
    colour = YELLOW_DIM if dim else YELLOW_LIVE
    if half_fill:
        cv2.rectangle(img, (x, y), (x + w // 2, y + h), colour, -1)
    else:
        cv2.rectangle(img, (x, y), (x + w, y + h), colour, -1)
    return {"fx": fx, "fy": fy, "fw": fw, "fh": fh}


def paint_badge(img, fx, fy, fw=0.10, fh=0.03):
    """A rank badge: narrower than a button and never fully filled --
    painted as a thin frame around empty space, the shape summon_button
    must not be fooled by."""
    x0, y0, gw, gh = D.game_rect(img)
    w, h = int(fw * gw), int(fh * gh)
    x, y = int(x0 + fx * gw - w / 2), int(y0 + fy * gh - h / 2)
    cv2.rectangle(img, (x, y), (x + w, y + h), YELLOW_LIVE, max(2, w // 6))
    return img


def paint_dots(img, active, fy=0.28, spacing=0.03):
    """Three small discs in a row, the active one orange."""
    x0, y0, gw, gh = D.game_rect(img)
    radius = max(2, int(0.006 * gw))
    centre_x = 0.49
    for i in range(3):
        fx = centre_x + (i - 1) * spacing
        colour = DOT_ORANGE_C if i == active - 1 else DOT_INACTIVE_C
        cv2.circle(img, (int(x0 + fx * gw), int(y0 + fy * gh)), radius,
                   colour, -1)
    return img


def paint_tabs(img, fy=0.135, fw=0.243, fh=0.031, fill=0.766):
    """The General / Buddy tab pair, at the size it really measures.

    The defaults are the live measurement from
    debug_summon/live_after_summon_tap.png and from the ADB-shaped frame of
    the same screen: both tabs 0.243 wide and 0.031 tall, General at 0.162,
    Buddy at 0.464.

    `fill` is the part that matters and the part a first version of this
    helper got wrong. A tab is not a solid block of colour -- its label is
    not in the colour mask -- and the real ones cover 0.785 of their own
    box once find_buttons has closed the mask. Painted solid they measure
    0.0076 of the window space, comfortably over the area floor the live
    run actually fell through at 0.0058. A test that paints them solid
    passes either way and proves nothing.

    The label is not painted as holes, which was the obvious next idea and
    does not work: find_buttons closes the mask with a 15 px wide kernel,
    so any hole narrower than that fills straight back in, and how much of
    it survives then depends on the frame size -- the helper would be
    faking a different fill at every window size. What is painted instead
    is a solid rectangle of the full measured width and of the height that
    leaves the real mask area behind.

    `fill` is set from the ADB measurement, 0.00577 of the window space,
    rather than the window one at 0.00613 -- the smaller of the two, so
    the test asserts the harder case instead of landing between them.

    The rectangle is drawn a pixel short in each direction because
    cv2.rectangle includes both corners. On a 32 px tall tab that pixel is
    3 % of the area, and it was enough to carry the painted tab back over
    the old floor at one frame size but not the other: a regression test
    that caught the bug or missed it depending on how int() rounded.
    """
    x0, y0, gw, gh = D.game_rect(img)
    w, h = int(fw * gw), max(1, int(fh * fill * gh))
    for fx, colour in ((0.162, BLUE_C), (0.464, GREEN_C)):
        x, y = int(x0 + fx * gw - w / 2), int(y0 + fy * gh - h / 2)
        cv2.rectangle(img, (x, y), (x + w - 1, y + h - 1), colour, -1)
    return img


def paint_blob(img, fx, fy, fw, fh, colour):
    """One solid patch, for the artwork a recogniser must not fall for."""
    x0, y0, gw, gh = D.game_rect(img)
    w, h = max(2, int(fw * gw)), max(2, int(fh * gh))
    x, y = int(x0 + fx * gw - w / 2), int(y0 + fy * gh - h / 2)
    cv2.rectangle(img, (x, y), (x + w, y + h), colour, -1)
    return img


EXIT_PLATE_C = (250, 250, 250)
EXIT_MARK_C = _bgr(108, 165, 213)
# What is behind the button when the button is not there. Deliberately a
# colour that is neither: at S 60 it is too saturated for the plate's mask
# (S <= 45) and too pale for the mark's (S >= 110), so a frame painted with
# `plate=False` fails on the missing plate and on nothing else. This module's
# own BACKGROUND cannot stand in for it -- at S 27 V 235 it reads as plate,
# which is what made the first version of this case pass for no reason.
EXIT_SKY_C = _bgr(105, 60, 250)


def paint_exit_x(img, fx=None, fy=None, plate=True, mark=True):
    """The white plate with its blue X, in the corner where the real one is.

    Painted as a plate with a stroked X across it rather than a solid
    patch, because the thresholds it has to clear are shares of a crop:
    the real button fills 0.75 of that crop with plate and 0.21 with
    mark, and a solid block of either colour would sail through a floor
    it was meant to fall below. Measured back out of exit_button below,
    which is the only reason these two arguments exist -- `plate=False`
    and `mark=False` are the two halves on their own, and neither may be
    enough.
    """
    x0, y0, gw, gh = D.game_rect(img)
    fx = S.EXIT_BUTTON_FX if fx is None else fx
    fy = S.EXIT_BUTTON_FY if fy is None else fy
    half = int(0.5 * S.EXIT_BUTTON_FW * gw)
    cx, cy = int(x0 + fx * gw), int(y0 + fy * gh)
    cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half),
                  EXIT_PLATE_C if plate else EXIT_SKY_C, -1)
    if mark:
        # 0.42 of the plate either side of centre, stroked at 0.18 of it.
        # Measured back out of exit_button over four window shapes: plate
        # 0.749 to 0.833, mark 0.167 to 0.251, against the game's own
        # 0.749 to 0.760 and 0.211 to 0.226. It straddles rather than
        # matches because the stroke is a whole number of pixels and the
        # windows are not multiples of each other -- which is the useful
        # half of the accident: the painted button is off the real one in
        # both directions, and the bands have to hold either way.
        arm = int(0.42 * half)
        thick = max(1, int(0.18 * half))
        cv2.line(img, (cx - arm, cy - arm), (cx + arm, cy + arm),
                 EXIT_MARK_C, thick)
        cv2.line(img, (cx - arm, cy + arm), (cx + arm, cy - arm),
                 EXIT_MARK_C, thick)
    return img


FONT = cv2.FONT_HERSHEY_DUPLEX


def paint_price(img, button, colour):
    x0, y0, gw, gh = D.game_rect(img)
    cx = x0 + button["fx"] * gw
    top = y0 + (button["fy"] - button["fh"] / 2.0) * gh
    scale = 0.55 * (gh / 1390.0)
    size = cv2.getTextSize("30", FONT, scale, 1)[0]
    org = (int(cx - size[0] / 2.0), int(top - 0.015 * gh))
    cv2.putText(img, "30", org, FONT, scale, colour, 1, cv2.LINE_AA)
    return img


def paint_ticket_badge(img, fx, fy, text, scale_mul=1.0):
    """White digits on a dark badge, the top-right currency counter.

    text avoids the digits 4 and 9: OpenCV's own font draws those two
    differently from the game's, and dungeon.read_digit was measured
    against the game's shapes. See test_passive_flow.py's own note on the
    same limitation -- what is under test here is this module's crop and
    grouping, not the shared digit reader.
    """
    x0, y0, gw, gh = D.game_rect(img)
    # Scaled so the digits come out about the same share of the crop's own
    # height as the game's do -- measured live, digit height 0.11 of the
    # crop. A smaller scale drew a comma under TICKET_MIN_H, real on the
    # game's own font but not on OpenCV's wider one at this size.
    scale = scale_mul * 0.85 * (gh / 1390.0)
    size = cv2.getTextSize(text, FONT, scale, 1)[0]
    pad = int(0.01 * gw)
    left = int(x0 + fx * gw)
    top = int(y0 + fy * gh)
    cv2.rectangle(img, (left - pad, top - size[1] - pad),
                  (left + size[0] + pad, top + pad), (70, 60, 55), -1)
    cv2.putText(img, text, (left, top), FONT, scale, (250, 250, 250), 1,
               cv2.LINE_AA)
    if "," in text:
        before = cv2.getTextSize(text.split(",")[0], FONT, scale, 1)[0][0]
        digit_h = 0.71 * cv2.getTextSize("0", FONT, scale, 1)[0][1]
        rows = max(2, int(round(0.4 * digit_h)))
        width = max(1, int(round(0.09 * digit_h)))
        cv2.rectangle(img, (left + before, top - rows + 1),
                      (left + before + width - 1, top), (250, 250, 250), -1)
    return img


# ----------------------------------------------------------------------------
# The scripted bot harness -- no pixels, plain dicts
# ----------------------------------------------------------------------------
BUTTON = {"fx": 0.75, "fy": 0.885, "fw": 0.25, "fh": 0.048}
RESULT_BUTTON = {"fx": 0.61, "fy": 0.96, "fw": 0.25, "fh": 0.05}
ADS_BUTTON = {"fx": 0.21, "fy": 0.885, "fw": 0.17, "fh": 0.046}


def F(**kw):
    base = {"button": None, "mode": None, "tickets": None, "red": False,
            "ads": None, "ads_button": None, "general": None,
            "main_clear": True, "failed": False, "exit": False}
    base.update(kw)
    return base


def round_frames(before, after, button=BUTTON, red=False):
    """One spam() round: the pre-tap reading, then the settled result,
    pushed twice so _wait_button_back's two-consecutive-frames rule is
    satisfied without depending on the queue running dry."""
    b = F(button=button, tickets=before, red=red)
    a = F(button=button, tickets=after)
    return [b, a, a]


class Screen:
    """A queue of frames; grab() pops one and keeps repeating the last
    once the queue is empty, the way a settled screen keeps looking the
    same on every further read."""

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

    def install(self):
        self.saved = (S.summon_button, S.mode_dots, S.ticket_counter,
                      S.price_is_red, S.ads_left, S.view_ads_button,
                      S.general_tab, S.exit_button, D.stage_failed,
                      D.auto_button)
        S.summon_button = lambda img: img["button"]
        S.mode_dots = lambda img: img["mode"]
        S.ticket_counter = lambda img: img["tickets"]
        S.price_is_red = lambda img, button: img["red"]
        S.ads_left = lambda img, button=None: img["ads"]
        S.view_ads_button = lambda img, button=None: img["ads_button"]
        S.general_tab = lambda img: img["general"]
        S.exit_button = lambda img: ({"fx": S.EXIT_BUTTON_FX,
                                      "fy": S.EXIT_BUTTON_FY,
                                      "plate": 0.75, "mark": 0.21}
                                     if img["exit"] else None)
        D.stage_failed = lambda img: img["failed"]
        D.auto_button = lambda img: ({"fx": 0.36, "fy": 0.77}
                                     if img["main_clear"] else None)

    def restore(self):
        (S.summon_button, S.mode_dots, S.ticket_counter, S.price_is_red,
         S.ads_left, S.view_ads_button, S.general_tab, S.exit_button,
         D.stage_failed, D.auto_button) = self.saved

    def bot(self, **kw):
        bot = S.SummonBot.__new__(S.SummonBot)
        bot.cap = None
        bot.dry_run = kw.get("dry_run", False)
        bot.log = kw.get("log", lambda t: None)
        bot.enabled = kw.get("enabled", {m: True for m in S.MODE_ORDER})
        bot.watch_ads_first = kw.get("watch_ads_first", True)
        bot.max_per_mode = kw.get("max_per_mode", 0)
        bot.patience = 0.0
        bot.stall_limit = kw.get("stall_limit", 3)
        bot.blind_limit = kw.get("blind_limit", 3)
        bot._aborted_said = False
        bot.debugdir = "debug_summon"
        bot.control = guard.Stop()
        bot.stats = {"summons": 0, "ads": 0, "modes_done": 0,
                    "modes_skipped": 0}
        bot._dumps = 99            # never actually write a debug frame
        screen = self

        class Inner:
            pause_long = 0.0
            pause_short = 0.0

            def grab(self):
                return screen.grab()

            def tap(self, fx, fy, was=""):
                # The same guard DungeonBot.tap itself has: a dry run logs
                # and does not click. Mirrored here rather than delegated,
                # since the fake stands in for that bot in every test.
                if not bot.dry_run:
                    screen.taps.append((round(fx, 3), round(fy, 3), was))

        bot.bot = Inner()
        return bot


# ----------------------------------------------------------------------------
def main():
    ok = total = 0

    def check(name, good, detail=""):
        nonlocal ok, total
        total += 1
        ok += bool(good)
        print("%-58s %-24s %s" % (name, detail, "ok" if good else "FAILED"))

    # -- summon_button, painted ------------------------------------------
    img = blank(759, 1387)
    paint_button(img, 0.61, 0.96)
    found = S.summon_button(img)
    check("summon_button finds a painted live button", found is not None
          and abs(found["fx"] - 0.61) < 0.01, found)

    check("summon_button finds nothing on an empty screen",
          S.summon_button(blank(759, 1387)) is None)

    img = blank(759, 1387)
    paint_button(img, 0.75, 0.66, dim=True)
    paint_button(img, 0.50, 0.50)
    found = S.summon_button(img)
    check("summon_button picks the bright one, not the dimmed one",
          found is not None and abs(found["fx"] - 0.50) < 0.01, found)

    img = blank(759, 1387)
    paint_badge(img, 0.75, 0.60)
    check("summon_button is not fooled by a narrow rank badge",
          S.summon_button(img) is None)

    img = blank(759, 1387)
    paint_button(img, 0.61, 0.96, half_fill=True)
    check("summon_button is not fooled by a half-filled button-width shape",
          S.summon_button(img) is None)

    # -- general_tab, painted, from both frame sources ---------------------
    # The pair of shapes is the point of this block, not either one alone.
    # 736 x 1392 is a window frame, 1080 x 1920 is what ADB delivers, and
    # the tabs measure the same fraction of the game on both. They did not
    # read the same: the area floor stood at 0.006 of the reference window
    # while the tabs themselves measure 0.0058 to 0.0061, so the window
    # frame cleared it by 2 % and the ADB frame missed it by 1 to 4 %. Every
    # painted test passed and the first live run never got past the entry
    # screen.
    for w, h in ((736, 1392), (1080, 1920)):
        img = blank(w, h)
        paint_tabs(img)
        found = S.general_tab(img)
        check("general_tab finds General at %dx%d" % (w, h),
              found is not None and abs(found["fx"] - 0.162) < 0.02,
              "fx %s" % (round(found["fx"], 3) if found else None))

    img = blank(1080, 1920)
    paint_button(img, 0.35, 0.88, fw=0.214, fh=0.048)
    paint_blob(img, 0.35, 0.88, 0.214, 0.048, BLUE_C)
    check("general_tab does not take a lone blue button for General",
          S.general_tab(img) is None)

    # -- mode_dots, painted, two window sizes -----------------------------
    for w, h in ((759, 1387), (619, 1132)):
        for active in (1, 2, 3):
            img = blank(w, h)
            paint_dots(img, active)
            got = S.mode_dots(img)
            check("mode_dots reads %d at %dx%d" % (active, w, h),
                  got == active, "read %s" % got)

    check("mode_dots is None with no dots painted",
          S.mode_dots(blank(759, 1387)) is None)

    # The Buddy tab: one banner, so one orange dot and no companions, with
    # banner artwork around it. The reader used to take the first orange
    # blob that had two neighbours of any size at any spacing and answered
    # "mode 2" for a screen that has no modes at all -- which would have
    # sent goto_mode tapping at neighbour banners that are not there.
    img = blank(759, 1387)
    x0, y0, gw, gh = D.game_rect(img)
    radius = max(2, int(0.006 * gw))
    cv2.circle(img, (int(x0 + 0.49 * gw), int(y0 + 0.26 * gh)), radius,
               DOT_ORANGE_C, -1)
    check("mode_dots is None for a single dot",
          S.mode_dots(img) is None, "read %s" % S.mode_dots(img))

    # The three blobs that actually formed the false row, measured off
    # debug_summon/summon-new-banner-1.png: 54 x 28, 111 x 70 and 12 x 16
    # at centres 21, 15 and 12 px apart in y. The big one is painted first
    # so the small orange one survives on top of it, the way two separate
    # colour masks behave on the real frame.
    img = blank(759, 1387)
    paint_blob(img, 0.404, 0.205, 0.138, 0.050, DOT_INACTIVE_C)
    paint_blob(img, 0.538, 0.202, 0.015, 0.012, DOT_INACTIVE_C)
    paint_blob(img, 0.481, 0.190, 0.067, 0.020, DOT_ORANGE_C)
    got = S.mode_dots(img)
    check("mode_dots is None for the Buddy tab's false row",
          got is None, "read %s" % got)

    # -- the price, painted ------------------------------------------------
    img = blank(759, 1387)
    button = paint_button(img, 0.61, 0.96)
    paint_price(img, button, RED_C)
    check("a red price reads as red", S.price_is_red(img, button))

    img = blank(759, 1387)
    button = paint_button(img, 0.61, 0.96)
    paint_price(img, button, WHITE_C)
    check("a white price does not read as red",
          not S.price_is_red(img, button))

    img = blank(759, 1387)
    button = paint_button(img, 0.61, 0.96)
    paint_price(img, button, BLUE_C)
    check("a dark-blue price does not read as red",
          not S.price_is_red(img, button))

    # -- the ticket counter, painted ---------------------------------------
    img = blank(759, 1387)
    paint_ticket_badge(img, 0.68, 0.30, "2,305")
    check("ticket_counter reads a number with a comma",
          S.ticket_counter(img) == 2305, S.ticket_counter(img))

    # The currency icon carries a small white mark inside it, and it lands
    # in the same white mask as the digits. Every box below is measured off
    # debug_summon/stalled_00.png, the frame the live run could not read:
    # the mark came out 14 x 20 against digits of 87 to 88, cleared the
    # crop-relative height floor by three pixels, joined the row as a sixth
    # character and left "2,739" unreadable for three rounds running.
    #
    # Built as a mask rather than painted with a font on purpose. The point
    # here is the size filter, and OpenCV's own font does not hold the
    # game's proportions closely enough to put the mark on the right side
    # of a three-pixel margin -- a painted version of this passed against
    # the broken filter too, which is no test at all.
    mask = np.zeros((564, 1100), np.uint8)
    boxes = [(518, 133, 56, 87), (586, 200, 22, 37), (627, 136, 62, 85),
             (701, 133, 57, 88), (770, 133, 63, 88)]
    icon_mark = (393, 168, 14, 20)
    for x, y, w, h in boxes + [icon_mark]:
        mask[y:y + h, x:x + w] = 255
    kept = S._ticket_glyphs(mask)
    check("the mark inside the currency icon is not taken for a character",
          len(kept) == len(boxes)
          and all((g[2], g[3]) != icon_mark[2:] for g in kept),
          "kept %d of %d" % (len(kept), len(boxes) + 1))

    # And the other half of the same story: one character on its own is not
    # a number. On the draw animation, where no badge is on screen at all, a
    # lone blob parsed as "7" and was returned -- and a made-up count is
    # worse than an admitted None, because the loop compares it against the
    # round before to decide what happened.
    img = blank(759, 1387)
    paint_ticket_badge(img, 0.68, 0.30, "7")
    check("ticket_counter reads nothing from a single character",
          S.ticket_counter(img) is None, S.ticket_counter(img))

    # A number of the wrong size is not the counter. Two stray marks in the
    # result band read as "77" during a live run -- their characters
    # measured 0.0048 of the game height against the badge's own 0.0107 to
    # 0.0112 -- the loop took 77 for the count, and the next perfectly good
    # 2,199 then looked like the number going up and stopped the mode.
    img = blank(759, 1387)
    paint_ticket_badge(img, 0.68, 0.30, "23", scale_mul=0.45)
    check("ticket_counter refuses a number of the wrong size",
          S.ticket_counter(img) is None, S.ticket_counter(img))

    img = blank(759, 1387)
    paint_ticket_badge(img, 0.68, 0.30, "23")
    check("ticket_counter reads a short number",
          S.ticket_counter(img) == 23, S.ticket_counter(img))

    # -- the exit X is read from the picture ---------------------------
    for w, h in ((573, 1056), (805, 1390), (1080, 1920)):
        img = paint_exit_x(blank(w, h))
        found = S.exit_button(img)
        check("the exit X is found at %d x %d" % (w, h),
              found is not None
              and abs(found["fx"] - S.EXIT_BUTTON_FX) < 0.001
              and abs(found["fy"] - S.EXIT_BUTTON_FY) < 0.001,
              "found" if found else "missed")

    # Each half alone, because either one on its own is ordinary
    # furniture: white plates are everywhere, and the plain main
    # screen measures 0.189 of the mark's own blue at this very spot.
    plate_only = paint_exit_x(blank(805, 1390), mark=False)
    check("a plate with no X on it is not the exit button",
          S.exit_button(plate_only) is None,
          "%s" % S.exit_button(plate_only))
    mark_only = paint_exit_x(blank(805, 1390), plate=False)
    check("a blue X with no plate under it is not the exit button",
          S.exit_button(mark_only) is None,
          "%s" % S.exit_button(mark_only))
    # And the position is part of the recognition, not an afterthought:
    # the same button drawn a tenth of the width away is not it.
    elsewhere = paint_exit_x(blank(805, 1390),
                             fx=S.EXIT_BUTTON_FX - 0.10)
    check("the exit X is not found where it does not belong",
          S.exit_button(elsewhere) is None,
          "%s" % S.exit_button(elsewhere))

    # -- the loop stops at a red price --------------------------------------
    screen = Screen()
    screen.install()
    try:
        screen.push(F(button=BUTTON, tickets=999, red=True))
        bot = screen.bot()
        done = bot.spam(S.SKILL)
        check("spam stops at once on a red price",
              done == 0 and not screen.taps,
              "%d done, %d tap(s)" % (done, len(screen.taps)))

        # -- the loop stops at the reached limit ---------------------------
        screen = Screen()
        screen.install()
        screen.push(*round_frames(100, 70))
        screen.push(*round_frames(70, 40))
        screen.push(F(button=BUTTON, tickets=40, red=False))
        bot = screen.bot(max_per_mode=2)
        done = bot.spam(S.SKILL)
        summon_taps = [t for t in screen.taps if t[2] == "summon"]
        check("spam stops at the reached limit",
              done == 2 and len(summon_taps) == 2,
              "%d done, %d summon tap(s)" % (done, len(summon_taps)))

        # -- the loop stops when the count does not fall 3 times ----------
        screen = Screen()
        screen.install()
        for _ in range(3):
            screen.push(*round_frames(50, 50))
        bot = screen.bot(stall_limit=3)
        done = bot.spam(S.SKILL)
        summon_taps = [t for t in screen.taps if t[2] == "summon"]
        check("spam stops after 3 rounds with no fall",
              done == 0 and len(summon_taps) == 3,
              "%d done, %d summon tap(s)" % (done, len(summon_taps)))

        # -- but an unreadable count is not a stall, it has its own limit --
        screen = Screen()
        screen.install()
        for _ in range(4):
            screen.push(*round_frames(None, None))
        bot = screen.bot(stall_limit=3, blind_limit=3)
        done = bot.spam(S.SKILL)
        check("spam gives up after 3 rounds with no count anywhere",
              done == 0 and len([t for t in screen.taps if t[2] == "summon"]) == 3,
              "%d done, %d summon tap(s)"
              % (done, len([t for t in screen.taps if t[2] == "summon"])))

        # -- the animation is tapped along while no button is on screen ---
        screen = Screen()
        screen.install()
        screen.push(F(button=None), F(button=None), F(button=None))
        screen.push(F(button=BUTTON), F(button=BUTTON))
        bot = screen.bot()
        got = bot._wait_button_back(timeout=5.0)
        hurry = [t for t in screen.taps if t[2] == "hurry the animation"]
        check("the draw animation is tapped along while it runs",
              got is not None and hurry,
              "%d tap(s) while no button was on screen" % len(hurry))
        check("none of those taps lands near the button row",
              all(t[1] <= 0.2 for t in hurry),
              "lowest at fy %s" % (max(t[1] for t in hurry) if hurry else None))

        # A Crest round must not be tapped along at all. The confirmation
        # dialog takes a moment to draw, and during that moment there is no
        # button on screen either -- a tap sent into that gap lands beside
        # the dialog and closes it. Live, that left the count at 388 for
        # three rounds and gave the mode up.
        screen = Screen()
        screen.install()
        screen.push(F(button=BUTTON, tickets=398))
        screen.push(F(button=None), F(button=None), F(button=None))
        screen.push(F(button=BUTTON, tickets=None),
                    F(button=BUTTON, tickets=None))
        screen.push(F(button=BUTTON, tickets=None))
        screen.push(F(button=BUTTON, tickets=388),
                    F(button=BUTTON, tickets=388))
        screen.push(F(button=BUTTON, tickets=388, red=True))
        bot = screen.bot()
        done = bot.spam(S.CREST)
        hurry = [t for t in screen.taps if t[2] == "hurry the animation"]
        check("a Crest round is never tapped along beside its dialog",
              done == 1 and not hurry,
              "%d done, %d hurry tap(s)" % (done, len(hurry)))

        # -- the Stop button in the launcher, and F8 -----------------------
        # Both do exactly one thing: set the flag on the bot's control. The
        # gate used to ask wait_while_paused alone, which answers only the
        # pause question and returns "go on" whenever the bot is not paused
        # -- so a stop that arrived while it was running was never seen and
        # the run could only be ended by closing the console.
        screen = Screen()
        screen.install()
        for _ in range(3):
            screen.push(*round_frames(100, 70))
        bot = screen.bot()
        bot.control.request("stop from the launcher")
        done = bot.spam(S.SKILL)
        check("a stop request ends spam without another tap",
              done == 0 and not screen.taps,
              "%d done, %d tap(s)" % (done, len(screen.taps)))

        # -- a Crest round with a dialog counts once, not twice -----------
        screen = Screen()
        screen.install()
        # The dialog does not leave the count unchanged, it makes it
        # unreadable: it dims the badge behind it out of the white mask.
        # Measured on Screenshot 2026-08-25 213248.png and 213301.png,
        # both of which ticket_counter answers None for, correctly. The
        # first version of this case modelled the step as 496 -> 496, so
        # it passed while the live loop counted the same step as a stall
        # and gave the mode up after three of them.
        screen.push(*round_frames(496, None))    # opens the dialog
        screen.push(*round_frames(None, 486))    # confirms the draw
        screen.push(F(button=BUTTON, tickets=486, red=True))
        bot = screen.bot(stall_limit=3)
        done = bot.spam(S.CREST)
        check("a Crest round with a dialog step counts as one summon",
              done == 1, "%d done" % done)

        # -- the ad phase: falling counter, never the yellow button --------
        screen = Screen()
        screen.install()
        screen.push(F(ads=2, ads_button=ADS_BUTTON))              # 1
        screen.push(F(ads=2, ads_button=ADS_BUTTON))               # tap 1
        screen.push(F(button=RESULT_BUTTON))                       # settle
        screen.push(F(button=RESULT_BUTTON))
        screen.push(F(mode=1))                                     # back_to_main
        screen.push(F(ads=1))                                      # re-check
        screen.push(F(ads=1, ads_button=ADS_BUTTON))               # tap 2
        screen.push(F(button=RESULT_BUTTON))
        screen.push(F(button=RESULT_BUTTON))
        screen.push(F(mode=1))
        screen.push(F(ads=0))
        bot = screen.bot()
        bot.watch_ads(S.SKILL)
        ad_taps = [t for t in screen.taps if t[0] == ADS_BUTTON["fx"]]
        button_taps = [t for t in screen.taps
                      if t[0] in (BUTTON["fx"], RESULT_BUTTON["fx"])]
        check("the ad phase watches both free ads",
              len(ad_taps) == 2 and bot.stats["ads"] == 2,
              "%d ad tap(s), stats %s" % (len(ad_taps), bot.stats))
        hurry = [t for t in screen.taps if t[2] == "hurry the animation"]
        check("the ad phase never taps into the ad itself",
              not hurry,
              "%d tap(s) during the ad" % len(hurry))
        check("the ad phase never presses the yellow summon button",
              not button_taps, "%d button tap(s)" % len(button_taps))

        # -- goto_mode gives up after three failed attempts -----------------
        screen = Screen()
        screen.install()
        screen.push(F(mode=1))
        for _ in range(3):
            screen.push(F(mode=1))          # the dots never move
        bot = screen.bot()
        ok_move = bot.goto_mode(S.CREST)
        check("goto_mode gives up after 3 tries",
              ok_move is False and len(screen.taps) == 3,
              "%s, %d tap(s)" % (ok_move, len(screen.taps)))

        # -- leaving: the X pops one screen at a time ----------------------
        screen = Screen()
        screen.install()
        # A result screen, then the mode screen, then the game itself.
        screen.push(F(exit=True, main_clear=False),
                    F(exit=True, main_clear=False),
                    F(main_clear=True))
        bot = screen.bot()
        left = bot.leave_summons()
        exits = [t for t in screen.taps if t[2] == "X to close Special Summon"]
        check("leave_summons taps the X until the main screen is back",
              left is True and len(exits) == 2,
              "%s, %d tap(s)" % (left, len(exits)))

        # -- already home, so nothing to close -----------------------------
        screen = Screen()
        screen.install()
        screen.push(F(main_clear=True))
        bot = screen.bot()
        left = bot.leave_summons()
        check("leave_summons taps nothing on the main screen",
              left is True and not screen.taps,
              "%s, %d tap(s)" % (left, len(screen.taps)))

        # -- an unknown screen is not tapped at ----------------------------
        # No X and no auto button: a battle, a dialog, somebody else's ad.
        # The one wrong answer here is to start clicking at the corner
        # anyway, which is how the stray tap in debug_summon happened.
        screen = Screen()
        screen.install()
        screen.push(F(exit=False, main_clear=False))
        bot = screen.bot()
        left = bot.leave_summons()
        check("leave_summons clicks nothing on a screen it cannot place",
              left is False and not screen.taps,
              "%s, %d tap(s)" % (left, len(screen.taps)))

        # -- and it gives up rather than tapping forever -------------------
        screen = Screen()
        screen.install()
        screen.push(F(exit=True, main_clear=False))
        bot = screen.bot()
        left = bot.leave_summons()
        exits = [t for t in screen.taps if t[2] == "X to close Special Summon"]
        check("leave_summons stops after %d fruitless taps" % S.EXIT_TAPS_MAX,
              left is False and len(exits) == S.EXIT_TAPS_MAX,
              "%s, %d tap(s)" % (left, len(exits)))

        # -- a dry run plans the way out and clicks nothing ----------------
        screen = Screen()
        screen.install()
        screen.push(F(exit=True, main_clear=False))
        bot = screen.bot(dry_run=True)
        bot.leave_summons()
        check("a dry run does not click its way out either", not screen.taps,
              "%d tap(s)" % len(screen.taps))

        # -- every way out of run() ends on the main screen -----------------
        # The run that never got in. open_summons refuses on a screen that
        # is not the plain main screen -- and the commonest reason for that
        # is Special Summon still standing open from the run before, which
        # is exactly the screen this has to close.
        screen = Screen()
        screen.install()
        screen.push(F(exit=True, main_clear=False),
                    F(exit=True, main_clear=False),
                    F(main_clear=True))
        bot = screen.bot()
        bot.run()
        exits = [t for t in screen.taps if t[2] == "X to close Special Summon"]
        check("a run that never opened Special Summon still walks out",
              len(exits) >= 1, "%d tap(s)" % len(exits))

        # A run stopped by the Stop button, at the gate between two modes.
        # leave_summons must not consult that flag: it is set, and walking
        # out is the one step that still has to happen. open_summons is
        # stubbed past so that the frames below are the ones leave_summons
        # sees -- otherwise the case measures which frame open_summons ate
        # on its way to refusing, which is not what it is asking about.
        screen = Screen()
        screen.install()
        screen.push(F(exit=True, main_clear=False), F(main_clear=True))
        bot = screen.bot()
        bot.open_summons = lambda: True
        bot.control.request("test")
        bot.run()
        exits = [t for t in screen.taps if t[2] == "X to close Special Summon"]
        check("a stopped run still walks back to the main screen",
              len(exits) == 1, "%d tap(s)" % len(exits))

        # And a run that threw. The stats are lost either way; the screen
        # the player comes back to should not be.
        screen = Screen()
        screen.install()
        screen.push(F(exit=True, main_clear=False), F(main_clear=True))
        bot = screen.bot()
        bot.open_summons = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            bot.run()
            threw = False
        except RuntimeError:
            threw = True
        exits = [t for t in screen.taps if t[2] == "X to close Special Summon"]
        check("a run that threw still walks back to the main screen",
              threw and len(exits) == 1,
              "raised %s, %d tap(s)" % (threw, len(exits)))

        # -- a dry run demonstrably clicks nothing --------------------------
        screen = Screen()
        screen.install()
        screen.push(*round_frames(100, 70))
        screen.push(F(button=BUTTON, tickets=70, red=True))
        bot = screen.bot(dry_run=True)
        done = bot.spam(S.SKILL)
        check("a dry run clicks nothing", not screen.taps,
              "%d tap(s)" % len(screen.taps))
    finally:
        screen.restore()

    print("\n%d of %d cases as expected%s"
          % (ok, total, "" if ok == total else "   <-- SOMETHING FAILED"))


if __name__ == "__main__":
    main()
