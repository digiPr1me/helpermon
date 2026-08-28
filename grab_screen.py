"""
Save what the emulator is showing right now, and say what the bots make of it.

For the rounds where a screen stops a bot and the log alone does not say
why. Bring the screen up by hand, run this, and it writes the frame plus the
recognition result -- the same result the dungeon bot acts on.

  py grab_screen.py                 5 s to bring the screen up, then grab
  py grab_screen.py --wait 10       longer, for a screen that takes clicking
  py grab_screen.py --name prompt   choose the file name

The frame lands in debug_dungeon/, which git ignores, so nothing from the
game ends up in the repository.
"""
import argparse
import os
import time

import cv2

import capture
import dungeon as D
import userdata

OUT = "debug_dungeon"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=5.0,
                    help="seconds before grabbing, to bring the screen up")
    ap.add_argument("--name", default="screen")
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames via adb or via the window. Default: the "
                         "stored switch (Helpermon's window, or "
                         "DGUP_ADB_MODE)")
    args = ap.parse_args()

    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)
    for left in range(int(args.wait), 0, -1):
        print("  %d ..." % left)
        time.sleep(1)

    img = cap.grab()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "%s.png" % args.name)
    cv2.imwrite(path, img)
    print("\nsaved %s, %d x %d" % (path, img.shape[1], img.shape[0]))

    info = D.recognise(img)
    print("state          %s" % info["state"])
    if info["state"] == D.EXIT:
        # The two prompts that look alike. Which one this is decides whether
        # OK is the way out or the end of the session.
        print("prompt kind    %s  (party -> OK, beenden -> Cancel)"
              % info.get("exit_kind"))
        print("OK button      %s" % _short(info.get("exit_ok")))
    for key in ("attempt", "party", "ad", "clear", "giveup"):
        if info.get(key):
            print("%-14s %s" % (key, _short(info[key])))
    if info.get("party_voll") is not None:
        print("party slots    %s filled" % info["party_voll"])
    print("claim button   %s" % _short(D.claim_button(img)))
    print("pop-up OK      %s" % _short(D.popup_ok(img)))

    # Per card, what the pre-check would decide and why. "unclear" is not
    # necessarily a misread: a card at 0 tickets that still has an ad
    # counter beside it is unclear on purpose. This says which it is.
    cards = D.list_cards(img, with_size=True)
    print("list cards     %d" % len(cards))
    for i, (fy, fh) in enumerate(cards):
        verdict = D.card_has_attempts(img, fy, fh)
        says = {True: "tickets available", False: "at 0, no ads",
                None: "unclear -> would be tried"}[verdict]
        print("  card %d  fy %.3f  %s" % (i + 1, fy, says))


def _short(button):
    if not button:
        return "none"
    return ("fx %.3f  fy %.3f  width %.3f"
            % (button["fx"], button["fy"], button["fw"]))


if __name__ == "__main__":
    main()
