"""
The shared Tk pieces, in the parts that are not Tk.

Only `stamp_lines` so far: it decides what every line of both logs looks
like, and it is plain text in and plain text out, so it can be checked
without a window, a bot or an emulator. Importing widgets pulls in tkinter
but never opens a display -- no Tk() is called here.

  py test_widgets.py
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import userdata
import widgets

CLOCK = re.compile(r"^\d\d:\d\d:\d\d {2}$")

# A fixed moment, so nothing here depends on when the suite is run. Which
# hour it comes out as depends on the machine's time zone, which is why
# every case below asks about the shape and about differences, never about
# one particular string.
NOON = 1756123456


# =====================================================
# One line
# =====================================================
pairs = widgets.stamp_lines("found the dungeon list", when=NOON)
assert len(pairs) == 1, pairs
stamp, line = pairs[0]
assert CLOCK.match(stamp), repr(stamp)
assert line == "found the dungeon list", repr(line)
print("a single line comes back with one clock in front of it")

# The bots indent their sub-steps, and that indent is how a reader tells a
# step from the thing it did. It has to survive the stamp.
(stamp, line), = widgets.stamp_lines("    [dry run] click on r2c3", when=NOON)
assert line == "    [dry run] click on r2c3", repr(line)
print("a line's own indent is left alone")


# =====================================================
# A block of several lines
# =====================================================
summary = "\n".join(["", "Dungeon 1     2 attempts   2 done",
                     "Dungeon 2     2 attempts   1 done, 1 failed",
                     "Ads watched   3"])
pairs = widgets.stamp_lines(summary, when=NOON)
assert len(pairs) == 4, pairs

# The empty first line is what separates this block from the run above it.
# A line holding nothing but a clock would not separate anything.
assert pairs[0] == ("", ""), pairs[0]
print("an empty line keeps its emptiness and gets no clock")

assert all(CLOCK.match(s) for s, _ in pairs[1:]), pairs
assert len({s for s, _ in pairs[1:]}) == 1, pairs
print("every line of a block carries a clock, all of them the same one, so "
      "searching the log for a time finds the inner lines too")

assert [l for _s, l in pairs] == summary.split("\n"), pairs
print("the text itself comes back unchanged")


# =====================================================
# The trailing newline
# =====================================================
# Both logs used to write `text + "\n"`, so a text that already ended in a
# newline left a blank line behind it. Bots rely on that to space their
# output, and the stamping must not quietly close the gap.
pairs = widgets.stamp_lines("done\n", when=NOON)
assert len(pairs) == 2 and pairs[1] == ("", ""), pairs
print("a text ending in a newline still leaves its blank line behind")


# =====================================================
# The clock follows `when`
# =====================================================
assert (widgets.stamp_lines("x", when=NOON)[0][0]
        == widgets.stamp_lines("x", when=NOON)[0][0])
assert (widgets.stamp_lines("x", when=NOON)[0][0]
        != widgets.stamp_lines("x", when=NOON + 3600)[0][0])
print("the same moment gives the same clock, an hour later a different one")

assert CLOCK.match(widgets.stamp_lines("x")[0][0])
print("with no moment given it stamps now")

# =====================================================
# The global ADB switch is a file, so it crosses processes
# =====================================================
# Same shape as test_guard.py's check of the mouse pause: a fresh folder, no
# real userdata touched, cleaned up whatever happens.
folder = tempfile.mkdtemp(prefix="helpermon_test_")
old_env, old_cache = os.environ.get("DGUP_DATA"), userdata._CACHED
old_mode_env = os.environ.pop("DGUP_ADB_MODE", None)
os.environ["DGUP_DATA"] = folder
userdata._CACHED = None
try:
    assert userdata.adb_mode() is True, "a fresh folder must default to ADB on"
    assert userdata.set_adb_mode(False) is False
    assert os.path.exists(os.path.join(folder, userdata.ADB_OFF_FLAG)), \
        "off has to leave something on disk, or another window cannot see it"
    assert userdata.adb_mode() is False
    assert userdata.set_adb_mode(True) is True
    assert not os.path.exists(os.path.join(folder, userdata.ADB_OFF_FLAG))
    print("the ADB switch is a file, so a second window sees it")

    os.environ["DGUP_ADB_MODE"] = "0"
    assert userdata.adb_mode() is False
    os.environ["DGUP_ADB_MODE"] = "1"
    assert userdata.adb_mode() is True
    os.environ.pop("DGUP_ADB_MODE")
    print("DGUP_ADB_MODE overrides the file in both directions")
finally:
    userdata._CACHED = old_cache
    if old_env is None:
        os.environ.pop("DGUP_DATA", None)
    else:
        os.environ["DGUP_DATA"] = old_env
    if old_mode_env is None:
        os.environ.pop("DGUP_ADB_MODE", None)
    else:
        os.environ["DGUP_ADB_MODE"] = old_mode_env
    shutil.rmtree(folder, ignore_errors=True)


print("all widget cases as expected")
