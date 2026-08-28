"""
Learning logic behind the setup wizard. No interface, so it stays testable. The
interface lives in setup_wizard.py.

What already works without any shipped image

  figure      body signature, dark desaturated pixels
  power-ups   colour pre-filter, the board is blue and objects are colourful

What has to be learned

  mapping     which colourful find is which power-up. That does not follow from
              the image; orange and pink look different, but only a human knows
              which one is the valuable currency
  pyramid     one image, because edge energy alone separates too narrowly,
              measured 12.5 against 13.5
  digits      labelled digit images
  banners     exclamation mark and texts
"""

import os

import cv2
import numpy as np

import userdata
import vision

# Was am Ende vorhanden sein muss, damit der Bot vollstaendig arbeitet
NEEDED_TEMPLATES = ["ticket_orange", "ticket_green", "ticket_pink", "claw",
                    "paw", "fireball", "pyramid", "banner_badge",
                    "banner_text_move"]
OPTIONAL_TEMPLATES = ["banner_text_insufficient", "arrow", "figure"]

LABELS = {
    "ticket_orange": "orange ticket, the valuable currency",
    "ticket_green": "green ticket",
    "ticket_pink": "pink ticket",
    "claw": "yellow claw, destroys pyramids",
    "paw": "pink paw, steps",
    "fireball": "green fireball, skill",
    "pyramid": "pyramid, obstacle",
}


# ----------------------------------------------------------------------------
# Zustand
# ----------------------------------------------------------------------------
def only_learned():
    return userdata.only_learned()


def set_only_learned(value):
    out = userdata.set_only_learned(value)
    vision.forget_templates()
    return out


def template_sources():
    """Woher jedes Template kommt, gelernt oder mitgeliefert. Wichtig, weil ein
    mitgeliefertes Bild den Eindruck erzeugt, es sei schon eingerichtet."""
    learned_dir = userdata.templates_dir(create=False)
    out = {}
    for name in NEEDED_TEMPLATES + OPTIONAL_TEMPLATES:
        if os.path.exists(os.path.join(learned_dir, name + ".png")):
            out[name] = "learned"
        elif (not userdata.only_learned()
              and os.path.exists(os.path.join(vision.TEMPLATE_DIR, name + ".png"))):
            out[name] = "shipped"
        else:
            out[name] = "missing"
    return out


def status():
    """What is learned and what is missing. Basis for the progress display.

    `fertig` is the readiness of the board minigame.
    """
    templates = vision.load_templates()
    digits = vision.digit_stats().get(vision.DIGIT_SET, {})
    missing_digits = [d for d in "0123456789" if digits.get(d, 0) == 0]
    thin_digits = [d for d, n in sorted(digits.items()) if 0 < n < 4]
    sources = template_sources()
    return {
        "ort": userdata.describe(),
        "quellen": sources,
        "shipped": [n for n, q in sources.items() if q == "shipped"],
        "vorhanden": [n for n in NEEDED_TEMPLATES if n in templates],
        "missing": [n for n in NEEDED_TEMPLATES if n not in templates],
        "optional_fehlt": [n for n in OPTIONAL_TEMPLATES if n not in templates],
        "ziffern": digits,
        "ziffern_fehlen": missing_digits,
        "ziffern_duenn": thin_digits,
        "fertig": not [n for n in NEEDED_TEMPLATES if n not in templates]
                  and not missing_digits,
    }


# ----------------------------------------------------------------------------
# Objekte
# ----------------------------------------------------------------------------
def object_candidates(img, calib, known_only=False):
    """Zellen, in denen etwas Buntes liegt, ohne die Figur.

    Der Farbvorfilter findet Power-ups zuverlaessig, gemessen 4 bis 9 Prozent
    bunte Pixel gegen 0 bei leeren Kacheln und Pyramiden. Was es ist, entscheidet
    danach der Mensch oder ein bereits gelerntes Template.
    """
    templates = vision.load_templates()
    board = vision.board_templates(templates)
    figure = vision.find_figure(img, calib, templates)
    grid = ([[None] * vision.COLS for _ in range(vision.ROWS)] if not board
            else vision.read_grid(img, calib, board, figure=figure)[0])
    out = []
    for row in range(vision.ROWS):
        for col in range(vision.COLS):
            if not vision.has_object_colour(img, calib, row, col):
                continue
            if vision.figure_body_fraction(img, calib, row, col) >= vision.FIGURE_BODY_MIN:
                continue  # das ist die Figur
            if figure and vision._is_cross_neighbour(figure, row, col):
                # kann der gelbe Richtungspfeil sein, wird nicht als offener
                # Fall gemeldet
                continue
            erkannt = grid[row][col] if grid else None
            if known_only and erkannt in (None, "?"):
                continue
            if not known_only and erkannt not in (None, "?"):
                continue  # schon erkannt, muss nicht gelernt werden
            out.append({"row": row, "col": col,
                        "crop": crop_cell(img, calib, row, col),
                        "erkannt": erkannt})
    return out


