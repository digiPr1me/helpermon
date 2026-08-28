"""
Check the dungeon bot flow offline, no emulator needed.

State sequences are played back and what the bot clicks is counted. That
surfaces endless loops and miscounting without needing a real run. Bugs of
exactly that kind cost several test runs during development.
"""
import cv2
import numpy as np

import dungeon as D


class Sim:
    def __init__(self, sequence, confirm_kind="party"):
        self.confirm_kind = confirm_kind
        self.sequence = list(sequence)
        self.i = 0
        self.clicks = []
        self.messages = []

    def next_state(self, _img=None):
        state = self.sequence[min(self.i, len(self.sequence) - 1)]
        self.i += 1
        def button(w, fy=0.70):
            return {"fx": 0.5, "fy": fy, "fw": w, "fh": 0.05}
        return {
            "state": state,
            "attempt": (button(0.21) if state == "close"
                        else button(0.30) if state == D.DIALOG else None),
            "party": button(0.28, 0.79) if state == D.DIALOG_PARTY else None,
            "ad": button(0.62) if state == D.DIALOG_AD else None,
            "clear": None, "blau": [], "violett": [], "karten": [0.3],
            "giveup": None, "party_voll": 0, "exit_ok": button(0.20),
            # For the party dialog, OK is the correct answer, it ends the
            # dungeon. The exit dialog, in contrast, is cancelled and the
            # flow continues.
            "exit_kind": self.confirm_kind,
        }


def make_bot(sim, **kw):
    bot = D.DungeonBot.__new__(D.DungeonBot)
    bot.dry_run = False
    bot.log = sim.messages.append
    bot.use_ads = True
    bot.max_ads = kw.get("max_ads", 2)
    bot.max_attempts = 6
    # Per-dungeon budgets, and what a survey read off the cards. Empty here:
    # these cases exercise the panel, where no counter is visible, so the
    # loop falls back on max_attempts exactly as it did before counting.
    bot.budgets = kw.get("budgets", {})
    bot.counted = kw.get("counted", {})
    bot.spent = {}
    bot.max_loops = 14
    bot.battle_timeout = 1
    bot.start_timeout = 1
    bot.min_battle = kw.get("min_battle", 6)
    bot.patience = 0
    bot.pause_short = bot.pause_long = bot.tick = 0
    bot.device = (1080, 1920)
    bot.stats = {k: 0 for k in ("attempts", "fights", "ads", "skipped",
                                "unknown", "declined", "exit_caught",
                                "not_selected")}
    bot.exhausted = set()
    bot.control = D.guard.Stop()
    bot.max_minutes = 0
    bot.deadline = None
    bot._saved = 0
    bot.debugdir = "/tmp"
    bot.entries = 7
    bot.visible_at_bottom = 5
    bot.swipes = 1
    bot.grab = lambda: "bild"
    bot.tap = lambda fx, fy, was="": sim.clicks.append(was)
    bot.back = lambda only_if_dialog=True, leaving_dungeon=False: True
    bot.return_to_list = lambda tries=5: True
    bot.dialog_settled = lambda tries=2, pause=None: sim.next_state()
    bot.wait_dialog_gone = lambda t: kw.get("attempt_wirkt", False)
    bot.wait_dialog_back = lambda t: sim.next_state()
    bot.dismiss_confirm = lambda info=None, leaving_dungeon=False: None
    bot.save_unknown = lambda img, tag: None
    bot.label_of = lambda i, l: "Test"
    return bot


def run_case(sequence, name, expected_ads=None, **kw):
    sim = Sim(sequence)
    orig_rec, orig_cards = D.recognise, D.list_cards
    D.recognise = sim.next_state
    D.list_cards = lambda img, with_size=False: ([(0.3, 0.12)] if with_size
                                                 else [0.3])
    try:
        bot = make_bot(sim, **kw)
        bot.play_entry(0, "oben")
    finally:
        D.recognise, D.list_cards = orig_rec, orig_cards
    ad_clicks = sum(1 for k in sim.clicks if k == "Werbung")
    good = expected_ads is None or ad_clicks == expected_ads
    print("%-44s ad clicks %d%s" % (
        name, ad_clicks,
        "" if expected_ads is None else
        "  expected %d  %s" % (expected_ads, "ok" if good else "FAILED")))
    return good, ad_clicks, sim


