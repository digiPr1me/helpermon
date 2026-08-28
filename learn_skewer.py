"""
Learn the skewer minigame's ingredient icons.

Standalone tool, not part of setup_wizard.py: that wizard is built around
the board minigame's grid/calibration concept, and every existing page is
hardwired to it -- there is no way to plug in a new kind of thing to learn
without touching its existing flow. This script does the same job for the
skewer bot's fixed 4x3 ingredient grid instead: crop, show, let you name
it, save it as a template PNG under userdata/templates, same on-disk format
and the same to_photo() display helper as the wizard uses.

  py learn_skewer.py                the stored switch decides ADB or window
  py learn_skewer.py --input mouse  window capture regardless of the switch

Never clicks anything in the game, same as setup_wizard.py. The 12 starter
names are guesses (see skewer.INGREDIENT_NAMES) -- rename them here to
whatever they actually are before saving, the filename is whatever you type.
"""

import argparse
import tkinter as tk

import capture
import skewer
import userdata
from setup_wizard import to_photo


class Learner(tk.Tk):
    def __init__(self, cap):
        super().__init__()
        self.title("Learn skewer ingredients")
        self.cap = cap
        self.img = None
        self.photos = []
        self._cells = []

        top = tk.Frame(self, padx=10, pady=8)
        top.pack(fill="x")
        tk.Button(top, text="Grab new frame", command=self.grab).pack(side="left")
        tk.Button(top, text="Test match", command=self.test_match).pack(side="left", padx=8)
        self.status = tk.Label(top, text="")
        self.status.pack(side="left", padx=8)

        self.grid_frame = tk.Frame(self, padx=10, pady=6)
        self.grid_frame.pack()

        roi_box = tk.Frame(self, padx=10, pady=10)
        roi_box.pack(fill="x")
        tk.Label(roi_box, text="Other ROIs, for eyeballing placement only "
                               "(not clickable, not learned here)").pack(anchor="w")
        self.roi_row = tk.Frame(roi_box)
        self.roi_row.pack(anchor="w", pady=4)

        self._build_grid()
        self.grab()

    # ------------------------------------------------------------------
    def _build_grid(self):
        i = 0
        for fy in skewer.GRID_ROWS_FY:
            for fx in skewer.GRID_COLS_FX:
                cell = tk.Frame(self.grid_frame, padx=6, pady=6, relief="groove", bd=1)
                cell.grid(row=i // 4, column=i % 4)
                img_label = tk.Label(cell)
                img_label.pack()
                starter = (skewer.INGREDIENT_NAMES[i]
                          if i < len(skewer.INGREDIENT_NAMES) else "ingredient_%d" % i)
                name_var = tk.StringVar(value=starter)
                tk.Entry(cell, textvariable=name_var, width=14).pack(pady=2)
                match_label = tk.Label(cell, text="", fg="#555")
                match_label.pack()
                tk.Button(cell, text="Save", width=10,
                          command=lambda fx=fx, fy=fy, v=name_var: self.save_one(fx, fy, v)
                          ).pack(pady=2)
                self._cells.append({"fx": fx, "fy": fy, "img_label": img_label,
                                    "name_var": name_var, "match_label": match_label})
                i += 1

    # ------------------------------------------------------------------
    def grab(self):
        try:
            self.img = self.cap.grab()
        except Exception as err:
            self.status.configure(text="grab failed: %s" % err)
            return
        self.status.configure(text="frame grabbed, %d x %d"
                              % (self.img.shape[1], self.img.shape[0]))
        self._refresh_crops()
        self._refresh_rois()

    def _refresh_crops(self):
        for cell in self._cells:
            crop = skewer.crop_rel(self.img, cell["fx"], cell["fy"],
                                   skewer.GRID_CELL_FW, skewer.GRID_CELL_FH)
            photo = to_photo(crop, scale=3)
            if photo:
                self.photos.append(photo)
                cell["img_label"].configure(image=photo)
                cell["img_label"].image = photo
            cell["match_label"].configure(text="")

    def _refresh_rois(self):
        for w in self.roi_row.winfo_children():
            w.destroy()
        for name, rect in (("order strip", skewer.POS_ORDER_STRIP),
                           ("current strip", skewer.POS_CURRENT_STRIP),
                           ("portraits", skewer.POS_PORTRAITS),
                           ("timer", skewer.POS_TIMER),
                           ("lives", skewer.POS_LIVES),
                           ("failed dialog", skewer.POS_FAILED_DIALOG)):
            crop = skewer.crop_rel(self.img, *rect)
            box = tk.Frame(self.roi_row, padx=6)
            box.pack(side="left")
            photo = to_photo(crop, scale=2)
            if photo:
                self.photos.append(photo)
                tk.Label(box, image=photo).pack()
            tk.Label(box, text=name).pack()

    # ------------------------------------------------------------------
    def save_one(self, fx, fy, name_var):
        name = name_var.get().strip()
        if not name:
            self.status.configure(text="type a name first")
            return
        crop = skewer.crop_rel(self.img, fx, fy, skewer.GRID_CELL_FW, skewer.GRID_CELL_FH)
        skewer.save_ingredient_template(name, crop)
        self.status.configure(text="%s saved" % name)

    def test_match(self):
        templates = skewer.load_ingredient_templates(force=True)
        if not templates:
            self.status.configure(text="nothing learned yet")
            return
        for cell in self._cells:
            crop = skewer.crop_rel(self.img, cell["fx"], cell["fy"],
                                   skewer.GRID_CELL_FW, skewer.GRID_CELL_FH)
            name, val = skewer.match_icon(crop, templates)
            cell["match_label"].configure(text="%s  %.2f" % (name or "?", val))
        self.status.configure(text="matched against %d learned icon(s)" % len(templates))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", choices=["adb", "mouse"], default=None,
                    help="frames via adb or via the window. Default: the "
                         "stored switch (Helpermon's window, or "
                         "DGUP_ADB_MODE)")
    args = ap.parse_args()
    adb = userdata.adb_mode() if args.input is None else args.input == "adb"
    cap = capture.open_for(adb)
    app = Learner(cap)
    app.mainloop()


if __name__ == "__main__":
    main()
