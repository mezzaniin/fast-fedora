"""Smoke-Test: öffnet das Fenster, aktiviert jedes Modul und meldet Ausnahmen.

Ausführen:  FAST_NO_ROOT=1 python3 tests/smoke_test.py
(FAST_NO_ROOT verhindert pkexec-Abfragen; es wird nichts verändert.)
"""
import os
import sys
import traceback

os.environ.setdefault("FAST_NO_ROOT", "1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fast.util import GLib  # noqa: E402
from fast.app import App, Window  # noqa: E402

errors = []
_orig_hook = sys.excepthook


def hook(t, v, tb):
    errors.append("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = hook


def run_all(app):
    win = Window(app)
    win.present()
    ids = [m.id for m in win.modules]

    def step():
        if not ids:
            GLib.timeout_add(4000, finish, win)
            return False
        mid = ids.pop(0)
        print("öffne", mid, flush=True)
        try:
            win.open(mid)
        except Exception:
            errors.append(f"{mid}: " + traceback.format_exc())
        return True

    GLib.timeout_add(400, step)


def finish(win):
    win.get_application().quit()
    return False


class TestApp(App):
    def do_activate(self):
        run_all(self)


app = TestApp()
app.run([])
if errors:
    print(f"\n{len(errors)} FEHLER:")
    for e in errors:
        print(e)
    sys.exit(1)
print("\nAlle Module ohne Ausnahme geladen.")
