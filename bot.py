"""
Console front end. A thin wrapper around engine.run.

The logic lives in engine.py so that console and window share one core. Here the
events are only turned into lines.

  py bot.py                     dry run, plans but does NOT click
  py bot.py --go                actually clicks
  py bot.py --go --max-actions 20
  py bot.py --go --wanted ticket_orange,ticket_green
  py bot.py --go --bit-per-action 0     resources only, no time value

F7 pauses/resumes and F8 aborts globally, even with the emulator window in
focus instead of this console. See guard.py. Disable both with
--no-hotkeys. Moving the mouse no longer pauses anything.
"""

import argparse

import engine
import planner as planner_mod
import world as world_mod

LABEL = {"paws": "paws", "claws": "claws", "fireballs": "fireballs",
         "meters": "metres", "top_orange": "orange", "top_green": "green",
         "top_pink": "pink"}


def show(ev):
    kind = ev["art"]
    if kind in (engine.INFO, engine.WARN):
        print(("    " if kind == engine.INFO else "") + ev["text"], flush=True)
    elif kind == engine.SETUP:
        print("capture: %s" % ev["capture"])
        print(ev["text"], flush=True)
    elif kind == engine.PLANNED:
        print("\n#%d  %s  ->  %s" % (ev["nr"], ev["position"], ev["aktion"]),
              flush=True)
    elif kind == engine.RESULT:
        deltas = ", ".join("%s %+d" % (LABEL.get(k, k), v)
                           for k, v in ev["deltas"].items())
        print("    result %s   %s   pace %.2f, tick %.2f s"
              % (ev["zustand"], deltas or "no change", ev["tempo"],
                 ev["takt"]), flush=True)
        for key, old, new in ev.get("verworfen") or []:
            print("    REJECTED %s %s -> %s, implausible"
                  % (LABEL.get(key, key), old, new))
        for key, old, new in ev.get("nachgezogen") or []:
            print("    RESYNCED %s %s -> %s, same value repeatedly"
                  % (LABEL.get(key, key), old, new))
    elif kind == engine.STOPPED:
        print("\nEnd: %s" % ev["grund"])
        print("%d actions in %.0f s, %.2f s per action"
              % (ev["aktionen"], ev["dauer"],
                 ev["dauer"] / max(ev["aktionen"], 1)))
        print("%s, pace %.2f" % (ev["position"], ev["tempo"]))
        print("counters " + " ".join("%s=%s" % (LABEL.get(k, k), v)
                                    for k, v in ev["counters"].items()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually click")
    ap.add_argument("--max-actions", type=int, default=25,
                    help="0 means no limit")
    ap.add_argument("--click-delay", type=float, default=0.7)
    ap.add_argument("--settle", type=float, default=0.45)
    ap.add_argument("--min-pace", type=float, default=0.60)
    ap.add_argument("--fixed-pace", action="store_true")
    ap.add_argument("--min-paws", type=int, default=20)
    ap.add_argument("--target-meters", type=int, default=0)
    ap.add_argument("--calib-frames", type=int, default=5)
    ap.add_argument("--wanted", default=",".join(world_mod.ALL_WANTED))
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames and clicks via adb or via the window and "
                         "mouse. Default: the stored switch (Helpermon's "
                         "window, or DGUP_ADB_MODE)")
    ap.add_argument("--screencap", choices=["auto", "raw", "png"], default="png")
    ap.add_argument("--bit-paw", type=int, default=planner_mod.BIT_PAW)
    ap.add_argument("--bit-claw", type=int, default=planner_mod.BIT_CLAW)
    ap.add_argument("--bit-skill", type=int, default=planner_mod.BIT_SKILL)
    ap.add_argument("--bit-per-action", type=int,
                    default=planner_mod.BIT_PER_ACTION)
    ap.add_argument("--bit-pyramid-loot", type=int,
                    default=planner_mod.BIT_PYRAMID_LOOT)
    ap.add_argument("--row-slack", type=int, default=planner_mod.ROW_SLACK)
    ap.add_argument("--bit-left-penalty", type=int,
                    default=planner_mod.BIT_LEFT_PENALTY,
                    help="surcharge for steps left, 0 makes them equal")
    ap.add_argument("--bit-middle-bias", type=int,
                    default=planner_mod.BIT_MIDDLE_BIAS,
                    help="bias towards the centre row, 0 disables it")
    ap.add_argument("--debugdir", default="debug_explore")
    ap.add_argument("--autostart", action="store_true",
                    help="start LDPlayer and the game")
    ap.add_argument("--ld-index", type=int, default=0)
    ap.add_argument("--ld-package", default=None)
    ap.add_argument("--wait-for-board", type=int, default=0,
                    help="wait this many seconds for the minigame, 0 to disable")
    ap.add_argument("--no-hotkeys", "--no-mouse-guard",
                    action="store_true", dest="no_hotkeys",
                    help="disable the global F7/F8 pause and abort keys "
                         "(--no-mouse-guard is the old name for this)")
    args = ap.parse_args()

    settings = engine.Settings(
        dry_run=not args.go, max_actions=args.max_actions,
        is_selected=[w.strip() for w in args.wanted.split(",") if w.strip()],
        min_paws=args.min_paws, target_meters=args.target_meters,
        click_delay=args.click_delay, settle=args.settle,
        min_pace=args.min_pace, adaptive=not args.fixed_pace,
        calib_frames=args.calib_frames,
        adb=None if args.input is None else args.input == "adb",
        screencap=args.screencap, bit_paw=args.bit_paw, bit_claw=args.bit_claw,
        bit_skill=args.bit_skill, bit_per_action=args.bit_per_action,
        bit_pyramid_loot=args.bit_pyramid_loot, row_slack=args.row_slack,
        debugdir=args.debugdir, autostart=args.autostart,
        hotkeys=not args.no_hotkeys,
        ld_index=args.ld_index, ld_package=args.ld_package,
        wait_for_board=args.wait_for_board)

    print("Mode: %s" % ("REAL, it will click" if args.go
                        else "dry run, no clicks"))
    print("Looking for %s" % ", ".join(settings.is_selected))
    stop = engine.Stop()
    _start_key_listener(stop)
    try:
        engine.run(settings, show, stop)
    except KeyboardInterrupt:
        print("\naborted")


def _start_key_listener(stop):
    """Pause key in the console. Space pauses and resumes, q aborts. Windows
    only, msvcrt is a built-in module there. Without msvcrt everything runs
    as before, just without key control."""
    try:
        import msvcrt
    except ImportError:
        return
    import threading

    def loop():
        while not stop.is_set():
            ch = msvcrt.getwch()
            if ch == " ":
                paused = stop.toggle_pause()
                print("    %s" % ("paused, space resumes"
                                  if paused else "resumed"), flush=True)
            elif ch in ("q", "Q"):
                stop.request("key q")
                print("    abort requested", flush=True)

    threading.Thread(target=loop, daemon=True).start()
    print("Keys: space pauses, q aborts")


if __name__ == "__main__":
    main()
