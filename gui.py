"""
Window for the minigame bot. Built on engine.run, the same core the console
uses, so there is no second copy of the logic.

  py gui.py

Needs no extra packages, tkinter ships with Python.

The first launch shows a large reminder to check the character skin, because
recognition is tuned to the skin the figure was learned from and a different
one makes the bot fail at startup. Everything here was measured with Botamon.
"""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import engine
import planner as planner_mod
import widgets
import world as world_mod

_APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
SETTINGS_FILE = os.path.join(_APPDATA, "helpermon_minigame.json")
# What this file was called before the program was named. Read once if the
# new one is not there, so the rename costs nobody their settings.
OLD_SETTINGS_FILE = os.path.join(_APPDATA, "digibot_gui.json")

# The item names live beside the items themselves, in world.WANTED_LABEL,
# so that renaming one is a single line rather than the same line in two
# windows. This file used to carry its own copy of that table.
COUNTER_LABEL = {"paws": "paws", "claws": "claws", "fireballs": "fire",
                 "meters": "metres", "top_orange": "orange",
                 "top_green": "green", "top_pink": "pink"}


# ----------------------------------------------------------------------------
class SkinReminder(tk.Toplevel):
    """A large reminder before the start.

    Recognising the figure is tuned to the skin it was learned from. With a
    different one the bot does not find the figure and stops at startup, or
    worse, finds something else and steers by it. That is the commonest
    avoidable mistake, which is why this stands at the front rather than in
    a footnote.
    """

    def __init__(self, master):
        super().__init__(master)
        self.title("Before you start")
        self.resizable(False, False)
        self.configure(padx=28, pady=24)
        self.transient(master)
        self.grab_set()

        tk.Label(self, text="Check the character skin in the game",
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(self, justify="left", font=("Segoe UI", 11),
                 text=("This bot was built and measured with the Botamon "
                       "skin.\n\n"
                       "Another skin may work. It may also make the bot miss "
                       "the figure\nand steer by something else, and it will "
                       "not always say so.\n\n"
                       "So pick the skin the figure was learned from before "
                       "going on.")
                 ).pack(anchor="w", pady=(10, 16))

        row = tk.Frame(self)
        row.pack(fill="x")
        self.dont_show = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="do not show again",
                       variable=self.dont_show).pack(side="left")
        tk.Button(row, text="Skin is right, continue", width=20,
                  command=self.destroy).pack(side="right")
        self.bind("<Return>", lambda _e: self.destroy())


