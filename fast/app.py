"""Hauptfenster: Kontrollzentrum mit Kategorien und Modulen (wie YaST)."""
import sys

from .util import Adw, Gio, GLib, Gtk, esc  # noqa: F401  (lädt gi-Versionen)
from . import APP_ID, __version__
from .modules import CATEGORIES, available_modules


class Window(Adw.ApplicationWindow):
    def __init__(self, app, start_module=None):
        super().__init__(application=app, title="FAST – Systemverwaltung",
                         default_width=1180, default_height=780)
        self.modules = available_modules()
        self.by_id = {m.id: m for m in self.modules}
        self.instances = {}
        self.header_extra = []

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.split = Adw.NavigationSplitView(min_sidebar_width=260, max_sidebar_width=340)
        self.toasts.set_child(self.split)

        # ---------- Seitenleiste ----------
        side_tv = Adw.ToolbarView()
        side_hb = Adw.HeaderBar()
        side_hb.set_title_widget(Adw.WindowTitle(title="FAST", subtitle="Fedora-Verwaltung"))
        menu = Gio.Menu()
        menu.append("Über FAST", "app.about")
        side_hb.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))
        side_tv.add_top_bar(side_hb)
        side_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.search = Gtk.SearchEntry(placeholder_text="Modul suchen …")
        self.search.set_margin_start(8)
        self.search.set_margin_end(8)
        self.search.set_margin_bottom(6)
        self.search.connect("search-changed", lambda *_: self.listbox.invalidate_filter())
        self.search.connect("activate", self._search_activate)
        side_box.append(self.search)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.set_header_func(self._header)
        self.listbox.set_filter_func(self._filter)
        self.listbox.connect("row-activated", lambda _l, r: self.open(r.module_id))
        home = self._row("home", "Übersicht", "go-home-symbolic", "")
        self.listbox.append(home)
        order = [c for c, _ in CATEGORIES]
        for m in sorted(self.modules, key=lambda m: (order.index(m.category)
                                                     if m.category in order else 99)):
            self.listbox.append(self._row(m.id, m.title, m.icon, m.category,
                                          f"{m.title} {m.description} {m.keywords}"))
        side_box.append(Gtk.ScrolledWindow(child=self.listbox, vexpand=True,
                                           hscrollbar_policy=Gtk.PolicyType.NEVER))
        side_tv.set_content(side_box)
        self.split.set_sidebar(Adw.NavigationPage(title="FAST", child=side_tv))

        # ---------- Inhalt ----------
        self.content_tv = Adw.ToolbarView()
        self.content_hb = Adw.HeaderBar()
        self.content_title = Adw.WindowTitle(title="Übersicht")
        self.content_hb.set_title_widget(self.content_title)
        self.content_tv.add_top_bar(self.content_hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.content_tv.set_content(self.stack)
        self.stack.add_named(self._overview(), "home")
        self.content_page = Adw.NavigationPage(title="Übersicht", child=self.content_tv)
        self.split.set_content(self.content_page)

        # Schmale Fenster: Seitenleiste einklappen
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 720sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)

        key = Gtk.ShortcutController()
        key.add_shortcut(Gtk.Shortcut.new(Gtk.ShortcutTrigger.parse_string("<Control>f"),
                                          Gtk.CallbackAction.new(
                                              lambda *_: self.search.grab_focus() or True)))
        self.add_controller(key)

        self.open(start_module if start_module in self.by_id else "home")

    # ---------------------------------------------------------------
    def _row(self, mid, title, icon, category, haystack=""):
        row = Gtk.ListBoxRow()
        row.module_id = mid
        row.category = category
        row.haystack = (haystack or title).lower()
        box = Gtk.Box(spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=title, xalign=0, ellipsize=3))
        row.set_child(box)
        return row

    def _header(self, row, before):
        if row.category and (before is None or before.category != row.category):
            lbl = Gtk.Label(label=row.category, xalign=0)
            lbl.add_css_class("heading")
            lbl.add_css_class("dim-label")
            lbl.set_margin_top(12)
            lbl.set_margin_start(12)
            lbl.set_margin_bottom(4)
            row.set_header(lbl)
        else:
            row.set_header(None)

    def _filter(self, row):
        q = self.search.get_text().strip().lower()
        if not q:
            return True
        return row.module_id != "home" and all(w in row.haystack for w in q.split())

    def _search_activate(self, *_):
        row = self.listbox.get_first_child()
        while row is not None:
            if isinstance(row, Gtk.ListBoxRow) and row.get_child_visible() and \
                    self._filter(row) and row.module_id != "home":
                self.open(row.module_id)
                return
            row = row.get_next_sibling()

    def _overview(self):
        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup()
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       halign=Gtk.Align.CENTER)
        head.set_margin_top(18)
        head.set_margin_bottom(6)
        head.append(Gtk.Image(icon_name=APP_ID, pixel_size=96))
        title = Gtk.Label(label="Systemverwaltung")
        title.add_css_class("title-1")
        head.append(title)
        sub = Gtk.Label(label="Alle Einstellungen deines Fedora-Systems an einem Ort. "
                              "Wähle ein Modul aus.", wrap=True, justify=Gtk.Justification.CENTER)
        sub.add_css_class("dim-label")
        head.append(sub)
        intro.add(head)
        page.add(intro)
        for cat, _icon in CATEGORIES:
            mods = [m for m in self.modules if m.category == cat]
            if not mods:
                continue
            g = Adw.PreferencesGroup(title=cat)
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                               min_children_per_line=1, column_spacing=8, row_spacing=8,
                               homogeneous=True)
            for m in mods:
                btn = Gtk.Button()
                btn.add_css_class("card")
                box = Gtk.Box(spacing=12)
                for side in ("top", "bottom", "start", "end"):
                    getattr(box, f"set_margin_{side}")(10)
                box.append(Gtk.Image(icon_name=m.icon, pixel_size=32))
                txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                t = Gtk.Label(label=m.title, xalign=0, wrap=True)
                t.add_css_class("heading")
                d = Gtk.Label(label=m.description, xalign=0, wrap=True)
                d.add_css_class("dim-label")
                d.add_css_class("caption")
                txt.append(t)
                txt.append(d)
                box.append(txt)
                btn.set_child(box)
                btn.connect("clicked", lambda _b, mid=m.id: self.open(mid))
                flow.append(btn)
            g.add(flow)
            page.add(g)
        return page

    def open(self, mid):
        for w in self.header_extra:
            self.content_hb.remove(w)
        self.header_extra = []
        if mid == "home":
            self.stack.set_visible_child_name("home")
            self.content_title.set_title("Übersicht")
            self.content_title.set_subtitle("")
            self.content_page.set_title("Übersicht")
        else:
            cls = self.by_id[mid]
            inst = self.instances.get(mid)
            first = inst is None
            if first:
                inst = cls()
                self.instances[mid] = inst
                self.stack.add_named(inst, mid)
            self.stack.set_visible_child_name(mid)
            self.content_title.set_title(cls.title)
            self.content_title.set_subtitle(cls.description)
            self.content_page.set_title(cls.title)
            for w in inst.header_widgets:
                self.content_hb.pack_end(w)
                self.header_extra.append(w)
            if first:
                GLib.idle_add(lambda: self._activate(inst) and False)
        self._select(mid)
        self.split.set_show_content(True)

    def _activate(self, inst):
        try:
            inst.activate()
        except Exception as e:  # Modulfehler sollen das Programm nicht beenden
            import traceback
            traceback.print_exc()
            inst.clear()
            inst.placeholder(f"Fehler beim Laden des Moduls:\n{e}")

    def _select(self, mid):
        row = self.listbox.get_first_child()
        while row is not None:
            if getattr(row, "module_id", None) == mid:
                self.listbox.select_row(row)
                return
            row = row.get_next_sibling()

    def show_toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=esc(text), timeout=3))


