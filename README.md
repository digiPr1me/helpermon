# Helpermon

> **An unofficial fan project.** Helpermon is not made, endorsed, sponsored or
> supported by Bandai Namco, Bandai, Toei Animation, or anyone else involved in
> Digimon UP. *Digimon* and every name, character and image belonging to the
> game are the property of their owners. Nothing from the game is contained
> here; what the bots need, they learn from your own screen.

Automation tools for Digimon UP running in LDPlayer.

----------------------------------------------------------------------------------------------------------------------------------

1. DOWNLOAD IS UNDER RELEASES (to the right)
2. UNZIP AND RUN "install.bat"
3. START with "Start Helpermon.bat" or using the desktop shortcut
4. Have fun farming
5. Emerald fund: https://ko-fi.com/digipr1me <3

----------------------------------------------------------------------------------------------------------------------------------

The tool is pretty self explanatory once you start but if you need more info on how to use look at [QUICKSTART.md](QUICKSTART.md). This
document is the technical companion and mainly explains *why* things are built
the way they are.

Something not working, or an idea for what it should do next? **Issues** and
**Discussions**, and [CONTRIBUTING.md](CONTRIBUTING.md) says which one fits and
what makes a report easy to act on.

```
install.bat                finds or installs Python, builds .venv, makes a
                           desktop shortcut. The only file a player starts
                           by hand
remove.bat                 takes it back out, asking separately about the
                           installation and about what was learned
py app.py                  launcher, start here
py setup_wizard.py         setup wizard
py dungeon.py --go         dungeon bot, command line
py bot.py --go             minigame bot, command line
py learn_skewer.py         learn the skewer bot's ingredient icons, standalone
py skewer.py --go          skewer bot, command line
py skewer.py --probe       skewer bot, shows what it reads, clicks nothing
py passive.py --probe      the passive helper, shows what it reads on the
                           main screen and clicks nothing
```

## Legal notice

The publisher's terms of service explicitly prohibit bots, emulators and
similar tools in section 11 g. Anyone using this software risks having their
game account suspended. It is provided without warranty; the decision to use it
and the consequences are the user's.

Helpermon is an independent project. It is not affiliated with, endorsed by or
connected to the publisher of Digimon UP in any way, and it contains no code,
text or image material from the game. Product names and trademarks belong to
their respective owners.

## Supporter features

Most of Helpermon is free, and the bots that were free stay free. A few of
the newer ones ask for a supporter code, which comes with a donation on
Ko-fi. The code is typed in once, on the About page or when one of those
bots is started; it is checked on the machine itself, nothing is sent
anywhere, and it survives an update because it is kept with the learned
data rather than in the program folder.

The code comes back by email, to the address the donation came from -- Ko-fi
asks for one as part of the payment, so there is nothing extra to fill in and
nothing to write in the public message. It is sent by hand, so give it a day.

Giving a code back -- handing the machine on, or moving it to another one --
is a command rather than a button, in a terminal in the Helpermon folder:

    py unlock.py              what this machine has, and where it is kept
    py unlock.py --forget     give the code back and lock the features again

`--forget` prints the code once on the way out. Nothing shows it again
afterwards, so copy it before closing the window.

It is worth being straight about what that is. This is open source: the
check is a few lines of Python in `unlock.py`, and anybody who wants past
it can walk past it. It is a request, not a lock. If Helpermon saves you
an evening a week, the code is how you say so.

## No third-party image material

The `templates` and `digits` folders are empty in a published copy. Otherwise
they would contain crops taken from the game, and those do not belong in a
public repository. The wizard learns the images it needs from your own screen.

```
py release.py --check      shows what would be excluded
py release.py              builds the copy for publishing
```

This makes setup mandatory, which is intentional.

## How it is shipped, and why there is no .exe

Source code and one `.bat`. A player installs Python once, `install.bat` builds
a `.venv` beside the program and puts the packages in it.

The obvious alternative, a single packaged `.exe`, is the wrong answer for this
program in particular. Helpermon hooks the keyboard globally, injects synthetic
mouse and key input, reads the screen continuously and starts `adb.exe`. Feature
for feature that is the behaviour a virus scanner is trained to catch, and a
one-file build that unpacks itself into `%TEMP%` and runs from there completes
the picture. Being flagged would not be bad luck, it would be the expected
outcome, and the only remedy is submitting a sample to Microsoft and waiting.
On top of that an unsigned executable meets SmartScreen at every download until
it has built a reputation, and signing it properly costs a few hundred euros a
year.

