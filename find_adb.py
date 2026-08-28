r"""
Show which ADB is found, which devices answer, and whether a frame arrives.

  py find_adb.py

This is the thing to run when a bot says it cannot reach the emulator, and
the thing to paste when reporting that it still cannot. It says where it
looked, not only what it concluded.
"""
import capture
import noconsole

print("Where Helpermon looks, in this order")
print("  1. the DGUP_ADB environment variable")
import os                                              # noqa: E402
print("       set to: %s" % (os.environ.get("DGUP_ADB") or "not set"))
print("  2. an adb on the PATH")
from shutil import which                               # noqa: E402
print("       found:  %s" % (which("adb") or "none"))
print("  3. the LDPlayer folders Windows has on file")
for place in capture.ld_from_registry() or ["none"]:
    print("       %s" % place)
print("  4. every fixed disk, for a folder called LDPlayer*")
print("       disks:  %s" % ", ".join(capture.fixed_drives()))
print()

path = capture.find_adb()
print("adb.exe: %s" % (path or "NOT FOUND"))
if not path:
    print()
    print("DGUP_ADB is not a file to look for, it is an environment "
          "variable.")
    print("Find adb.exe in your LDPlayer folder, beside dnplayer.exe, then")
    print("start from PowerShell with your own path:")
    print()
    print('  $env:DGUP_ADB = "C:\\LDPlayer\\LDPlayer14\\adb.exe"')
    print("  py app.py")
    raise SystemExit

print()
print(noconsole.run([path, "devices"], capture_output=True,
                    text=True).stdout)

cap = capture.AdbCapture()
devices = cap.devices()
if not devices:
    print("No device answers. Switch ADB debugging on in LDPlayer:")
    print("  Settings, Other settings, ADB debugging")
    print("It offers three choices, and the one to pick is")
    print("  Enable local connection")
    print("Remote is for driving the emulator from another machine.")
    print()
    print("If it is already on, the emulator may simply not be running yet.")
    raise SystemExit

for serial in devices:
    cap.serial = serial
    if cap.works():
        img = cap.grab()
        print("%-22s works, frame %d x %d"
              % (serial, img.shape[1], img.shape[0]))
    else:
        print("%-22s answers but sends no frame, an old TCP connection?"
              % serial)

print()
print("If more than one works, pin the right one with")
print('  $env:DGUP_SERIAL = "<serial>"')
