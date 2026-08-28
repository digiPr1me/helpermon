"""Check the world model offline, above all the scrolling."""
import vision
import world as world_mod

def empty():
    return [[None] * vision.COLS for _ in range(vision.ROWS)]

def main():
    ok = []
    w = world_mod.World()
    g = empty(); g[2][3] = "ticket_orange"
    w.observe(g, dict(row=2, col=1, how="t"))
    ok.append(("one sighting is not enough", w.at(3, 2) is None))
    w.observe(g, dict(row=2, col=1, how="t"))
    ok.append(("two sightings confirm", w.at(3, 2) == "ticket_orange"))

    # Phantom aus einem Animationsbild darf nicht in die Karte
    ph = empty(); ph[0][0] = "ticket_orange"; ph[2][3] = "ticket_orange"
    w.observe(ph, dict(row=2, col=1, how="t"))
    ok.append(("phantom after one frame ignored", w.at(0, 0) is None))
    w.observe(g, dict(row=2, col=1, how="t"))
    ok.append(("phantom disappears again", w.at(0, 0) is None))
    ok.append(("real ticket stays", w.at(3, 2) == "ticket_orange"))

    # ein einzelnes Bild ohne das Ticket darf es nicht loeschen
    w.observe(empty(), dict(row=2, col=1, how="t"))
    ok.append(("one bad frame does not delete", w.at(3, 2) == "ticket_orange"))
    w.observe(empty(), dict(row=2, col=1, how="t"))
    ok.append(("two bad frames delete", w.at(3, 2) is None))

    # Rechtsschritt aus Spalte 0, Figur laeuft, Welt bleibt
    w.col = 0
    w.apply_step("right")
    ok.append(("column 0 to the right, no scroll", w.col == 1 and w.scroll_offset == 0))

    # Rechtsschritt aus Spalte 1, Welt scrollt
    w.apply_step("right")
    ok.append(("column 1 to the right, scroll", w.col == 1 and w.scroll_offset == 1))
    ok.append(("ticket now in visible column 2", w.to_visible(3) == 2))

    # nach dem Scrollen muss das Ticket im neuen Raster an Spalte 2 liegen
    g2 = empty(); g2[2][2] = "ticket_orange"
    w.observe(g2, dict(row=2, col=1, how="t"))
    w.observe(g2, dict(row=2, col=1, how="t"))
    ok.append(("ticket unchanged globally after scroll", w.at(3, 2) == "ticket_orange"))

    # Vertikalschritt scrollt nicht
    before = w.scroll_offset
    w.apply_step("down")
    ok.append(("vertical does not scroll", w.scroll_offset == before and w.row == 3))

    # Skill aus Spalte 1 gibt 3, aus Spalte 0 gibt 2
    w.col = 1; s = w.scroll_offset; gain = w.apply_skill()
    ok.append(("skill from column 1 gives 3", gain == 3 and w.scroll_offset == s + 3
               and w.col == 1))
    w.col = 0; s = w.scroll_offset; gain = w.apply_skill()
    ok.append(("skill from column 0 gives 2", gain == 2 and w.scroll_offset == s + 2
               and w.col == 1))

    # Zeilengrenzen halten
    w.row = 0; w.apply_step("up")
    ok.append(("row 1 is a hard boundary", w.row == 0))
    w.row = vision.ROWS - 1; w.apply_step("down")
    ok.append(("row 5 is a hard boundary", w.row == vision.ROWS - 1))

    # eingesammeltes Objekt kommt nicht zurueck
    w2 = world_mod.World()
    g3 = empty(); g3[1][2] = "ticket_green"
    w2.observe(g3, dict(row=1, col=1, how="t"))
    w2.observe(g3, dict(row=1, col=1, how="t"))
    w2.mark_collected(2, 1)
    w2.observe(g3, dict(row=1, col=1, how="t"))
    ok.append(("collected items stay gone", w2.at(2, 1) is None))

    # The names shown in the two windows. They are meant to be edited, and
    # the keys beside them are template filenames that are not -- so this
    # checks that a rename stayed on the right side of that line: an entry
    # for every item, no entry for anything that is not one (a mistyped key
    # would silently show the fallback instead), and no empty name, which
    # would draw a tick box with nothing beside it.
    labels = world_mod.WANTED_LABEL
    ok.append(("every item has a name",
               all(key in labels for key in world_mod.ALL_WANTED)))
    ok.append(("no name for something that is not an item",
               set(labels) <= set(world_mod.ALL_WANTED)))
    ok.append(("no name is empty",
               all(str(text).strip() for text in labels.values())))
    ok.append(("an item with no entry falls back to its key",
               world_mod.wanted_label("ticket_blue") == "ticket blue"))

    for name, good in ok:
        print("%-42s %s" % (name, "ok" if good else "FAILED"))
    print("\n%d of %d ok" % (sum(1 for _, g in ok if g), len(ok)))

if __name__ == "__main__":
    main()
