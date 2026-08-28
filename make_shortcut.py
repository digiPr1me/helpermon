r"""
Create a desktop shortcut so the launcher opens with a double click.

  py make_shortcut.py            shortcut on the desktop plus a starter
  py make_shortcut.py --here     only the starter in the project folder

Normally run by install.bat, not by hand.

It uses pythonw.exe rather than python.exe. The difference is that pythonw opens
no black console window. Output goes to the window log anyway.

The interpreter it points at is whichever one is running this script, so when
install.bat calls it through .venv\Scripts\python.exe the shortcut lands on
the venv. That is the whole mechanism by which a virtual environment needs no
activating: the full path is in the shortcut.

The starter beside it works the other way round. A path written into it is a
path that a moved folder invalidates, so it looks for .venv relative to itself
and falls back to a Python on PATH. The one thing neither can repair is a venv
that has been moved -- it records the folder it was built in -- so the starter
recognises that case and offers install.bat, which rebuilds it. The shortcut
cannot do the same: it names an .exe, and pointing it at the starter instead
would flash up a console window on every launch, which is what pythonw is for.

The shortcut is created via PowerShell, which ships with every Windows, so no
extra package such as pywin32 is required.
"""

import argparse
import os
import sys

import noconsole

HERE = os.path.dirname(os.path.abspath(__file__))
BAT_NAME = "Start Helpermon.bat"
# The starter used to be called "Bot starten.bat". Cleaned up when found, so a
# folder that has been through both versions does not end up with two of them.
OLD_BAT_NAMES = ["Start bot.bat", "Bot starten.bat"]


def pythonw():
    """Path to pythonw.exe next to the running interpreter."""
    exe = sys.executable
    guess = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return guess if os.path.exists(guess) else exe


def outside_project(path):
    """True for an interpreter a move of this folder would not take away.

    The one install.bat builds sits in `.venv` inside the folder, so its
    absolute path is worth nothing the moment the folder is renamed or
    dragged elsewhere -- the starter finds that one relative to itself
    instead. A Python installed system-wide is somewhere else entirely and
    is still there afterwards, so that one is worth writing down.
    """
    try:
        return os.path.commonpath([os.path.abspath(path), HERE]) != HERE
    except ValueError:
        # Different drives, which commonpath refuses to compare. Then it is
        # certainly not inside this folder.
        return True


def bat_text(interpreter, built_at=None):
    """What the starter contains, for one interpreter.

    Kept apart from writing it so that it can be read without a Windows
    machine and without overwriting the starter of whoever runs the suite;
    test_starter.py checks what comes back from here.

    The interpreter is searched for while the starter runs rather than
    written into it, because the path that was right at installation time
    is the first thing a moved folder invalidates.

    A move is then recognised by comparing the folder the starter is
    standing in against the one it was written in, which is the one thing
    an installation can be sure of afterwards. It was first done by
    starting the venv's python.exe and reading the exit code -- a moved
    venv keeps every file it had and none of them run, so that does answer
    the question. What it also does is run a program in order to find out
    something about a path: an executable that is damaged rather than
    merely misplaced makes Windows put up "This app can't run on your PC",
    modal, in front of a starter that is then waiting on the exit code of
    a process waiting on a dialog. Measured, not inferred, and nothing is
    launched to ask.
    """
    dp = "%~dp0"
    venv = dp + ".venv" + os.sep + "Scripts" + os.sep
    built_at = built_at if built_at is not None else HERE
    if not built_at.endswith(os.sep):
        # %~dp0 always ends in a backslash, so the recorded one has to.
        built_at += os.sep

    lines = [
        "@echo off",
        "rem ------------------------------------------------------------",
        "rem Starts Helpermon. Written by make_shortcut.py at the end of",
        "rem an installation -- not a file from the repository and not one",
        "rem that ships, because it is about this machine.",
        "rem",
        "rem It looks for its interpreter instead of being told where one",
        "rem is, so that moving this folder does not break the starter",
        "rem along with it.",
        "rem ------------------------------------------------------------",
        'cd /d "' + dp + '"',
        "",
        "rem Where this was installed. Not a path to start anything by --",
        "rem the launches below are all relative or on PATH -- but the",
        "rem evidence for whether the folder is still where it was. A venv",
        "rem records the folder it was built in and stops working when",
        "rem that changes, and this is how that is noticed without having",
        "rem to run anything to find out.",
        'set "BUILT_AT=' + built_at + '"',
        'if /i not "' + dp + '"=="%BUILT_AT%" goto moved',
        "",
        'if not exist "' + venv + 'pythonw.exe" goto no_venv',
        'start "" "' + venv + 'pythonw.exe" app.py',
        "exit /b 0",
        "",
        ":no_venv",
    ]

    if interpreter and outside_project(interpreter):
        lines += [
            "rem The interpreter this was installed with. Written down",
            "rem because it lives outside this folder, which is what makes",
            "rem it still valid after a move.",
            'if not exist "' + interpreter + '" goto on_path',
            'start "" "' + interpreter + '" app.py',
            "exit /b 0",
            "",
        ]

    lines += [
        ":on_path",
        "rem Nothing installed here, but perhaps a Python on the machine.",
        "rem pyw rather than py: py opens a console window, and this",
        "rem starter exists so that nothing does.",
        "where pyw >nul 2>&1",
        "if errorlevel 1 goto no_python",
        'start "" pyw -3 app.py',
        "exit /b 0",
        "",
        ":no_python",
        "echo.",
        "echo   No Python was found, and there is no installation in this",
        "echo   folder. Double-click install.bat here once - it finds",
        "echo   Python, offers to fetch it if there is none, and sets up",
        "echo   the rest.",
        "echo.",
        "pause",
        "exit /b 1",
        "",
        ":moved",
        "echo.",
        "echo   This folder has been moved or renamed since it was",
        "echo   installed.",
        "echo.",
        "echo   It was installed in",
        "echo     %BUILT_AT%",
        "echo   and is now in",
        "echo     " + dp,
        "echo.",
        "echo   The installation in .venv records the folder it was built",
        "echo   in, so it stops working when that changes. What you taught",
        "echo   the bots is not affected - it is in userdata, untouched.",
        "echo.",
        "echo   install.bat repairs this: it builds .venv again, writes",
        "echo   this starter again and puts a fresh shortcut on the",
        "echo   desktop. The old shortcut still points at the old folder",
        "echo   and can be deleted.",
        "echo.",
        'set "ANSWER="',
        "set /p ANSWER=Run install.bat now? [Y/n] ",
        'if /i "%ANSWER%"=="n" exit /b 1',
        'call "' + dp + 'install.bat"',
        "exit /b 0",
        "",
    ]
    return "\r\n".join(lines)


