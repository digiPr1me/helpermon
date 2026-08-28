"""
The supporter code: the mechanism, and the wiring around it.

No emulator and no network -- the whole point of this unlock is that it
answers offline. What it does need is a throwaway data folder, because
redeeming writes the code down and the real one belongs to whoever is
sitting at this machine.

The slow part is deliberate: every digest costs about a sixth of a second,
so this suite mints three codes and no more.

  py test_unlock.py
"""
import io
import os
import re
import secrets
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FRESH = os.path.join(tempfile.gettempdir(), "helpermon_test_unlock")
shutil.rmtree(FRESH, ignore_errors=True)
os.makedirs(FRESH)
os.environ["DGUP_DATA"] = FRESH

import unlock
import userdata

assert userdata.data_dir() == FRESH, userdata.data_dir()

HERE = os.path.dirname(os.path.abspath(__file__))
REAL_CODES = unlock.CODES_FILE
# Everything below checks against a list of this suite's own making. The
# shipped one is looked at once, at the end, and only to see that it has
# the right shape.
unlock.CODES_FILE = os.path.join(FRESH, "codes.txt")


# =====================================================
# What counts as the same code
# =====================================================
SAMPLE = "ABCD-EFGH-JKMN"

for written in ("ABCD-EFGH-JKMN", "abcd-efgh-jkmn", "ABCDEFGHJKMN",
                "  abcd efgh jkmn\n", "AbCd-EfGh-JkMn"):
    assert unlock.normalise(written) == "ABCDEFGHJKMN", written
print("dashes, spaces, case and a trailing newline all read as one code")

assert unlock.pretty("abcdefghjkmn") == SAMPLE
assert unlock.pretty(SAMPLE) == SAMPLE
print("shown back as %s however it was typed" % SAMPLE)

# The five characters people get wrong reading a code off a screen. If one
# of them ever enters the alphabet, every code containing it becomes a
# support case rather than an unlock.
for confusable in "ILO01":
    assert confusable not in unlock.ALPHABET, confusable
assert len(unlock.ALPHABET) == 31, len(unlock.ALPHABET)
print("alphabet has no I, L, O, 0 or 1, and %d characters left"
      % len(unlock.ALPHABET))

assert unlock.looks_like_code(SAMPLE)
assert not unlock.looks_like_code("ABCD-EFGH")
assert not unlock.looks_like_code("ABCD-EFGH-JKMN-PQRS")
assert not unlock.looks_like_code("")
assert not unlock.looks_like_code(None)
# The shape check must not hash: it is what stands between a typo and a
# sixth of a second of a window that looks frozen.
source = io.open(os.path.join(HERE, "unlock.py"), encoding="utf-8").read()
body = source.split("def looks_like_code")[1].split("\ndef ")[0]
assert "digest" not in body and "pbkdf2" not in body
print("wrong lengths refused, and refused without hashing")


# =====================================================
# A list this suite minted, and one code out of it
# =====================================================
# Minted here rather than by make_codes.py. That file is the generator and
# stays in the private repository, while this suite ships -- and an import
# of something deliberately left out of the build fails the whole suite on
# every public checkout. On the one suite that is about the supporter
# codes, which reads to a contributor as "the codes are broken" when
# nothing is wrong at all. Caught by building the release into a folder
# and running the suites there, which is the only place the two rules meet.
def mint():
    """A code of the right shape, the way the generator makes one."""
    raw = "".join(secrets.choice(unlock.ALPHABET)
                  for _ in range(unlock.LENGTH))
    return unlock.pretty(raw)


MINE = [mint() for _ in range(2)]
STRANGER = mint()

# Where the generator is present -- the private repository -- it has to
# agree with the line above and with the checker. A generator that drifted
# from either would issue codes that can never be redeemed, and nobody
# would find out until a supporter had already paid.
try:
    import make_codes
except ImportError:
    print("make_codes.py is not in this checkout, so the suite mints its own")
else:
    sample = make_codes.new_code()
    assert unlock.looks_like_code(sample), sample
    assert all(ch in unlock.ALPHABET for ch in unlock.normalise(sample))
    assert unlock.pretty(sample) == sample, sample
    print("make_codes mints exactly what unlock accepts")