def selection_cases():
    """The short-name selection must act on the right cards.

    What matters is that numbers refer to the overall list, not cards in the
    current view. Counted from the bottom, the first visible card sits at
    total minus visible.
    """
    cases = [
        (None, [], "no selection", [(0, "oben"), (4, "unten")], [True, True]),
        (None, [0], "skip apocalymon", [(0, "oben"), (1, "oben")], [False, True]),
        ([0, 4], [], "only apocalymon and network",
         [(0, "oben"), (1, "oben"), (2, "unten")], [True, False, True]),
        (None, [5], "skip metalsea", [(3, "unten"), (2, "unten")], [False, True]),
    ]
    ok = 0
    for only, skip, name, cards, expected in cases:
        bot = D.DungeonBot.__new__(D.DungeonBot)
        bot.entries = 7
        bot.visible_at_bottom = 5
        bot.only = set(only) if only else None
        bot.skip = set(skip)
        got = [bot.is_selected(i, label) for i, label in cards]
        good = got == expected
        ok += good
        details = ", ".join(
            "%s %s" % (D.dungeon_label(i, label == "unten", 7, 5), g)
            for (i, label), g in zip(cards, got))
        print("  %-30s %s   %s" % (name, "ok" if good else "FAILED", details))
    return ok, len(cases)


def party_panel(filled=(False, True, False)):
    """The dungeon dialog with its three party slots.

    Rebuilt from a real frame, not captured from one. What matters is the
    thing that fooled the reader: the panel's own bright edge sits just to
    the right of the third slot, and a crop that reaches it measures
    contrast that is the panel, not a team-mate.
    """
    h, w = 1390, 805
    img = np.full((h, w, 3), 18, np.uint8)
    # the panel, with a bright border down its right-hand side
    cv2.rectangle(img, (int(0.11 * w), int(0.18 * h)),
                  (int(0.845 * w), int(0.83 * h)), (90, 45, 20), -1)
    cv2.rectangle(img, (int(0.815 * w), int(0.18 * h)),
                  (int(0.845 * w), int(0.83 * h)), (240, 190, 90), -1)
    for fx, occupied in zip(D.PARTY_SLOTS, filled):
        x = int((fx - 0.09) * w)
        y = int((D.PARTY_SLOT_Y - 0.05) * h)
        cv2.rectangle(img, (x, y), (x + int(0.18 * w), y + int(0.10 * h)),
                      (55, 30, 14), -1)
        if occupied:
            # a figure: bright, and nothing like the flat slot behind it
            cv2.circle(img, (x + int(0.09 * w), y + int(0.05 * h)),
                       int(0.03 * w), (230, 230, 240), -1)
            cv2.rectangle(img, (x + int(0.05 * w), y + int(0.06 * h)),
                          (x + int(0.13 * w), y + int(0.09 * h)),
                          (60, 200, 240), -1)
    return img


def party_cases():
    """One team-mate must read as one.

    A live run read two, never searched for a party, and pressed Attempt
    without one -- which does nothing. It then sat in the dialog until it
    gave up.
    """
    ok = 0
    img = party_panel()
    wide = D.PARTY_SLOT_HALF_W
    try:
        D.PARTY_SLOT_HALF_W = 0.10
        fooled = D.party_slots_filled(img)
    finally:
        D.PARTY_SLOT_HALF_W = wide
    got = D.party_slots_filled(img)
    print("  one filled slot: %d with the crop as it is, %d with the wide "
          "crop that reached the panel edge" % (got, fooled))
    ok += got == 1
    ok += fooled > got
    ok += D.party_slots_filled(party_panel((True, True, True))) == 3
    ok += D.party_slots_filled(party_panel((False, False, False))) == 0
    print("  three filled read as 3, none read as 0")
    return ok, 4


def hsv(h, sat, val):
    """One BGR colour from the HSV numbers measured on the real frames."""
    return tuple(int(c) for c in cv2.cvtColor(
        np.uint8([[[h, sat, val]]]), cv2.COLOR_HSV2BGR)[0][0])


# Measured over the Cancel button of real frames of all three prompts:
# the in-game pink at hue 147-149 (89.6% of the button) saturation 147, the
# exit prompt's grey-blue at hue 100-110 saturation 151, and the dialog body
# behind both at hue 103 saturation 233.
#
# 147 and not 145: VIOLET ends at 145, and the two must not touch. Measured
# 0.000 of the real pink button inside the violet range, which is what lets
# a violet neighbour veto the exit reading without vetoing a real prompt.
PINK = hsv(148, 147, 225)
GREY = hsv(103, 151, 159)
BODY = hsv(103, 233, 139)