def crop_cell(img, calib, row, col):
    """Ausschnitt in derselben Groesse, in der auch Templates geschnitten
    werden. Muss zum Referenzmasstab passen, sonst greift die Skalierung
    spaeter nicht."""
    px, py = vision.cell_center(calib, row, col)
    half_w = int(0.29 * calib["cell_w"])
    half_h = int(0.25 * calib["cell_h"])
    y1, y2 = max(0, py - half_h), py + half_h
    x1, x2 = max(0, px - half_w), px + half_w
    return img[y1:y2, x1:x2].copy()


def save_template(name, crop, calib, ref_cell_w=87.5):
    """Speichert einen Ausschnitt als Template im Lernordner.

    Der Ausschnitt wird auf den Referenzmasstab gerechnet, damit er bei jeder
    Fenstergroesse und jeder Emulatorauflaesung passt. Ohne das wuerde ein auf
    1080 geschnittenes Bild bei Fensteraufnahme nicht mehr treffen.
    """
    factor = ref_cell_w / calib["cell_w"]
    if abs(factor - 1.0) > 0.02:
        h, w = crop.shape[:2]
        crop = cv2.resize(crop, (max(6, int(w * factor)), max(6, int(h * factor))),
                          interpolation=cv2.INTER_AREA)
    path = userdata.template_path(name)
    cv2.imwrite(path, crop)
    vision.forget_templates()
    return path


# ----------------------------------------------------------------------------
# Pyramide
# ----------------------------------------------------------------------------
def pyramid_candidates(img, calib, limit=6):
    """Vorschlaege fuer die Pyramide, nach Kantenenergie sortiert.

    Kantenenergie allein trennt zu knapp fuer den Dauerbetrieb, gemessen
    Pyramiden 13,5 bis 26,8 gegen leere Kacheln 4,8 bis 12,5. Als Vorschlag
    reicht es aber gut, bestaetigen muss der Mensch.
    """
    out = []
    for row in range(vision.ROWS):
        # Unterste Zeile auslassen. Dort erzeugen Mauersims und Meterlabel
        # Kanten und liefern falsche Vorschlaege, gemessen 22,9 fuer eine leere
        # Kachel gegen 18,2 fuer eine echte Pyramide
        if row == vision.ROWS - 1:
            continue
        for col in range(vision.COLS):
            if vision.has_object_colour(img, calib, row, col):
                continue
            if vision.figure_body_fraction(img, calib, row, col) >= vision.FIGURE_BODY_MIN:
                continue
            patch = vision.search_patch(img, calib, row, col)
            if patch.size == 0:
                continue
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY).astype(np.float32)
            energy = float(np.abs(cv2.Laplacian(gray, cv2.CV_32F)).mean())
            out.append({"row": row, "col": col, "energie": round(energy, 2),
                        "crop": crop_cell(img, calib, row, col)})
    out.sort(key=lambda c: -c["energie"])
    return out[:limit]


# ----------------------------------------------------------------------------
# Ziffern
# ----------------------------------------------------------------------------
def learn_digits(img, calib, values):
    """Zifferbilder aus eingetippten Zaehlerwerten lernen.

    values ist ein Dictionary wie {"paws": 1028, "meters": 11917}. Ein Bereich
    wird nur gelernt, wenn die Anzahl gefundener Zeichen zur eingetippten Zahl
    passt. Sonst waere die Zuordnung verschoben und wuerde den Ziffernsatz
    dauerhaft vergiften.
    """
    report = []
    gelernt = 0
    for key, value in values.items():
        if value in (None, ""):
            continue
        roi_key = "roi_" + key
        if roi_key not in calib:
            report.append((key, "unknown region"))
            continue
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        glyphs = vision.segment_digits(img, calib[roi_key],
                                       vision.POLARITY[roi_key])
        if len(glyphs) != len(digits):
            report.append((key, "found %d characters, typed %d, skipped"
                           % (len(glyphs), len(digits))))
            continue
        for glyph, ch in zip(glyphs, digits):
            _save_digit(glyph, ch)
            gelernt += 1
        report.append((key, "%d digits learned" % len(digits)))
    vision.forget_templates()
    return gelernt, report


def _save_digit(glyph, ch):
    folder = userdata.digit_dir(ch)
    idx = userdata.next_index(folder)
    small = cv2.resize(glyph, (vision.GLYPH_W, vision.GLYPH_H))
    cv2.imwrite(os.path.join(folder, "%02d.png" % idx), small)


