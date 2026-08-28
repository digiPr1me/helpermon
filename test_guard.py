"""
The run control: the pause flag, the global hotkeys, and the watcher that
is gone.

No emulator and no display needed. The hotkeys are called directly rather
than pressed, so the whole file runs without the `keyboard` package.

  py test_guard.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import guard
import userdata


# --- the flag every bot checks --------------------------------------------
def stop_flag():
    stop = guard.Stop()
    assert not stop.is_set() and not stop.is_paused()

    assert stop.toggle_pause() is True and stop.is_paused()
    assert stop.toggle_pause() is False and not stop.is_paused()

    # Not paused: wait_while_paused says go on and admits it did not wait,
    # which is what tells a caller whether the screen has to be re-read.
    assert stop.wait_while_paused() == (True, False)

    stop.pause()
    released = []

    def resume_soon():
        time.sleep(0.1)
        released.append(True)
        stop.resume()

    threading.Thread(target=resume_soon, daemon=True).start()
    go_on, was_paused = stop.wait_while_paused(tick=0.01)
    assert released, "wait_while_paused returned before anything resumed it"
    assert (go_on, was_paused) == (True, True)
    print("pause blocks until something resumes it, and says that it waited")

    # An abort during a pause gets out of it, and says stop rather than go on.
    stop.pause()
    threading.Thread(target=lambda: (time.sleep(0.1), stop.request("test")),
                     daemon=True).start()
    assert stop.wait_while_paused(tick=0.01) == (False, True)
    assert stop.is_set() and stop.reason == "test"
    stop.clear()
    assert not stop.is_set() and not stop.is_paused()
    print("an abort gets a bot out of a pause and reports itself")


# --- the hotkeys ----------------------------------------------------------
def hotkeys():
    stop = guard.Stop()
    lines = []
    control = guard.RunControl(stop, log=lines.append)

    control._on_hotkey_pause()
    assert stop.is_paused(), "F7 did not pause"
    control._on_hotkey_pause()
    assert not stop.is_paused(), "F7 did not resume"

    control._on_hotkey_abort()
    assert stop.is_set(), "F8 did not abort"
    assert "f8" in stop.reason
    assert any("abort" in line for line in lines), "the abort was not logged"
    print("F7 pauses and resumes, F8 aborts")

    # Without the keyboard package the hotkeys say so and change nothing
    # else. A bot that only cares about its own console keys still runs.
    real = guard.keyboard
    guard.keyboard = None
    try:
        lines[:] = []
        guard.RunControl(guard.Stop(), log=lines.append).start()
        assert any("keyboard" in line for line in lines), \
            "a missing keyboard package has to be said out loud"
        print("no keyboard package: it says so instead of crashing")
    finally:
        guard.keyboard = real


# --- the mouse-movement pause, and that it stays gone ---------------------
def no_mouse_watcher():
    """The auto-pause on mouse movement was removed. This is the guard
    against it coming back by accident.

    It was written for the mode where the bot drives the real cursor, but it
    watched in every mode -- and under ADB, the default, the bot never
    touches the mouse, so every movement was a person using their own
    machine. A run paused between two dungeon attempts and asked for three
    seconds of stillness before going on.
    """
    for gone in ("_watch_mouse", "_release_own_pause", "_mouse_owns_pause"):
        assert not hasattr(guard.RunControl, gone), \
            "%s is back, and with it the pause nobody can switch off" % gone
    assert not hasattr(userdata, "mouse_pause"), \
        "the setting is back, so something is reading the mouse again"
    assert not hasattr(userdata, "set_mouse_pause")

    # Nothing may ask a capture object when it last moved the cursor either,
    # because nothing stamps that any more.
    import capture
    assert not hasattr(capture.WindowCapture, "_note_move")
    assert "last_bot_move" not in guard.__doc__

    # Whatever a caller passes, no watcher thread is started.
    before = threading.active_count()
    control = guard.RunControl(guard.Stop(), log=lambda _t: None)
    real, guard.keyboard = guard.keyboard, None
    try:
        control.start()
    finally:
        guard.keyboard = real
    time.sleep(0.05)
    assert threading.active_count() == before, \
        "start() spawned a thread, and the only thread it ever had watched " \
        "the mouse"
    print("no mouse watcher, no thread, no setting")

    # cursor_pos stays: the passive helper asks where the mouse is before it
    # taps, which holds up one tap and not a whole run.
    assert callable(guard.cursor_pos)
    pos = guard.cursor_pos()
    assert pos is None or (isinstance(pos, tuple) and len(pos) == 2)
    print("cursor_pos is still there for the passive helper")


def main():
    stop_flag()
    hotkeys()
    no_mouse_watcher()
    print("all run-control cases as expected")


if __name__ == "__main__":
    main()
