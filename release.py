"""
Build the copy for publishing.

The `templates` and `digits` folders contain crops taken from the game. They
ship, because the board bots cannot read the screen without them and a fresh
install has no userdata folder to fall back on: held back, Digital World
Search was unusable until somebody had sat through the whole setup wizard.
The wizard is still there and still wins -- a learned image in userdata beats
a shipped one -- but it is no longer the price of a first run.

Building into an existing folder empties it first, but never touches the
things that live there in their own right: a `.git` folder, a `.venv`, a
`userdata`. That matters because the target is meant to be the published
checkout, and an earlier version deleted the whole folder, `.git` included,
which left a copy that had forgotten it was a repository.

  py release.py                 writes ../helpermon_release
  py release.py --target path
  py release.py --check         only show what would be excluded
"""
import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Do not ship: third-party imagery or local state.
# Every folder whose name starts with one of these prefixes is dropped. This
# covers the debug dumps, which keep appearing under new names, without anyone
# having to remember to extend a list.
EXCLUDED_FOLDER_PREFIXES = ["debug"]
# Folders that do not follow that naming convention and have to be named.
# .venv is the environment install.bat builds. It must never be copied: it
# is hundreds of megabytes and every path inside it is absolute, so it
# would not work anywhere but on this machine anyway.
# .claude is the tooling's own folder, and worktrees live under it: whole
# copies of this repository at some earlier state, .git pointer and all.
# Nothing in it is game content, so the audit at the bottom has no opinion
# about it -- and a build shipped 127 files of stale duplicate program out
# of one, in a hidden folder, where nobody would have looked for them.
# docs is the screenshot folder INSTALL.md used to show. It stays here now:
# the pictures are of this machine's own windows, they are nobody else's
# business, and .gitignore holds them back from the repository as well.
EXCLUDED_FOLDERS = ["userdata", "__pycache__", ".git", ".venv", ".claude",
                    "docs"]
# The starter make_shortcut.py writes is local state: it hardcodes the
# absolute path of the pythonw.exe on the machine that made it. install.bat,
# which creates it, does ship. Hence names rather than a *.bat rule.
# codes_issued.csv is the plaintext of every supporter code ever minted, and
# make_codes.py is what mints them. Neither is dangerous on its own -- a code
# is only worth anything once its hash is in codes.txt, which ships either way
# -- but the ledger is the whole pool in the clear, and a build that shipped it
# would hand out five hundred unlocks in one file. codes.txt itself ships: it
# is what the program checks against, and the hashes give nothing away.
EXCLUDED_FILES = ["calib.json", "Start Helpermon.bat", "Start bot.bat",
                  "Bot starten.bat", "codes_issued.csv", "make_codes.py"]
EXCLUDED_SUFFIXES = [".pyc", ".png", ".jpg", ".log"]

# Documents ship by whitelist. Everything else ending in .md is internal --
# working notes, plans, instructions for tooling -- and stays here. A list of
# what to leave out is one somebody has to remember to extend, and CLAUDE.md
# and RELEASE_PLAN.md shipped for exactly that reason. Only .md is covered, so
# requirements.txt and LICENSE.txt are unaffected.
PUBLIC_DOCS = ["README.md", "QUICKSTART.md", "INSTALL.md", "CONTRIBUTING.md"]

# The two folders the board bots read the screen with, and now the only
# place in the tree an image may ship from at all. Their contents are crops
# from the game and they ship anyway, see the note at the top. Everywhere
# else the audit below refuses an image outright.
GAME_IMAGE_FOLDERS = ["templates", "digits"]

# Present in the target and not ours to delete when rebuilding into it. The
# git repository is the one that matters; the other two are what a player
# would have there if they ran the copy.
KEEP_IN_TARGET = [".git", ".venv", "userdata"]

# The shipping promise: not one file derived from the game screen. Nothing may
# ever be included that matches this, no matter what the rules above say.
FORBIDDEN_SUFFIXES = [".png", ".jpg", ".jpeg", ".bmp"]
# The second promise, added when the supporter codes were: not one file
# holding a code in the clear. Named here as well as in EXCLUDED_FILES
# because that list is a rule and this one is a refusal -- a renamed ledger
# or a copy left behind by an editor is caught by the shape of the name.
FORBIDDEN_NAMES = ["calib.json", "codes_issued.csv"]
FORBIDDEN_FRAGMENTS = ["codes_issued"]


def is_excluded_folder(name):
    return (name in EXCLUDED_FOLDERS
            or any(name.startswith(p) for p in EXCLUDED_FOLDER_PREFIXES))


def is_internal_doc(name):
    return name.lower().endswith(".md") and name not in PUBLIC_DOCS


