r"""
Take the screenshots INSTALL.md wants of Helpermon's own windows.

  py doc_shots.py                 all of them, into docs/images
  py doc_shots.py --fresh         with an empty data folder, so the bots
                                  report "not set up" and Start here shows
                                  its "Try it right now" card

Which files it writes, and what INSTALL.md expects in them, is listed in
docs/images/READ_ME.txt. The ones only a person can take are in there too:
the Releases page, the unblock dialog, LDPlayer's settings, a dry run with
the game open.

Not through the screen. mss photographs the framebuffer, which carries
whatever the display is doing to it -- with Windows Night Light on, every
attempt came out orange and unusable. PrintWindow asks the window to draw
itself into a bitmap instead, so the colours are the ones the program chose
and the setting on the machine does not matter.

The two modal dialogs are photographed from an after() callback: wait_window
blocks the caller, but the Tk event loop keeps running inside it, so a timer
set before the call still fires.
"""

import argparse
import ctypes
import os
import tempfile
from ctypes import wintypes

import cv2
import numpy as np

import app as A

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs", "images")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 0x00000002


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


def grab_window(hwnd, path):
    """One window into one PNG, by its own drawing rather than the screen."""
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    src = user32.GetWindowDC(hwnd)
    dc = gdi32.CreateCompatibleDC(src)
    bmp = gdi32.CreateCompatibleBitmap(src, w, h)
    gdi32.SelectObject(dc, bmp)
    ok = user32.PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h            # negative: top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(dc, bmp, 0, h, buf, ctypes.byref(info), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(dc)
    user32.ReleaseDC(hwnd, src)

    # BGRA and top-down, so the alpha column is simply dropped.
    img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3]
    cv2.imwrite(path, img)
    # One pixel as evidence the colours are the program's and not the
    # screen's: eight pixels in is the sidebar, which is #e8eaed. Anything
    # warmer than that means the picture was taken off the display after all.
    b, g, r = img[h // 2, 8]
    print("   %-34s %4d x %-4d  PrintWindow=%d  probe #%02x%02x%02x"
          % (os.path.basename(path), w, h, ok, r, g, b))
    return img


def shoot_dialog(win, name):
    """Photograph the dialog that is up, then close it.

    Closing is what lets wait_window return, so the caller carries on.
    """
    def go():
        tops = [w for w in win.winfo_children()
                if isinstance(w, A.tk.Toplevel) and w.winfo_exists()]
        if not tops:
            print("   no dialog appeared for %s" % name)
            return
        dialog = tops[-1]
        dialog.update()
        grab_window(dialog.winfo_id(), os.path.join(OUT, name))
        dialog.destroy()
    return go


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true",
                    help="run against an empty data folder, so the bots "
                         "report not set up")
    args = ap.parse_args()

    if args.fresh:
        # Only for this process. The player's own learned data is untouched.
        os.environ["DGUP_DATA"] = os.path.join(tempfile.gettempdir(),
                                               "helpermon_doc_shots")
    os.makedirs(OUT, exist_ok=True)

    win = A.App()
    win.update()

    win.show_page("home")
    win.update()
    grab_window(win.winfo_id(), os.path.join(OUT, "10-start-here.png"))

    win.after(900, shoot_dialog(win, "08-first-run-input-dialog.png"))
    win._adb_notice()

    win.after(900, shoot_dialog(win, "09-first-run-legal-notice.png"))
    win._legal_notice()

    win.destroy()
    print("\nwritten to %s" % OUT)
    print("What is still owed, and who can take it, is in "
          "docs/images/READ_ME.txt")


if __name__ == "__main__":
    main()
