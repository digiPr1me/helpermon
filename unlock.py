"""
The supporter code: one code, one unlock, no server.

A supporter donates on Ko-fi, receives a code, types it in once, and the
features marked as supporter features start working. Nothing is sent
anywhere, the check runs offline, and the answer survives a program update
because it is kept with the learned data and not in the program folder.

What this protects, and what it does not

  This is an honesty barrier, not a lock. Helpermon is MIT-licensed Python
  that ships as source: anybody may delete the check, and doing so is not
  a crack, it is the licence. That is a deliberate trade -- the alternative
  is a server the bot has to phone, and a bot that reads the screen locally
  has nothing a server could usefully withhold.

  What it *does* protect is the code itself. The hashes below ship in the
  public repository, so a shipped list of plain sha256 sums would be a
  brute-force target: at ten billion guesses a second the whole alphabet
  space falls in about a day once a few hundred codes are in the list,
  because the attacker only has to hit *any* one of them. PBKDF2 with
  600_000 rounds and one global salt costs a legitimate check 0.16 s, once
  at startup, and multiplies that day by six hundred thousand. One
  derivation covers the whole list, so adding supporters never slows the
  check down.

The alphabet leaves out I, L, O, 0 and 1, because a code is read off a
Ko-fi message and typed by hand, and those five are the pairs people get
wrong. Input is normalised before anything looks at it, so spaces, hyphens
and lower case all work.

  IMPORTANT: the generator (make_codes.py, which stays in the private
  repository) imports `normalise` and `digest` from here. They must never
  be reimplemented on that side -- two copies that drift by one strip()
  would issue codes that can never be redeemed, and the failure shows up
  at a supporter, after the money.

Revocation: a code that turns up shared in public is deleted from
codes.txt, and the next release locks it out. `unlocked()` re-checks the
saved code against the list on every start rather than trusting a stored
"yes", which is what makes that work.

From the command line, for handing a machine on and for testing:

  py unlock.py                       what this machine has, and where
  py unlock.py --forget              throw the saved code away
  py unlock.py --redeem ABCD-EFGH-JKMN   type one in without the window
  py unlock.py --check ABCD-EFGH-JKMN    would it be accepted? nothing written
"""

import argparse
import hashlib
import os
import re
import sys

import userdata

HERE = os.path.dirname(os.path.abspath(__file__))

# Where the money goes and the code comes from. Shown wherever a locked
# feature explains itself, so it is written down once.
KOFI_URL = "https://ko-fi.com/digipr1me"

CODES_FILE = os.path.join(HERE, "codes.txt")
# The redeemed code, in the data folder rather than in the settings file:
# settings are meant to be resettable and the data folder is what survives
# an update. It sits beside the learned data rather than among it --
# templates, digits and unknown -- so anything that clears what the
# wizard taught leaves the code alone.
SAVED_FILE = "supporter.txt"

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GROUP = 4
GROUPS = 3
LENGTH = GROUP * GROUPS

SALT = b"helpermon-supporter-v1"
ROUNDS = 600_000

_CACHE = {}


def normalise(code):
    """What the checker and the generator both agree a code is.

    Everything that is not an alphabet character is dropped, so
    "abcd-efgh jkmn", "ABCDEFGHJKMN" and a value pasted with a trailing
    newline are the same code.
    """
    if not code:
        return ""
    return re.sub("[^%s]" % ALPHABET, "", code.strip().upper())


def pretty(code):
    """The grouped form, for showing a code back to the person who typed it."""
    plain = normalise(code)
    return "-".join(plain[i:i + GROUP] for i in range(0, len(plain), GROUP))


def looks_like_code(code):
    """Shape only, and no hashing.

    Worth its own step because the slow part costs a sixth of a second: a
    typo should come back at once and say "that is not the right length",
    not stall first.
    """
    return len(normalise(code)) == LENGTH


def digest(code):
    """The one way a code becomes a line in codes.txt."""
    plain = normalise(code)
    return hashlib.pbkdf2_hmac("sha256", plain.encode("ascii"),
                               SALT, ROUNDS).hex()


def known_hashes(path=None):
    """The codes this build accepts. Blank lines and # comments ignored.

    Read fresh each time rather than cached: the file is a few kilobytes,
    and a cached list would outlive a build that revoked something.
    """
    out = set()
    try:
        with open(path or CODES_FILE) as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip().lower()
                if line:
                    out.add(line)
    except OSError:
        # No list is not an error. A source checkout with no codes yet, or
        # a build that ships none, simply accepts nothing.
        pass
    return out


