"""
Storage for learned data.

Everything the setup wizard learns lands here and never in the program folder.
That way a published copy contains no third-party image material, and a program
update deletes nothing that was learned.

Order of preference

  1. the DGUP_DATA environment variable, if set
  2. a `userdata` folder next to the program, if writable. The normal case,
     because it is easy to find, back up and delete there
  3. AppData, as a fallback. That applies for example to a future executable
     placed under Program Files, where writing is not allowed

Layout

  userdata/templates/<name>.png     objects, pyramid, banner parts
  userdata/digits/<digit>/NN.png    digit images, several per digit
  userdata/unbekannt/*.png          open cases collected during runs
"""

import os

APP_NAME = "digibot"
HERE = os.path.dirname(os.path.abspath(__file__))

_CACHED = None


def _writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".schreibtest")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def data_dir():
    """Folder for learned data, created when it is first needed."""
    global _CACHED
    if _CACHED:
        return _CACHED

    env = os.environ.get("DGUP_DATA")
    if env and _writable(env):
        _CACHED = env
        return _CACHED

    local = os.path.join(HERE, "userdata")
    if _writable(local):
        _CACHED = local
        return _CACHED

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback = os.path.join(base, APP_NAME)
    if _writable(fallback):
        _CACHED = fallback
        return _CACHED

    raise RuntimeError("no writable folder found for learned data")


def sub(*parts, create=True):
    path = os.path.join(data_dir(), *parts)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def templates_dir(create=True):
    return sub("templates", create=create)


def digits_dir(create=True):
    return sub("digits", create=create)


def unknown_dir(create=True):
    return sub("unknown", create=create)


def template_path(name, create=True):
    return os.path.join(templates_dir(create=create), name + ".png")


def digit_dir(digit, create=True):
    return sub("digits", str(digit), create=create)


def next_index(folder, suffix=".png"):
    """Next free number in a folder, so learning samples do not overwrite
    each other."""
    try:
        files = [f for f in os.listdir(folder) if f.endswith(suffix)]
    except FileNotFoundError:
        return 0
    return len(files)


ONLY_FLAG = "nur_gelernt.flag"


def only_learned():
    """Should the images that ship with the program be ignored?

    A file in the data folder rather than an environment variable, so that
    the switch applies to the wizard and the bot at the same time. They run
    as separate processes.
    """
    if os.environ.get("DGUP_ONLY_LEARNED") == "1":
        return True
    try:
        return os.path.exists(os.path.join(data_dir(), ONLY_FLAG))
    except Exception:
        return False


def set_only_learned(value):
    path = os.path.join(data_dir(), ONLY_FLAG)
    if value:
        with open(path, "w") as fh:
            fh.write("The images shipped with the program are ignored.\n")
    elif os.path.exists(path):
        os.remove(path)
    return only_learned()


# The mouse-movement pause is gone, and with it `mouse_pause` and
# DGUP_MOUSE_PAUSE. It lost its checkbox first, because a switch offering to
# turn off the one thing that got a hand out from under a running bot was an
# invitation rather than a setting -- and then the pause itself, because ADB
# became the default and there the bot never touches the mouse: every
# movement was a person using their own machine, and a run spent it pausing.
# See guard.py. A flag file left behind by the old checkbox is not read by
# anything.


# The global "Use ADB" switch: frames and clicks both, on or off together.
#
# A flag file, like ONLY_FLAG above, and for the same reason: the
# launcher, the setup wizard, the minigame window and a bot started from a
# console are separate processes, and a switch reaching only one of them
# looks broken rather than off.
#
# The file means "off", so its absence -- a fresh install, a deleted data
# folder -- gives ADB, the safer default: a window that has to stay visible
# and unobscured breaks in more ways than a few hundred milliseconds per
# frame costs.
ADB_OFF_FLAG = "adb_off.flag"


def adb_mode():
    """True means frames and clicks both go through ADB."""
    if os.environ.get("DGUP_ADB_MODE") in ("0", "1"):
        return os.environ["DGUP_ADB_MODE"] == "1"
    try:
        return not os.path.exists(os.path.join(data_dir(), ADB_OFF_FLAG))
    except Exception:
        return True


def set_adb_mode(value):
    path = os.path.join(data_dir(), ADB_OFF_FLAG)
    if value and os.path.exists(path):
        os.remove(path)
    elif not value:
        with open(path, "w") as fh:
            fh.write("Helpermon reads the window and drives the real mouse "
                     "instead of ADB.\n")
    return adb_mode()


# Which of ADB's two screenshot methods, raw or png, benchmark() found
# faster on this machine. Cached so that only the first process to ever
# grab an ADB frame here pays for the measurement -- benchmarked at roughly
# a second, and repeating that on every process start, including a short
# CLI call, would tax exactly the run it is meant to speed up.
SCREENCAP_METHOD_FILE = "screencap_method.flag"


def cached_screencap_method():
    """"raw" or "png" if benchmark() has measured this machine before,
    otherwise None."""
    try:
        with open(os.path.join(data_dir(), SCREENCAP_METHOD_FILE)) as fh:
            value = fh.read().strip()
    except Exception:
        return None
    return value if value in ("raw", "png") else None


def set_cached_screencap_method(value):
    try:
        with open(os.path.join(data_dir(), SCREENCAP_METHOD_FILE), "w") as fh:
            fh.write(value)
    except Exception:
        pass


def describe():
    """Short line for showing where the data lives."""
    where = data_dir()
    kind = ("DGUP_DATA environment variable" if os.environ.get("DGUP_DATA")
            else "project folder" if where.startswith(HERE) else "AppData")
    return "%s (%s)" % (where, kind)
