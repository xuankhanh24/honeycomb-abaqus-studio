"""Provide a local X display for the existing CAE geometry preview, never TCP X11."""

import os
import subprocess
import sys
import time

display = None
try:
    if sys.argv[1:2] == ["cae"]:
        display = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"])
        for _ in range(100):
            if os.path.exists("/tmp/.X11-unix/X99"):
                break
            if display.poll() is not None:
                raise RuntimeError("Headless display failed")
            time.sleep(0.05)
        else:
            raise RuntimeError("Headless display not ready")
        os.environ.update(DISPLAY=":99", LIBGL_ALWAYS_SOFTWARE="1", XLIB_SKIP_ARGB_VISUALS="1")
    sys.exit(subprocess.call(["/opt/SIMULIA/Commands/abaqus"] + sys.argv[1:]))
finally:
    if display is not None:
        display.terminate()
        display.wait()
