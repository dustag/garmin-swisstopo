"""Entry point of the packaged application (see build_app.py).

The same executable opens the window, or runs download.py or build.py when its first
argument is "download" or "build": the window starts them that way in a child process.
The build's worker processes go through freeze_support() before anything else is imported.
"""
import importlib
import multiprocessing
import sys
import traceback

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] in ("download", "build"):
        step = sys.argv.pop(1)
        try:
            sys.exit(importlib.import_module(step).main())
        except Exception:
            # To the window's log, instead of the error dialog of the packaged application
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)
    import gui
    gui.main()