with open(unlock.CODES_FILE, "w") as fh:
    fh.write("# a comment, and a blank line, both ignored\n\n")
    for code in MINE:
        fh.write(unlock.digest(code) + "  # " + "who it went to\n")

assert len(unlock.known_hashes()) == 2, unlock.known_hashes()
print("two codes in the list, comments and blank lines skipped")

assert unlock.check(MINE[0])
assert unlock.check(MINE[1].lower().replace("-", " "))
assert not unlock.check(STRANGER)
assert not unlock.check("")
print("a minted code holds however it is typed; one that was never minted "
      "does not")

# Two codes cannot collide into one another's hash, which is the only way a
# list of hashes could unlock the wrong thing.
assert unlock.digest(MINE[0]) != unlock.digest(MINE[1])


# =====================================================
# Redeeming, remembering, and forgetting
# =====================================================
assert not unlock.unlocked()
assert unlock.saved() is None
print("nothing redeemed to start with -> locked")

assert not unlock.redeem(STRANGER)
assert unlock.saved() is None, "a code that failed was written down anyway"
unlock._CACHE.clear()
assert not unlock.unlocked()
print("a code that does not hold is not written down")

assert unlock.redeem(MINE[0].lower())
assert unlock.saved() == unlock.normalise(MINE[0])
assert unlock.unlocked()
print("redeemed -> unlocked, and the code is kept in %s"
      % os.path.basename(unlock.SAVED_FILE))

# What the next start of the program sees: nothing in memory, only the file.
unlock._CACHE.clear()
assert unlock.unlocked()
print("still unlocked after a restart, with no cache to help it")

# Where it is kept matters as much as that it is kept: the folder that
# survives an update, and beside the learned data rather than among it,
# so anything that clears templates, digits or unknown leaves it.
assert os.path.dirname(unlock._saved_path()) == FRESH
assert unlock.SAVED_FILE not in ("templates", "digits", "unknown")
print("kept with the learned data, so an update does not cost it")


# =====================================================
# Revocation
# =====================================================
# The saved code is checked against the list again on every start rather
# than trusted because it is there. Without that, revoking would be a note
# in a file nobody reads.
with open(unlock.CODES_FILE, "w") as fh:
    fh.write(unlock.digest(MINE[1]) + "\n")
unlock._CACHE.clear()
assert unlock.saved() is not None, "the code is still on disk"
assert not unlock.unlocked(), "a revoked code still unlocks"
print("a code taken out of the list stops working, though it is still saved")

with open(unlock.CODES_FILE, "w") as fh:
    fh.write(unlock.digest(MINE[0]) + "\n")
unlock._CACHE.clear()
assert unlock.unlocked()

unlock.forget()
assert unlock.saved() is None
assert not unlock.unlocked()
print("given back -> locked again, and nothing left behind")

# =====================================================
# The command line, which is where giving a code back lives
# =====================================================
# There is no button for it any more: the window can only take a code in.
# So this is the only way out, and it is also the only way to look at what
# a machine has without starting the window.
import contextlib


