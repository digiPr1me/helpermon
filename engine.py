"""
The minigame core. One loop, two front ends.

Previously deciding, clicking and printing were one lump, with `print` sitting
in the middle of the logic. That does not work for a window: it cannot display
`print` and would freeze while the loop runs.

So the core only reports **what happened**, not **where it should be written**.
It hands events to a callback. Who displays them is up to the caller.

  bot.py   turns the events into console lines
  gui.py   turns the same events into a log and tiles

That leaves exactly one engine. A fix works in both front ends, and the test
suites keep covering the same code.

The core also checks a stop flag before every action, so an emergency stop takes
effect immediately rather than at the end of the loop.
"""

import os
import time

import cv2

import actions
import capture
import explore
import guard
import planner as planner_mod
import tracker
import userdata
import vision
import world as world_mod

# Re-exported so existing callers (bot.py, gui.py) can keep writing
# engine.Stop(); the class itself lives in guard.py, shared with dungeon.py.
Stop = guard.Stop


# ----------------------------------------------------------------------------
# Event kinds. An event is a dictionary with the key "art".
# ----------------------------------------------------------------------------
INFO = "info"            # text
WARN = "warn"            # text
SETUP = "setup"          # calib, figure, capture, counters
PLANNED = "planned"      # nr, aktion, position
RESULT = "result"        # nr, zustand, deltas, counters, tempo
STOPPED = "stopped"      # grund, aktionen, dauer, counters


class Settings:
    """Everything that can be configured from outside. The window front end
    sets the same fields as the console, so there is no second source of
    truth."""

    def __init__(self, **kw):
        self.dry_run = True
        self.max_actions = 0          # 0 means no limit
        self.is_selected = list(world_mod.ALL_WANTED)
        self.min_paws = 20
        self.target_meters = 0
        self.click_delay = 0.7
        self.settle = 0.45
        self.min_pace = 0.60
        self.adaptive = True
        self.calib_frames = 5
        # None means the stored switch (userdata.adb_mode()) decides; True
        # or False overrides it for this run, which is what the "Check
        # calibration" button in gui.py needs to test the other mode.
        self.adb = None
        self.screencap = "png"
        self.bit_paw = planner_mod.BIT_PAW
        self.bit_claw = planner_mod.BIT_CLAW
        self.bit_skill = planner_mod.BIT_SKILL
        self.bit_per_action = planner_mod.BIT_PER_ACTION
        self.bit_pyramid_loot = planner_mod.BIT_PYRAMID_LOOT
        self.row_slack = planner_mod.ROW_SLACK
        self.bit_left_penalty = planner_mod.BIT_LEFT_PENALTY
        self.bit_middle_bias = planner_mod.BIT_MIDDLE_BIAS
        self.debugdir = "debug_explore"
        # Cold start. Starts the emulator and the game itself, then waits
        # until the minigame is visible. The bot deliberately does not
        # navigate menus, that is the most fragile part and changes with
        # every game update.
        self.autostart = False
        self.ld_index = 0
        self.ld_package = None
        self.wait_for_board = 0  # seconds, 0 means do not wait
        self.hotkeys = True  # global F7/F8 pause and abort keys
        # Open the board from the main screen and go back there at the end.
        # Off means the old behaviour: the player navigates there by hand,
        # the bot takes over wherever it is started, and wait_for_board (if
        # set) is what waits for that.
        self.navigate = True
        for key, value in kw.items():
            if not hasattr(self, key):
                raise TypeError("unknown setting %r" % key)
            setattr(self, key, value)


# ----------------------------------------------------------------------------
def merge_counters(cap, calib, tries=4, pause=0.25, need=("paws",)):
    """Merge counters across several frames.

    A single frame may fall inside an animation, making a counter unreadable.
    Across three to four frames, practically all values show up. The first
    readable value per counter counts.
    """
    merged = {}
    last_img = None
    for _ in range(tries):
        last_img = cap.grab()
        for key, value in vision.read_counters(last_img, calib).items():
            if value is not None and key not in merged:
                merged[key] = value
        if all(k in merged for k in need):
            break
        time.sleep(pause)
    return merged, last_img


