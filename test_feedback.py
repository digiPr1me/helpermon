"""
feedback.py: building a report, turning it into text, and the two ways it
can leave the machine -- a Discord POST or a file on disk.

Needs no emulator and must never touch the network: the empty-URL case and
the fake-opener cases are what keep this suite offline, and are checked by
call count, not just by return value.

  py test_feedback.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FRESH = os.path.join(tempfile.gettempdir(), "helpermon_test_feedback")
shutil.rmtree(FRESH, ignore_errors=True)
os.makedirs(FRESH)
os.environ["HELPERMON_FEEDBACK_DIR"] = FRESH

import feedback
from version import VERSION

assert feedback.FEEDBACK_DIR == FRESH, feedback.FEEDBACK_DIR


# =====================================================
# build_report
# =====================================================
long_log = "\n".join("line %d" % i for i in range(500))
report = feedback.build_report("Dungeons", thumb="down", text="It stopped",
                               log=long_log, seconds=252, dry_run=True)
assert report["bot"] == "Dungeons" and report["thumb"] == "down"
assert report["version"] == VERSION
kept = report["log"].splitlines()
assert len(kept) == feedback.LOG_LINES, len(kept)
assert kept[-1] == "line 499", kept[-1]
assert kept[0] == "line %d" % (500 - feedback.LOG_LINES), kept[0]
print("build_report keeps version and bot, and trims the log to the last "
      "%d lines" % feedback.LOG_LINES)


# =====================================================
# as_text
# =====================================================
text = feedback.as_text(report)
assert "It stopped" in text
assert "Contact:" not in text, text
with_contact = feedback.as_text(feedback.build_report(
    "Dungeons", thumb="up", text="fine", contact="someone#1234"))
assert "Contact: someone#1234" in with_contact, with_contact
print("as_text carries the written text and leaves out an empty Contact "
      "line")

# The date has to be in the text, not only in the dict. Discord writes its
# own time beside a message, so a missing one shows up nowhere until a
# report that could not be sent is opened as a file weeks later -- and the
# log tail under it carries clock times only.
import re as _re
assert _re.search(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", text), text
assert "T" not in text.splitlines()[0].split(" - ")[1], text.splitlines()[0]
print("as_text puts the full date and time in the header, without the ISO T")


# =====================================================
# _discord_payload
# =====================================================
# Long lines rather than many short ones: build_report already trims to
# LOG_LINES=80, and 80 short lines fit comfortably under MAX_CONTENT. What
# forces _discord_payload's own cut is a log that is few lines but many
# characters, the way a stack trace or a wrapped path can be.
long_lines = ["line %d: %s" % (i, "x" * 200) for i in range(60)]
huge = feedback.build_report("Dungeons", thumb="down", text="broke",
                             log="\n".join(long_lines))
assert huge["log"].splitlines() == long_lines  # under LOG_LINES, untouched
payload = feedback._discord_payload(huge)
content = payload["content"]
assert len(content) <= 2000, len(content)
assert "(log truncated)" in content, content
assert content.rstrip().endswith(long_lines[-1] + "\n```"), content[-260:]
print("a log too long in characters is cut from the front, stays under "
      "2000 chars, and still ends with the log's last line (%d chars)"
      % len(content))


# =====================================================
# send
# =====================================================
class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append((request, timeout))


small = feedback.build_report("Dungeons", thumb="up")

opener = _Recorder()
ok, detail = feedback.send(small, url="", opener=opener)
assert ok is False and opener.calls == [], (ok, detail, opener.calls)
print("send with no endpoint touches the network zero times")

opener = _Recorder()
ok, detail = feedback.send(small, url="https://example.invalid/hook",
                           opener=opener)
assert ok is True, (ok, detail)
assert len(opener.calls) == 1
request = opener.calls[0][0]
assert request.get_header("Content-type") == "application/json", \
    request.headers
assert request.get_header("User-agent").startswith("Helpermon/"), \
    request.headers
print("send sets Content-Type and a Helpermon User-Agent, which is what "
      "keeps Discord from answering with a 403")


def _raises(request, timeout=None):
    raise __import__("urllib.error", fromlist=["URLError"]).URLError(
        "refused")


ok, detail = feedback.send(small, url="https://example.invalid/hook",
                           opener=_raises)
assert ok is False and "refused" in detail, (ok, detail)
print("a URLError from the opener comes back as a failure, not an "
      "exception")


# =====================================================
# submit
# =====================================================
# submit() takes no opener, so these three cases reach the network through
# whatever WEBHOOK_URL happens to hold. Pinned empty rather than trusted to
# be empty: the moment a real webhook is pasted into feedback.py, an
# unpinned suite posts test reports into that channel for real and then
# fails on `ok is False`.
_real_url = feedback.WEBHOOK_URL
feedback.WEBHOOK_URL = ""

state = {}
result = feedback.submit(small, state)
assert result["ok"] is False and result["path"], result
with open(result["path"]) as fh:
    saved = fh.read()
assert saved == feedback.as_text(small), (saved, feedback.as_text(small))
print("with no endpoint configured, submit writes a file and names it")

# rate guard: MAX_PER_HOUR recent sends block the next one
import time

state = {"feedback_sent_at": [time.time()] * feedback.MAX_PER_HOUR}
before = len(os.listdir(FRESH))
result = feedback.submit(small, state)
assert result["ok"] is False and "hour" in result["detail"].lower(), result
assert len(os.listdir(FRESH)) == before, "the rate guard should send nothing"
print("the rate guard refuses once %d reports have gone out in the last "
      "hour" % feedback.MAX_PER_HOUR)

# a timestamp older than an hour does not count against the guard
state = {"feedback_sent_at": [time.time() - 7200] * feedback.MAX_PER_HOUR}
result = feedback.submit(small, state)
assert result["path"], result  # ran the send path rather than refusing
assert len(state["feedback_sent_at"]) == 0, state
print("a timestamp older than an hour drops out of the guard")

feedback.WEBHOOK_URL = _real_url


def _blows_up(request, timeout=None):
    raise RuntimeError("something unexpected")


# submit() has no opener parameter of its own -- it always goes through
# send()'s default, urllib.request.urlopen. To prove submit swallows an
# unexpected exception from that default rather than a URLError it has to
# be patched at the source, with WEBHOOK_URL pointed somewhere so send()
# actually reaches the opener instead of returning early.
old_url, old_urlopen = feedback.WEBHOOK_URL, feedback.urllib.request.urlopen
feedback.WEBHOOK_URL = "https://example.invalid/hook"
feedback.urllib.request.urlopen = _blows_up
try:
    result = feedback.submit(small, {})
finally:
    feedback.WEBHOOK_URL = old_url
    feedback.urllib.request.urlopen = old_urlopen
assert result["ok"] is False and result["path"], result
print("submit never raises, even when the opener throws something "
      "unexpected -- it falls back to a file")


shutil.rmtree(FRESH, ignore_errors=True)
print("all feedback cases as expected")