class App(Adw.Application):
    def __init__(self, start_module=None):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.start_module = start_module
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._about)
        self.add_action(about)

    def do_activate(self):
        # Beim Start aus dem Quellordner das mitgelieferte Icon finden
        import os
        from gi.repository import Gdk
        icons = os.path.join(os.path.dirname(__file__), "..", "data", "icons")
        display = Gdk.Display.get_default()
        if os.path.isdir(icons) and display is not None:
            Gtk.IconTheme.get_for_display(display).add_search_path(os.path.abspath(icons))
        Gtk.Window.set_default_icon_name(APP_ID)
        win = self.props.active_window or Window(self, self.start_module)
        win.present()

    def _about(self, *_):
        Adw.AboutDialog(application_name="FAST", application_icon="de.pattiit.Fast",
                        version=__version__, developer_name="Raphael-Leon Patti",
                        comments="Fedora Administration & Setup Tool – "
                                 "Systemverwaltung im Stil von YaST",
                        license_type=Gtk.License.MIT_X11).present(self.props.active_window)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if len(argv) > 1 and argv[1] in ("-l", "--list"):
        for m in available_modules():
            print(f"{m.id:14} {m.category:26} {m.title}")
        return 0
    if len(argv) > 1 and argv[1] in ("-h", "--help"):
        print("Aufruf: fast [MODUL]\n       fast --list    verfügbare Module anzeigen")
        return 0
    start = argv[1] if len(argv) > 1 and not argv[1].startswith("-") else None
    return App(start).run([argv[0]])


if __name__ == "__main__":
    sys.exit(main())