None of that touches a `.py` file. Scanners do not treat source as an
executable, and pip fetches signed wheels from PyPI. The price is the Python
installation, and `install.bat` reduces that to one question.

A venv rather than `pip install --user`, which is what an earlier version did:
a venv never has to be *activated*. Activation only edits `PATH` for a shell,
and nothing here runs through a shell — the shortcut names
`.venv\Scripts\pythonw.exe` by its full path, just as it previously named the
system one. Everything that spawns a second process uses `sys.executable`, so
the wizard and the bots inherit the same interpreter automatically. The
double-click is unchanged and the packages can no longer break another project.

## Languages

The **dungeon bot** needs no templates at all. It recognises buttons by colour
and position, so it works in every game language.

The **minigame bot** needs two banner texts, and those read differently in every
language. They are therefore learned in the wizard rather than shipped. The
exclamation mark on the left of the banner is a symbol and identical in all
languages; only the text beside it changes, which is why they are two separate
images.

| Text | how it is learned |
|---|---|
| move not possible | the wizard provokes it itself by clicking diagonally next to the figure |
| resource empty | provoke it yourself, or let the bot collect it during a run |

The **skewer bot** is the opposite case: the ingredient icons are pictures, not
text, so language does not matter, but nothing about them can be derived from
colour or position the way the dungeon bot's buttons can. The twelve icons must
be learned once, against your own screen, before `skewer.py --go` has anything
to match against. `learn_skewer.py` does that, as a standalone window; it has
no page of its own in the launcher or the setup wizard, both of which cover
only the bots on the launcher's sidebar.

## Architecture

| File | Role |
|---|---|
| `app.py` | launcher: the sidebar's bots, setup status, emulator control |
| `setup_wizard.py` | learns object images, digits, banner texts |
| `engine.py` | minigame core loop, emits events instead of printing |
| `bot.py` | console front end for the minigame core |
| `gui.py` | standalone window for the same core, with every tuning knob. The launcher runs this bot itself; this is the way in for the advanced settings |
| `dungeon.py` | dungeon bot, screen recognition and reactive loop |
| `skewer.py` | skewer bot, screen recognition and reactive loop |
| `learn_skewer.py` | learns the skewer bot's ingredient icons |
| `vision.py` | calibration, object detection, digit reading, banners |
| `capture.py` | screen sources and input, window and ADB |
| `guard.py` | shared pause/abort signal and the global F7/F8 hotkeys |
| `planner.py` | picks one next action, priced in Bits |
| `router.py` | Dijkstra pathfinding over the visible board |
| `world.py` | global map, scroll offset, position bookkeeping |
| `actions.py` | clicks and verifies against the counters |
| `tracker.py` | plausibility checks on counter values |
| `learning.py` | learning logic behind the wizard |
| `userdata.py` | where learned data is stored, and the settings two processes share |
| `widgets.py` | Tk pieces more than one window needs: the ADB switch and the log box |
| `feedback.py` | builds a feedback report and sends it to Discord, or saves it locally if that fails |
| `version.py` | the one place the version number is written down |
| `ldplayer.py` | starts the emulator and the game, LDPlayer only, needs ADB for the package name |
| `launcher.py` | starts the game by finding and clicking its icon, any emulator, no ADB |
| `release.py` | builds a copy without game-derived images |
| `install.bat` | double-click installer: Python, `.venv`, packages, desktop shortcut |
| `remove.bat` | uninstaller. Two questions, because the packages and the learned images are not the same decision |
| `make_shortcut.py` | writes the starter and the desktop shortcut |
| `.github/ISSUE_TEMPLATE/` | the two issue forms and the links beside them. The URLs in `config.yml` carry a placeholder owner that has to be replaced once |

Diagnostics: `bench.py`, `calibrate.py`, `counters_probe.py`, `dump_rois.py`,
`figure_probe.py`, `find_adb.py`, `grab_screen.py`, `learn_digits.py`,
`selftest.py`, `watch_mode.py`.

Offline test suites, no emulator needed:

```
py test_world.py           scroll model, boundaries, bookkeeping
py test_planner.py         decisions on constructed boards
py test_router.py          pathfinding on text boards
py test_verify.py          action verification
py test_pace.py            adaptive pacing
py test_capture.py         all screen sources share one interface
py test_dungeon_flow.py    dungeon loop and dungeon selection
py test_skewer_flow.py     skewer loop, undo/mismatch, round-end
py test_wake_flow.py       every screen that ever stopped a cold start
py test_launcher.py        icon learning, waiting for the emulator
py test_guard.py           the pause flag, the hotkeys, and that no bot
                           watches the mouse any more
py test_learning.py        wizard logic against saved screenshots
py test_feedback.py        building a report, and the two ways it can leave
                           the machine
```

## Guiding principle

Never trust a single frame, and never click blindly. Every action is verified
against something independent, and if the expected change does not appear the
bot re-reads the screen instead of clicking again. Most bugs found during
development were violations of exactly that rule.

---

## Design notes and measurements

Every threshold below was measured, not guessed. Several first attempts failed
and are recorded here because the failure is the useful part.

### Calibration without fixed pixel values

Anchor chain: find the light grey card as the largest bright desaturated
contour, fit the column grid periodically onto the vertical edge profile, then
fit rows with the cell aspect ratio forced.

Cells are **not** square, measured about 87 x 72 pixels, ratio 1.22. An early
plausibility check demanded squareness and rejected valid calibrations.

The geometry is averaged over the first few good frames and then frozen. A
single unlucky frame had pushed cell height to 130.9 instead of 134.7.

### Finding objects

A colour pre-filter runs before template matching. The board is uniformly blue,
every power-up is strongly orange, green, pink or yellow. Measured share of
saturated pixels: power-ups 4 to 9 percent, empty tiles and pyramids 0. Board
reading dropped from 156 ms to 27 ms.

An earlier attempt used the dark glow every power-up sits on. That failed,
measured values overlap completely with empty tiles.

### Finding the character

Measured with the **Botamon** skin throughout, and the numbers below are that
skin's. Another one is not ruled out, but nothing here has been tried against
it: the body signature is a share of dark desaturated pixels, which is a
property of how that figure is drawn. A skin that misses the thresholds costs
the run; a skin that meets them by accident, somewhere else on the board, costs
more, because then the bot walks confidently in the wrong direction.

Four stages: optional colour mask, body signature, template matching, eye pair.

The body signature is the share of dark desaturated pixels per cell, measured 15
to 19 percent for the figure against below 1.3 percent for everything else. It
became necessary after a real failure: a template hit sat correctly but scored
only 0.505 against a required 0.62 because an orange ticket next to it changed
the surroundings. The eye-pair fallback then mistook that ticket's flash for a
pair of eyes and reported a column too far left.

### Reading numbers

One shared digit set, compared by bitmap overlap rather than correlation. A
match needs 0.82 coverage plus a margin over the runner-up; uncertain yields
`None` and is never guessed. Validated against 58 known values, zero wrong.

The digits are identical top and bottom, only the polarity differs. An early
version used a dark threshold of 100 for the bottom bar, which captured only the
core of each glyph and forced a second, chronically undersized digit set.

An unreadable counter returns `None` and never 0, otherwise a read error would
look like consumption.

### Pathfinding, cost search instead of rules

`router.py` runs Dijkstra over the 25 visible cells.

| Edge | Bits |
|---|---|
| step | paw plus action value, 40 + 40 |
| entering a pyramid cell | plus claw plus action minus loot, 215 |
| step left | surcharge 20, allowed but not free |
| row | small bias per row away from the centre, only breaks ties |

The desired behaviours follow from the arithmetic rather than being coded
individually: detour instead of claw because two steps cost 160 against 215,
dodge towards the centre row, step left when genuinely cheaper, destroy only as
a last resort. Seven special-case methods in the planner became unnecessary.

### Shop prices

50 paws cost 2,000 Bits, one claw 200, one fireball 400. So one paw is 40 Bits.
The fireball takes three columns in one action and collects what it uncovers,
but it is expensive: it only pays off when detours are impossible.

`--bit-per-action` prices a saved action, default 40, which reflects "items per
minute" rather than pure resource saving. `--bit-pyramid-loot` estimates what
sits under a pyramid; loot found that way is worth much less than loot found
freely.

### Verification, evidence instead of exact deltas

Checking for an exact delta does not work. A step costs one paw but may collect
a power-up in the same moment, making the delta +4 instead of −1. Instead: if
any counter moved plausibly, the action happened; if none moved, check for a
banner; if still nothing, re-read.

Counters are merged over three frames because a single frame may fall inside an
animation.