def quiet_frame(cap, calib, templates, tries=4, pause=0.25, first=None,
                assume_calm=False, figure=None):
    """Wait for a calm frame before reading the board.

    Animations run after an action. While collecting, a ticket icon flies
    across the board and would be logged as an object on the wrong cell.
    Calm means two frames produce the same grid.
    """
    board = vision.board_templates(templates)
    last_grid = None
    img = None
    grid = None
    if first is not None:
        img = first
        last_grid, _ = vision.read_grid(img, calib, board, figure=figure)
        grid = last_grid
        if assume_calm:
            return img, grid, True
    for _ in range(tries):
        img = cap.grab()
        grid, _ = vision.read_grid(img, calib, board, figure=figure)
        if last_grid is not None and grid == last_grid:
            return img, grid, True
        last_grid = grid
        time.sleep(pause)
    return img, grid, False


def cold_start(settings, emit):
    """Start the emulator and the game. Returns the ADB serial or None."""
    try:
        import ldplayer
    except ImportError:
        emit({"art": WARN, "text": "ldplayer.py missing, cold start skipped"})
        return None
    try:
        ld = ldplayer.LdPlayer(log=lambda t: emit({"art": INFO, "text": t}))
        serial = ld.ensure_running(settings.ld_index,
                                   package=settings.ld_package)
        os.environ["DGUP_SERIAL"] = serial
        emit({"art": INFO, "text": "cold start done, device %s" % serial})
        return serial
    except Exception as err:
        emit({"art": WARN, "text": "cold start failed: %s" % err})
        return None


def board_visible(img, templates):
    """Is the minigame open? Geometry must fit and the figure must be found.
    Both together are reliable evidence, neither alone is."""
    try:
        calib = vision.calibrate(img)
    except vision.CalibrationError:
        return None, None
    if vision.banner_visible(img, calib):
        return calib, None
    return calib, vision.find_figure(img, calib, templates)


def wait_for_board(cap, templates, seconds, emit, stop=None, poll=1.5,
                   settings=None):
    """Wait until the minigame is visible.

    This covers the cold start without the bot having to operate menus. You
    click your way through daily rewards and events yourself, and the bot
    takes over the moment the board appears.

    What it gives up on is kept, for the same reason find_start keeps its
    frame: a wait that ran out says nothing about whether the board was
    never opened or was opened and not recognised.
    """
    deadline = time.time() + seconds
    said = False
    last = None
    while time.time() < deadline:
        if stop is not None and stop.is_set():
            return False
        try:
            img = cap.grab()
        except Exception as err:
            emit({"art": WARN, "text": "no frame: %s" % err})
            time.sleep(poll)
            continue
        last = img
        calib, figure = board_visible(img, templates)
        if calib and figure:
            emit({"art": INFO, "text": "minigame recognised, taking over"})
            return True
        if not said:
            emit({"art": INFO, "text": "waiting for the minigame, please navigate there yourself"})
            said = True
        time.sleep(poll)
    emit({"art": WARN, "text": "minigame not recognised within %d s" % seconds})
    if settings is not None and last is not None:
        path = _save_debug(settings, "no_board", last, emit)
        if path:
            emit({"art": WARN, "text": "the last frame is in %s" % path})
    return False


def open_capture(settings, emit=print):
    """Frame source and input, chosen by the global switch (userdata.adb_mode)
    unless settings.adb overrides it for this one call.

      ADB      frames and clicks both via ADB, insensitive to window state
      window   everything via the window. The mouse is then blocked and the
               window must stay visible and unobscured
    """
    adb = userdata.adb_mode() if settings.adb is None else settings.adb
    cap = capture.open_for(adb)
    if settings.screencap != "auto" and not cap.moves_mouse:
        cap.method = settings.screencap
    return cap