PINK_OK = {"fx": 0.602, "fy": 0.599, "fw": 0.195, "fh": 0.04}
GREY_OK = {"fx": 0.561, "fy": 0.652, "fw": 0.153, "fh": 0.04}


def prompt(pink=True):
    """A confirmation prompt, built to the real one's proportions.

    Cancel deliberately does NOT sit where the mirror of OK would put it --
    measured 0.34 against a mirror of 0.398 -- because that offset is what
    makes the sample straddle the button and the dialog behind it, and a
    test on a neatly centred button would not exercise the case that failed.
    """
    button, ok = (PINK, PINK_OK) if pink else (GREY, GREY_OK)
    h, w = 1390, 805
    img = np.full((h, w, 3), 20, np.uint8)
    cv2.rectangle(img, (int(0.13 * w), int((ok["fy"] - 0.22) * h)),
                  (int(0.87 * w), int((ok["fy"] + 0.06) * h)), BODY, -1)
    cv2.rectangle(img, (int(0.25 * w), int((ok["fy"] - 0.021) * h)),
                  (int(0.435 * w), int((ok["fy"] + 0.020) * h)), button, -1)
    cv2.rectangle(img, (int((ok["fx"] - ok["fw"] / 2) * w),
                        int((ok["fy"] - 0.021) * h)),
                  (int((ok["fx"] + ok["fw"] / 2) * w),
                   int((ok["fy"] + 0.020) * h)), (230, 150, 40), -1)
    return img


def loading_panel():
    """The dungeon panel before its artwork has arrived.

    Placeholder text, empty slots, and an Attempt button that is narrower
    than the loaded one -- 0.214 against 0.251, measured -- which is what
    slipped it inside the exit prompt's width band. Its violet Clear
    Previous Difficulty sits beside it at the same height, and that pair is
    what no prompt has.
    """
    h, w = 1390, 805
    img = np.full((h, w, 3), 20, np.uint8)
    cv2.rectangle(img, (int(0.09 * w), int(0.24 * h)),
                  (int(0.86 * w), int(0.80 * h)), BODY, -1)
    for fx, colour in ((0.358, hsv(130, 200, 200)), (0.595, (230, 150, 40))):
        cv2.rectangle(img, (int((fx - 0.107) * w), int(0.556 * h)),
                      (int((fx + 0.107) * w), int(0.592 * h)), colour, -1)
    # Find a Party, below and centred, as on the real frame
    cv2.rectangle(img, (int(0.364 * w), int(0.738 * h)),
                  (int(0.589 * w), int(0.774 * h)), (230, 150, 40), -1)
    return img


def confirm_cases():
    """Which prompt is this, and what is the answer.

    Three dialogs wear the same face. The pink pair is identical to the
    pixel, so colour can only rule out the one whose OK ends the session;
    which of the other two it is comes from the caller.
    """
    ok = 0
    # A prompt is a prompt, and a loading panel is not -- read end to end,
    # not by handing confirm_kind a button that recognise never found.
    for img, name, want in ((prompt(True), "pink prompt", D.EXIT),
                            (prompt(False), "grey prompt", D.EXIT),
                            (loading_panel(), "loading panel", D.DIALOG)):
        got = D.recognise(img)["state"]
        print("  %-14s reads as %s" % (name, got))
        ok += got == want
    kind_pink = D.confirm_kind(prompt(True), PINK_OK)
    kind_grey = D.confirm_kind(prompt(False), GREY_OK)
    print("  pink Cancel reads %r, grey Cancel reads %r"
          % (kind_pink, kind_grey))
    ok += kind_pink == "party"
    ok += kind_grey == "beenden"

    sim = Sim([])
    bot = make_bot(sim)
    saved = []
    bot.save_unknown = lambda img, tag: saved.append(tag)
    bot.dismiss_confirm = D.DungeonBot.dismiss_confirm.__get__(bot)

    def answer(kind, **kw):
        sim.clicks = []
        saved[:] = []
        bot.dismiss_confirm({"state": D.EXIT, "exit_ok": PINK_OK,
                             "exit_kind": kind}, **kw)
        return list(sim.clicks), list(saved)

    clicks, _ = answer("party", leaving_dungeon=True)
    print("  pink, on the way out of a dungeon: %s" % clicks)
    ok += clicks == ["OK, Party verlassen"]

    clicks, _ = answer("party")
    print("  pink, anywhere else: %s" % clicks)
    ok += clicks == ["Abbrechen"]

    # Even asked to leave a dungeon, the exit prompt is never confirmed.
    clicks, kept = answer("beenden", leaving_dungeon=True)
    print("  grey, even on the way out of a dungeon: %s, kept %s"
          % (clicks, kept))
    ok += clicks == ["Abbrechen"]
    ok += kept == ["confirm_beenden"]
    return ok, 9