def check(code, path=None):
    """Is this a code this build was told about?"""
    if not looks_like_code(code):
        return False
    return digest(code) in known_hashes(path)


# ----------------------------------------------------------------------
# What is remembered between sessions
# ----------------------------------------------------------------------
def _saved_path():
    return os.path.join(userdata.data_dir(), SAVED_FILE)


def saved():
    """The code that was redeemed here, or None."""
    try:
        with open(_saved_path()) as fh:
            code = normalise(fh.read())
    except OSError:
        return None
    return code or None


def redeem(code):
    """Check a code and, if it holds, remember it. Returns whether it held.

    The write is read back before this reports success. A data folder that
    turned read-only would otherwise unlock the session and forget by the
    next start, which reads to a supporter as the code having stopped
    working -- and they have no way to tell that from a revocation.
    """
    if not check(code):
        return False
    plain = normalise(code)
    try:
        with open(_saved_path(), "w") as fh:
            fh.write(plain + "\n")
    except OSError:
        return False
    _CACHE.clear()
    return saved() == plain


def forget():
    """Give the code back, for handing a machine on -- and for testing.

    There is no button for this. Throwing the code away is the one thing
    in the program that cannot be undone by pressing something else: the
    copy that matters is in a Ko-fi message from months ago, and a
    live-looking button beside the line that names the code invites a
    press to find out what it does. It lives on the command line instead,
    where it has to be typed out:

        py unlock.py --forget
    """
    try:
        os.remove(_saved_path())
    except OSError:
        pass
    _CACHE.clear()


def unlocked():
    """Are the supporter features available on this machine?

    The saved code is checked against the list again, not merely read: that
    is what lets a revoked code stop working, and it costs one PBKDF2
    derivation per process, cached below.
    """
    if "unlocked" not in _CACHE:
        code = saved()
        _CACHE["unlocked"] = bool(code) and check(code)
    return _CACHE["unlocked"]


# ----------------------------------------------------------------------
# From the command line
# ----------------------------------------------------------------------
def _describe():
    """The three states, in the same words the About page uses."""
    code = saved()
    print("data folder: %s" % userdata.data_dir())
    print("code file:   %s%s"
          % (_saved_path(), "" if code else "   (not there)"))
    print("codes.txt:   %s, %d live hashes"
          % (CODES_FILE, len(known_hashes())))
    print("")
    if not code:
        print("No code on this machine. The supporter features are locked.")
    elif check(code):
        print("%s is redeemed here and accepted." % pretty(code))
    else:
        # The state that is worth telling apart: kept, and no longer on the
        # list. Reads as the program having forgotten unless it is said.
        print("%s is redeemed here and is NOT on this build's list -- "
              "revoked, or a codes.txt from another build." % pretty(code))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="The supporter code on this machine.")
    ap.add_argument("--forget", action="store_true",
                    help="delete the saved code, locking the machine again")
    ap.add_argument("--redeem", metavar="CODE",
                    help="check a code and save it, as the window would")
    ap.add_argument("--check", metavar="CODE",
                    help="say whether a code holds, and write nothing")
    args = ap.parse_args(argv)

    if args.check:
        # The code is named back before it is judged, because the
        # normalising is half of what one debugs here: a code that reads
        # back wrong was mistyped, and that is not a revocation.
        held = check(args.check)
        print("%s: %s" % (pretty(args.check),
                          "accepted" if held
                          else "not the right shape"
                          if not looks_like_code(args.check)
                          else "not on this build's list"))
        return 0 if held else 1

    if args.redeem:
        if not redeem(args.redeem):
            print("%s was not accepted, and nothing was written."
                  % pretty(args.redeem))
            return 1
        print("%s redeemed. The supporter features are open on this machine."
              % pretty(saved()))
        return 0

    if args.forget:
        code = saved()
        if not code:
            print("No code on this machine. Nothing to give back.")
            return 0
        # Printed before it goes, and this is the only place it is shown
        # again: the copy that matters is in a Ko-fi message from months
        # ago, and there is nothing in the program that gets it back.
        print("Giving back %s. Write it down -- it is not shown anywhere "
              "after this." % pretty(code))
        forget()
        print("Gone. The supporter features are locked again.")
        return 0

    _describe()
    return 0


if __name__ == "__main__":
    sys.exit(main())