# ----------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Helpermon - minigame")
        self.geometry("980x620")
        self.minsize(880, 560)

        self.events = queue.Queue()
        self.stop = engine.Stop()
        self.worker = None
        self.vars = {}
        self.conf = self._load()

        self._build()
        # Tastenkuerzel, damit man nicht ins Fenster klicken muss
        self.bind("<space>", lambda _e: self._shortcut_pause())
        self.bind("<Escape>", lambda _e: self._shortcut_stop())
        self.after(80, self._pump)
        if not self.conf.get("skin_hint_off"):
            self.after(120, self._skin_reminder)

    # ------------------------------------------------------------------
    def _skin_reminder(self):
        dlg = SkinReminder(self)
        self.wait_window(dlg)
        if dlg.dont_show.get():
            self.conf["skin_hint_off"] = True
            self._save()

    # ------------------------------------------------------------------
    def _build(self):
        # This window has no header of its own, so it gets a thin one for the
        # same reason the other two have the switch top right: it belongs in
        # the same place wherever you are when a run starts.
        head = tk.Frame(self, padx=12, pady=6)
        head.pack(fill="x")
        widgets.AdbSwitch(head).pack(side="right")

        left = tk.Frame(self, padx=12, pady=10)
        left.pack(side="left", fill="y")
        right = tk.Frame(self, padx=12, pady=10)
        right.pack(side="right", fill="both", expand=True)

        # Einsammeln
        tk.Label(left, text="Collect", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        box = tk.Frame(left)
        box.pack(anchor="w", pady=(2, 10))
        for i, key in enumerate(world_mod.ALL_WANTED):
            var = tk.BooleanVar(value=key in self.conf.get("wanted", world_mod.ALL_WANTED))
            self.vars["want_" + key] = var
            tk.Checkbutton(box, text=world_mod.wanted_label(key),
                           variable=var).grid(row=i // 2, column=i % 2,
                                              sticky="w")

        self._spin(left, "Limits", "min_paws", "Stop at paws", 20, 0, 9999)
        self._spin(left, None, "max_actions", "Max actions, 0 for none", 0, 0, 99999)
        self._spin(left, None, "target_meters", "Metre target, 0 for none", 0, 0, 999999)

        tk.Label(left, text="Tempo", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(10, 0))
        var = tk.BooleanVar(value=self.conf.get("adaptive", True))
        self.vars["adaptive"] = var
        tk.Checkbutton(left, text="self-regulating", variable=var).pack(anchor="w")
        frm = tk.Frame(left)
        frm.pack(anchor="w", fill="x")
        tk.Label(frm, text="min").pack(side="left")
        self.vars["min_pace"] = tk.DoubleVar(value=self.conf.get("min_pace", 0.60))
        tk.Scale(frm, from_=0.4, to=1.0, resolution=0.05, orient="horizontal",
                 variable=self.vars["min_pace"], showvalue=True,
                 length=140).pack(side="left")

        tk.Label(left, text="Cold start", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(10, 0))
        var = tk.BooleanVar(value=self.conf.get("autostart", False))
        self.vars["autostart"] = var
        tk.Checkbutton(left, text="Start LDPlayer and the game",
                       variable=var).pack(anchor="w")
        self._spin(left, None, "wait_for_board", "Wait for board, seconds", 180, 0, 900)

        # Erweitert, zugeklappt
        self.adv_open = False
        self.adv_btn = tk.Button(left, text="Show advanced", width=24,
                                 command=self._toggle_adv)
        self.adv_btn.pack(anchor="w", pady=(12, 2))
        self.adv = tk.Frame(left)
        self._spin(self.adv, None, "click_delay", "Base tick, s", 0.7, 0.1, 5.0, True)
        self._spin(self.adv, None, "settle", "Wait time, s", 0.45, 0.1, 3.0, True)
        self._spin(self.adv, None, "row_slack", "Row change buffer",
                   planner_mod.ROW_SLACK, 0, 4)
        self._spin(self.adv, None, "bit_per_action", "Bits per saved action",
                   planner_mod.BIT_PER_ACTION, 0, 500)
        self._spin(self.adv, None, "bit_pyramid_loot", "Loot under a pyramid",
                   planner_mod.BIT_PYRAMID_LOOT, 0, 500)
        self._spin(self.adv, None, "bit_paw", "Price of a paw", planner_mod.BIT_PAW, 1, 999)
        self._spin(self.adv, None, "bit_claw", "Price of a claw", planner_mod.BIT_CLAW, 1, 9999)
        self._spin(self.adv, None, "bit_skill", "Price of a fireball",
                   planner_mod.BIT_SKILL, 1, 9999)

        # rechte Seite, Status
        self.status = tk.Label(right, text="ready", anchor="w", fg="#444")
        self.status.pack(fill="x")

        tiles = tk.Frame(right)
        tiles.pack(fill="x", pady=(6, 4))
        self.tiles = {}
        for i, (key, cap) in enumerate([("position", "Position"), ("meters", "Meter"),
                                        ("actions", "Actions"), ("pace", "Tick (pace)")]):
            cell = tk.Frame(tiles, bd=1, relief="solid", padx=8, pady=4)
            cell.grid(row=0, column=i, sticky="ew", padx=2)
            tiles.columnconfigure(i, weight=1)
            tk.Label(cell, text=cap, fg="#777", font=("Segoe UI", 8)).pack(anchor="w")
            lab = tk.Label(cell, text="-", font=("Segoe UI", 12, "bold"))
            lab.pack(anchor="w")
            self.tiles[key] = lab

        cnt = tk.Frame(right)
        cnt.pack(fill="x", pady=(0, 6))
        self.counters = {}
        for i, key in enumerate(["paws", "claws", "fireballs", "top_orange",
                                 "top_green", "top_pink"]):
            lab = tk.Label(cnt, text="%s -" % COUNTER_LABEL[key], bd=1,
                           relief="solid", padx=6)
            lab.grid(row=0, column=i, sticky="ew", padx=2)
            cnt.columnconfigure(i, weight=1)
            self.counters[key] = lab

        self.log = tk.Text(right, height=18, wrap="none", font=("Consolas", 9))
        scroll = tk.Scrollbar(right, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set, state="disabled")
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ok", foreground="#1a7f37")
        self.log.tag_configure("warn", foreground="#b3261e")
        self.log.tag_configure("dim", foreground="#777")

        btns = tk.Frame(right, pady=8)
        btns.pack(fill="x")
        self.b_calib = tk.Button(btns, text="Check calibration",
                                 command=self._check_calib)
        self.b_calib.pack(side="left")
        tk.Button(btns, text="Set up", command=self._open_wizard).pack(
            side="left", padx=6)
        self.b_dry = tk.Button(btns, text="Dry run",
                               command=lambda: self._start(dry=True))
        self.b_dry.pack(side="left", padx=6)
        self.b_stop = tk.Button(btns, text="Emergency stop", state="disabled",
                                command=self._panic)
        self.b_stop.pack(side="right")
        self.b_pause = tk.Button(btns, text="Pause", state="disabled",
                                 command=self._toggle_pause)
        self.b_pause.pack(side="right", padx=6)
        self.b_go = tk.Button(btns, text="Start", command=lambda: self._start(dry=False))
        self.b_go.pack(side="right", padx=6)

    def _spin(self, parent, header, key, label, default, lo, hi, floaty=False):
        if header:
            tk.Label(parent, text=header, font=("Segoe UI", 9, "bold")).pack(
                anchor="w", pady=(10, 0))
        row = tk.Frame(parent)
        row.pack(anchor="w", fill="x")
        tk.Label(row, text=label, width=20, anchor="w").pack(side="left")
        var = (tk.DoubleVar if floaty else tk.IntVar)(
            value=self.conf.get(key, default))
        self.vars[key] = var
        tk.Spinbox(row, from_=lo, to=hi, textvariable=var, width=7,
                   increment=0.05 if floaty else 1).pack(side="left")

    def _toggle_adv(self):
        self.adv_open = not self.adv_open
        if self.adv_open:
            self.adv.pack(anchor="w", fill="x")
            self.adv_btn.configure(text="Hide advanced")
        else:
            self.adv.pack_forget()
            self.adv_btn.configure(text="Show advanced")

    # ------------------------------------------------------------------
    def _settings(self, dry):
        is_selected = [k for k in world_mod.ALL_WANTED if self.vars["want_" + k].get()]
        return engine.Settings(
            dry_run=dry, is_selected=is_selected or list(world_mod.ALL_WANTED),
            max_actions=self.vars["max_actions"].get(),
            min_paws=self.vars["min_paws"].get(),
            target_meters=self.vars["target_meters"].get(),
            click_delay=self.vars["click_delay"].get(),
            settle=self.vars["settle"].get(),
            min_pace=self.vars["min_pace"].get(),
            adaptive=self.vars["adaptive"].get(),
            autostart=self.vars["autostart"].get(),
            wait_for_board=self.vars["wait_for_board"].get(),
            bit_paw=self.vars["bit_paw"].get(),
            bit_claw=self.vars["bit_claw"].get(),
            bit_skill=self.vars["bit_skill"].get(),
            bit_per_action=self.vars["bit_per_action"].get(),
            bit_pyramid_loot=self.vars["bit_pyramid_loot"].get(),
            row_slack=self.vars["row_slack"].get())

    def _start(self, dry):
        if self.worker and self.worker.is_alive():
            return
        self._save()
        self.stop.clear()
        settings = self._settings(dry)
        self._write("\n%s gestartet, gesucht %s"
                    % ("Dry run" if dry else "Echter Lauf",
                       ", ".join(settings.is_selected)), "dim")
        for b in (self.b_go, self.b_dry, self.b_calib):
            b.configure(state="disabled")
        self.b_stop.configure(state="normal")
        self.b_pause.configure(state="normal", text="Pause")
        self.status.configure(text="laeuft" + (", Trockenlauf" if dry else ""))

        def job():
            try:
                engine.run(settings, self.events.put, self.stop)
            except Exception as err:  # damit ein Fehler im Fenster landet
                self.events.put({"art": engine.WARN, "text": "Error: %s" % err})
                self.events.put({"art": engine.STOPPED, "grund": "Fehler",
                                 "aktionen": 0, "dauer": 0, "counters": {},
                                 "position": "", "tempo": 1.0})

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _toggle_pause(self):
        """Pause haelt nach der laufenden Aktion. Beim Weitermachen liest der
        Kern Position, Brett und Zaehler neu ein, weil du in der Pause selbst
        gespielt haben koenntest."""
        paused = self.stop.toggle_pause()
        self.b_pause.configure(text="Continue" if paused else "Pause")
        self.status.configure(text="paused" if paused else "laeuft")
        self._write("    %s" % ("paused" if paused else "weiter"), "dim")

    def _shortcut_pause(self):
        if str(self.b_pause["state"]) != "disabled":
            self._toggle_pause()

    def _shortcut_stop(self):
        if str(self.b_stop["state"]) != "disabled":
            self._panic()

    def _panic(self):
        self.stop.request("Emergency stop")
        self.status.configure(text="Not-Aus, haelt nach der laufenden Aktion")

    def _open_wizard(self):
        """Assistent in einem eigenen Prozess starten, damit ein Fehler dort
        das Hauptfenster nicht mitnimmt."""
        import noconsole
        import sys
        try:
            noconsole.popen([sys.executable, "setup_wizard.py"],
                            cwd=os.path.dirname(os.path.abspath(__file__)))
            self._write("Assistent gestartet", "dim")
        except Exception as err:
            self._write("Assistent nicht startbar, %s" % err, "warn")

    def _check_calib(self):
        self._write("\nKalibrierung wird geprueft", "dim")

        def job():
            import cv2
            import vision
            try:
                cap = engine.open_capture(engine.Settings())
                img = cap.grab()
                calib = vision.calibrate(img)
                tpl = vision.load_templates()
                grid, _ = vision.read_grid(img, calib, vision.board_templates(tpl))
                fig = vision.find_figure(img, calib, tpl)
                counters = vision.read_counters(img, calib)
                os.makedirs("debug", exist_ok=True)
                path = os.path.join("debug", "calib_overlay.png")
                cv2.imwrite(path, vision.draw_overlay(img, calib, grid, fig, counters))
                self.events.put({"art": engine.INFO,
                                 "text": "Zelle %.2f x %.2f, Figur %s, Debugbild %s"
                                 % (calib["cell_w"], calib["cell_h"],
                                    fig and "Zeile %d Spalte %d" % (fig["row"] + 1,
                                                                    fig["col"] + 1),
                                    path)})
                self.events.put({"art": "counters_only", "counters": counters})
                if fig is None:
                    self.events.put({"art": engine.WARN,
                                     "text": "Figur nicht gefunden. Stimmt der "
                                             "Figur-Skin im Spiel?"})
            except Exception as err:
                self.events.put({"art": engine.WARN, "text": "Error: %s" % err})

        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------------
    def _pump(self):
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            self._handle(ev)
        self.after(80, self._pump)

    def _handle(self, ev):
        kind = ev["art"]
        if kind == engine.INFO:
            self._write("    " + ev["text"], "dim")
        elif kind == engine.WARN:
            self._write("    " + ev["text"], "warn")
        elif kind == engine.SETUP:
            self._write("Aufnahme %s, %s" % (ev["capture"], ev["text"]))
            self._counters(ev["counters"])
        elif kind == "counters_only":
            self._counters(ev["counters"])
        elif kind == engine.PLANNED:
            self._write("#%d  %s  ->  %s" % (ev["nr"], ev["position"], ev["aktion"]))
            self.tiles["actions"].configure(text=str(ev["nr"]))
        elif kind == engine.RESULT:
            deltas = ", ".join("%s %+d" % (COUNTER_LABEL.get(k, k), v)
                               for k, v in ev["deltas"].items())
            tag = "ok" if ev["zustand"] in ("ok", "dry_run") else "warn"
            self._write("    %s  %s" % (ev["zustand"], deltas or "no change"), tag)
            self._counters(ev["counters"])
            # Kachel zeigt den Takt in Sekunden, in Klammern den Tempofaktor
            self.tiles["pace"].configure(text="%.2f s (%.2f)"
                                        % (ev["takt"], ev["tempo"]))
            for key, old, new in ev.get("verworfen") or []:
                self._write("    VERWORFEN %s %s -> %s"
                            % (COUNTER_LABEL.get(key, key), old, new), "warn")
            for key, old, new in ev.get("nachgezogen") or []:
                self._write("    NACHGEZOGEN %s %s -> %s"
                            % (COUNTER_LABEL.get(key, key), old, new), "dim")
        elif kind == engine.STOPPED:
            self._write("Ende, %s. %d Aktionen in %.0f s, %.2f s pro Aktion"
                        % (ev["grund"], ev["aktionen"], ev["dauer"],
                           ev["dauer"] / max(ev["aktionen"], 1)), "dim")
            self.status.configure(text="gestoppt, %s" % ev["grund"])
            for b in (self.b_go, self.b_dry, self.b_calib):
                b.configure(state="normal")
            self.b_stop.configure(state="disabled")
            self.b_pause.configure(state="disabled", text="Pause")

    def _counters(self, counters):
        for key, lab in self.counters.items():
            value = counters.get(key)
            lab.configure(text="%s %s" % (COUNTER_LABEL[key],
                                          "-" if value is None else value))
        if counters.get("meters") is not None:
            self.tiles["meters"].configure(text=str(counters["meters"]))

    def _write(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------
    def _load(self):
        for path in (SETTINGS_FILE, OLD_SETTINGS_FILE):
            try:
                with open(path) as fh:
                    return json.load(fh)
            except Exception:
                continue
        return {}

    def _save(self):
        data = {"wanted": [k for k in world_mod.ALL_WANTED
                           if self.vars["want_" + k].get()],
                "skin_hint_off": self.conf.get("skin_hint_off", False)}
        for key in ("min_paws", "max_actions", "target_meters", "click_delay",
                    "settle", "min_pace", "adaptive",
                    "bit_paw", "bit_claw", "bit_skill", "bit_per_action",
                    "bit_pyramid_loot", "row_slack", "autostart",
                    "wait_for_board"):
            if key in self.vars:
                data[key] = self.vars[key].get()
        self.conf.update(data)
        try:
            with open(SETTINGS_FILE, "w") as fh:
                json.dump(self.conf, fh, indent=2)
        except Exception:
            pass


def main():
    app = App()

    def on_close():
        app.stop.request("Fenster geschlossen")
        app._save()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