def write_bat():
    """Starter in the project folder. It always works, even when creating the
    shortcut fails."""
    for old in OLD_BAT_NAMES:
        path = os.path.join(HERE, old)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
    path = os.path.join(HERE, BAT_NAME)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(bat_text(pythonw()))
    return path


def known_desktop():
    """The desktop as Windows itself reports it.

    SHGetKnownFolderPath answers the question rather than guessing at it, and
    it is right in both layouts: with OneDrive's folder backup switched on it
    returns the OneDrive path, without it the local one. It also removes the
    need to know what the folder is called in another language -- on a German
    Windows the folder on disk is still `Desktop`, only its displayed name is
    translated, and this returns the real path either way.
    """
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    # FOLDERID_Desktop, {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
    folder = GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                  (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                       0x9A, 0x87, 0xC6, 0x41))
    out = ctypes.c_wchar_p()
    try:
        hr = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder), 0, None, ctypes.byref(out))
        if hr != 0:
            return None
        try:
            return out.value
        finally:
            ctypes.windll.ole32.CoTaskMemFree(out)
    except Exception:
        return None


def desktop():
    """Where the shortcut goes.

    Ask first, guess second. The guess used to be the whole of it, and it
    tried OneDrive before the user profile -- right on a machine where
    OneDrive has taken the desktop over, wrong on one where an empty
    `OneDrive\\Desktop` is merely left lying about. On such a machine the
    shortcut landed in a folder the player never looks at, while install.bat
    reported it created.
    """
    path = known_desktop()
    if path and os.path.isdir(path):
        return path

    # Only if the system did not answer. Then there is nothing left but to
    # guess, and the old order is as good a guess as any.
    for var in ("OneDrive", "USERPROFILE"):
        base = os.environ.get(var)
        if not base:
            continue
        for name in ("Desktop", "Schreibtisch"):
            candidate = os.path.join(base, name)
            if os.path.isdir(candidate):
                return candidate
    return None


def make_shortcut(target, args, workdir, link_path):
    """Create the shortcut through PowerShell's COM interface."""
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.Arguments = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.Description = 'Helpermon, the launcher';"
        "$s.Save()"
    ) % (link_path, target, args, workdir)
    res = noconsole.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "PowerShell error").strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--here", action="store_true",
                    help="only create the starter in the project folder")
    ap.add_argument("--name", default="Helpermon")
    args = ap.parse_args()

    bat = write_bat()
    print("Starter created: %s" % bat)
    print("It can be double-clicked directly.")

    if args.here:
        return
    if os.name != "nt":
        print("Shortcuts are Windows only, the starter above is enough here.")
        return

    target_dir = desktop()
    if not target_dir:
        print("Desktop not found. Drag the starter above there yourself.")
        return

    link = os.path.join(target_dir, args.name + ".lnk")
    try:
        make_shortcut(pythonw(), "app.py", HERE, link)
    except Exception as err:
        print("Shortcut failed (%s)." % err)
        print("Alternative: right-click the starter, Send to, Desktop.")
        return
    print("Shortcut created: %s" % link)
    print("It starts %s with app.py in the folder %s" % (pythonw(), HERE))
    print("\nNote: you can give it your own icon via right-click, "
          "Properties, Change Icon.")


if __name__ == "__main__":
    main()
