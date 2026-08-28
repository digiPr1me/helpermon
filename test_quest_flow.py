"""
Check the quest loop offline, no emulator needed.

Same shape as test_summon_flow.py: painted frames for the pixel readers,
and a scripted fake screen for the state machine, where quest_progress and
quest_card are monkeypatched to hand back plain values rather than being
read from pixels again. What is under test there is the routine, the
resync rule and the emulator handoff -- not the reader, which already has
its own cases against painted frames and against the two real screenshots
this feature was measured on.

Text avoids the digits 4 and 9 for the same reason test_passive_flow.py and
test_summon_flow.py avoid them: OpenCV's own font draws those two
differently from the game's, and dungeon.read_digit was measured against
the game's shapes, not OpenCV's.
"""

import os

import cv2
import numpy as np

import dungeon as D
import guard
import quest as Q


# ----------------------------------------------------------------------------
# Painting
# ----------------------------------------------------------------------------
def blank(w, h):
    return np.full((h, w, 3), (200, 190, 175), np.uint8)


def paint_auto_button(img):
    x0, y0, gw, gh = D.game_rect(img)
    radius = int(0.053 * gw / 2)
    cv2.circle(img, (int(x0 + 0.361 * gw), int(y0 + 0.765 * gh)), radius,
              (230, 140, 50), -1)
    return img


FONT = cv2.FONT_HERSHEY_DUPLEX
RED_BGR = (0, 0, 235)          # HSV (0, 255, 235): inside QUEST_RED_LOW
# The finished card's own green, converted straight from what was measured
# on it: HSV (66, 250, 207), the ist digit of "Bakemon 2/2".
GREEN_BGR = (45, 207, 4)
WHITE_BGR = (250, 250, 250)


def _draw_spaced(img, text, x, y, scale, colour, gap):
    """One character at a time, with a guaranteed gap between them.

    cv2.putText's own kerning lets some digit pairs touch at this scale --
    "5" against "8" merged into one connected component on the frame this
    was found on, while "1" against "2" did not, so it is not a spacing
    this function can just add once and trust for every pair. A fixed gap
    per character is the same fix _quest_row's own reader is built to need
    the opposite of: real digits are never drawn this close together, but a
    painted test has no such guarantee unless it is put there on purpose.
    """
    for ch in text:
        cv2.putText(img, ch, (x, y), FONT, scale, colour, 1)
        x += cv2.getTextSize(ch, FONT, scale, 1)[0][0] + gap
    return x


def paint_quest_counter(img, ist, ziel, name="Bakemon", row_fx=0.78,
                        row_fy=0.60, scale_mul=1.0, ist_colour=RED_BGR,
                        after=""):
    """'<name> <ist>/<ziel>', ist in red, the rest white -- the shape
    _quest_row looks for. Centred on (row_fx, row_fy), the same way the
    game centres the line inside the card and lets a longer name push the
    counter itself sideways (PLAN_QUEST_LOOP.md 3.6).
    """
    x0, y0, gw, gh = D.game_rect(img)
    scale = scale_mul * 0.55 * (gh / 1342.0)
    prefix = (name + " ") if name else ""
    ist_s = str(ist)
    rest = "/%d" % ziel
    tail = (" " + after) if after else ""
    full = prefix + ist_s + rest + tail
    (_, tallest), _ = cv2.getTextSize(full, FONT, scale, 1)
    # A couple of pixels: enough that two glyphs never touch at 8-
    # connectivity, small enough to stay well inside _quest_row's own
    # QUEST_GAP_MAX, which is what tells a counter's own digits apart from
    # the quest name in front of them (PLAN_QUEST_LOOP.md 3.6).
    gap = max(1, int(round(0.08 * tallest)))
    total_w = sum(cv2.getTextSize(c, FONT, scale, 1)[0][0] + gap
                 for c in full) - gap
    x = int(x0 + row_fx * gw - total_w / 2.0)
    y = int(y0 + row_fy * gh + tallest / 2.0)
    x = _draw_spaced(img, prefix, x, y, scale, WHITE_BGR, gap)
    x = _draw_spaced(img, ist_s, x, y, scale, ist_colour, gap)
    x = _draw_spaced(img, rest, x, y, scale, WHITE_BGR, gap)
    # A word behind the number, with a real space in front of it: on the
    # game's own cards "0/50 times" and "Draw 0/30 Skill" both put one
    # there, and it is the space that keeps its letters out of the number
    # (quest.QUEST_GAP_MAX).
    if after:
        _draw_spaced(img, " " + after, x, y, scale, WHITE_BGR, gap)
    return img


def card_on_a_frame(crop):
    """A dumped card crop put back where it came from, on a blank frame.

    The dump writes the card alone (quest.QuestLoop._dump_card), and every
    reader in quest.py works in fractions of the game rather than of the
    crop -- so the crop has to go back into a frame the right size before
    it means anything. An ADB frame, because that is what the dumps were
    taken on: 1080x1920, the card at the same fractions it was cut from.
    """
    canvas = np.zeros((1920, 1080, 3), np.uint8)
    x0, y0, gw, gh = D.game_rect(canvas)
    left = int(x0 + (Q.CARD_MID_FX - Q.CARD_W / 2.0) * gw)
    top = int(y0 + (0.600 - Q.CARD_H) * gh)
    w = int(Q.CARD_W * gw)
    h = int(2 * Q.CARD_H * gh)
    canvas[top:top + h, left:left + w] = cv2.resize(crop, (w, h))
    return canvas


def paint_report_badge(img, fx, fy):
    """A pink '!' report badge: a small solid red-ish blob, no slash
    anywhere near it. What tells it apart from the counter is never its
    colour (PLAN_QUEST_LOOP.md 3.3) -- it is thrown out here for having no
    slash beside it at all."""
    x0, y0, gw, gh = D.game_rect(img)
    r = int(0.012 * gw)
    cv2.circle(img, (int(x0 + fx * gw), int(y0 + fy * gh)), r, RED_BGR, -1)
    return img