def reopen_cases():
    """A card that drops back to the list gets one more look.

    A live run left Metal Sea with an attempt unspent: the panel closed
    itself after a battle, the list showed, and the dungeon counted as
    finished. Once, though -- a card the game keeps closing must not become
    a loop.
    """
    ok = 0
    # In the list, open the card, one attempt, and the panel is gone again.
    good, _, sim = run_case([D.LIST, D.DIALOG, D.LIST],
                            "card re-opened after dropping to the list",
                            None, attempt_wirkt=True, min_battle=0)
    taps = [c for c in sim.clicks if c == "Test"]
    print("     card taps: %d, clicks %s" % (len(taps), sim.clicks[:6]))
    ok += len(taps) == 2

    # Nothing was attempted, so the list means it never opened. No re-open.
    good, _, sim = run_case([D.LIST, D.LIST],
                            "list straight away is not re-opened", None)
    print("     card taps: %d" % len([c for c in sim.clicks if c == "Test"]))
    ok += len([c for c in sim.clicks if c == "Test"]) == 1
    return ok, 2


def return_cases():
    """Finding the way back to the list from a prompt.

    Whether OK may be pressed depends on what was on screen one frame
    earlier. A dungeon panel means the prompt is the dungeon's own; anything
    else means it could be "Return to the title screen?", which must not be
    confirmed.
    """
    ok = 0
    for before, expected in ((D.DIALOG_PARTY, True), (D.UNKNOWN, False)):
        sim = Sim([before, D.EXIT, D.LIST])
        bot = make_bot(sim)
        seen = []
        bot.dismiss_confirm = (lambda info=None, leaving_dungeon=False:
                               seen.append(leaving_dungeon))
        bot.return_to_list = D.DungeonBot.return_to_list.__get__(bot)
        orig = D.recognise
        D.recognise = sim.next_state
        try:
            bot.return_to_list()
        finally:
            D.recognise = orig
        print("  prompt after %-13s -> OK allowed: %s" % (before, seen))
        ok += seen == [expected]
    return ok, 2


# ----------------------------------------------------------------------------
# The way home
# ----------------------------------------------------------------------------
# Every size the real frames were measured at, plus the two shapes that catch
# the mistakes: 1080 x 1920 is an ADB frame, where the reference rect starts
# above and left of the image, and 730 x 1389 is a window of the wrong shape,
# where LDPlayer letterboxes the game and every fraction slides. A recogniser
# that has only been run on one of those has not been tested. See CLAUDE.md.
HOME_SIZES = ((805, 1390), (765, 1390), (657, 1198), (573, 1056), (497, 914),
              (1080, 1920), (730, 1389))


def blank(w, h):
    return np.full((h, w, 3), 30, np.uint8)


def globe_tile(side):
    """The wireframe globe, drawn eight times over and shrunk down.

    Drawn straight at the target size, the stroke is one whole pixel wide or
    two, and the glyph's fill jumps from 0.27 to 0.62 between two window
    sizes twenty pixels apart -- an artefact of the drawing, not of the
    shape, and exactly the sort of thing that makes a painted case pass or
    fail for a reason the game knows nothing about. Shrinking a big drawing
    keeps the stroke the same share of the glyph: fill stays at 0.42 to 0.48
    over every size below, against 0.42 to 0.49 measured on the real button.
    """
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