def find_start(cap, templates, settings, emit, stop=None):
    """Wait for a calm frame in which geometry, figure and paws are certain.

    Whatever it gives up on, it keeps the frame. A run that ends here used
    to leave nothing behind but "no portrait-format card found", which says
    what the reader missed and not what was on the screen -- and the two
    answers ("the board was not open" against "the board was open and the
    reader could not see it") need completely different work. The frame is
    the only thing that tells them apart afterwards.
    """
    samples = []
    calib = None
    last = None
    ever = False
    for _ in range(30):
        if stop is not None and stop.is_set():
            return None
        img = cap.grab()
        last = img
        try:
            fresh = vision.calibrate(img)
        except vision.CalibrationError as err:
            emit({"art": WARN, "text": "calibration not possible yet: %s" % err})
            time.sleep(0.4)
            continue
        ever = True
        if vision.banner_visible(img, fresh):
            emit({"art": INFO, "text": "banner visible, waiting"})
            time.sleep(0.6)
            continue
        samples.append(fresh)
        calib = vision.median_calib(samples)
        if len(samples) < settings.calib_frames:
            continue

        counters, img = merge_counters(cap, calib)
        last = img
        figure = vision.find_figure(img, calib, templates)
        if figure and counters.get("paws") is not None:
            img, grid, _ = quiet_frame(cap, calib, templates)
            figure = vision.find_figure(img, calib, templates) or figure
            return calib, img, grid, figure, counters
        emit({"art": WARN, "text": "waiting for a calm frame, figure %s, paws %s"
              % (figure and figure["how"], counters.get("paws"))})
        time.sleep(0.5)

    if not ever:
        emit({"art": WARN, "text":
              "the minigame board was never on the screen. Open Digital "
              "World Search in the game yourself, wait for the board, then "
              "start again."})
    if last is not None:
        path = _save_debug(settings, "no_start", last, emit)
        if path:
            emit({"art": WARN, "text": "the frame it gave up on is in %s" % path})
    return None


# ----------------------------------------------------------------------------
def run(settings, emit, stop=None):
    """The loop. Returns the summary at the end.

    emit receives events, stop is checked before every action.
    """
    stop = stop or Stop()
    os.makedirs(settings.debugdir, exist_ok=True)

    if settings.autostart:
        cold_start(settings, emit)

    cap = open_capture(settings, emit)

    control = None
    if settings.hotkeys:
        control = guard.start(stop,
                              log=lambda t: emit({"art": INFO, "text": t}))

    nav = None
    if settings.navigate:
        nav = explore.Nav(cap, dry_run=settings.dry_run, control=stop,
                          log=lambda t: emit({"art": INFO, "text": t}))

    try:
        # open_board is inside the try, not before it, unlike the sketch in
        # PLAN_WORLD_SEARCH_NAV.md 5.4: a run that fails to reach the board
        # still needs its way back and its hotkeys unregistered, the same
        # "every way out, not only the good one" rule the plan states for
        # go_home and leave_summons elsewhere. A return before the finally
        # would skip both.
        if nav is not None:
            if not nav.open_board() and not settings.dry_run:
                emit({"art": WARN, "text": "could not open the Digital World Search"})
                return None
        return _run_loop(settings, emit, stop, cap)
    finally:
        if nav is not None:
            nav.leave_board()
        if control:
            control.stop()


