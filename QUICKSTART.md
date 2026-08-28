# Helpermon - quick start

> **An unofficial fan project.** Helpermon is not made, endorsed, sponsored or
> supported by Bandai Namco, Bandai, Toei Animation, or anyone else involved in
> Digimon UP. *Digimon* and every name, character and image belonging to the
> game are the property of their owners. Nothing from the game is contained
> here; what the bots need, they learn from your own screen.

For people seeing this program for the first time. Helpermon plays parts of
Digimon UP for you: the dungeon list and the **Digital World Search**.

## What you need

* Windows
* LDPlayer with Digimon UP installed. Do **not** start LDPlayer as
  administrator, see [If Windows gets in the way](#if-windows-gets-in-the-way)
* Python 3.10 or newer. If you do not have it, the installer offers to fetch
  it for you and no administrator password is needed

## Installing

**[INSTALL.md](INSTALL.md) is the installation, step by step and with
pictures.** In short: take the newest `helpermon-x.y.zip` from **Releases**,
right-click it and tick **Unblock** in its Properties *before* unpacking,
unpack it under your own user folder, and double-click `install.bat`. It finds
or fetches Python, builds a `.venv` beside the program and puts a **Helpermon**
shortcut on your desktop. That shortcut is what you start from then on.

The unblocking is the one step that causes trouble when it is skipped, because
Windows passes the internet mark from the ZIP to every file inside it.

Prefer a terminal, or do you already keep your own environments? Then the
packages by hand and skip `install.bat` entirely:

```
py -m pip install -r requirements.txt
py app.py
```

**Updating later:** unpack the new ZIP over the old folder and run
`install.bat` again. `userdata` and `.venv` are not in the ZIP, so nothing you
have taught the bots is lost. If you use git, `git clone` and `git pull` do the
same job, and files from git carry no internet mark, so the unblocking does not
apply to them.

The first launch shows two dialogs. The first one is about **how Helpermon
reaches the emulator**, and it is the one that decides what the next hour
looks like. Both frames and clicks are picked together, by the **Use ADB for
screen and clicks** switch at the top right of every window a bot runs in.
It defaults to on:

* **With ADB**, Helpermon sends its taps straight to the emulator. Your mouse
  stays yours and the window may sit behind other windows. You have to switch
  it on first: in LDPlayer, **Settings → Other settings → ADB debugging**.
  Then press **Check ADB now** in that dialog, which asks the emulator instead
  of guessing.

  LDPlayer itself puts up an error when a lot is driven through ADB in one
  sitting. That is the emulator complaining, not the game — restart the
  emulator, or put that bot on mouse input for the rest of the session.
* **Without ADB**, the bot moves your real mouse. Then leave the mouse alone
  while a bot runs: you and the bot are sharing it, and every move of yours
  goes into the game as well. Press F7 when you want it back. The emulator
  window also has to stay visible, in front and uncovered, and the screen must
  not go to sleep — screen capture keeps returning the last picture that
  was drawn, and a bot reading that clicks at what was there minutes ago.

Finding `adb.exe` is automatic: Helpermon asks Windows where LDPlayer is
installed, then looks on every hard disk. On the rare machine where neither
turns it up — an install somewhere unusual, or a copy of `adb.exe` kept apart
from LDPlayer's own folder — **Start here** has a row under step 1 to browse
for it directly, either the file itself or the LDPlayer folder it lives in.

The second dialog is the legal notice, which you have to read. After that you
land on **Start here**.

The first time you start each bot, it tells you in one dialog what has to be
on screen before it can do anything. That same list is on the bot's page, in
the yellow box under the heading.

The window has three parts, and they do not change:

* a **header** across the top with the emulator's state: a coloured dot and
  one line saying what was found. It reports and nothing more — the buttons
  that start the emulator live on step 1 of Start here, because a row of
  buttons repeated on every page competes with whatever that page is for. The
  one exception is top right, the **Use ADB** switch, which is wanted at the
  moment a bot has just taken the mouse.
* a **sidebar** on the left listing where you can go: Start here, the three
  bots, About. A green dot next to a bot means it is ready to run, an orange
  one means it still needs setup. There is no shared Setup page: each bot is
  set up from its own page, with the button at the bottom right.
* the **page** you selected, filling the rest.

**Start here** offers you two ways in, with an **OR** between them.

At the top, while there is still setup to be done, is **Try it right now**.
The dungeon bot needs nothing taught, so that card starts the emulator and
takes you straight to it. This is the short way, and it is the one to take
first: you see the program actually working before you spend any time on it.
The card disappears once the bots that need setup are set up, since by then
you know.

Underneath is **Set everything up**, three numbered steps: start the emulator,
teach it what your screen looks like, run a bot. Each one shows how far you
have got and has the one button that moves you on. Steps you have finished get
a tick.

## Two bots, different requirements

| | Dungeons | Digital World Search |
|---|---|---|
| Plays | the dungeon list | Digital World Search |
| Setup required | no | yes, about 5 minutes |
| Game language | any | you teach it the banner texts |
| Character skin | irrelevant | **Botamon**, see below |
| In the sidebar | Dungeons | World Search |

**The dungeon bot can start right away.** It recognises buttons by colour and
position, so it needs no images from the game at all and works in any language.

**Digital World Search needs setup.** It has to tell tickets, claws, pyramids
and your character apart. It crops those images from your own screen, nothing
is shipped with the program.

> **The skin matters for this one.** This bot was built and measured with the
> **Botamon** skin, and finding the figure is the part that depends on it.
> Another skin may work perfectly well. It may also make the bot miss the
> figure and steer by something else instead, and it will not always say so —
> it can simply walk the wrong way. If you use a different skin, watch the
> first run with **Dry run** before letting it click.

## Order of things

Follow the three steps on **Start here** and you are done. In full:

1. Start LDPlayer and open the game, or press **Start LDPlayer** in the
   header. Do not minimise the window
2. Open **Dungeons** in the sidebar and press **Dry run** first. It clicks
   nothing and only shows what it would do
3. If that looks sensible, press **Start**
4. For Digital World Search, open that bot in the sidebar and press **Set up
   this bot**, bottom right. That window has that bot's steps and no others,
   so there is no way to wander into a different bot's setup by pressing
   Continue
5. After setup, stand on Digimon UP's plain main screen, then **World
   Search** in the sidebar and press **Start**. The bot opens the Digital
   World Search itself and goes back to the main screen when it is done

Every bot page works the same way: its settings, then **Start**, **Pause** and
**Stop**, then its log. **Dry run** sits below under *For testing* — it plans
everything and clicks nothing, which is what to send along if you report a
problem.

### The Dungeons page

Each dungeon has a number: how many attempts you want the bot to spend there.

| Number | What it means |
|---|---|
| **4** | a day's worth, and the default. Two tickets from the daily reset plus two more for watching ads |
| **0** | leave this dungeon alone |
| more than 4 | eats into tickets you have bought or saved up |

**Set all** puts one number on every dungeon at once. It stamps them, so you
can still put a single dungeon back to 0 afterwards. It starts at **5**
rather than 4, its own default and not a reflection of the one above.

The bot reads both counters off each card before it opens anything — the
tickets you have, and the ads you have not watched yet — and plays the smaller
of the two numbers: what you asked for, and what the game will actually hand
out. A dungeon with nothing left is skipped without being opened. If a counter
cannot be read, the dungeon is played anyway; unreadable is not the same as
empty.

There is no *Rounds* setting, and the bot no longer goes round at all: it walks
the list once, top half then bottom half, and each dungeon gets its number in
that one visit. Rounds were there so a lost battle could be retried later, but
this routine has no lost battles — it spends attempts, and a spent attempt is
spent whatever the outcome.

However the run ends — finished, stopped, or with an error — the bot presses
the game's own home button, the globe in the middle of the bottom bar, and
leaves the game on its main screen. That is where the passive helper does its
work and where the next bot expects to start, so nothing is left standing on a
dungeon panel. If it cannot get there it says so and leaves the game where it
stands rather than tapping about blindly.

### The Bond & Quest Loop page

This one has no Start button. It is a helper that runs by itself for as long
as Helpermon is open, and two switches turn its two halves on independently:

| Setting | What it does |
|---|---|
| Watch the main screen while Helpermon is open | the bond/hologram switch. Takes effect at once and is remembered |
| Collect the bond token | taps your partner when the food bubble is up |
| Keep Auto Spend for Hologram Tickets running | reads the counter under the device and presses the (A) button when it stops falling |
| Show everything it sees | every round in the log, not just what happened |
| Work through the repeating quests | the quest loop's own switch. Takes effect at once and is remembered |
| Play the dungeon quests | lets the loop spend two of the day's dungeon attempts on a dungeon quest |
| Do the summon quests | lets the loop watch the free ads and draw once for a summon quest |
| Claim only, never play anything | collects a finished quest, but never plays one to finish it |

**The quest half asks for a supporter code.** The four settings from "Work
through the repeating quests" down are a supporter feature; the bond token
and Auto Spend above them are free and stay free. Ticking the switch without
a code explains itself and offers the two ways on -- see *Supporter features*
in the README, or the About page in the window.

**The quests come in a fixed order that repeats.** The game hands out fifteen
of them, one at a time on a card at the right edge of the battle screen, and
starts again from the first once the fifteenth is claimed. The loop reads
that card and follows the same order — it does not pick a quest, it works
through the row exactly as the game presents it. A quest it cannot do yet
(no dungeon attempts left, not enough summon tickets, Auto Spend switched
off) holds up every quest after it, because the routine is a queue and not a
choice: the status line under the switch says which step the loop is on and,
once it is waiting on something, why.

Starting one of the three bots by hand takes the emulator back from a
dungeon or summon step the loop is in the middle of playing, within a few
seconds — the same way starting a second bot always wins over whatever ran
before it.

**Without ADB, keep LDPlayer uncovered.** Window capture reads the screen
where the emulator window sits, not the window itself, so anything in front of
it — a browser, this window — is what the helper sees, and it will report that
it cannot find the main screen. Switch ADB on and that stops mattering: the
frames then come from the device, and the emulator may be behind other windows
or minimised. For a helper meant to run all day while you do something else,
ADB is the mode that fits.

It works on the game's **main screen** and nowhere else. On any other screen,
under any dialog, and while one of the three bots is playing, it does nothing
at all and says so in its log. Without ADB a tap moves your real mouse, so it
also holds off while the mouse is being used — it keeps reading, it just does
not touch anything.

Two things worth knowing about what it does:

**The bond token is collected by tapping the figure, not the bubble.** So the
bubble has to be found first: tapping a Digimon without one open opens its
Partner window instead. If that happens anyway — you collected the token
yourself a moment earlier — the helper taps that window away again. **Only
that one.** A window is the helper's for fifteen seconds after its own tap on
a figure, and nothing else it ever sees gets closed, so a window you open
stays open. It taps the moment it sees a bubble rather than waiting for a
second look, because your character can die with the bubble up and take it
with them.

**The (A) button is a toggle.** Pressing it while Auto Spend is already
running would switch it off, so the helper never presses on a hunch. It
presses only after the counter has stood still for twenty seconds, checks the
counter again five seconds later, and waits longer before each further
attempt. At zero tickets it does not press at all: the game switches Auto
Spend off by itself when they run out, and there is nothing to spend.

The log is the point of this page. Every line names either a number it read
or the reason it did nothing:

```
  holograms 77,605, first reading
  holograms 77,595 (-10 in 5 s), auto spend is running
  bond bubble at 0.507/0.338, seen once
  bond bubble at 0.507/0.338 confirmed, tapping the figure at 0.326/0.338
    bubble gone, token collected
  holograms 77,545, unchanged for 21 s
  auto spend looks off, pressing the button
  not the plain main screen, nothing done this round
```

## Creating the templates

**The program ships with no images from the game.** Every picture the bots
match against is one you create yourself, once, from your own screen. That is
deliberate: game artwork is someone else's material and does not belong in a
published copy.

Press **Set up this bot** at the bottom right of a bot's page and a window
opens with that bot's steps and nothing else — Continue past the last one
finishes. That is the only way in from the window, on purpose. To walk every
step of every bot in one go, run `py setup_wizard.py` from a terminal. The
seven steps and who owns them:

| Step | Belongs to | What it learns | What must be on screen |
|---|---|---|---|
| Overview | the full wizard only | nothing, it shows what is present and what is missing | anything |
| Counters | World Search | digit images, from seven numbers you type in | the minigame board |
| Objects | World Search | tickets, claws, paws, fireballs | the minigame board |
| Pyramid | World Search | the pyramid obstacle | the minigame board |
| Banners | World Search | the two banner texts, in your game language | the minigame board |
| Game icon | Dungeons | what the game's icon looks like, so Helpermon can tell the emulator's home screen from the game | the emulator's home screen |
| Open cases | World Search | rare finds the bot collected while running | anything |

Worth knowing: press **Grab a new frame** after switching what is on screen.
The board steps need a board on screen.

Everything learned is stored under `userdata/`, next to the program, never in
the program folder itself. That means:

* a program update deletes nothing you taught it
* deleting `userdata/` resets the setup completely
* backing up that one folder backs up your whole setup

**Redo the setup after a skin change or a game update.** The images are crops
of what your screen looked like at the time. A new character skin, a redrawn
icon or a different UI scale makes them stop matching, and the wizard is a few
minutes' work.

Rare power-ups do not show up in a short session. The bot collects what it
cannot identify while it runs, and you label those later under **Open cases**.

## If Windows gets in the way

Helpermon reads the screen, moves the mouse and listens for a hotkey. That is
the same list of abilities as a piece of spyware, so Windows watches for it.
Everything below is Windows doing its job, not something being wrong.

| What you see | What it is | What to do |
|---|---|---|
| "Windows protected your PC" or "the publisher could not be verified" when starting `install.bat` | the internet mark on the unpacked files | unblock the ZIP as in step 2 and unpack it again, or click **More info**, **Run anyway** |
| a bot runs, the log looks right, but nothing happens in the game | LDPlayer is running as administrator and Helpermon is not. Windows lets no ordinary program send clicks or keys into an elevated window, and it reports no error for the attempt | start LDPlayer normally, without administrator. If it has to be elevated, start Helpermon elevated too. Or use ADB, which does not go through Windows input at all |
| the pause hotkey does nothing | the same cause | the same answer |
| a firewall box when ADB starts | the ADB server opens a port on your own machine | allow it for **private networks**, take the tick off **public** |
| your antivirus quarantines something | rare with the source code, since nothing here is a packaged program | exclude the Helpermon folder in your antivirus, and tell us which file it named |

There is deliberately no packaged `.exe`. A single file containing a screen
reader, an input injector and a keyboard hook is exactly the shape of thing
virus scanners are built to flag, and an unsigned one carries a SmartScreen
warning until enough people have downloaded it. The source and one `.bat` avoid
all of it, at the price of installing Python once.

## Feedback

After a run of at least a minute, a thin bar appears under that bot's
buttons: **Did this run do what you wanted?**, Yes or No, and **Tell me
more**. One click on Yes or No sends and is done — no follow-up dialog. It
shows at most once a day, and never while a bot is starting or running.

**Tell me more**, and the **Feedback** entry in the sidebar, open a small
form: what part of the program it is about, what happened, and an optional
way to reach you. **Show exactly what will be sent** expands into the exact
text before you press Send.

A report carries the version, your Windows and Python version, whether adb
was found, how long the run took, and the last 80 lines of that bot's log —
only if the box for it is ticked. **Nothing from the game screen is ever
included, not even a screenshot.** The first time you send anything, a
one-off dialog says exactly this before it goes anywhere.

If it cannot be sent, nothing is silently lost: it is written to a file
instead, and you get the choice of copying it to the clipboard or opening
the GitHub issue form. The Feedback page also opens that GitHub form
directly, and shows a button to the folder if any report is still sitting
there unsent.

## If something does not work

| Symptom | Likely cause |
|---|---|
| no emulator window found | LDPlayer is not running or is minimised |
| character not found | different character skin, relearn it in the wizard |
| bot clicks the wrong spot | the window was not in the foreground |
| list does not scroll | raise Patience on the Dungeons page |
| unknown banner text | learn text 2 in the wizard |

Pause and emergency stop are available in every bot. They take effect
between two actions, so within about a second, never in the middle of a click.

## Uninstalling

**Double-click `remove.bat`.** It asks twice, because the two halves are not
the same decision:

1. **The installation** — the `.venv` folder with the packages in it, the
   starter and the desktop shortcut. Around 400 MB, and `install.bat` puts all
   of it back in a few minutes. The shortcut is checked before it goes: one
   that points at a different copy of Helpermon is left alone.
2. **What you taught it** — the `userdata` folder and your settings. This is
   the part that cannot be downloaded again. Say no if you are reinstalling or
   moving the folder somewhere else.

What is left afterwards is text files. Delete the folder to finish; the file
cannot delete the folder it is running from. Python itself is not touched,
since other things on your machine may be using it.

## Important notice

The publisher's terms of service explicitly prohibit bots and emulators in
section 11 g. Anyone using this program risks having their game account
suspended. The decision and its consequences are yours.
