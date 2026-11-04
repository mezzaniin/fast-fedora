"""Gemeinsame Hilfsfunktionen: Prozesse starten, Root-Rechte, Dialoge, Basis-Seite."""
import os
import shutil
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

HELPER_INSTALLED = "/usr/libexec/fast/fast-helper"
HELPER_LOCAL = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "helper", "fast-helper")
)


def helper_path():
    return HELPER_INSTALLED if os.path.exists(HELPER_INSTALLED) else HELPER_LOCAL


def have(binary):
    return shutil.which(binary) is not None


NO_ROOT = bool(os.environ.get("FAST_NO_ROOT"))  # für Tests: keine Root-Aufrufe


def _argv(cmd, root):
    cmd = [str(c) for c in cmd]
    if root and NO_ROOT:
        return ["false"]
    if root and os.geteuid() != 0:
        return ["pkexec", helper_path(), "run", *cmd]
    return cmd


def _launcher(flags):
    launcher = Gio.SubprocessLauncher.new(flags)
    launcher.setenv("LC_ALL", "C.UTF-8", True)
    launcher.setenv("SYSTEMD_COLORS", "0", True)
    launcher.setenv("NO_COLOR", "1", True)
    return launcher


def run(cmd, callback=None, root=False, input=None):
    """Startet cmd asynchron. callback(ok, stdout, stderr)."""
    argv = _argv(cmd, root)
    flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
    if input is not None:
        flags |= Gio.SubprocessFlags.STDIN_PIPE
    try:
        proc = _launcher(flags).spawnv(argv)
    except GLib.Error as e:
        if callback:
            GLib.idle_add(lambda: callback(False, "", e.message) and False)
        return None

    def done(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
            ok = p.get_if_exited() and p.get_exit_status() == 0
        except GLib.Error as e:
            ok, out, err = False, "", e.message
        if callback:
            callback(ok, out or "", err or "")

    proc.communicate_utf8_async(input, None, done)
    return proc


def run_sync(cmd, root=False, input=None, timeout=30):
    """Synchron – nur für schnelle Lesezugriffe. Gibt (ok, stdout, stderr) zurück."""
    env = dict(os.environ, LC_ALL="C.UTF-8", SYSTEMD_COLORS="0", NO_COLOR="1")
    try:
        p = subprocess.run(
            _argv(cmd, root), input=input, capture_output=True, text=True,
            env=env, timeout=timeout,
        )
        return p.returncode == 0, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, "", str(e)


def write_root_file(path, content, callback=None):
    """Schreibt eine Systemdatei über den Helper (mit Backup)."""
    if NO_ROOT:
        argv = ["false"]
    elif os.geteuid() == 0:
        argv = [helper_path(), "write", path]
    else:
        argv = ["pkexec", helper_path(), "write", path]
    flags = (Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE
             | Gio.SubprocessFlags.STDERR_PIPE)
    proc = _launcher(flags).spawnv(argv)

    def done(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
            ok = p.get_if_exited() and p.get_exit_status() == 0
        except GLib.Error as e:
            ok, out, err = False, "", e.message
        if callback:
            callback(ok, out or "", err or "")

    proc.communicate_utf8_async(content, None, done)


def read_file(path, root=False):
    """Liest eine Datei. Mit root=True wird bei fehlenden Rechten pkexec genutzt."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except PermissionError:
        if root:
            ok, out, _ = run_sync(["cat", path], root=True)
            return out if ok else ""
        return ""
    except OSError:
        return ""


def launch(cmd):
    """Externes Programm (GUI) losgelöst starten."""
    try:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# UI-Helfer
# --------------------------------------------------------------------------

def get_window(widget):
    root = widget.get_root() if widget else None
    return root if isinstance(root, Gtk.Window) else None


def toast(widget, text):
    win = get_window(widget)
    if win is not None and hasattr(win, "show_toast"):
        win.show_toast(text)


def error(widget, heading, text):
    dlg = Adw.AlertDialog(heading=heading, body=(text or "").strip()[-3000:])
    dlg.add_response("ok", "OK")
    dlg.present(get_window(widget))


def confirm(widget, heading, body, action_label, callback, destructive=True):
    dlg = Adw.AlertDialog(heading=heading, body=body)
    dlg.add_response("cancel", "Abbrechen")
    dlg.add_response("ok", action_label)
    dlg.set_response_appearance(
        "ok",
        Adw.ResponseAppearance.DESTRUCTIVE if destructive
        else Adw.ResponseAppearance.SUGGESTED,
    )
    dlg.set_default_response("cancel")
    dlg.connect("response", lambda _d, r: r == "ok" and callback())
    dlg.present(get_window(widget))


def ask(widget, heading, fields, callback, body=None, action_label="OK"):
    """Formular-Dialog.

    fields: Liste von Dicts {key, label, default, kind}
    kind: "text" (Standard), "password", "switch", "combo" (mit options=[...])
    callback(values: dict)
    """
    dlg = Adw.AlertDialog(heading=heading, body=body or "")
    box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    box.add_css_class("boxed-list")
    rows = {}
    for f in fields:
        kind = f.get("kind", "text")
        if kind == "password":
            row = Adw.PasswordEntryRow(title=f["label"])
        elif kind == "switch":
            row = Adw.SwitchRow(title=f["label"], active=bool(f.get("default")))
        elif kind == "combo":
            opts = f["options"]
            row = Adw.ComboRow(title=f["label"], model=Gtk.StringList.new(opts))
            if f.get("default") in opts:
                row.set_selected(opts.index(f["default"]))
        else:
            row = Adw.EntryRow(title=f["label"])
            row.set_text(str(f.get("default", "") or ""))
        rows[f["key"]] = (kind, row, f)
        box.append(row)
    dlg.set_extra_child(box)
    dlg.add_response("cancel", "Abbrechen")
    dlg.add_response("ok", action_label)
    dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dlg.set_default_response("ok")

    def on_response(_d, r):
        if r != "ok":
            return
        values = {}
        for key, (kind, row, f) in rows.items():
            if kind == "switch":
                values[key] = row.get_active()
            elif kind == "combo":
                values[key] = f["options"][row.get_selected()]
            else:
                values[key] = row.get_text()
        callback(values)

    dlg.connect("response", on_response)
    dlg.present(get_window(widget))


class LogDialog(Adw.Dialog):
    """Führt einen (langen) Befehl aus und zeigt die Ausgabe live an."""

    def __init__(self, widget, title, cmd, root=False, on_done=None):
        super().__init__(title=title, content_width=760, content_height=520)
        self.on_done = on_done
        self.ok = False
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        self.spinner = Adw.Spinner()
        hb.pack_start(self.spinner)
        tv.add_top_bar(hb)
        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.set_margin_start(12)
        view.set_margin_end(12)
        view.set_margin_top(6)
        view.set_margin_bottom(6)
        self.scroller = Gtk.ScrolledWindow(child=view, vexpand=True)
        tv.set_content(self.scroller)
        self.status = Gtk.Label(label="Läuft …", xalign=0)
        self.status.set_margin_start(12)
        self.status.set_margin_end(12)
        self.status.set_margin_top(8)
        self.status.set_margin_bottom(8)
        tv.add_bottom_bar(self.status)
        self.set_child(tv)
        self.connect("closed", self._on_closed)
        self.present(get_window(widget))
        self._start(_argv(cmd, root))

    def _append(self, text):
        self.buffer.insert(self.buffer.get_end_iter(), text)
        adj = self.scroller.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) and False)

    def _start(self, argv):
        flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
        self._append("$ " + " ".join(argv) + "\n")
        try:
            self.proc = _launcher(flags).spawnv(argv)
        except GLib.Error as e:
            self._finish(False, e.message)
            return
        self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self._read()

    def _read(self):
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line)

    def _on_line(self, stream, res):
        try:
            line, _len = stream.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            self.proc.wait_async(None, self._on_exit)
            return
        self._append(line.replace("\r", "") + "\n")
        self._read()

    def _on_exit(self, proc, res):
        try:
            proc.wait_finish(res)
        except GLib.Error:
            pass
        ok = proc.get_if_exited() and proc.get_exit_status() == 0
        self._finish(ok, None)

    def _finish(self, ok, msg):
        self.ok = ok
        self.spinner.set_visible(False)
        if msg:
            self._append(msg + "\n")
        self.status.set_label("✔ Erfolgreich abgeschlossen" if ok
                              else "✘ Fehlgeschlagen oder abgebrochen")
        if self.on_done:
            cb, self.on_done = self.on_done, None
            cb(ok)

    def _on_closed(self, *_a):
        proc = getattr(self, "proc", None)
        if proc is not None and not proc.get_if_exited():
            proc.force_exit()


def label_row(title, subtitle="", suffix_text=None):
    row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                        subtitle=GLib.markup_escape_text(subtitle or ""))
    row.set_subtitle_lines(2)
    if suffix_text is not None:
        lbl = Gtk.Label(label=str(suffix_text), xalign=1, wrap=True,
                        selectable=True, max_width_chars=40)
        lbl.add_css_class("dim-label")
        row.add_suffix(lbl)
    return row


def icon_button(icon, tooltip, callback, *args, css=None):
    b = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    b.add_css_class("flat")
    if css:
        b.add_css_class(css)
    b.connect("clicked", lambda *_: callback(*args))
    return b


def text_button(label, callback, *args, css=None):
    b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
    if css:
        b.add_css_class(css)
    b.connect("clicked", lambda *_: callback(*args))
    return b


def esc(text):
    return GLib.markup_escape_text(str(text or ""))


# --------------------------------------------------------------------------
# Basis-Klasse für Module
# --------------------------------------------------------------------------

class Module(Gtk.Box):
    """Basis für alle Module. Unterklassen setzen die Klassenattribute
    und implementieren refresh()."""

    id = ""
    title = ""
    icon = "applications-system-symbolic"
    category = "System"
    description = ""
    keywords = ""
    requires = ()  # Programme, die vorhanden sein müssen

    @classmethod
    def available(cls):
        return all(have(b) for b in cls.requires)

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.page = Adw.PreferencesPage()
        self._groups = []
        self.header_widgets = []
        self.append(self.page)
        self.page.set_vexpand(True)

    # Kopfzeilen-Buttons (werden vom Fenster in die HeaderBar gesetzt)
    def add_header_button(self, icon, tooltip, callback):
        b = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
        b.connect("clicked", lambda *_: callback())
        self.header_widgets.append(b)
        return b

    def clear(self):
        for g in self._groups:
            self.page.remove(g)
        self._groups = []

    def group(self, title="", description="", suffix=None):
        g = Adw.PreferencesGroup(title=esc(title), description=esc(description))
        if suffix is not None:
            g.set_header_suffix(suffix)
        self.page.add(g)
        self._groups.append(g)
        return g

    def placeholder(self, text):
        g = self.group()
        lbl = Gtk.Label(label=text, wrap=True)
        lbl.add_css_class("dim-label")
        lbl.set_margin_top(24)
        g.add(lbl)
        return g

    def refresh(self):
        pass

    def activate(self):
        """Wird beim ersten Anzeigen aufgerufen."""
        self.refresh()

    # Bequeme Wrapper
    def run_root(self, cmd, success_msg=None, then=None, input=None):
        def cb(ok, out, err):
            if ok:
                if success_msg:
                    toast(self, success_msg)
            elif "dismissed" in err.lower() or "126" in err or "Not authorized" in err:
                toast(self, "Authentifizierung abgebrochen")
            else:
                error(self, "Fehler", err or out or "Unbekannter Fehler")
            if then:
                then(ok)
            else:
                self.refresh()
        run(cmd, cb, root=True, input=input)

    def run_user(self, cmd, success_msg=None, then=None):
        def cb(ok, out, err):
            if ok and success_msg:
                toast(self, success_msg)
            if not ok:
                error(self, "Fehler", err or out)
            if then:
                then(ok)
            else:
                self.refresh()
        run(cmd, cb)

    def log(self, title, cmd, root=True):
        LogDialog(self, title, cmd, root=root, on_done=lambda ok: self.refresh())