def _run_loop(settings, emit, stop, cap):
    templates = vision.load_templates()
    if not templates:
        emit({"art": WARN, "text": "no templates found in the templates folder"})
        return None

    if settings.wait_for_board:
        if not wait_for_board(cap, templates, settings.wait_for_board, emit,
                              stop, settings=settings):
            return None

    started = find_start(cap, templates, settings, emit, stop)
    if started is None:
        emit({"art": WARN, "text": "no usable start frame. Diagnose with counters_probe.py and calibrate.py"})
        return None
    calib, img, grid, figure, counters = started

    world = world_mod.World(is_selected=settings.is_selected)
    # Observe twice, because an object needs two sightings to be confirmed.
    # At the start the frame is calm, so that is not a concern.
    world.observe(grid, figure)
    world.observe(grid, figure)

    plan = planner_mod.Planner(
        world, min_paws=settings.min_paws, target_meters=settings.target_meters,
        bit_paw=settings.bit_paw, bit_claw=settings.bit_claw,
        bit_skill=settings.bit_skill, bit_per_action=settings.bit_per_action,
        bit_pyramid_loot=settings.bit_pyramid_loot, row_slack=settings.row_slack,
        bit_left_penalty=settings.bit_left_penalty,
        bit_middle_bias=settings.bit_middle_bias)
    actor = actions.Actor(cap, calib, templates, click_delay=settings.click_delay,
                          settle=settings.settle, min_pace=settings.min_pace,
                          adaptive=settings.adaptive, dry_run=settings.dry_run,
                          log=lambda t: emit({"art": INFO, "text": t}))
    counters_state = tracker.CounterTracker(max_actions_per_frame=1)
    counters_state.update(counters)

    emit({"art": SETUP, "calib": calib, "figure": figure,
          "capture": getattr(cap, "method", "?"), "counters": dict(counters_state.values),
          "text": "cell %.2f x %.2f, start row %d column %d"
                  % (calib["cell_w"], calib["cell_h"], figure["row"] + 1,
                     figure["col"] + 1)})

    done = 0
    t_start = time.time()
    reason = "action limit reached"

    while not settings.max_actions or done < settings.max_actions:
        if stop.is_set():
            reason = stop.reason or "aborted"
            break

        go_on, was_paused = stop.wait_while_paused(emit)
        if not go_on:
            reason = stop.reason or "aborted"
            break
        if was_paused:
            # Nach einer Pause nichts annehmen. Der Mensch kann die Figur
            # bewegt oder Ressourcen ausgegeben haben, deshalb Position,
            # Brett und Zaehler frisch bestimmen.
            actor.on_trouble()  # wieder vorsichtig starten
            img, grid, _ = quiet_frame(cap, calib, templates)
            found = vision.find_figure(img, calib, templates)
            if found:
                world.row = found["row"]
                world.col = min(found["col"], world_mod.FIG_COL_MAX)
            world.observe(grid, found)
            fresh, _ = merge_counters(cap, calib)
            counters_state.update(fresh)
            emit({"art": INFO, "text": "re-read after pause: %s"
                  % world.describe()})

        action = plan.next_action(counters_state.values)
        emit({"art": PLANNED, "nr": done + 1, "aktion": str(action),
              "position": world.describe(), "kind": action.kind,
              "reason": action.reason})

        if action.kind == "stop":
            reason = action.reason
            break

        if action.kind == "wait":
            actor.wait_tick()
            img, grid, _ = quiet_frame(cap, calib, templates)
            world.observe(grid, vision.find_figure(img, calib, templates))
            done += 1
            continue

        before = dict(counters_state.values)
        state, after, img, deltas = actor.perform(action, before, world.col)

        if actor.dry_run:
            # In a dry run, the effect is assumed, so the planner can be
            # judged over several steps
            _apply(world, action)
            emit({"art": RESULT, "nr": done + 1, "zustand": "dry_run",
                  "deltas": {}, "counters": dict(counters_state.values),
                  "tempo": actor.pace, "takt": actor.click_delay})
            actor.wait_tick()
            img, grid, _ = quiet_frame(cap, calib, templates)
            world.observe(grid, vision.find_figure(img, calib, templates))
            done += 1
            continue

        if state == actions.BANNER_UNKNOWN:
            path = _save_debug(settings, "banner_UNBEKANNT",
                               vision.banner_roi(img, calib), emit)
            emit({"art": WARN, "text": "unknown banner text, aborting.%s"
                  % (" Saved to %s" % path if path else "")})
            reason = "unknown banner text"
            break

        if state == actions.OK:
            _apply(world, action)
            counters_state.update(after)
        elif state == actions.INSUFFICIENT:
            resource = {"destroy": "claws", "skill": "fireballs",
                        "step": "paws"}[action.kind]
            counters_state.values[resource] = 0
            emit({"art": WARN, "text": "%s used up, planner adapts" % resource})
            if resource == "paws":
                reason = "no paws left"
                break
            time.sleep(2.1)
        elif state == actions.MOVED_INSTEAD:
            emit({"art": INFO, "text": "pyramid was already gone, logged as step %s" % action.direction})
            world.forget(world.fig_gcol + (1 if action.direction == "right" else 0),
                         action.cell[0])
            world.apply_step(action.direction)
            world.mark_collected(world.fig_gcol, world.row)
            counters_state.update(after)
        else:
            _save_debug(settings, "resync", img, emit)
            time.sleep(2.1)  # the banner takes about two seconds to fade
            img = actor.grab()
            found = vision.find_figure(img, calib, templates)
            if found:
                world.row = found["row"]
                world.col = min(found["col"], world_mod.FIG_COL_MAX)
            counters_state.update(vision.read_counters(img, calib))

        emit({"art": RESULT, "nr": done + 1, "zustand": state, "deltas": deltas,
              "counters": dict(counters_state.values), "tempo": actor.pace,
              "takt": actor.click_delay,
              "verworfen": list(counters_state.suspicious),
              "nachgezogen": list(counters_state.resynced)})

        actor.wait_tick()
        # Without collecting anything the board stays still, so the check frame is enough
        picked = any(v > 0 for v in deltas.values())
        img, grid, calm = quiet_frame(cap, calib, templates, tries=2,
                                      pause=0.15 * actor.pace, first=img,
                                      assume_calm=not picked,
                                      figure=(world.row, world.col))
        if not calm:
            emit({"art": INFO, "text": "frame still unsettled, observation provisional"})
        world.observe(grid, None)
        _queue_unknowns(img, calib, grid, world, emit)
        done += 1

    if _debug_counts:
        emit({"art": INFO, "text": "debug frames: " + ", ".join(
            "%s %d" % (k, v) for k, v in sorted(_debug_counts.items()))})
    summary = {"art": STOPPED, "grund": reason, "aktionen": done,
               "dauer": time.time() - t_start,
               "counters": dict(counters_state.values),
               "position": world.describe(), "tempo": actor.pace}
    emit(summary)
    return summary


