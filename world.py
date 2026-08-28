"""
World model.

Core idea: the board only scrolls when stepping right out of the second column.
Every cell is therefore tracked in global coordinates, otherwise pyramids and
power-ups would drop out of the bookkeeping when scrolling.

  global column = scroll_offset + visible column

The figure lives only in visible columns 0 and 1. Stepping right out of column 1
scrolls the world and yields exactly one metre; stepping right out of column 0
only moves the figure.
"""

import vision

# Power-up types, each one switchable on its own.
#
# These are identifiers, not labels. Every one of them is the name of a
# template file on disk -- templates/ticket_orange.png and the player's own
# userdata/templates/ticket_orange.png, which vision.load_templates looks up
# by exactly this string -- and they are also in learning.NEEDED_TEMPLATES,
# in bot.py's --wanted, and in the "wanted" list saved in everybody's
# settings file. Renaming one here orphans a player's learned image and
# costs them the setup, so it is the one thing in this file not to do.
ALL_WANTED = ["ticket_orange", "ticket_green", "ticket_pink", "claw", "paw", "fireball"]

# What a player sees instead. This is the place to rename an item: the
# windows read it and nothing on disk knows about it. Both windows read it
# -- Helpermon's World Search page and gui.py, the developer one -- so that
# a rename does not have to be remembered twice. An item with no entry
# falls back to its key with the underscores opened out, which is what the
# World Search page did for all six of them before this existed.
WANTED_LABEL = {
    "ticket_orange": "SP Training Chip",
    "ticket_green": "Skill Card Summon Ticket",
    "ticket_pink": "Support Summon Ticket",
    "claw": "Attack Token",
    "paw": "Stamina Token",
    "fireball": "Dash Token",
}


def wanted_label(key):
    """The name to show for a board item."""
    return WANTED_LABEL.get(key, key.replace("_", " "))

FIG_COL_MAX = 1  # Figur kann nur in sichtbarer Spalte 0 oder 1 stehen


class World:
    def __init__(self, is_selected=None):
        self.is_selected = set(is_selected if is_selected is not None else ALL_WANTED)
        self.scroll_offset = 0
        self.row = None
        self.col = None  # sichtbare Spalte der Figur, 0 oder 1
        self.cells = {}  # (globale Spalte, Zeile) -> Objektname, bestaetigt
        self.collected = set()
        self.last_grid = None
        # Ein einzelnes Bild reicht nicht als Beweis. Waehrend der
        # Einsammelanimation fliegt ein Ticketsymbol ueber das Brett und
        # erzeugt sonst Phantomobjekte. Deshalb muss ein Objekt in zwei
        # Beobachtungen hintereinander auftauchen, und es verschwindet erst
        # nach zwei Beobachtungen ohne es.
        self.confirm_hits = 2
        self.confirm_misses = 2
        self._hits = {}
        self._misses = {}
        # Objekte, die ohne Krallen und ohne Skill nicht erreichbar sind. Sie
        # werden uebersprungen statt den Bot festzunageln
        self.unreachable = set()

    # ------------------------------------------------------------------
    # Koordinaten
    # ------------------------------------------------------------------
    def to_global(self, col):
        return self.scroll_offset + col

    def to_visible(self, gcol):
        return gcol - self.scroll_offset

    @property
    def fig_gcol(self):
        return None if self.col is None else self.to_global(self.col)

    # ------------------------------------------------------------------
    # Zustand fortschreiben
    # ------------------------------------------------------------------
    def apply_step(self, direction):
        """Position nach einem bestaetigten Schritt fortschreiben."""
        if direction == "up":
            self.row -= 1
        elif direction == "down":
            self.row += 1
        elif direction == "left":
            self.col -= 1
        elif direction == "right":
            if self.col < FIG_COL_MAX:
                self.col += 1
            else:
                self.scroll_offset += 1
        self.row = max(0, min(vision.ROWS - 1, self.row))
        self.col = max(0, min(FIG_COL_MAX, self.col))

    def apply_skill(self):
        """Skill endet immer in Spalte 1. Aus Spalte 0 scrollt die Welt um 2,
        aus Spalte 1 um 3."""
        gain = 3 if self.col >= FIG_COL_MAX else 2
        self.scroll_offset += gain
        self.col = FIG_COL_MAX
        return gain

    def mark_collected(self, gcol, row):
        self.collected.add((gcol, row))
        self.cells.pop((gcol, row), None)
        self._hits.pop((gcol, row), None)

    def mark_unreachable(self, gcol, row):
        self.unreachable.add((gcol, row))

    def forget(self, gcol, row):
        """Objekt sofort vergessen, zum Beispiel eine zerstoerte Pyramide."""
        self.cells.pop((gcol, row), None)
        self._hits.pop((gcol, row), None)

    # ------------------------------------------------------------------
    # Karte aktualisieren
    # ------------------------------------------------------------------
    def observe(self, grid, figure=None):
        """Sichtbares Raster in die globale Karte uebernehmen.

        Ein Objekt wird erst nach zwei Sichtungen hintereinander uebernommen
        und erst nach zwei Fehlsichtungen wieder verworfen. Das filtert
        Animationsbilder heraus, in denen ein eingesammeltes Ticket quer ueber
        das Brett fliegt.
        """
        if figure:
            self.row = figure["row"]
            self.col = min(figure["col"], FIG_COL_MAX)

        for col in range(vision.COLS):
            gcol = self.to_global(col)
            for row in range(vision.ROWS):
                cell = grid[row][col]
                key = (gcol, row)

                # Die Zelle der Figur wird uebersprungen. Die Figur ist selbst
                # bunt und wuerde sonst als unbekanntes Objekt gemeldet, und
                # unter ihr kann ausserdem etwas verdeckt sein.
                if cell == "figure" or (row == self.row and col == self.col):
                    continue
                if key in self.collected:
                    continue

                if cell is None:
                    self._hits.pop(key, None)
                    if key in self.cells:
                        self._misses[key] = self._misses.get(key, 0) + 1
                        if self._misses[key] >= self.confirm_misses:
                            self.cells.pop(key, None)
                            self._misses.pop(key, None)
                    continue

                self._misses.pop(key, None)
                if self.cells.get(key) == cell:
                    continue
                self._hits[key] = self._hits.get(key, 0) + 1
                if self._hits[key] >= self.confirm_hits:
                    self.cells[key] = cell
                    self._hits.pop(key, None)
        self.last_grid = grid

    # ------------------------------------------------------------------
    # Abfragen
    # ------------------------------------------------------------------
    def at(self, gcol, row):
        return self.cells.get((gcol, row))

    def is_pyramid(self, gcol, row):
        return self.at(gcol, row) == "pyramid"

    def is_wanted(self, gcol, row):
        return self.at(gcol, row) in self.is_selected

    def visible_wanted(self):
        """Alle gewuenschten Power-ups im sichtbaren Bereich, sortiert nach
        globaler Spalte. Damit werden sie von links nach rechts abgearbeitet
        und Linksschritte entstehen im Normalfall gar nicht."""
        out = []
        for col in range(vision.COLS):
            gcol = self.to_global(col)
            for row in range(vision.ROWS):
                if self.is_wanted(gcol, row) and (gcol, row) not in self.unreachable:
                    out.append((gcol, row, self.cells[(gcol, row)]))
        out.sort(key=lambda t: (t[0], abs(t[1] - (self.row or 0))))
        return out

    def describe(self):
        return "row %s column %s (global %s) scroll %d" % (
            None if self.row is None else self.row + 1,
            None if self.col is None else self.col + 1,
            self.fig_gcol,
            self.scroll_offset,
        )
