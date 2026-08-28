# Taking part

Helpermon is written and maintained by one person. That shapes what is useful
to send and what will simply sit there, so it is worth saying plainly.

## Reporting something that does not work

Open an **Issue**. The form asks for the things that decide whether a report
can be acted on:

* **which bot**, because the three of them share almost no code
* **a dry-run log.** Every bot page has a **Dry run** button under *For
  testing*. It plans everything and clicks nothing, so it is safe to run at
  any moment, and it shows what the bot believed it was looking at. A
  description says what happened; a dry run says why
* **ADB or mouse input**, from the first dialog. Nearly every "it does nothing"
  report turns on this one answer
* **the version**, from the About page

For the Night Market bot there is a second one: press **Diagnostics**. It reads
the current screen once, names every ingredient it thinks it sees, and writes
the crops it read from into `debug_skewer/`. An icon that names itself wrongly
there is the whole bug, visible in one line.

Screenshots are welcome in an issue, including ones with the game on them.

## Ideas

Also an **Issue**, with the other form. If it is not a request yet — a "would
it be possible to", a "how do you all handle X" — open a **Discussion**
instead. A discussion that turns into a plan becomes an issue afterwards.

The most useful thing an idea can carry is what you do **by hand** today.
Knowing the manual routine usually shows whether the feature as written is
really the shortest way there.

## Questions

**Discussions.** They need no form and no version number, and other people can
find the answer afterwards, which is not true of a chat message.

## Changing the code

Pull requests are welcome, and small ones are easier to accept than large ones.
Four house rules, each of which exists because breaking it cost a working day:

1. **Run the test suites.** They need no emulator and take seconds. In
   PowerShell:

   ```
   Get-ChildItem test_*.py | ForEach-Object { py $_.Name }
   ```

   By pattern rather than by name, so a suite added later is picked up
   without anybody having to remember this file. Every one of them has to
   say it passed.

2. **No image material from the game, ever.** No screenshots, no crops, no
   `calib.json`. `py release.py --check` refuses to build if any of it
   would ship. `templates/` and `digits/` are the one exception, and only
   because a published copy is unusable without them: they are what the
   board bots read the screen with.

3. **Never trust a single frame, and never click blindly.** State changes are
   confirmed across two frames and every action is verified against something
   independent. Most bugs found so far were violations of exactly that.

4. **Measure thresholds, do not guess them.** Print the numbers, put them in
   the commit message or a comment, and pick from the numbers. The README's
   design notes are full of first attempts that looked reasonable and did not
   survive contact with a real screen.

Code, comments and program output are in English.

## What Helpermon will not do

It plays parts of a game that its publisher's terms of service say may not be
automated — section 11 g. That is stated in the README, in the licence file and
in a dialog on first launch, and it is not going to be softened.

Anything aimed at making that harder to notice — hiding the program from the
game, imitating human timing to defeat detection, working around an account
ban — is out of scope, and a pull request doing it will be closed rather than
discussed.