# Limit debug images. A run of several hours would otherwise produce hundreds
# of images and fill the disk. Only the first few cases are saved, after that
# just counted, since the tenth resync of the same kind shows nothing new.
DEBUG_IMAGE_LIMIT = 8
_debug_counts = {}


def _save_debug(settings, kind, img, emit=None):
    n = _debug_counts.get(kind, 0)
    _debug_counts[kind] = n + 1
    if n >= DEBUG_IMAGE_LIMIT:
        if n == DEBUG_IMAGE_LIMIT and emit:
            emit({"art": INFO, "text": "further %s frames will only be counted, not saved" % kind})
        return None
    path = os.path.join(settings.debugdir, "%s_%02d.png" % (kind, n))
    cv2.imwrite(path, img)
    return path


def debug_counts():
    return dict(_debug_counts)


_QUEUED = set()


def _queue_unknowns(img, calib, grid, world, emit, limit=12):
    """Stash colourful finds with no matching template, to label them later.

    Rare power-up types do not show up in a short session, so they are
    collected during operation and learned afterwards in the wizard.
    """
    if len(_QUEUED) >= limit:
        return
    try:
        import learning
    except ImportError:
        return
    for row in range(vision.ROWS):
        for col in range(vision.COLS):
            if grid[row][col] != "?":
                continue
            key = (world.to_global(col), row)
            if key in _QUEUED:
                continue
            _QUEUED.add(key)
            try:
                learning.queue_unknown(img, calib, row, col)
                emit({"art": INFO, "text": "unknown object queued, label it in the wizard under Open cases"})
            except Exception:
                pass


def _apply(world, action):
    if action.kind == "step":
        world.apply_step(action.direction)
        world.mark_collected(world.fig_gcol, world.row)
    elif action.kind == "destroy":
        world.forget(world.to_global(action.cell[1]), action.cell[0])
    elif action.kind == "skill":
        gain = world.apply_skill()
        # The skill collects everything and clears pyramids along its path
        for back in range(gain + 1):
            world.forget(world.fig_gcol - back, world.row)
            world.mark_collected(world.fig_gcol - back, world.row)