`tracker.py` checks values against game rules and re-syncs itself: the same
implausible value three times in a row is the truth and the stored value is
stale. Without that the meter counter got stuck and reported "+9" for thirteen
actions straight.

### Speed

Measured per screenshot: ADB PNG about 430-470 ms, ADB raw a little faster,
window capture about 9 ms. ADB is the default anyway: a window capture can go
wrong in ways that cost nothing and say nothing, see "One switch for screen
and clicks" below. `capture.AdbCapture` benchmarks raw against PNG once per
machine and keeps the faster one; the result is cached so later starts do not
pay for the measurement again.

Pacing is adaptive. All wait times hang off one factor; after three clean
actions it shrinks by 10 percent, a retry nudges it back slightly, a real
failure resets it. Floor is 0.6, because below roughly 0.24 s per tick the game
cannot keep up.

### Dungeon bot, recognition without any game images

Buttons separate unambiguously by colour and horizontal position, measured
across two window sizes.

| Element | Colour | rel. x | width |
|---|---|---|---|
| Attempt | blue | 0.66, or 0.50 when alone | 0.30 |
| Find a Party | blue | 0.50 | 0.28 |
| Clear Previous Difficulty | violet | 0.34 | 0.30 |
| Ad | violet | 0.50 | 0.62 |
| List card | blue | 0.49 | 0.77 |

The emulator's title bar is computed away from the fixed 1080:1920 device
aspect, not detected.

Several traps were found only in real runs:

* The ad button is about 7:1 wide; an aspect limit of 6 made whole dialogs
  unrecognisable
* The violet range started at hue 125 while the buttons measure 122 to 125, so
  the same button was found or missed depending on the frame
* Game artwork during a battle looks like the Attempt button at 0.681/0.698 with
  matching size. Battles are therefore detected first, via the Give Up button at
  the very bottom, and nothing is tapped while one is running
* Apocalymon Wall shows a results window whose Close button sits almost exactly
  where its Attempt button is. They are told apart by width, 0.216 against 0.261
  to 0.301

### Skewer bot, two recognition strategies on one screen

The cooking minigame is read in two quite different ways, on purpose.

The **4x3 ingredient grid** is fixed and unscaled, so it is matched at fixed
relative positions by straight template correlation against the learned icons.
Solid, matches come back 0.9 to 1.0.

The **order strip and the plate** have no fixed icon count, no fixed spacing
and no fixed position: a short order spreads its ingredients along the stick, a
long one packs them until they overlap. Nothing positional works there, and
threshold-based matching failed in both directions. Against a real five-icon
order the five correct icons scored 0.87 / 0.80 / 0.93 / 0.80 / 0.86 against a
cutoff of 0.80 — two of them sitting exactly on it, and an icon that dips a
hundredth under is silently dropped, which is the "an ingredient got skipped"
bug seen live. Lowering the cutoff is not a fix either: at a neighbouring window
size a phantom `tuna` scored 0.82, above it. There is no setting that neither
drops real icons nor invents absent ones.

So the strip is read in two stages, with **no match threshold anywhere**:

1. **Find the icons geometrically.** Inside the white speech bubble or plate, a
   column carrying an icon has more non-background pixel height than one
   carrying only the bare wooden stick. Measured on a real five-icon capture:
   bare stick 17 to 23 px, icon columns 24 to 55 px, no overlap. The background
   level is measured per container, never assumed — the bubble is pure white at
   255 while the plate only reaches 236.
2. **Name each one by argmax** over all twelve candidates. argmax cannot drop
   an icon, because something is always the best match, and cannot invent one,
   because positions come from pixels rather than scores. Only the ranking
   matters, absolute scores stop mattering.

Icons are compared by masked colour signature, not by correlation: the same
ingredient appears on a dark grid button and on a white plate, and
`TM_CCOEFF_NORMED` between those two scores near zero even when it is plainly
the same thing. Masking the background away scored five real icons 0.97 / 0.90
/ 0.68 / 0.61 / 0.96 against their correct templates, each a clear winner over
its runner-up at 0.43 / 0.19 / 0.42 / 0.33 / 0.47, which is all argmax needs.

Two failures worth keeping: detecting the black outline between icons was tried
first and does not work, because pale ingredients have outlines as thin as the
stick reads and dark ones are dark right through the middle. And deriving the
icon count by classification instead of geometry got it right on only four of
seven captures.