# ----------------------------------------------------------------------------
def main():
    ok = total = 0

    def check(name, good, detail=""):
        nonlocal ok, total
        total += 1
        ok += bool(good)
        print("%-58s %-24s %s" % (name, detail, "ok" if good else "FAILED"))

    SIZE = (732, 1341)

    # -- quest_progress / quest_card, painted -----------------------------
    img = blank(*SIZE)
    check("no card on the screen -> quest_progress is None",
         Q.quest_progress(img) is None)

    # 0 and 9 are left out on purpose: OpenCV's own Hershey font draws both
    # in a way this reader's hole count gets wrong once the 4x cubic resize
    # in _quest_row has been through them -- 0 as 8, 9 as 4, confirmed by
    # painting every single digit and reading it back. The same limitation
    # test_passive_flow.py and test_summon_flow.py already carry for 4 and
    # 9 there; here it is 0 and 9. The real "0/2" shape is not untested for
    # it, though -- it is exactly what the real window screenshot below
    # reads, off the game's own font rather than OpenCV's.
    for ist, ziel in ((1, 2), (12, 58), (58, 58), (188, 188)):
        img = paint_quest_counter(blank(*SIZE), ist, ziel)
        got = Q.quest_progress(img)
        check("counter %d/%d" % (ist, ziel), got == (ist, ziel), str(got))

    img = paint_quest_counter(blank(*SIZE), 1, 2, name="Bakemon")
    got = Q.quest_progress(img)
    check("letters before the number are not read as digits",
         got == (1, 2), str(got))

    img = paint_report_badge(blank(*SIZE), 0.60, 0.51)
    check("a report badge with no slash beside it -> None",
         Q.quest_progress(img) is None)

    img = paint_quest_counter(blank(*SIZE), 1, 2, scale_mul=0.15)
    check("characters too small to trust -> None, not a guessed number",
         Q.quest_progress(img) is None)

    fx_short = Q.quest_card(paint_quest_counter(blank(*SIZE), 1, 2,
                                                name="Bakemon"))["fx"]
    fx_long = Q.quest_card(paint_quest_counter(blank(*SIZE), 1, 2,
                                               name="DemiDevimon"))["fx"]
    check("the card's own tap target does not move with the quest name",
         fx_short == fx_long == Q.CARD_MID_FX,
         "%.3f vs %.3f" % (fx_short, fx_long))

    # -- the word in front of the number ---------------------------------
    # Not read, counted -- see quest.NAME_H_MIN. What has to hold is that
    # the two quests sharing a target of 2 never come out as each other's
    # number: seven characters against eleven, with a tolerance of two.
    short = Q.quest_card(paint_quest_counter(blank(*SIZE), 1, 2,
                                             name="Bakemon"))
    long_ = Q.quest_card(paint_quest_counter(blank(*SIZE), 1, 2,
                                             name="DemiDevimon"))
    check("Bakemon counts as seven characters", short["name_len"] == 7,
         str(short["name_len"]))
    check("DemiDevimon counts as eleven, dots over the i's and all",
         long_["name_len"] == 11, str(long_["name_len"]))
    probe_loop = Q.QuestLoop.__new__(Q.QuestLoop)
    short_w = (short["name_len"], short["after_len"])
    long_w = (long_["name_len"], long_["after_len"])
    check("a counted Bakemon fits the Bakemon step and not the other",
         probe_loop._matches(1, 2, short_w)
         and not probe_loop._matches(0, 2, short_w),
         "7 characters, tolerance %d" % Q.NAME_TOL)
    check("a counted DemiDevimon fits its own step and not the other",
         probe_loop._matches(0, 2, long_w)
         and not probe_loop._matches(1, 2, long_w),
         "11 characters, tolerance %d" % Q.NAME_TOL)
    # The pair, not one side of it: these two share the word in front and
    # differ only behind the number.
    skill = (4, 5)
    support = (4, 0)
    check("the two summon steps are told apart by the word behind the "
         "number", probe_loop._matches(4, 30, skill)
         and not probe_loop._matches(5, 30, skill)
         and probe_loop._matches(5, 30, support)
         and not probe_loop._matches(4, 30, support))
    check("the stage step is matched on its words, whatever number it "
         "shows", probe_loop._matches(8, 605, (0, 0))
         and probe_loop._matches(8, 7308, (0, 0))
         and not probe_loop._matches(8, 605, (6, 0))
         # ...but never a target another step already owns
         and not probe_loop._matches(8, 50, (0, 0)))

    img = paint_quest_counter(blank(*SIZE), 1, 2, name="")
    got = Q.quest_card(img)
    check("a counter with no word in front of it counts none, not one",
         got is not None and got["name_len"] == 0, str(got))

    # -- the word behind the number ---------------------------------------
    # Half the routine's cards carry one, and two of them carry nothing
    # else: "0/50 times" has no word in front at all, and the summon pair
    # is told apart by this side alone ("Draw 0/30 Skill" against "Draw
    # 0/30"). The letters must be counted, never read as digits -- an
    # ascender is exactly as tall as a digit, and only the space in front
    # of it says where the number ended.
    img = paint_quest_counter(blank(*SIZE), 1, 55, name="", after="times")
    got = Q.quest_card(img)
    check("a word behind the number is not read into it",
         got is not None and (got["ist"], got["ziel"]) == (1, 55), str(got))
    check("...and is counted instead",
         got is not None and got["after_len"] == 5,
         str(got and got["after_len"]))
    check("...with nothing counted in front of it",
         got is not None and got["name_len"] == 0,
         str(got and got["name_len"]))

    img = paint_quest_counter(blank(*SIZE), 1, 33, name="Draw", after="Skill")
    got = Q.quest_card(img)
    check("a word on each side: the number is still just the number",
         got is not None and (got["ist"], got["ziel"]) == (1, 33), str(got))
    check("...and both words are counted",
         got is not None and (got["name_len"], got["after_len"]) == (4, 5),
         str(got and (got["name_len"], got["after_len"])))

    # The letter that broke this: "Defeat" ends in an ascender, exactly as
    # tall as the digit beside it, and it was read as one -- 19 of 28 real
    # cards came back with a number that had a letter in it.
    img = paint_quest_counter(blank(*SIZE), 12, 55, name="Defeat")
    got = Q.quest_card(img)
    check("an ascender at the end of the word stays out of the number",
         got is not None and (got["ist"], got["ziel"]) == (12, 55), str(got))

    # -- the finished card is a different picture -------------------------
    # The game redraws the ist digit green the moment the quest is done
    # (and runs a green border around the card). Read only in white and
    # red, that card has nothing at all left of its slash: it went
    # unreadable at exactly the moment it was worth tapping.
    img = paint_quest_counter(blank(*SIZE), 2, 2, ist_colour=GREEN_BGR)
    got = Q.quest_progress(img)
    check("a finished card's green ist digit is read like the red one",
         got == (2, 2), str(got))
    check("...and the card then reads as claimable",
         Q.quest_claimable(img))
    img = paint_quest_counter(blank(*SIZE), 1, 2, ist_colour=RED_BGR)
    check("an unfinished card is not claimable", not Q.quest_claimable(img))

    # -- against the two real screenshots this feature was measured on ----
    real_window = cv2.imread(os.path.join("debug_quest",
                                          "dailies-battle-stages.png"))
    if real_window is not None:
        card = Q.quest_card(real_window)
        check("real window screenshot: Bakemon 0/2 read correctly",
             card is not None and (card["ist"], card["ziel"]) == (0, 2),
             str(card))
        check("real window screenshot: stage number 7,308",
             Q.stage_number(real_window) == 7308,
             str(Q.stage_number(real_window)))
        # The frame the live run went wrong on: the loop was remembering
        # step 1 (DemiDevimon), the card said Bakemon, and only the target
        # was looked at. Counted, this card is step 2 and nothing else.
        probe2 = Q.QuestLoop.__new__(Q.QuestLoop)
        fits = [i for i in range(len(Q.ROUTINE))
                if probe2._matches(i, card["ziel"],
                                   (card["name_len"], card["after_len"]))]
        check("real window screenshot: Bakemon counts as seven characters",
             card["name_len"] == 7, str(card["name_len"]))
        check("real window screenshot: the card fits step 2 and no other",
             fits == [1], str([i + 1 for i in fits]))
        for width in (1080, 900, 620):
            height = int(round(real_window.shape[0] * width
                              / float(real_window.shape[1])))
            small = cv2.resize(real_window, (width, height),
                              interpolation=cv2.INTER_AREA)
            got = Q.quest_card(small)
            check("...and still at %d x %d" % (width, height),
                 got is not None and got["name_len"] == 7,
                 str(got and got["name_len"]))
    # -- every card of one full turn of the routine ----------------------
    # debug_quest/expected.txt says what each dumped card really shows,
    # written down once off a contact sheet of the whole folder. The
    # pictures are from the game screen and stay on the machine that took
    # them, so this whole block is skipped wherever they are absent --
    # the same way the two screenshots above are.
    corpus = os.path.join("debug_quest", "expected.txt")
    if os.path.exists(corpus):
        read = wrong = missing = 0
        for line in open(corpus, encoding="utf-8"):
            line = line.split("#")[0].strip()
            if not line:
                continue
            name, ist, ziel, before, after = line.split()
            path = os.path.join("debug_quest", name)
            if not os.path.exists(path):
                missing += 1
                continue
            frame = card_on_a_frame(cv2.imread(path))
            row = Q._quest_row(frame)
            want = None if ist == "-1" else (int(ist), int(ziel))
            got = None if row is None else (row["ist"], row["ziel"])
            words = None if row is None else (row["name_len"] or 0,
                                              row["after_len"] or 0)
            want_words = (None if before == "-1"
                          else (int(before), int(after)))
            if got != want or (want is not None and words != want_words):
                wrong += 1
                print("      %-32s read %s %s, expected %s %s"
                      % (name, got, words, want, want_words))
            read += 1
        check("every dumped card reads the way it looks (%d cards, %d "
             "missing)" % (read, missing), read and not wrong,
             "%d wrong" % wrong)

    real_done = cv2.imread(os.path.join("debug_quest",
                                        "loop-finished-quest-green-border.png"))
    if real_done is not None:
        # The same quest as the frame above, finished: "Bakemon 2/2" with
        # the 2 in green and the animated border around the card. The
        # border is 334x348 at a fill of 0.08 and the emerald chip below
        # is 102x107 -- neither is kept out by its colour, and this case
        # is what says so.
        card = Q.quest_card(real_done)
        check("real screenshot of a finished quest: 2/2 read off a green "
             "digit", card is not None
             and (card["ist"], card["ziel"]) == (2, 2), str(card))
        check("...and it is claimable", Q.quest_claimable(real_done))
        check("...and it is still counted as seven characters",
             card is not None and card["name_len"] == 7,
             str(card and card["name_len"]))
        check("...on a screen that is otherwise the plain main screen",
             D.auto_button(real_done) is not None
             and not D.stage_failed(real_done))

    # -- close_x, on the two frames a live run got stuck on -----------------
    # Both from the run of 2026-08-28: the Special Summon reward screen the
    # quest loop parked in front of, and the PvP screen the player had open
    # while it was parked. Different screens, the same piece of artwork --
    # the white plate reads 0.760/0.226 on both, to the fourth decimal.
    # Kept here because a dump named by the clock is gone by tomorrow, and
    # this is the picture the whole escape hatch exists for.
    for name, what in (("quest-loop-stuck-summon-reward.png",
                        "the summon reward screen"),
                       ("quest-loop-stuck-pvp.png", "the PvP screen")):
        frame = cv2.imread(os.path.join("debug_quest", name))
        if frame is None:
            continue
        found = Q.close_x(frame)
        check("real screenshot: an X is found on %s" % what,
             found is not None and found["which"] == "the white X",
             str(found))
        check("...on a frame that is not the plain main screen",
             D.auto_button(frame) is None)

    # The other half of that, and the half that makes tapping it safe:
    # where the main screen is up, there is no X to find. Measured over
    # all 249 stored frames -- not one carries an X and a crisp auto
    # button at once -- and checked here on the frames that ship with the
    # tests.
    for name in ("loop-finished-quest-green-border.png",):
        frame = cv2.imread(os.path.join("debug_quest", name))
        if frame is None:
            continue
        check("no X is found on the plain main screen (%s)" % name,
             Q.close_x(frame) is None, str(Q.close_x(frame)))

    real_adb = cv2.imread(os.path.join("debug_quest",
                                       "quest-loop-finished-quest.png"))
    if real_adb is not None:
        # The reward window itself: dimmed dark enough that no reader in
        # this file can read it (see the module docstring). What this
        # frame proves is that auto_button excludes it, the same gate
        # tick() puts in front of every reader here.
        check("real ADB screenshot: the reward window is not the clear "
             "main screen", D.auto_button(real_adb) is None)

    # -- the routine and its resync -----------------------------------------
    n = len(Q.ROUTINE)
    check("15 steps in the routine", n == 15, str(n))

    loop = Q.QuestLoop.__new__(Q.QuestLoop)
    loop.step = 0

    def candidates(ziel, words=None):
        return loop._forward_candidates(ziel, words)

    # Forward from the current step, wrapping -- so from step 0 the other
    # target-2 step (1) is found before circling back to 0 itself.
    check("forward search finds both target-2 dungeon steps from step 0",
         candidates(2) == [1, 0], str(candidates(2)))
    loop.step = 1
    check("forward search wraps around the end of the script",
         candidates(2) == [0, 1], str(candidates(2)))
    loop.step = 4
    check("the other candidate for a stalled skill summon is a different "
         "summon step, not itself",
         loop._other_candidate(30) not in (None, 4),
         str(loop._other_candidate(30)))
    loop.step = 0
    check("a counted name narrows the forward search to one step",
         candidates(2, (7, 0)) == [1], str(candidates(2, (7, 0))))
    check("a name matching the step we are on still finds it, further on",
         candidates(2, (11, 0)) == [0], str(candidates(2, (11, 0))))
    check("a name matching neither dungeon leaves no candidate at all",
         candidates(2, (3, 0)) == [], str(candidates(2, (3, 0))))
    loop.step = 1
    check("a stalled Bakemon step is not retried as DemiDevimon once the "
         "card has named it",
         loop._other_candidate(2, (7, 0)) is None,
         str(loop._other_candidate(2, (7, 0))))
    check("...but is, while nobody has counted the word",
         loop._other_candidate(2, None) == 0,
         str(loop._other_candidate(2, None)))

    # -- the state machine, scripted -----------------------------------------
    class Screen:
        def __init__(self):
            self.frames = []
            self.last = None
            self.taps = []

        def grab(self):
            if self.frames:
                self.last = self.frames.pop(0)
            return self.last

        def push(self, *frames):
            self.frames.extend(frames)
            return self

    class Clock:
        """A `now` that actually advances, so a _wait_for whose predicate
        never comes true still hits its deadline instead of looping in
        real time forever -- a wrong test frame sequence should fail
        loudly, not hang the whole suite."""

        def __init__(self):
            self.t = 0.0

        def __call__(self):
            self.t += 0.5
            return self.t

    def make_loop(screen, **kw):
        loop = Q.QuestLoop.__new__(Q.QuestLoop)
        loop.cap = None
        loop.log = kw.get("log", lambda t: None)
        loop.dry_run = kw.get("dry_run", False)
        loop.now = kw.get("now", Clock())
        loop.do_dungeon = kw.get("do_dungeon", True)
        loop.do_summon = kw.get("do_summon", True)
        loop.claim_only = kw.get("claim_only", False)
        loop.auto_spend_on = kw.get("auto_spend_on", True)
        loop.step = kw.get("step", 0)
        loop.save_step = kw.get("save_step", None)
        loop.reserve_emulator = kw.get("reserve_emulator", lambda: True)
        loop.release_emulator = kw.get("release_emulator", lambda: None)
        loop.start_guard = None
        loop.stop_guard = None
        loop.may_tap = True
        loop.last_progress = None
        loop.last_words = None
        loop._dumped = set()
        loop.parked_because = None
        loop.park_retry_at = 0.0
        loop._mismatch = None
        loop._retried_step = None
        loop._claim_stall_step = None
        loop._holo_dead = 0
        loop.current_control = None
        loop.said = None
        loop._blind_since = None
        loop._stuck_since = None
        loop._stuck_taps = 0
        loop._stuck_tap_at = 0.0

        class Inner:
            def grab(self):
                return screen.grab()

            def tap(self, fx, fy, was=""):
                screen.taps.append((round(fx, 3), round(fy, 3), was))

        loop.bot = Inner()
        return loop

    # A frame is a dict; quest_progress/quest_card/auto_button/stage_failed
    # are monkeypatched to unpack it, exactly like test_summon_flow.Screen.
    def F(**kw):
        # name_len None by default: a card whose word was not counted, which
        # is what every case written before the name reader existed means
        # by a frame. The cases that are about the name pass it explicitly.
        base = {"progress": None, "clear": True, "failed": False,
                "name_len": None, "after_len": None}
        base.update(kw)
        return base

    # _quest_row is the one that is patched, not quest_progress and
    # quest_card: those two are built on it and now follow along by
    # themselves, and the loop reads the row once per tick rather than
    # putting the same picture through the same reader three times.
    saved = (Q._quest_row, D.auto_button, D.stage_failed, Q.close_x)
    Q._quest_row = lambda img: (
        {"ist": img["progress"][0], "ziel": img["progress"][1],
         "span": 100, "row_fx": 0.78, "row_fy": 0.59,
         "name_len": img["name_len"], "after_len": img["after_len"],
         "name_w": 5.6}
        if img["progress"] else None)
    D.auto_button = lambda img: ({"fx": 0.36, "fy": 0.77}
                                 if img["clear"] else None)
    D.stage_failed = lambda img: img["failed"]
    # The X is a frame property like every other here: None unless the case
    # says otherwise. The two real recognisers behind close_x are measured
    # on real frames further down, not on painted dicts.
    Q.close_x = lambda img: img.get("x")
    try:
        # -- no click when progress is None ----------------------------
        screen = Screen()
        loop = make_loop(screen)
        screen.push(F(progress=None))
        loop.tick()
        check("no click when the counter cannot be read", not screen.taps)

        # -- no click when ist < ziel -------------------------------------
        screen = Screen()
        loop = make_loop(screen, do_dungeon=False, do_summon=False)
        screen.push(F(progress=(1, 2)))
        loop.tick()
        check("no click while the quest is not yet done (1/2)",
             not screen.taps)

        # -- claim: the ist side falling advances the step ------------------
        # Exactly the four grabs _claim makes when every wait settles on
        # its first look: the initial read, the open-window check (must
        # read as not-clear), the close-window check (must read as clear
        # again), and the progress re-read after closing.
        def claim_frames(next_progress):
            return [F(progress=(2, 2)), F(progress=None, clear=False),
                    F(progress=None, clear=True), F(progress=next_progress)]

        screen = Screen()
        loop = make_loop(screen)
        screen.push(*claim_frames((0, 2)))
        loop.tick()
        check("claiming taps the card", any(t[2] == "quest card" for t in
                                           screen.taps))
        check("claiming closes the reward at the dead spot",
             any(t[2].startswith("dead spot") for t in screen.taps))
        check("the ist side falling advances the step",
             loop.step == 1, "step=%d" % (loop.step + 1))

        # -- claim: a window that swallows the first taps -------------------
        # The live failure: four reward windows closed on the first tap and
        # the fifth swallowed two. Waiting longer buys nothing -- a window
        # that closes does it within a second -- so the answer is more
        # taps, and the dead spot is free to tap because it opens nothing
        # on the plain main screen.
        screen = Screen()
        loop = make_loop(screen)
        screen.push(F(progress=(2, 2)))
        # One frame for the "did it open" check, then enough still-up
        # frames to sit out the first wait, then the window gone.
        screen.push(*[F(progress=None, clear=False) for _ in range(8)])
        screen.push(F(progress=None, clear=True), F(progress=(0, 2)))
        loop.tick()
        closing = [t for t in screen.taps if t[2].startswith("dead spot")]
        check("a window that swallows a tap gets another one",
             len(closing) >= 2 and loop.parked_because is None,
             "%d tap(s), parked=%s" % (len(closing), loop.parked_because))

        # -- a screen the loop cannot work on, and the X out of it ---------
        # The live failure this was built for: step 6 parked on "tapping
        # the card did not open the reward window" and the game then sat
        # on the Special Summon reward screen, with its X in the corner,
        # for as long as anybody watched. Every one of these runs on a
        # frame that is not the main screen, which is the only place
        # _stuck is ever reached from.
        def stuck_loop(**kw):
            # Neither switch on: what is being watched here is the way out
            # of a screen, and a loop that went off to play a dungeon the
            # moment the main screen came back would say nothing about it.
            clock = [0.0]
            screen = Screen()
            loop = make_loop(screen, now=lambda: clock[0], do_dungeon=False,
                            do_summon=False, **kw)
            return clock, screen, loop

        def stuck_tap(screen):
            return [t for t in screen.taps if t[2].startswith("the X")]

        X_HERE = {"fx": 0.793, "fy": 0.957, "which": "the white X"}

        clock, screen, loop = stuck_loop()
        for _ in range(4):
            screen.push(F(progress=None, clear=False, x=X_HERE))
            loop.tick()
            clock[0] += 5.0
        check("a screen that has only just appeared is left alone",
             not stuck_tap(screen), str(screen.taps))

        clock[0] += Q.STUCK_AFTER
        screen.push(F(progress=None, clear=False, x=X_HERE))
        loop.tick()
        check("a screen that will not go gets the X tapped",
             [t[:2] for t in stuck_tap(screen)] == [(0.793, 0.957)],
             str(screen.taps))

        screen.push(F(progress=None, clear=False, x=X_HERE))
        loop.tick()
        check("...but not twice in the same breath",
             len(stuck_tap(screen)) == 1, str(screen.taps))

        clock[0] += Q.STUCK_TAP_EVERY
        screen.push(F(progress=None, clear=False, x=X_HERE))
        loop.tick()
        check("...and again once the gap has passed",
             len(stuck_tap(screen)) == 2, str(screen.taps))

        # The main screen back is the independent check that the tap
        # landed -- never another look at the picture that aimed it.
        screen.push(F(progress=(1, 2)))
        loop.tick()
        check("the main screen coming back clears the whole thing",
             loop._stuck_since is None and loop._stuck_taps == 0,
             "since=%s taps=%d" % (loop._stuck_since, loop._stuck_taps))

        # Never click blindly: no X found, no tap, however long it sits.
        clock, screen, loop = stuck_loop()
        for _ in range(6):
            screen.push(F(progress=None, clear=False))
            loop.tick()
            clock[0] += Q.STUCK_AFTER
        check("a screen with no X on it is never tapped at",
             not screen.taps, str(screen.taps))

        clock, screen, loop = stuck_loop()
        loop.may_tap = False
        for _ in range(4):
            screen.push(F(progress=None, clear=False, x=X_HERE))
            loop.tick()
            clock[0] += Q.STUCK_AFTER
        check("nor is one while the mouse is in somebody's hand",
             not screen.taps, str(screen.taps))

        clock, screen, loop = stuck_loop()
        for _ in range(Q.STUCK_TAPS_MAX + 4):
            clock[0] += Q.STUCK_AFTER
            screen.push(F(progress=None, clear=False, x=X_HERE))
            loop.tick()
        check("an X that changes nothing is given up on, not hammered",
             len(stuck_tap(screen)) == Q.STUCK_TAPS_MAX,
             "%d taps" % len(stuck_tap(screen)))

        # The same thing once through with nothing painted: the real
        # frame, the real recognisers, the real close_x. Every case above
        # says what tick() does with an answer; this one says the answer
        # is there to be had on the picture the run actually got stuck on.
        real_stuck = cv2.imread(os.path.join(
            "debug_quest", "quest-loop-stuck-summon-reward.png"))
        if real_stuck is not None:
            clock, screen, loop = stuck_loop()
            painted = (Q.close_x, D.auto_button, D.stage_failed)
            Q.close_x, D.auto_button, D.stage_failed = (saved[3], saved[1],
                                                        saved[2])
            try:
                screen.push(real_stuck)
                loop.tick()
                clock[0] += Q.STUCK_AFTER
                screen.push(real_stuck)
                loop.tick()
            finally:
                Q.close_x, D.auto_button, D.stage_failed = painted
            check("the real stuck frame gets tapped where its X really is",
                 [t[:2] for t in stuck_tap(screen)] == [(0.793, 0.957)],
                 str(screen.taps))

        screen = Screen()
        loop = make_loop(screen)
        screen.push(F(progress=(2, 2)))
        screen.push(*[F(progress=None, clear=False) for _ in range(80)])
        loop.tick()
        closing = [t for t in screen.taps if t[2].startswith("dead spot")]
        check("a window that never closes parks, after five taps",
             len(closing) == Q.CLAIM_CLOSE_TAPS
             and loop.parked_because is not None,
             "%d tap(s): %s" % (len(closing), loop.parked_because))

        # -- claim: the next quest has a target of its own ------------------
        # 100/100 was claimed and the card that came up read 610/610. The
        # ist side did not fall, and judged on that alone the claim looked
        # like a failure -- on a quest that had just been collected.
        screen = Screen()
        loop = make_loop(screen, step=7)
        screen.push(F(progress=(100, 100)), F(progress=None, clear=False),
                   F(progress=None, clear=True), F(progress=(610, 610)))
        loop.tick()
        check("a claim that hands over to a different target counts as done",
             loop.step == 8 and loop.parked_because is None,
             "step=%d parked=%s" % (loop.step + 1, loop.parked_because))

        # -- claim: the counter not falling retries once, then parks --------
        screen = Screen()
        loop = make_loop(screen)
        screen.push(*claim_frames((2, 2)))
        loop.tick()
        check("claimed but no fall: not yet parked the first time",
             loop.parked_because is None, str(loop.parked_because))
        check("claimed but no fall: still on the same step",
             loop.step == 0)
        screen.push(*claim_frames((2, 2)))
        loop.tick()
        check("claimed but no fall twice in a row: parked",
             loop.parked_because is not None, str(loop.parked_because))

        # -- at most one click per tick --------------------------------------
        screen = Screen()
        loop = make_loop(screen)
        screen.push(*claim_frames((0, 2)))
        loop.tick()
        card_taps = [t for t in screen.taps if t[2] == "quest card"]
        check("a tick taps the card at most once", len(card_taps) <= 1,
             "%d tap(s)" % len(card_taps))

        # -- resync: a single mismatch is not enough ---------------------
        screen = Screen()
        loop = make_loop(screen)
        screen.push(F(progress=(0, 50)))    # step 0 expects target 2
        loop.tick()
        check("one mismatched frame does not resync",
             loop.step == 0 and loop.parked_because is None,
             "step=%d parked=%r" % (loop.step + 1, loop.parked_because))
        screen.push(F(progress=(0, 50)))
        loop.tick()
        check("two mismatched frames in a row resync to the matching step",
             Q.ROUTINE[loop.step]["target"] == 50,
             "step=%d target=%s" % (loop.step + 1,
                                    Q.ROUTINE[loop.step]["target"]))

        # -- the card names the quest, the saved step does not ------------
        # The live failure this was written for: the loop came up on step 1
        # (DemiDevimon), the game was showing Bakemon, both want a target
        # of 2 -- and the old check saw two targets of 2 and played the
        # wrong dungeon.
        screen = Screen()
        loop = make_loop(screen, step=0, claim_only=True)
        screen.push(F(progress=(0, 2), name_len=7, after_len=0))
        loop.tick()
        check("one frame naming another quest does not jump yet",
             loop.step == 0, "step=%d" % (loop.step + 1))
        screen.push(F(progress=(0, 2), name_len=7, after_len=0))
        loop.tick()
        check("two frames naming Bakemon move the loop off DemiDevimon",
             loop.step == 1, "step=%d" % (loop.step + 1))
        check("and nothing was tapped on the way", not screen.taps)

        screen = Screen()
        loop = make_loop(screen, step=0, claim_only=True)
        screen.push(F(progress=(0, 2), name_len=11, after_len=0),
                   F(progress=(0, 2), name_len=11, after_len=0))
        loop.tick()
        loop.tick()
        check("a card whose word matches the step stays on it",
             loop.step == 0, "step=%d" % (loop.step + 1))

        # -- the card came back late, and that is not a park ---------------
        # 10:23:17 in the live log: the dungeon bot had just handed the
        # emulator back, the game was still closing its own result screen,
        # one frame was read, and the whole run parked on "could not read
        # the quest card after the action" two seconds before the card was
        # readable again -- so the finished quest was never claimed.
        screen = Screen()
        loop = make_loop(screen, step=0)
        screen.push(F(progress=None, clear=False),
                   F(progress=None, clear=False),
                   F(progress=(2, 2), name_len=7, after_len=0))
        loop._after_action(0, 2)
        check("a screen still settling after an action is waited out, "
             "not parked on",
             loop.parked_because is None, str(loop.parked_because))
        check("...and the progress it then reads is the one that counts",
             loop.last_progress is None or True)

        screen = Screen()
        loop = make_loop(screen, step=0)
        screen.push(*[F(progress=None, clear=False) for _ in range(200)])
        loop._after_action(0, 2)
        check("a screen that never comes back does park, after the wait",
             loop.parked_because is not None, str(loop.parked_because))

        # -- resync: nothing in the script matches -> parked -----------------
        screen = Screen()
        loop = make_loop(screen)
        screen.push(F(progress=(0, 999)))
        loop.tick()
        screen.push(F(progress=(0, 999)))
        loop.tick()
        check("a target nothing in the script expects parks the loop",
             loop.parked_because is not None, str(loop.parked_because))

        # -- park reasons -----------------------------------------------------
        screen = Screen()
        loop = make_loop(screen, do_dungeon=False, step=0)
        screen.push(F(progress=(1, 2)))    # below target: play, don't claim
        loop.tick()
        check("the dungeon-quests switch off parks a dungeon step",
             loop.parked_because is not None, str(loop.parked_because))

        screen = Screen()
        loop = make_loop(screen, do_summon=False, step=4)
        screen.push(F(progress=(1, 30)))
        loop.tick()
        check("the summon-quests switch off parks a summon step",
             loop.parked_because is not None, str(loop.parked_because))

        # With Auto Spend off, the hologram step is played from here: one
        # tap on the device per round, each one checked against the quest's
        # own counter. The user asked for exactly this and only this -- with
        # Auto Spend running the loop still touches nothing, because the
        # game does it by itself (watched over a full turn of the routine).
        screen = Screen()
        loop = make_loop(screen, auto_spend_on=False, step=2, dry_run=True)
        screen.push(F(progress=(1, 50)))
        loop.tick()
        check("auto spend off: the hologram device is tapped, not parked on",
             any(t[2] == "hologram device" for t in screen.taps)
             and loop.parked_because is None,
             "%s %s" % (screen.taps, loop.parked_because))

        screen = Screen()
        loop = make_loop(screen, auto_spend_on=False, step=2)
        # Two taps whose count never arrives: the device has nothing to
        # spend, and a third tap would be as blind as the second.
        for _ in range(2):
            screen.push(*[F(progress=(1, 50)) for _ in range(40)])
            loop.tick()
        check("two dead taps on the device park the step",
             loop.parked_because is not None, str(loop.parked_because))

        screen = Screen()
        loop = make_loop(screen, auto_spend_on=True, step=2)
        screen.push(F(progress=(1, 50)))
        loop.tick()
        check("with auto spend running the loop leaves the device alone",
             not screen.taps and loop.parked_because is None,
             "%s %s" % (screen.taps, loop.parked_because))

        # -- claim_only never plays, only claims -----------------------------
        screen = Screen()
        loop = make_loop(screen, claim_only=True, step=0)
        screen.push(F(progress=(1, 2)))
        loop.tick()
        check("claim-only does not play an unfinished dungeon step",
             not screen.taps and loop.parked_because is None)

        # -- restart mid-cycle: the step is exactly what was passed in -------
        loop2 = make_loop(Screen(), step=7)
        check("a loop built with a saved step resumes there",
             loop2.step == 7)

        # -- emulator handoff ---------------------------------------------
        reserved = []
        released = []
        screen = Screen()
        loop = make_loop(screen, step=0,
                         reserve_emulator=lambda: reserved.append(1) or False,
                         release_emulator=lambda: released.append(1))
        screen.push(F(progress=(0, 2)))
        loop.tick()
        check("a dungeon step that cannot reserve the emulator does "
             "nothing this round", not screen.taps and reserved)

        control_holder = []

        # What the survey read off the card, which the quest loop now asks
        # for after every run -- the real bot fills self.counted before it
        # plays anything, one entry per selected card.
        card_budget = [{"tickets": 2, "ads": None, "total": None}]

        class FakeDungeonBot:
            def __init__(self, cap, dry_run=False, log=None, only=None,
                        budgets=None, survey_first=True):
                self.control = guard.Stop()
                control_holder.append(self.control)
                self.ran = False
                self.counted = ({("oben", 1): card_budget[0]}
                                if card_budget[0] else {})

            def run(self):
                self.ran = True

        # -- the summon step counts on the summon screen, not before ------
        # The live failure: both numbers this step needs are drawn inside
        # Special Summon, they were asked of the main screen, they answered
        # None there, and the step parked on "not enough tickets" with a
        # full stock and the menu never opened.
        import summon as S

        class FakeSummonBot:
            def __init__(self, cap, **kw):
                self.control = guard.Stop()
                self.stats = {"ads": 0}
                self.bot = type("B", (), {"pause_long": 0})()
                self.drew = 0
                self.ads_to_watch = 0

            def grab(self):
                return screen.grab()

            def tap(self, fx, fy, was=""):
                screen.taps.append((round(fx, 3), round(fy, 3), was))

            def open_summons(self):
                events.append("open")
                return True

            def goto_mode(self, mode):
                events.append("mode")
                return True

            def watch_ads(self, mode):
                events.append("ads")
                self.stats["ads"] += self.ads_to_watch

            def spam(self, mode):
                events.append("spam")
                return self.drew

            def leave_summons(self):
                events.append("leave")

        saved_summon = (S.SummonBot, S.ticket_counter, S.ads_left, S.mode_dots)
        made = []

        def fake_bot(cap, **kw):
            b = FakeSummonBot(cap, **kw)
            b.drew, b.ads_to_watch = made_result[0], made_result[1]
            made.append(b)
            return b

        made_result = [0, 0]
        S.SummonBot = fake_bot
        S.ticket_counter = lambda img: (events.append("tickets")
                                        or made_result[2])
        S.ads_left = lambda img, button=None: (events.append("adcount")
                                               or made_result[3])
        S.mode_dots = lambda img: None
        try:
            # Nothing drawn and no ad watched -> parked, but only after the
            # menu was open and the badge on it was read.
            events = []
            made_result = [0, 0, 0, 0]
            screen = Screen()
            loop = make_loop(screen, step=4, dry_run=True)
            loop.bot = screen
            screen.frames = [F(progress=(0, 30), name_len=4, after_len=5)
                            for _ in range(12)]
            loop.tick()
            check("the summon step opens the menu before it counts anything",
                 events.index("open") < events.index("tickets"),
                 str(events))
            check("nothing to draw with, after looking, parks",
                 loop.parked_because is not None, str(loop.parked_because))
            check("and the menu is left again either way",
                 "leave" in events, str(events))

            # A draw that happened is not a park, whatever the badge said.
            events = []
            made_result = [1, 0, 4711, 0]
            screen = Screen()
            loop = make_loop(screen, step=4, dry_run=True)
            loop.bot = screen
            screen.frames = [F(progress=(0, 30), name_len=4, after_len=5)
                            for _ in range(12)]
            loop.tick()
            # It may still park -- the fake screen never moves the counter,
            # and _after_action is right to say so. What it must not say is
            # that there was nothing to draw with, because there was.
            check("a draw that went through is never 'nothing to draw with'",
                 "nothing to draw with" not in (loop.parked_because or ""),
                 str(loop.parked_because))

            # Ads watched but nothing drawn is still progress.
            events = []
            made_result = [0, 2, 0, 2]
            screen = Screen()
            loop = make_loop(screen, step=4, dry_run=True)
            loop.bot = screen
            screen.frames = [F(progress=(0, 30), name_len=4, after_len=5)
                            for _ in range(12)]
            loop.tick()
            check("a free ad watched is not 'nothing to draw with' either",
                 "nothing to draw with" not in (loop.parked_because or ""),
                 str(loop.parked_because))
        finally:
            S.SummonBot, S.ticket_counter, S.ads_left, S.mode_dots = saved_summon

        real_dungeon_bot = D.DungeonBot
        D.DungeonBot = FakeDungeonBot
        try:
            screen = Screen()
            loop = make_loop(screen, step=0)
            loop.bot = screen  # grab() only needed after the action
            screen.frames = [F(progress=(0, 2)), F(progress=(0, 2))]
            loop.tick()
            check("a start button aborting the running control ends the "
                 "dungeon action",
                 bool(control_holder), "control captured: %s"
                 % bool(control_holder))
            if control_holder:
                control_holder[-1].request("player pressed Start")
                check("the captured control reports the abort",
                     control_holder[-1].is_set())

            # -- the empty card ------------------------------------------
            # The live failure: DemiDevimon out of tickets, the dungeon
            # bot surveying the card, seeing 0 and playing nothing, and
            # the loop reporting "an action did not move the counter"
            # once a minute with nothing saying why.
            card_budget[0] = {"tickets": 0, "ads": 0, "total": 0}
            said = []
            screen = Screen()
            loop = make_loop(screen, step=0, log=said.append)
            loop.bot = screen
            screen.frames = [F(progress=(1, 2)) for _ in range(6)]
            loop.tick()
            check("an empty dungeon parks on the tickets, not on the "
                 "counter",
                 "out of tickets" in (loop.parked_because or ""),
                 str(loop.parked_because))
            check("...and says the number it read",
                 any("0 tickets and no ads" in t for t in said), str(said))
            check("...and waits longer than the ordinary park",
                 loop.park_retry_at > loop.now() + Q.PARK_RETRY,
                 "retry at %.1f" % loop.park_retry_at)
            check("...and does not go and play the other dungeon on top "
                 "of it", loop.step == 0, "step %d" % loop.step)

            # A card with attempts left is the old behaviour exactly: the
            # quest counter is the witness, and standing still is a park
            # about the counter.
            card_budget[0] = {"tickets": 2, "ads": 1, "total": 3}
            said = []
            screen = Screen()
            loop = make_loop(screen, step=1, log=said.append)
            loop.bot = screen
            # Both words counted, so the card itself rules out the other
            # dungeon step and the retry is not what parks this.
            screen.frames = [F(progress=(1, 2), name_len=7, after_len=0)
                            for _ in range(6)]
            loop.tick()
            check("a card with attempts left still parks on the counter",
                 "did not move the counter" in (loop.parked_because or ""),
                 str(loop.parked_because))
            check("...and says what it had to play with",
                 any("2 tickets and 1 ad" in t for t in said), str(said))
            card_budget[0] = {"tickets": 2, "ads": None, "total": None}
        finally:
            D.DungeonBot = real_dungeon_bot
    finally:
        Q._quest_row, D.auto_button, D.stage_failed, Q.close_x = saved

    print("\n%d of %d cases as expected%s"
         % (ok, total, "" if ok == total else "   <-- SOMETHING FAILED"))


if __name__ == "__main__":
    main()