def auto_learn_digit(img, calib, roi_key, expected):
    """Selbstlernen im Betrieb, aber nur im eindeutigen Fall.

    Bedingung, genau ein Zeichen ist unsicher und der erwartete Wert folgt
    eindeutig aus dem Delta, zum Beispiel Tatzen minus 1 nach einem Schritt.
    Dann ist die Identitaet des unsicheren Zeichens bestimmt. Bei zwei
    unsicheren Zeichen wird nicht geraten, ein Fehler wuerde den Ziffernsatz
    dauerhaft verderben.
    """
    digits = "".join(ch for ch in str(expected) if ch.isdigit())
    glyphs = vision.segment_digits(img, calib[roi_key], vision.POLARITY[roi_key])
    if len(glyphs) != len(digits):
        return None
    table = vision._digit_templates()
    unsure = []
    for i, glyph in enumerate(glyphs):
        found, _score = vision._classify_glyph(glyph, table)
        if found is None:
            unsure.append(i)
        elif found != digits[i]:
            return None  # Widerspruch, lieber nichts lernen
    if len(unsure) != 1:
        return None
    i = unsure[0]
    _save_digit(glyphs[i], digits[i])
    vision.forget_templates()
    return digits[i]


# ----------------------------------------------------------------------------
# Banner
# ----------------------------------------------------------------------------
BANNER_KINDS = {
    "banner_text_move": "Zug nicht moeglich, etwa \"Cannot move to this location\"",
    "banner_text_insufficient": "Ressource leer, etwa \"Insufficient ...\"",
}


def learn_banner(img, calib, text_name="banner_text_move"):
    """Ausrufezeichen und Text aus einem Bild mit sichtbarem Banner schneiden.

    Die Zuschnitte folgen denselben Anteilen, mit denen die urspruenglichen
    Templates entstanden sind, bezogen auf den Bannerbereich und den
    Referenzmasstab.
    """
    roi = vision.banner_roi(img, calib)
    if roi.size == 0:
        return None, "banner region empty"
    scale = calib["cell_w"] / vision.BANNER_REF_CELL_W

    def cut(x1, x2, y1, y2):
        part = roi[int(y1 * scale):int(y2 * scale), int(x1 * scale):int(x2 * scale)]
        if part.size == 0:
            return None
        if abs(scale - 1.0) > 0.02:  # auf Referenzmasstab bringen
            f = 1.0 / scale
            part = cv2.resize(part, (max(6, int(part.shape[1] * f)),
                                     max(6, int(part.shape[0] * f))),
                              interpolation=cv2.INTER_CUBIC)
        return part

    badge = cut(10, 190, 60, 230)
    text = cut(200, 425, 95, 215)
    if badge is None or text is None:
        return None, "cropping not possible"
    # Das Ausrufezeichen links ist in jeder Sprache gleich, es ist ein Symbol.
    # Nur der Text daneben wechselt, deshalb wird er getrennt gespeichert und
    # kann fuer jede Sprache neu gelernt werden.
    cv2.imwrite(userdata.template_path("banner_badge"), badge)
    cv2.imwrite(userdata.template_path(text_name), text)
    vision.forget_templates()
    return ["banner_badge", text_name], "learned"


def diagonal_cell(figure):
    """Zelle fuer den absichtlichen Fehlklick. Diagonal, damit das Spiel
    'Cannot move to this location' meldet. Kostet nichts, es passiert nur
    nichts."""
    row, col = figure["row"], figure["col"]
    for dr in (1, -1):
        for dc in (1, -1):
            r, c = row + dr, col + dc
            if 0 <= r < vision.ROWS and 0 <= c < vision.COLS:
                return r, c
    return None


# ----------------------------------------------------------------------------
# Warteschlange offener Faelle
# ----------------------------------------------------------------------------
def queue_unknown(img, calib, row, col, tag="unknown"):
    """Im Betrieb gefundenes, nicht zuordenbares Objekt zum spaeteren
    Beschriften ablegen. Seltene Typen tauchen in einer kurzen Sitzung nicht
    auf, deshalb wird nachgelernt statt alles vorab zu verlangen."""
    folder = userdata.unknown_dir()
    idx = userdata.next_index(folder)
    path = os.path.join(folder, "%s_%03d.png" % (tag, idx))
    cv2.imwrite(path, crop_cell(img, calib, row, col))
    # Zellgroesse mitschreiben, damit spaeter richtig skaliert werden kann
    with open(path + ".txt", "w") as fh:
        fh.write("cell_w=%.3f\n" % calib["cell_w"])
    return path


def queued_unknown():
    folder = userdata.unknown_dir()
    return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                  if f.endswith(".png"))


def label_queued(path, name):
    """Einen abgelegten Fall als Template uebernehmen."""
    crop = cv2.imread(path)
    if crop is None:
        return None
    cell_w = vision.BANNER_REF_CELL_W  # Rueckfall
    meta = path + ".txt"
    if os.path.exists(meta):
        for line in open(meta):
            if line.startswith("cell_w="):
                cell_w = float(line.split("=", 1)[1])
    saved = save_template(name, crop, {"cell_w": cell_w})
    for extra in (path, meta):
        try:
            os.remove(extra)
        except OSError:
            pass
    return saved