**Open assumption.** The icon pitch, 36 to 38 px in a 650 px crop, was measured
across seven captures that are all five-ingredient orders. Whether the game
keeps the icons the same size and lengthens the skewer, or keeps the skewer the
same length and shrinks the icons, is not distinguishable from that data. If it
is the second, a long order reads as a five. Probe a clearly shorter and a
clearly longer order before trusting it. Details and the numbers are in the
`SKEWER_*` comment block in `skewer.py`.

The round is 60 s and scored by meals served, so the click loop is tuned for
speed over caution: two agreeing reads to settle instead of the three used
elsewhere. Full pace is 330 ms per click. It was 180, and that turned out to
be reaching for a grid the emulator had not finished redrawing — which costs
an order rather than saving time — so the pace was cut to 55 % of it.

Recognising a frame costs about 21 ms, so all but a twentieth of each click is
spent waiting on purpose, which is why `--speed` divides the waits and there is
nothing to win by making recognition faster. It deliberately does not touch
`--patience`, which governs waits for the *game* to do something; an earlier
version divided those too and made the bot act on half-drawn orders.

### Two confirmation dialogs, opposite answers

| Dialog | Correct answer | Why |
|---|---|---|
| Exit the game? | Cancel | OK closes the game |
| Disband the party and leave? | OK | Cancel keeps the bot trapped in the dialog |

Assuming Cancel is always safe was a design error; the party dialog appeared
four times in a row because of it. The two are told apart by the left button:
grey with saturation 79 for the exit dialog, pink with 130 for the party one.

Related cause: tapping anywhere while a party exists acts like the back key and
opens that dialog. Rewards are therefore tapped away high up, above any dialog.

### The back key is dangerous

It is used to close dialogs. With no dialog open, Android leaves the game and
shows "Exit the game?". That is exactly how the bot ended up there. It is now
pressed only when a dialog is actually open.

### Party detection

The Network Defense Ops dialog looks identical with and without a party, both
buttons in the same place. An Attempt without team-mates does nothing; six such
clicks were once logged as six battles. The three party slots tell them apart:
an empty slot is a flat dark area with standard deviation 0.0, an occupied one
shows a figure at 28 to 48.

### Ads

Two ads per dungeon per day, each granting one ticket. An ad that yields no
ticket will not yield one next time either; the game then reports "Ad viewing
limit reached". Detected by the ad button reappearing instead of Attempt. An
earlier abort condition was exactly inverted and allowed further ads as long as
no battle materialised, producing six ads and zero battles.

### Pre-check, which dungeons still have attempts

Read from the list rather than by opening each dialog. Digit recognition failed
here, six of nine correct, because the font differs. It is not needed: only
whether the leading digit is a zero matters, and zero is the only digit with a
hole in the middle, measured 0.00 against 0.33 to 0.93.

The ad counter beside it is drawn over artwork rather than in a dark box and
cannot be read reliably; measured 0.20 against 0.57 separates, but with only
0.05 of margin. So the outcome is three-way: tickets left means play, zero
tickets with no ad counter means skip, zero tickets with an ad counter means
unknown and gets tried. Being wrong here would cost a whole dungeon per day.

### Two-phase plan against playing a dungeon twice

The bot counts cards instead of reading names, which would be text recognition
and would break on every game update. The list is longer than the window, so the
number of cards visible at the bottom tells it how many to play from the top for
the two views to complement each other exactly.

### One switch for screen and clicks

Two operating modes, not three. One switch, at the top of every window a bot
runs in, picks between them for frames *and* clicks together:

| Switch | Frames | Clicks | Trade-off |
|---|---|---|---|
| ADB (default) | ADB | ADB | ~400 ms per frame. The window may sit behind other windows, be minimised, and colour is unaffected by night light or an HDR profile |
| off | screen capture | `pydirectinput` | ~9 ms per frame, but the window must stay visible, unobscured and in the foreground, and the screen must not sleep |

There used to be a third way, frames from the window with clicks via ADB,
kept because a window capture is far faster than an ADB one. It needed a
coordinate conversion between window pixels and device pixels, and it
rested on an assumption that turned out not to hold: that a window capture
fails only when the window is not in the foreground. Measured directly
(two Tk windows of a known colour, the same `mss` `capture.WindowCapture`
uses): a window that is merely unfocused is captured correctly, but one
*obscured* by another window returns that other window's picture instead,
and a *minimised* one returns black with no error anywhere. Night light or
any colour profile tints every frame, and every threshold in `dungeon.py`
is a threshold on colour. ADB does not have any of those failure modes and
stays fresh while the window is minimised.