def run(*argv):
    """main() with its printing caught, so the words can be checked too."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = unlock.main(list(argv))
    return code, out.getvalue()

with open(unlock.CODES_FILE, "w") as fh:
    fh.write(unlock.digest(MINE[0]) + "\n")
unlock._CACHE.clear()

status, said = run("--check", MINE[0])
assert status == 0 and "accepted" in said, said
assert unlock.saved() is None, "--check wrote the code down"
status, said = run("--check", STRANGER)
assert status == 1 and "not on this build" in said, said
status, said = run("--check", "ABCD")
assert status == 1 and "not the right shape" in said, said
print("--check answers for a code and writes nothing, whatever the answer")

status, said = run("--redeem", MINE[0].lower())
assert status == 0, said
assert unlock.saved() == unlock.normalise(MINE[0])
unlock._CACHE.clear()
assert unlock.unlocked()
print("--redeem opens the machine up, the same as typing it into the window")

status, said = run()
assert status == 0
assert unlock.pretty(MINE[0]) in said, "the status does not name the code"
assert FRESH in said, "the status does not say where the code is kept"
print("no arguments says what this machine has, and where it is")

status, said = run("--forget")
assert status == 0
# Printed on the way out, once. Nothing else in the program shows a code
# that has been given back, so this line is the last chance to copy it.
assert unlock.pretty(MINE[0]) in said,     "the code is thrown away without being shown one last time"
assert unlock.saved() is None
unlock._CACHE.clear()
assert not unlock.unlocked()
print("--forget names the code, then gives it back and locks the machine")

status, said = run("--forget")
assert status == 0 and "othing to give back" in said, said
print("--forget on a machine with no code says so instead of failing")


# No list at all is not an error, and it is not an unlock either. A source
# checkout with no codes yet used to be the obvious way to get this wrong.
os.remove(unlock.CODES_FILE)
unlock._CACHE.clear()
assert unlock.known_hashes() == set()
assert not unlock.check(MINE[0])
assert not unlock.unlocked()
print("no list at all -> accepts nothing, rather than everything")


# =====================================================
# The ledger, and what it must never ship as
# =====================================================
import release

for name in ("codes_issued.csv", "make_codes.py"):
    assert name in release.EXCLUDED_FILES, name
assert "codes.txt" not in release.EXCLUDED_FILES
assert "codes_issued.csv" in release.FORBIDDEN_NAMES
# Named twice on purpose: EXCLUDED_FILES is the rule, FORBIDDEN_NAMES is
# the refusal that catches a copy the rule missed.
assert release.audit(["codes_issued.csv"]) == ["codes_issued.csv"]
assert release.audit(["a_backup_of_codes_issued.csv"])
assert release.audit(["codes.txt"]) == []
print("the ledger cannot ship, under that name or a copy of it; the hashes "
      "can")

# A build written inside the working copy is shipped whole by the next
# build. It happened: a shell ate the backslashes out of an absolute
# Windows path, the relative remainder was taken from the repository, and
# the next --check listed 161 files instead of 82.
assert release.inside_source(".")
assert release.inside_source("Aleks/Documents/Helpermon-test")
assert release.inside_source(os.path.join(release.HERE, "anywhere"))
assert not release.inside_source(os.path.join(
    os.path.dirname(release.HERE), "helpermon_public"))
assert not release.inside_source(tempfile.gettempdir())
# The sibling whose name merely starts the same way is not inside it.
assert not release.inside_source(release.HERE + "_test")
print("a build target inside the working copy is refused")


# =====================================================
# The gate in the window
# =====================================================
import app

app_src = io.open(os.path.join(HERE, "app.py"), encoding="utf-8").read()

assert app.SUPPORTER_ONLY, "nothing is a supporter feature"
for key in app.SUPPORTER_ONLY:
    assert key in app.EXTRA_BOTS or any(b["key"] == key for b in app.BOTS), \
        "%s is locked and is not a bot" % key
    # The whole point of one gate: a key in the table whose start path does
    # not go through `_may_run` would be locked in the table and open in
    # fact, and nothing at runtime would ever say so.
    assert '_may_run("%s")' % key in app_src, \
        "%s is a supporter feature whose Start button does not ask" % key
print("every supporter feature's start goes through the gate: %s"
      % ", ".join(sorted(app.SUPPORTER_ONLY)))

# And nothing may reach past the gate to the notice underneath it. The one
# call with a literal key would be a start path that skipped the check.
assert 'self._first_run_notice("' not in app_src, \
    "a Start button calls the requirements notice directly, past _may_run"
print("no start path calls the requirements notice behind the gate's back")

for method in ("_may_run", "_supporter_gate", "_code_dialog",
               "_supporter_box", "_refresh_supporter", "_locked_name"):
    assert hasattr(app.App, method), method

# Giving the code back is not a button. It cannot be undone by pressing
# something else -- the copy that matters is a Ko-fi message from months
# ago -- and next to a line naming the code, a live-looking button invites
# a press to find out what it does.
assert not hasattr(app.App, "_forget_code"),     "the window can throw the code away again"
assert "unlock.forget()" not in app_src, "the window still gives codes back"
assert "unlock.py --forget" in app_src.split("def _page_about")[1],     "About does not say how to give it back"
print("no button gives a code back; About points at py unlock.py --forget")

# The one that would put the wrong bot's name on a request for money.
assert app.App._locked_name(None, "summon") == "Special Summon"
assert app.App._locked_name(None, "dungeon") == "Dungeons"
assert app.App._locked_name(None, "nonesuch") != app.BOTS[0]["name"]
print("a locked page is named after itself, with no fall back to Dungeons")

# Three states, not two. A code that was redeemed here and has since been
# revoked reads as the program forgetting unless something says otherwise,
# and "it forgot" is the reading that sends somebody to pay a second time.
assert app.SUPPORTER_STALE.count("%s") == 1, "the stale line names no code"
assert "write to me" in app.SUPPORTER_STALE
NEXT_METHOD = "\n    def "
about = app_src.split("def _page_about")[1].split(NEXT_METHOD)[0]
assert "SUPPORTER_STALE" in about, "About cannot tell a revoked code from none"
banner = app_src.split("def _supporter_box")[1].split(NEXT_METHOD)[0]
assert "SUPPORTER_STALE" in banner, "the banner cannot tell either"
print("a revoked code says so on both the banner and About, naming itself")

# --- half a page, and only half of it locked ------------------------------
# The bond token and Auto Spend shipped free. The quest loop shares their
# page, their thread and their kind of switch, and is a supporter feature --
# so the lock is on the half, not on the page, and the two switches ask
# separately. Asking once for the pair was right while the pair was free and
# would now let the free half's answer stand for the paid one.
assert "quest" in app.SUPPORTER_ONLY
assert "passive" not in app.SUPPORTER_ONLY,     "the bond helper was free and has been taken back off people who had it"
for key in ("passive", "quest"):
    assert '_may_run("%s")' % key in app_src, "%s asks nobody" % key
sync = app_src.split("def _sync_helper_thread")[1].split(NEXT_METHOD)[0]
assert "is_alive()" not in sync,     "the quest switch is waved through whenever the free half is running"
print("the free half of that page stays free, and the two switches ask "
      "separately")

# The switch is a line in a settings file, and a settings file outlives the
# code that was accepted when it was written. Both places that act on it --
# the thread that taps, and the start of the window -- ask the lock itself.
loop = app_src.split("def _passive_loop")[1].split(NEXT_METHOD)[0]
assert 'settings.get("quest_on", False) and unlock.unlocked()' in loop,     "the quest loop taps on a saved switch alone"
start = app_src.split("class App")[1].split(NEXT_METHOD)[1]
assert 'state_data.get("quest_on") and not unlock.unlocked()' in start,     "a window opening on a locked machine starts a saved quest switch anyway"
print("a saved quest switch is not evidence: the thread and the start of "
      "the window both ask the lock")


assert unlock.KOFI_URL.startswith("https://ko-fi.com/")
assert "ko-fi.com/your" not in unlock.KOFI_URL.lower(), \
    "the Ko-fi link is still the placeholder"
print("Ko-fi link: %s" % unlock.KOFI_URL)


# =====================================================
# The list that actually ships
# =====================================================
if os.path.exists(REAL_CODES):
    lines = [ln.split("#", 1)[0].strip()
             for ln in io.open(REAL_CODES, encoding="utf-8")]
    live = [ln for ln in lines if ln]
    for line in live:
        assert re.fullmatch("[0-9a-f]{64}", line), \
            "codes.txt has a line that is not a hash: %r" % line[:20]
    # A code minted after a build went out is unknown to that build, so the
    # pool is minted ahead. An empty or nearly empty list means the next
    # donation cannot be answered until a release goes out.
    assert len(live) >= 50, \
        "only %d codes in the pool; py make_codes.py --mint 500" % len(live)
    print("codes.txt: %d hashes, all well formed" % len(live))
else:
    print("codes.txt: none in this checkout, so nothing would unlock")

shutil.rmtree(FRESH, ignore_errors=True)
print("all supporter code cases as expected")
