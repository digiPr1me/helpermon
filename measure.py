"""
Measurement mode. Performs single actions and logs every counter before and
after, so costs are measured rather than assumed.

  py measure.py --action right --repeat 3
  py measure.py --action up
  py measure.py --action skill
  py measure.py --action destroy --dir right
  py measure.py --dry-run

Exactly one action per tick, waiting in between until the counters settle.
"""
import argparse
import time

import actions
import engine
import capture
import userdata
import vision
import world as world_mod

KEYS = ["paws", "claws", "fireballs", "meters", "top_orange", "top_green", "top_pink"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--action", required=True,
                    choices=["up", "down", "left", "right", "skill", "destroy"])
    ap.add_argument("--dir", default="right", choices=["up", "down", "left", "right"],
                    help="Richtung der Pyramide bei --action destroy")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--click-delay", type=float, default=1.8)
    ap.add_argument("--calib-frames", type=int, default=5)
    args = ap.parse_args()

    cap = capture.open_for(userdata.adb_mode())
    templates = vision.load_templates()
    st = engine.Settings(calib_frames=args.calib_frames)
    started = engine.find_start(cap, templates, st,
                                lambda e: print(e.get("text", "")))
    if started is None:
        raise SystemExit("kein brauchbarer Startframe")
    calib, img, grid, figure, counters = started
    world = world_mod.World()
    world.observe(grid, figure)
    actor = actions.Actor(cap, calib, templates, click_delay=args.click_delay,
                          dry_run=args.dry_run)
    print("Start", world.describe())
    print("Zaehler", {k: counters.get(k) for k in KEYS})

    for i in range(args.repeat):
        before, _, _ = actions.merge_counters(cap, calib)
        if args.action == "skill":
            actor.tap_skill()
            target = "Skillknopf"
        else:
            direction = args.dir if args.action == "destroy" else args.action
            dr, dc = {"up": (-1, 0), "down": (1, 0), "left": (0, -1),
                      "right": (0, 1)}[direction]
            row, col = world.row + dr, world.col + dc
            actor.tap_cell(row, col)
            target = "r%dc%d" % (row + 1, col + 1)

        time.sleep(args.click_delay)
        after, _, img_after = actions.merge_counters(cap, calib)
        actor.last_frame = img_after
        banner = vision.classify_banner(img_after, calib)
        deltas = {k: (after.get(k) - before.get(k))
                  for k in KEYS
                  if before.get(k) is not None and after.get(k) is not None
                  and after.get(k) != before.get(k)}
        print("\n%d. %s auf %s   Banner %s" % (i + 1, args.action, target, banner or "nein"))
        print("   vorher ", {k: before.get(k) for k in KEYS})
        print("   nachher", {k: after.get(k) for k in KEYS})
        print("   DELTA  ", deltas or "no change")

        figure = vision.find_figure(actor.last_frame, calib, templates)
        grid, _ = vision.read_grid(actor.last_frame, calib,
                                   vision.board_templates(templates))
        world.observe(grid, figure)
        print("   Position laut Bild:", world.describe())


if __name__ == "__main__":
    main()
