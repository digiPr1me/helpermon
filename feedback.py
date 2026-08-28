"""Sends a player's thumbs-up/down or written report to the developer.

No tkinter here, and nothing beyond the standard library: that is what
lets this run in the test suite without an emulator, a network, or a
display. `app.py` is the only caller.
"""

import datetime
import json
import os
import platform
import time
import urllib.error
import urllib.request

from version import VERSION

# A Discord webhook can only post into the one channel it was created for.
# It cannot read messages, members or anything else about the server, and it
# cannot act as the account that made it -- so it is fine for this URL to
# sit in a public repository. If it is ever abused, rotating it is deleting
# the webhook in Discord and pasting a fresh one in here.
WEBHOOK_URL = "https://discord.com/api/webhooks/1541824086206972006/ex5EyVbhliMn6EinO4bTcLVKZqO62tBTmcz8sSFR7rVA-9ZPG6sdVTzOpw9UmEOpfr3e"

# Discord rejects a `content` over 2000 characters outright. Headroom, not
# the edge, because the payload also carries fenced-block markup.
MAX_CONTENT = 1900

# Discord answers urllib's default User-Agent with a 403 and no other
# explanation. Somebody would otherwise spend an hour looking for the bug
# at the wrong end.
USER_AGENT = "Helpermon/%s" % VERSION

# A guard against a stuck loop in Helpermon itself hammering the webhook,
# not against a malicious user.
MAX_PER_HOUR = 10

# How much of the tail of a bot's log travels with a report.
LOG_LINES = 80

_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
FEEDBACK_DIR = (os.environ.get("HELPERMON_FEEDBACK_DIR")
                or os.path.join(_APPDATA, "helpermon-feedback"))


def environment():
    """The facts that make a report actionable, gathered from this machine.

    Nothing here identifies a person: version, Windows build, Python
    version, and whether adb was found.
    """
    try:
        import capture
        adb = "yes" if capture.find_adb() else "no"
    except Exception:
        adb = "no"
    return {"version": VERSION, "os": platform.platform(),
            "python": platform.python_version(), "adb": adb}


def _tail(log, n):
    lines = log.splitlines()
    return "\n".join(lines[-n:])


def _duration(seconds):
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return "%dm%ds" % (m, s)


def build_report(bot, thumb=None, text="", log="", contact="",
                 seconds=None, dry_run=None):
    report = environment()
    report.update(
        bot=bot, thumb=thumb, text=text, contact=contact,
        seconds=seconds, dry_run=dry_run, log=_tail(log, LOG_LINES),
        when=datetime.datetime.now().isoformat(timespec="seconds"))
    return report


def as_text(report):
    """One human-readable block, the thing a person actually reads."""
    bot = report.get("bot") or "Feedback"
    first = ("[%s] %s" % (report["thumb"], bot) if report.get("thumb")
              else bot)
    segments = [first]
    # The full date here and nowhere else. Discord writes its own time
    # beside a message, so this looks redundant there -- but a report that
    # could not be sent is a text file, and that file had no date in it at
    # all. The log tail below carries clock times only, and a bare 12:04:31
    # says nothing about which day a week-old report is from.
    if report.get("when"):
        segments.append(report["when"].replace("T", " "))
    segments += ["v%s" % report["version"], report["os"],
                 "py %s" % report["python"], "adb %s" % report["adb"]]
    if report.get("seconds") is not None:
        segments.append(_duration(report["seconds"]))
    if report.get("dry_run"):
        segments.append("dry run")
    lines = [" - ".join(segments)]
    if report.get("text"):
        lines.append(report["text"])
    if report.get("contact"):
        lines.append("Contact: %s" % report["contact"])
    if report.get("log"):
        lines.append("--- log ---")
        lines.append(report["log"])
    return "\n".join(lines)


def _discord_payload(report):
    header = as_text(dict(report, log=""))
    log = report.get("log", "")
    if not log:
        return {"content": header}

    content = header + "\n```\n" + log + "\n```"
    if len(content) <= MAX_CONTENT:
        return {"content": content}

    # Cut lines off the front of the log, never the end -- the end of a
    # log is the half that says what went wrong.
    marker = "(log truncated)"
    fence_overhead = len("\n```\n") + len(marker) + len("\n") + len("\n```")
    budget = max(0, MAX_CONTENT - len(header) - fence_overhead)
    kept, total = [], 0
    for line in reversed(log.splitlines()):
        total += len(line) + 1
        if total > budget:
            break
        kept.insert(0, line)
    body = marker + "\n" + "\n".join(kept)
    return {"content": header + "\n```\n" + body + "\n```"}


def send(report, url=None, opener=None):
    """POSTs the report to Discord. Never raises -- it is called from a
    button, and a stack trace instead of a result is worse than either."""
    # `is None`, not `or`: an explicitly passed url has to be authoritative,
    # empty string included. With `url or WEBHOOK_URL` an explicit "" fell
    # through to the constant, so the test that proves the suite touches no
    # network only held while the constant was empty -- it would have posted
    # test reports into the real channel the day a webhook was pasted in.
    if url is None:
        url = WEBHOOK_URL
    opener = opener or urllib.request.urlopen
    if not url:
        return False, "no endpoint configured"
    try:
        payload = json.dumps(_discord_payload(report)).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "User-Agent": USER_AGENT})
        opener(request, timeout=10)
        return True, "sent"
    except urllib.error.URLError as err:
        return False, "could not reach the webhook: %s" % err
    except Exception as err:
        return False, "could not send: %s" % err


def save_locally(report):
    os.makedirs(FEEDBACK_DIR, exist_ok=True)
    name = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S") + ".txt"
    path = os.path.join(FEEDBACK_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(as_text(report))
    return path


def submit(report, state):
    """The one function app.py calls. Never raises -- it runs off a button
    click, on a worker thread, with nobody there to catch an exception."""
    try:
        now = time.time()
        sent_at = [t for t in state.get("feedback_sent_at", [])
                  if now - t < 3600]
        state["feedback_sent_at"] = sent_at
        if len(sent_at) >= MAX_PER_HOUR:
            return {"ok": False, "path": None,
                    "detail": "already sent %d reports in the last hour, "
                              "try again later" % MAX_PER_HOUR}

        ok, detail = send(report)
        if ok:
            sent_at.append(now)
            return {"ok": True, "path": None, "detail": detail}
        path = save_locally(report)
        return {"ok": False, "path": path, "detail": detail}
    except Exception as err:
        return {"ok": False, "path": None, "detail": "could not send: %s" % err}
