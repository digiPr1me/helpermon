"""The starter make_shortcut.py writes, and whether a move survives it.

Nothing here runs cmd and nothing here writes into the project folder: the
text is built by `bat_text`, which was split off from `write_bat` for exactly
that. So this suite runs on any machine, the same as the rest of them.

What it is guarding is one mistake with two halves. A path written into the
starter is a path a moved folder invalidates -- that is why the venv is found
relative to the starter and only an interpreter outside the folder is written
down at all. And a state that is decided by running a program can be answered
by a modal dialog instead of an exit code: an .exe that is damaged rather than
misplaced makes Windows put up "This app can't run on your PC" in front of a
starter that is then waiting on it. The move is compared, not attempted.
"""

import os

import make_shortcut as ms

HERE = ms.HERE
IN_VENV = os.path.join(HERE, ".venv", "Scripts", "pythonw.exe")
OUTSIDE = os.path.join("C:" + os.sep, "Python313", "pythonw.exe")


def lines(text):
    return text.split("\r\n")


def launches(text):
    return [l for l in lines(text) if l.startswith("start ")]


# --- the interpreter is not written in when it would move with the folder --
text = ms.bat_text(IN_VENV)
assert IN_VENV not in text, "the venv interpreter was written in by its path"
assert "%~dp0.venv" in text, "the venv is not found relative to the starter"
print("venv interpreter -> found relative, absolute path not written in")

text_out = ms.bat_text(OUTSIDE)
assert OUTSIDE in text_out, "an interpreter outside the folder is worth keeping"
print("outside interpreter -> written down as a fallback")

assert ms.outside_project(OUTSIDE) is True
assert ms.outside_project(IN_VENV) is False
assert ms.outside_project(os.path.join(HERE, "python.exe")) is False
print("outside_project tells the two apart")


# --- every launch is relative, on PATH, or the recorded outside one --------
for interpreter in (IN_VENV, OUTSIDE, None):
    for line in launches(ms.bat_text(interpreter)):
        ok = ("%~dp0" in line or " pyw " in line
              or (interpreter and interpreter in line))
        assert ok, "a launch names a path that a move would invalidate: " + line
print("every launch is relative, on PATH, or the recorded outside one")


# --- the move is compared, never attempted --------------------------------
text = ms.bat_text(OUTSIDE, built_at=r"C:\Somewhere\Else")
assert 'set "BUILT_AT=C:\\Somewhere\\Else\\"' in text, text
assert 'if /i not "%~dp0"=="%BUILT_AT%" goto moved' in text
print("the folder it was built in is compared against %~dp0")

# The old way of asking. It is the point of the suite that it does not come
# back: running a program to find out about a path can raise a dialog, and a
# dialog is not an exit code.
for line in lines(text):
    stripped = line.strip()
    if stripped.startswith("rem"):
        continue
    assert "-c " not in stripped, "the starter runs something to decide: " + line
print("nothing is executed to decide whether the folder moved")

assert ":moved" in text and "install.bat" in text
assert "userdata" in text, "the move message has to say what is not lost"
print("the move leads to install.bat, and says userdata is untouched")


# --- a trailing separator, because %~dp0 always has one --------------------
for built in (r"C:\Games\Helpermon", r"C:\Games\Helpermon" + os.sep):
    text = ms.bat_text(OUTSIDE, built_at=built)
    recorded = [l for l in lines(text) if l.startswith('set "BUILT_AT=')][0]
    assert recorded.endswith(os.sep + '"'), recorded
print("the recorded folder always ends in a separator, like %~dp0 does")


# --- the shape cmd needs --------------------------------------------------
text = ms.bat_text(OUTSIDE)
assert text.startswith("@echo off\r\n"), "not a batch file"
assert lines(text)[0].endswith("off"), lines(text)[0]
labels = set(l for l in lines(text) if l.startswith(":"))
for target in ("no_venv", "on_path", "no_python", "moved"):
    assert ":" + target in labels, "missing label :" + target
    assert any(l.endswith("goto " + target) or l == "goto " + target
               for l in lines(text)), "nothing jumps to :" + target
print("every label exists and is jumped to: %s"
      % ", ".join(sorted(labels)))

print("\ntest_starter OK")