def paint_home(img, bright=True):
    """The home button where the game draws it, in the bottom nav bar.

    `bright` off is the same button with a dialog over it: the game dims what
    is behind one, and the dimmed glyph leaves the white range entirely --
    which is what lets one test answer both "where do I tap" and "is anything
    covering it".
    """
    x0, y0, gw, gh = D.game_rect(img)
    cx, cy = int(x0 + 0.481 * gw), int(y0 + 0.945 * gh)
    r = int(0.081 * gw / 2)
    cv2.circle(img, (cx, cy), r, (210, 140, 60) if bright else (70, 60, 50), -1)
    cv2.circle(img, (cx, cy), int(r * 0.62), (90, 40, 20), -1)
    side = int(round(0.0485 * gw))
    tile = globe_tile(side)
    x, y = cx - side // 2, cy - side // 2
    img[y:y + side, x:x + side][tile] = ((255, 255, 255) if bright
                                         else (110, 110, 110))
    return img


def paint_white_bar(img):
    """A white panel across the bottom, which is what a loading screen and
    Special Summon standing open over the game both look like down there. It
    fills the whole crop -- 0.125 wide against the globe's 0.048 -- and is why
    the width band has a ceiling and not only a floor."""
    x0, y0, gw, gh = D.game_rect(img)
    cv2.rectangle(img, (max(0, int(x0 + 0.30 * gw)), int(y0 + 0.88 * gh)),
                  (int(x0 + 0.70 * gw), int(y0 + 0.99 * gh)),
                  (250, 250, 250), -1)
    return img


def home_button_cases():
    ok = 0
    for w, h in HOME_SIZES:
        found = D.home_button(paint_home(blank(w, h)))
        good = (found is not None and abs(found["fx"] - 0.481) <= 0.01
                and abs(found["fy"] - 0.945) <= 0.01)
        print("  %4d x %-4d  globe -> %s  %s"
              % (w, h, ("fx %.3f fy %.3f fw %.4f"
                        % (found["fx"], found["fy"], found["fw"])
                        if found else "not found"),
                 "ok" if good else "FAILED"))
        ok += good
    negatives = (("dimmed by a dialog", paint_home(blank(805, 1390), bright=False)),
                 ("white panel over the bar", paint_white_bar(blank(805, 1390))),
                 ("nothing down there", blank(805, 1390)))
    for name, img in negatives:
        found = D.home_button(img)
        print("  %-24s -> %s  %s"
              % (name, "found" if found else "None",
                 "ok" if not found else "FAILED"))
        ok += found is None
    return ok, len(HOME_SIZES) + len(negatives)


class HomeScreen:
    """One word per round: what go_home sees when it looks.

    "main" is the main screen with nothing over it, "bar" a screen with the
    nav bar on it, "away" anything else. Scripted rather than painted: the
    pictures have their own cases above, these are about the order of the
    steps.
    """

    def __init__(self, script):
        self.script = list(script)
        self.presses = 0
        self.back_to_list = 0

    def grab(self):
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]

    def tap(self, fx, fy, was=""):
        self.presses += 1

    def to_list(self, tries=5):
        self.back_to_list += 1
        return True


def home_bot(screen, dry_run=False):
    bot = make_bot(Sim([D.LIST]))
    bot.dry_run = dry_run
    bot.grab = screen.grab
    bot.tap = screen.tap
    bot.return_to_list = screen.to_list
    bot.save_unknown = lambda img, tag: None
    return bot