So there is no silent fall back from ADB to the window any more, in either
direction: with the switch on, a run that cannot reach ADB stops and says
so (`capture.require_adb`) rather than quietly reading a stale or wrong
picture. The switch itself is a file in the data folder, the same pattern
as the one the mouse-movement pause used to have, because the launcher, the
setup wizard and a bot started from a console are separate processes and a
switch that reached only one of them would look broken.

Without ADB, clicks go through `pydirectinput`, swipes are a held mouse
moved in about twelve steps, and back is Escape. Both screen sources expose
the same `grab`, `tap`, `swipe`, `back`, `focus` and a `moves_mouse` flag,
checked by `test_capture.py`, because the bots used to reach through to ADB
directly in several places.

### One vocabulary for two kinds of frame

Every relative position in `dungeon.py` is a fraction of the *window image*,
because that is what they were measured on -- and LDPlayer's 40 px tab bar and
43 px sidebar are inside all of them. An ADB frame has neither, so the same
fraction means a different place.

The chrome is a fixed pixel size and does not scale with the window, measured
at two sizes against ADB: the game sits at 4, 40 and is 758 x 1348 in an
805 x 1390 window, and 572 x 1017 in a 619 x 1059 one. So a fraction of the
window image is only worth something once the window has been measured -- at
619 wide, reading it as if the window were still 805 lands 18 device pixels
out.

`game_rect` is the single place that knows this. It hands every frame back the
same reference window: an ADB frame gets one larger than itself, starting
above and to the left; a window frame gets its chrome taken off and the rest
stretched back to the reference. Nothing else in the file divides by the frame
size.

### One bot, one setup window

Every bot is set up from its own page, with the button at the bottom right,
and that window carries that bot's steps and no others: Continue past the last
one finishes. There used to be one shared Setup page and one wizard behind it
that walked through all eight steps in a row, so setting up the Night Market
carried you on into the World Search's four with nothing saying you had left
what you came for.

Nothing in the window offers all eight steps any more, which is the point. The
full sequence still exists for the two things no single bot owns, the overview
and Diagnostics, and is reached by running `py setup_wizard.py`.

### Saying what a bot needs

Each bot has a short list of things that have to be true before it can do
anything -- the game open, Digimon UP on its plain main screen, the Night
Market at its own main menu. They are kept in one table in `app.py` and shown
twice: in a box near the top of the bot's page, and in a dialog the first time
that bot is started. Every line in that list is a way for a bot to sit there
achieving nothing while looking busy, which is not a thing to leave in a
README.

The first dialog of all is about how Helpermon reaches the emulator, before
the legal notice, because that is the choice that decides whether the next
hour is spent with the mouse or without it. ADB debugging has to be switched
on in LDPlayer, under Settings, Other settings; the dialog says so and then
offers a button that asks ADB whether it answers, so nobody has to wonder
whether it took.

It also says the thing that is easy to meet and hard to explain afterwards:
LDPlayer puts up an error of its own when a lot is driven through ADB in one
sitting. That is the emulator complaining, not the game.

### The mouse-movement pause, and why it is gone

A bot that drives the real mouse and a person who wants their mouse back is a
conflict the bot has to lose, so `guard.py` used to watch the cursor and pause
on any movement it had not made itself, going on again a few seconds after the
mouse went still.

It was built for the mode where the bot drives the cursor, and it watched in
every mode. ADB is the default now, and there the bot never puts a hand on the
mouse: every movement is somebody using their own machine, and the pause fired
at all of them. A dungeon run reads like this --

```
21:12:14      mouse moved, pausing
21:12:53      mouse still for 3 s, resuming
21:12:53    resuming, checking the screen first
21:12:55      mouse moved, pausing
```

-- three seconds of stillness demanded, and the screen re-read every time,
between two attempts of a bot that was not touching the mouse at all. The
checkbox for it had already been taken out of every window, because a switch
offering to turn off the one thing that gets a hand out from under a running
bot is an invitation rather than a setting; so by then there was nothing left
anywhere that could stop it either.

The watcher is gone, and with it `userdata.mouse_pause`, `DGUP_MOUSE_PAUSE`
and `WindowCapture.last_bot_move`, the timestamp whose only reader it was.
What is left is F7 and F8: the pause is something a person asks for now.
Without ADB, that means the mouse belongs to the bot until you press F7, and
the dialogs say so. `test_guard.py` asserts the watcher stays gone, rather
than only that it is absent today.