def is_shipped_image(rel):
    """True for an image that is allowed out: the templates and digits the
    bots need, and nothing else."""
    rel = os.path.normpath(rel)
    return any(rel.startswith(f + os.sep) for f in GAME_IMAGE_FOLDERS)


def clear_target(target):
    """Empty the target, keeping what belongs to it rather than to us."""
    kept = []
    for name in sorted(os.listdir(target)):
        if name in KEEP_IN_TARGET:
            kept.append(name)
            continue
        path = os.path.join(target, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    return kept


def count_files(path):
    return sum(len(files) for _, _, files in os.walk(path))


def collect():
    included, excluded = [], []
    for root, folders, files in os.walk(HERE):
        rel_root = os.path.relpath(root, HERE)
        dropped = [o for o in folders if is_excluded_folder(o)]
        folders[:] = [o for o in folders if o not in dropped]
        for name in sorted(dropped):
            path = os.path.join(root, name)
            rel = os.path.normpath(os.path.join(rel_root, name))
            excluded.append("%s%s  (%d files)" % (rel, os.sep, count_files(path)))
        for name in files:
            rel = os.path.normpath(os.path.join(rel_root, name))
            by_suffix = (any(name.endswith(e) for e in EXCLUDED_SUFFIXES)
                         and not is_shipped_image(rel))
            if (name in EXCLUDED_FILES
                    or is_internal_doc(name)
                    or by_suffix):
                excluded.append(rel)
            else:
                included.append(rel)
    return sorted(included), sorted(excluded)


def audit(included):
    """Return every included file that breaks the no-game-content promise."""
    offenders = []
    for rel in included:
        if is_shipped_image(rel):
            continue
        name = os.path.basename(rel).lower()
        if (name in FORBIDDEN_NAMES
                or any(f in name for f in FORBIDDEN_FRAGMENTS)
                or any(name.endswith(e) for e in FORBIDDEN_SUFFIXES)):
            offenders.append(rel)
    return offenders


def inside_source(target):
    """Would this target write the build into the working copy itself?

    A relative --target is taken from wherever the command was run, which
    is normally this folder -- and a shell that ate the backslashes out of
    an absolute Windows path leaves exactly that. "$USERPROFILE/Documents/
    Helpermon-test" came through as "Aleks/Documents/Helpermon-test" and
    the whole build landed in a new folder inside the repository, where
    nothing looks for it and where the *next* build would have shipped all
    79 files of it: a second, older Helpermon inside the public copy, 161
    files instead of 82. That has happened once before with the tooling's
    worktrees, which is one time more than a check this cheap is worth.
    """
    here = os.path.realpath(HERE)
    dest = os.path.realpath(os.path.abspath(target))
    return dest == here or dest.startswith(here + os.sep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=os.path.join(os.path.dirname(HERE),
                                                   "helpermon_release"))
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if inside_source(args.target):
        print("STOP: the target is inside the working copy, nothing written")
        print("   asked for : %s" % args.target)
        print("   which is  : %s" % os.path.realpath(os.path.abspath(
            args.target)))
        print("   inside    : %s" % HERE)
        print("A build there would be shipped by the next one. Give an "
              "absolute path outside this folder,")
        print("with forward slashes: py release.py --target "
              "C:/Users/you/Documents/Helpermon-test")
        return 1

    included, excluded = collect()
    print("Will be shipped, %d files" % len(included))
    for name in included:
        print("   %s" % name)
    print("\nWill be excluded")
    for name in excluded:
        print("   %s" % name)
    internal = [n for n in excluded if is_internal_doc(os.path.basename(n))]
    if internal:
        print("\nHeld back as internal documents: %s" % ", ".join(internal))
        print("Shipped documents are %s." % ", ".join(PUBLIC_DOCS))

    offenders = audit(included)
    if offenders:
        print("\nSTOP: these files would ship game content, nothing was written")
        for name in offenders:
            print("   %s" % name)
        print("Fix the exclusion rules in release.py before building.")
        return 1

    if args.check:
        print("\nChecked only, nothing written.")
        return 0

    if os.path.exists(args.target):
        kept = clear_target(args.target)
        if kept:
            print("\nLeft alone in the target: %s" % ", ".join(kept))
    for rel in included:
        source = os.path.join(HERE, rel)
        target = os.path.join(args.target, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)

    print("\nBuild written to %s" % args.target)
    images = len([n for n in included
                  if any(os.path.normpath(n).startswith(f + os.sep)
                         for f in GAME_IMAGE_FOLDERS)])
    print("%d template and digit images went with it, so the board bots read "
          "the screen there without the setup wizard." % images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