def go_home_cases():
    """What go_home does with each screen a run can end on."""
    ok = 0
    cases = [
        ("already on the main screen", ["main"], True, 0, 0),
        ("from the list, one press", ["bar", "main"], True, 1, 0),
        ("first press swallowed", ["bar", "bar", "main"], True, 2, 0),
        ("never gets there", ["bar"] * 8, False, D.HOME_PRESSES_MAX, 0),
        ("no bar, back to the list first", ["away", "bar", "main"], True, 1, 1),
        ("nowhere it knows", ["away"] * 8, False, 0, 1),
    ]
    extra = 3
    orig_auto, orig_home = D.auto_button, D.home_button
    D.auto_button = (lambda img: {"fx": 0.361, "fy": 0.766}
                     if img == "main" else None)
    D.home_button = (lambda img: {"fx": 0.481, "fy": 0.945}
                     if img == "bar" else None)
    try:
        for name, script, expected, presses, backs in cases:
            screen = HomeScreen(script)
            got = home_bot(screen).go_home()
            good = (got == expected and screen.presses == presses
                    and screen.back_to_list == backs)
            print("  %-30s -> %-5s %d press(es), %d back to the list  %s"
                  % (name, got, screen.presses, screen.back_to_list,
                     "ok" if good else "FAILED"))
            ok += good

        # A dry run clicks nothing, so it must not then sit out its rounds
        # and report a failure that never happened.
        screen = HomeScreen(["bar"] * 8)
        got = home_bot(screen, dry_run=True).go_home()
        good = got is False and screen.presses == 1
        print("  %-30s -> %-5s %d press(es)  %s"
              % ("dry run presses once", got, screen.presses,
                 "ok" if good else "FAILED"))
        ok += good

        # go_home runs in a finally. A run that ended because the capture
        # died has to end with its own error, not with this one on top.
        screen = HomeScreen(["bar"])
        bot = home_bot(screen)
        said = []
        bot.log = said.append

        def dead():
            raise RuntimeError("capture is gone")

        bot.grab = dead
        good = (bot.go_home() is False
                and any("capture is gone" in line for line in said))
        print("  %-30s -> says so and carries on  %s"
              % ("a dead capture", "ok" if good else "FAILED"))
        ok += good

        # And it happens on the bad way out of run, not only the good one.
        screen = HomeScreen(["bar", "main"])
        bot = home_bot(screen)

        def broken():
            raise RuntimeError("mid-run")

        bot._play = broken
        threw = False
        try:
            bot.run()
        except RuntimeError:
            threw = True
        good = threw and screen.presses == 1
        print("  %-30s -> error kept, %d press(es)  %s"
              % ("a run that throws still goes home", screen.presses,
                 "ok" if good else "FAILED"))
        ok += good
    finally:
        D.auto_button, D.home_button = orig_auto, orig_home
    return ok, len(cases) + extra


def main():
    ok = 0
    total = 0

    print("Re-opening a card")
    a, b = reopen_cases()
    ok += a
    total += b
    print()

    print("Back to the list")
    a, b = return_cases()
    ok += a
    total += b
    print()

    print("Confirmation prompts")
    a, b = confirm_cases()
    ok += a
    total += b
    print()

    print("Party slots")
    a, b = party_cases()
    ok += a
    total += b
    print()

    print("Dungeon selection")
    a, b = selection_cases()
    ok += a
    total += b
    print()

    print("The home button")
    a, b = home_button_cases()
    ok += a
    total += b
    print()

    print("The way home")
    a, b = go_home_cases()
    ok += a
    total += b
    print()

    # The party dialog must end the dungeon, not lead into a loop. In a test
    # run it appeared four times in a row, because Cancel keeps the bot
    # stuck in the dialog.
    sim = Sim([D.EXIT] * 8, confirm_kind="party")
    orig_rec, orig_cards = D.recognise, D.list_cards
    D.recognise = sim.next_state
    D.list_cards = lambda img, with_size=False: ([(0.3, 0.12)] if with_size
                                                 else [0.3])
    try:
        bot = make_bot(sim)
        seen = []
        real_run = D.DungeonBot.dismiss_confirm
        def spy(info=None, leaving_dungeon=False):
            seen.append(leaving_dungeon)
        bot.dismiss_confirm = spy
        bot.play_entry(0, "oben")
        del real_run
    finally:
        D.recognise, D.list_cards = orig_rec, orig_cards
    good = len(seen) <= 2
    ok += good
    total += 1
    print("%-44s leave_exit %dx  should be at most 2  %s"
          % ("party dialog ends the dungeon", len(seen),
             "ok" if good else "FAILED"))

    # An ad never yields a ticket. After the first one has no effect, it
    # must stop, otherwise the bot runs six ads into nothing as it did in a
    # test run.
    good, _, _ = run_case([D.DIALOG_AD] * 12,
                     "ad without effect, must stop after 1", 1)
    ok += good
    total += 1

    # An ad works, then the Attempt button appears
    good, _, _ = run_case([D.DIALOG_AD, D.DIALOG, D.DIALOG_AD, D.DIALOG],
                     "ad works, then Attempt", None)
    ok += good
    total += 1

    # A reward window is closed and does not block
    good, _, sim = run_case(["close", D.DIALOG_AD, "close", D.DIALOG_AD],
                       "reward window in between", None)
    print("     click sequence: %s" % ", ".join(sim.clicks[:6]))
    ok += good
    total += 1

    print("\n%d of %d cases as expected" % (ok, total))


if __name__ == "__main__":
    main()
