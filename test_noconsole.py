r"""
Every child process goes through noconsole, and noconsole hides the window.

The desktop shortcut runs Helpermon under pythonw.exe, which has no console.
Windows hands every console program started from there a console window of
its own, and adb.exe is started several times a second -- once per frame,
once per tap -- so the screen flickers for as long as a bot runs. It is not
one machine's setup: it happens to everybody who starts from the shortcut.

The flag that fixes it only helps where it is passed, and a call site that
forgets it is invisible from the code -- it shows up as a flicker on
somebody else's screen, half an hour into a run. So the source is read
here instead.

  py test_noconsole.py
"""

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# noconsole.py is where the real calls live. The suites are started from a
# terminal by hand and have a console anyway.
ALLOWED = {"noconsole.py"}

DIRECT = re.compile(r"\bsubprocess\.(run|Popen|call|check_call|check_output)\(")

offenders = []
for path in sorted(glob.glob(os.path.join(HERE, "*.py"))):
    name = os.path.basename(path)
    if name in ALLOWED or name.startswith("test_"):
        continue
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            if DIRECT.search(line):
                offenders.append("%s:%d %s" % (name, number, line.strip()))

if offenders:
    print("These start a process without going through noconsole:")
    for item in offenders:
        print("  " + item)
    raise AssertionError("%d direct subprocess call(s)" % len(offenders))
print("no module calls subprocess directly, %d checked"
      % len(glob.glob(os.path.join(HERE, "*.py"))))

# ---------------------------------------------------------------------------
# And the flag itself. Passed on Windows, not passed anywhere else, where
# creationflags is not a valid argument at all.
import noconsole

seen = {}


def fake(cmd, **kw):
    seen.clear()
    seen.update(kw)
    return "ran"


real = noconsole.subprocess.run
real_popen = noconsole.subprocess.Popen
noconsole.subprocess.run = fake
noconsole.subprocess.Popen = fake
try:
    noconsole.run(["adb", "devices"], capture_output=True)
    windows = seen.get("creationflags", 0)
    noconsole.popen(["adb", "devices"])
    popen_flags = seen.get("creationflags", 0)
finally:
    noconsole.subprocess.run = real
    noconsole.subprocess.Popen = real_popen

if os.name == "nt":
    assert windows & noconsole.CREATE_NO_WINDOW, windows
    assert popen_flags & noconsole.CREATE_NO_WINDOW, popen_flags
    print("run and popen both pass CREATE_NO_WINDOW (0x%08X)"
          % noconsole.CREATE_NO_WINDOW)
else:
    assert windows == 0 and popen_flags == 0, (windows, popen_flags)
    print("not Windows: no creationflags passed, which is the only thing "
          "that works there")

# A caller that has flags of its own keeps them.
noconsole.subprocess.run = fake
try:
    noconsole.run(["adb", "devices"], creationflags=0x00000200)
finally:
    noconsole.subprocess.run = real
if os.name == "nt":
    assert seen["creationflags"] & 0x00000200, seen
    assert seen["creationflags"] & noconsole.CREATE_NO_WINDOW, seen
    print("a caller's own flags survive")

print("\nOK")
