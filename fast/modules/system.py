"""System: Dienste, Protokolle, Bootloader, Zeit, Sprache, Hostname, Kernel,
Energieprofile, Snapshots, geplante Aufgaben, Systeminfo."""
import json
import os
import platform
import re

from gi.repository import Adw, Gtk

from ..util import (Module, ask, confirm, error, esc, icon_button, label_row,
                    read_file, run, run_sync, text_button, toast,
                    write_root_file)


# --------------------------------------------------------------------------
class Services(Module):
    id = "services"
    title = "Dienste-Verwaltung"
    icon = "system-run-symbolic"
    category = "System"
    description = "systemd-Dienste starten, stoppen, aktivieren"
    keywords = "systemd service dienst unit start stop enable runlevel target"
    requires = ("systemctl",)

    def __init__(self):
        super().__init__()
        bar = Gtk.Box(spacing=6)
        for m in ("margin_start", "margin_end", "margin_top"):
            bar.set_property(m, 12)
        self.filter = Gtk.SearchEntry(placeholder_text="Dienste filtern …", hexpand=True)
        self.filter.connect("search-changed", lambda *_: self._render())
        self.scope = Gtk.DropDown.new_from_strings(["System", "Benutzer"])
        self.scope.connect("notify::selected", lambda *_: self.refresh())
        self.show = Gtk.DropDown.new_from_strings(["Alle", "Laufend", "Fehlgeschlagen",
                                                   "Aktiviert", "Deaktiviert"])
        self.show.connect("notify::selected", lambda *_: self._render())
        bar.append(self.filter)
        bar.append(self.scope)
        bar.append(self.show)
        self.prepend(bar)
        self.units = []
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    @property
    def user(self):
        return self.scope.get_selected() == 1

    def _sc(self, *args):
        return ["systemctl", *(["--user"] if self.user else []), *args]

    def refresh(self):
        ok1, units, _ = run_sync(self._sc("list-units", "--type=service", "--all",
                                          "--output=json"))
        ok2, files, _ = run_sync(self._sc("list-unit-files", "--type=service",
                                          "--output=json"))
        try:
            units = json.loads(units) if ok1 else []
            files = json.loads(files) if ok2 else []
        except ValueError:
            units, files = [], []
        states = {f["unit_file"]: f["state"] for f in files}
        merged = {}
        for u in units:
            merged[u["unit"]] = dict(u, state=states.get(u["unit"], ""))
        for name, st in states.items():
            if name not in merged and not name.endswith("@.service"):
                merged[name] = {"unit": name, "active": "inactive", "sub": "dead",
                                "description": "", "state": st}
        self.units = sorted(merged.values(), key=lambda u: u["unit"])
        self._render()

    def _render(self):
        self.clear()
        f = self.filter.get_text().lower()
        mode = self.show.get_selected()
        shown = []
        for u in self.units:
            if f and f not in u["unit"].lower() and f not in u.get("description", "").lower():
                continue
            if mode == 1 and u["active"] != "active":
                continue
            if mode == 2 and u["active"] != "failed":
                continue
            if mode == 3 and u["state"] != "enabled":
                continue
            if mode == 4 and u["state"] != "disabled":
                continue
            shown.append(u)
        g = self.group(f"{len(shown)} Dienste")
        for u in shown[:400]:
            name = u["unit"]
            row = Adw.ActionRow(title=esc(name.removesuffix(".service")),
                                subtitle=esc(f"{u.get('description', '')}\n"
                                             f"{u['active']} ({u['sub']}) · {u['state'] or '–'}"))
            row.set_subtitle_lines(2)
            dot = Gtk.Image.new_from_icon_name("media-record-symbolic")
            dot.add_css_class("success" if u["active"] == "active"
                              else "error" if u["active"] == "failed" else "dim-label")
            dot.set_tooltip_text(u["active"])
            row.add_prefix(dot)
            if u["state"] in ("enabled", "disabled"):
                sw = Gtk.Switch(active=u["state"] == "enabled", valign=Gtk.Align.CENTER,
                                tooltip_text="Beim Systemstart aktivieren")
                sw.connect("state-set", self._enable, name)
                row.add_suffix(sw)
            if u["active"] == "active":
                row.add_suffix(icon_button("view-refresh-symbolic", "Neu starten",
                                           self._act, "restart", name))
                row.add_suffix(icon_button("media-playback-stop-symbolic", "Stoppen",
                                           self._act, "stop", name))
            else:
                row.add_suffix(icon_button("media-playback-start-symbolic", "Starten",
                                           self._act, "start", name))
            row.add_suffix(icon_button("text-x-generic-symbolic", "Status & Log",
                                       self._status, name))
            g.add(row)

    def _act(self, action, name):
        cmd = self._sc(action, name)
        msg = f"{name}: {action} ausgeführt"
        if self.user:
            self.run_user(cmd, msg)
        else:
            self.run_root(cmd, msg)

    def _enable(self, sw, state, name):
        cmd = self._sc("enable" if state else "disable", name)
        if self.user:
            self.run_user(cmd, f"{name} {'aktiviert' if state else 'deaktiviert'}")
        else:
            self.run_root(cmd, f"{name} {'aktiviert' if state else 'deaktiviert'}")
        return False

    def _status(self, name):
        _, out, err = run_sync(self._sc("status", "--no-pager", "-n", "40", name))
        error(self, name, out or err)


# --------------------------------------------------------------------------
class Journal(Module):
    id = "journal"
    title = "Systemprotokolle"
    icon = "document-properties-symbolic"
    category = "System"
    description = "journald- und Kernel-Protokolle durchsuchen"
    keywords = "log journal protokoll dmesg kernel fehler boot"
    requires = ("journalctl",)

    PRIOS = ["Alle", "emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]

    def __init__(self):
        super().__init__()
        self.remove(self.page)
        bar = Gtk.Box(spacing=6)
        for m in ("margin_start", "margin_end", "margin_top", "margin_bottom"):
            bar.set_property(m, 12 if m != "margin_bottom" else 6)
        self.unit = Gtk.Entry(placeholder_text="Unit (optional, z. B. sshd)")
        self.grep = Gtk.SearchEntry(placeholder_text="Text suchen …", hexpand=True)
        self.prio = Gtk.DropDown.new_from_strings(self.PRIOS)
        self.prio.set_selected(4)
        self.boot = Gtk.DropDown.new_from_strings(["Aktueller Start", "Vorheriger Start",
                                                   "Alle Starts"])
        self.kernel = Gtk.CheckButton(label="Nur Kernel")
        self.lines = Gtk.SpinButton.new_with_range(50, 20000, 50)
        self.lines.set_value(500)
        for w in (self.unit, self.grep, self.prio, self.boot, self.kernel, self.lines):
            bar.append(w)
            if hasattr(w, "connect") and isinstance(w, (Gtk.Entry, Gtk.SearchEntry)):
                w.connect("activate", lambda *_: self.refresh())
        bar.append(text_button("Anzeigen", self.refresh, css="suggested-action"))
        self.append(bar)
        self.buffer = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self.buffer, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(12)
        self.append(Gtk.ScrolledWindow(child=view, vexpand=True))
        self.root_box = Gtk.CheckButton(label="Als root (alle Logs)")
        self.root_box.set_margin_start(12)
        self.root_box.set_margin_bottom(6)
        self.append(self.root_box)
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        cmd = ["journalctl", "--no-pager", "-o", "short-iso", "-n",
               str(int(self.lines.get_value()))]
        b = self.boot.get_selected()
        if b == 0:
            cmd.append("-b")
        elif b == 1:
            cmd.append("-b-1")
        if self.prio.get_selected() > 0:
            cmd += ["-p", self.PRIOS[self.prio.get_selected()]]
        if self.kernel.get_active():
            cmd.append("-k")
        if self.unit.get_text().strip():
            cmd += ["-u", self.unit.get_text().strip()]
        if self.grep.get_text().strip():
            cmd += ["-g", self.grep.get_text().strip(), "--case-sensitive=false"]
        self.buffer.set_text("Lade …")
        run(cmd, lambda ok, out, err: self.buffer.set_text(out or err or "(keine Einträge)"),
            root=self.root_box.get_active())


# --------------------------------------------------------------------------
class Bootloader(Module):
    id = "bootloader"
    title = "Bootloader"
    icon = "drive-harddisk-system-symbolic"
    category = "System"
    description = "Kernel-Auswahl, Standard-Kernel, Kernel-Parameter, Timeout"
    keywords = "grub boot kernel parameter cmdline timeout grubby"
    requires = ("grubby",)

    def activate(self):
        self.clear()
        g = self.placeholder("Für das Lesen der Boot-Einträge sind Root-Rechte nötig.")
        b = text_button("Boot-Einträge laden", self.refresh, css="suggested-action")
        b.set_halign(Gtk.Align.CENTER)
        b.set_margin_top(12)
        g.add(b)

    def refresh(self):
        def got_default(ok, out, err):
            self._default_index = out.strip()
            run(["grubby", "--info=ALL"], self._show, root=True)
        run(["grubby", "--default-index"], got_default, root=True)

    def _show(self, ok, out, err):
        if not ok:
            error(self, "Bootloader", err)
            return
        self.clear()
        entries, cur = [], None
        for line in out.splitlines():
            m = re.match(r'(\w+)=("?)(.*)\2$', line.strip())
            if not m:
                continue
            k, v = m[1], m[3]
            if k == "index":
                cur = {"index": v}
                entries.append(cur)
            elif cur is not None:
                cur[k] = v
        default = getattr(self, "_default_index", "")
        grub = read_file("/etc/default/grub")
        timeout = re.search(r'^GRUB_TIMEOUT=(\S+)', grub, re.M)
        running = platform.release()

        g = self.group("Allgemein")
        g.add(label_row("Laufender Kernel", running))
        g.add(label_row("Kernel-Parameter (aktuell)", read_file("/proc/cmdline").strip()))
        t = Adw.SpinRow.new_with_range(0, 60, 1)
        t.set_title("Wartezeit im Bootmenü (Sekunden)")
        t.set_value(float(timeout[1].strip('"')) if timeout else 5)
        t.add_suffix(text_button("Übernehmen", self._timeout, t, grub))
        g.add(t)
        sb = run_sync(["mokutil", "--sb-state"])[1].strip()
        if sb:
            g.add(label_row("Secure Boot", sb))

        g = self.group("Boot-Einträge")
        for e in entries:
            if "kernel" not in e:
                continue
            is_def = e["index"] == default
            row = Adw.ActionRow(title=esc(e.get("title", e["kernel"])),
                                subtitle=esc(f"{e['kernel']}\nParameter: {e.get('args', '')}"))
            row.set_subtitle_lines(3)
            if is_def:
                lbl = Gtk.Label(label="Standard")
                lbl.add_css_class("accent")
                row.add_suffix(lbl)
            else:
                row.add_suffix(text_button("Als Standard", self._default, e["kernel"]))
            g.add(row)

        g = self.group("Kernel-Parameter für alle Kernel",
                       "Fügt Parameter hinzu oder entfernt sie (grubby --update-kernel=ALL)")
        add = Adw.EntryRow(title="Parameter hinzufügen (z. B. quiet nvidia-drm.modeset=1)")
        add.add_suffix(icon_button("list-add-symbolic", "Hinzufügen",
                                   lambda: self._args("--args", add.get_text())))
        rem = Adw.EntryRow(title="Parameter entfernen (z. B. rhgb)")
        rem.add_suffix(icon_button("list-remove-symbolic", "Entfernen",
                                   lambda: self._args("--remove-args", rem.get_text())))
        g.add(add)
        g.add(rem)

    def _default(self, kernel):
        self.run_root(["grubby", "--set-default", kernel], "Standard-Kernel gesetzt")

    def _args(self, flag, val):
        if val.strip():
            self.run_root(["grubby", "--update-kernel=ALL", f"{flag}={val.strip()}"],
                          "Kernel-Parameter geändert (wirkt nach Neustart)")

    def _timeout(self, spin, grub):
        val = int(spin.get_value())
        if re.search(r"^GRUB_TIMEOUT=", grub, re.M):
            new = re.sub(r"^GRUB_TIMEOUT=.*$", f"GRUB_TIMEOUT={val}", grub, flags=re.M)
        else:
            new = grub.rstrip("\n") + f"\nGRUB_TIMEOUT={val}\n"

        def after(ok, out, err):
            if not ok:
                error(self, "Fehler", err)
                return
            target = "/boot/grub2/grub.cfg"
            self.log("GRUB-Konfiguration erzeugen", ["grub2-mkconfig", "-o", target])
        write_root_file("/etc/default/grub", new, after)


# --------------------------------------------------------------------------
class DateTime(Module):
    id = "datetime"
    title = "Datum und Uhrzeit"
    icon = "preferences-system-time-symbolic"
    category = "System"
    description = "Zeitzone, NTP-Synchronisation, Uhrzeit"
    keywords = "zeit uhr datum zeitzone ntp timezone"
    requires = ("timedatectl",)

    def refresh(self):
        self.clear()
        _, out, _ = run_sync(["timedatectl", "show"])
        info = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        _, zones, _ = run_sync(["timedatectl", "list-timezones"])
        zones = zones.split()
        g = self.group("Aktuell")
        g.add(label_row("Lokale Zeit", info.get("TimeUSec", "")))
        g.add(label_row("Synchronisiert", "ja" if info.get("NTPSynchronized") == "yes" else "nein"))
        g = self.group("Einstellungen")
        z = Adw.ComboRow(title="Zeitzone", model=Gtk.StringList.new(zones),
                         enable_search=True)
        z.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        if info.get("Timezone") in zones:
            z.set_selected(zones.index(info["Timezone"]))
        z.connect("notify::selected", lambda r, _p: self.run_root(
            ["timedatectl", "set-timezone", zones[r.get_selected()]],
            f"Zeitzone: {zones[r.get_selected()]}"))
        g.add(z)
        ntp = Adw.SwitchRow(title="Automatisch über das Internet (NTP)",
                            active=info.get("NTP") == "yes")
        ntp.connect("notify::active", lambda r, _p: self.run_root(
            ["timedatectl", "set-ntp", "true" if r.get_active() else "false"], "NTP geändert"))
        g.add(ntp)
        rtc = Adw.SwitchRow(title="Hardware-Uhr in Ortszeit",
                            subtitle="Nur für Dual-Boot mit Windows sinnvoll",
                            active=info.get("LocalRTC") == "yes")
        rtc.connect("notify::active", lambda r, _p: self.run_root(
            ["timedatectl", "set-local-rtc", "1" if r.get_active() else "0"],
            "Hardware-Uhr geändert"))
        g.add(rtc)
        e = Adw.EntryRow(title="Uhrzeit manuell setzen (JJJJ-MM-TT HH:MM:SS, NTP muss aus sein)")
        e.add_suffix(icon_button("object-select-symbolic", "Setzen", lambda: self.run_root(
            ["timedatectl", "set-time", e.get_text().strip()], "Zeit gesetzt")))
        g.add(e)


# --------------------------------------------------------------------------
class Language(Module):
    id = "language"
    title = "Sprache und Tastatur"
    icon = "preferences-desktop-locale-symbolic"
    category = "System"
    description = "Systemsprache (Locale) und Tastaturbelegung"
    keywords = "sprache locale tastatur keyboard keymap layout"
    requires = ("localectl",)

    def refresh(self):
        self.clear()
        _, st, _ = run_sync(["localectl", "status"])
        cur = {}
        for line in st.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                cur[k.strip()] = v.strip()
        lang = re.search(r"LANG=(\S+)", cur.get("System Locale", ""))
        lang = lang[1] if lang else ""
        _, locales, _ = run_sync(["localectl", "list-locales"])
        locales = locales.split() or [lang]
        _, keymaps, _ = run_sync(["localectl", "list-keymaps"])
        keymaps = keymaps.split()
        _, x11, _ = run_sync(["localectl", "list-x11-keymap-layouts"])
        x11 = x11.split()

        def combo(title, items, current, cb):
            r = Adw.ComboRow(title=title, model=Gtk.StringList.new(items), enable_search=True)
            r.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
            if current in items:
                r.set_selected(items.index(current))
            r.connect("notify::selected", lambda w, _p: cb(items[w.get_selected()]))
            return r

        g = self.group("Systemsprache", "Gilt für Anmeldebildschirm und neue Benutzer. "
                       "Die Sprache deiner Sitzung stellst du in GNOME ein.")
        g.add(combo("Locale (LANG)", locales, lang, lambda v: self.run_root(
            ["localectl", "set-locale", f"LANG={v}"], f"Sprache: {v}")))
        r = Adw.ActionRow(title="Sprachpakete installieren")
        r.add_suffix(text_button("Deutsch", lambda: self.log(
            "Sprachpaket", ["dnf5", "install", "-y", "glibc-langpack-de",
                            "langpacks-de"])))
        g.add(r)
        g = self.group("Tastatur")
        g.add(combo("Konsole (VC Keymap)", keymaps, cur.get("VC Keymap", ""),
                    lambda v: self.run_root(["localectl", "set-keymap", v],
                                            f"Konsolen-Tastatur: {v}")))
        g.add(combo("Grafisch (X11/Wayland Layout)", x11, cur.get("X11 Layout", ""),
                    lambda v: self.run_root(["localectl", "set-x11-keymap", v],
                                            f"Layout: {v}")))


# --------------------------------------------------------------------------
class Hostname(Module):
    id = "hostname"
    title = "Rechnername"
    icon = "computer-symbolic"
    category = "System"
    description = "Hostname, angezeigter Name, Gerätetyp"
    keywords = "hostname name rechner computer chassis"
    requires = ("hostnamectl",)

    def refresh(self):
        self.clear()
        _, out, _ = run_sync(["hostnamectl", "--json=short"])
        try:
            info = json.loads(out)
        except ValueError:
            info = {}
        g = self.group("Rechnername")
        for key, label, flag in (("StaticHostname", "Hostname", "--static"),
                                 ("PrettyHostname", "Angezeigter Name", "--pretty")):
            e = Adw.EntryRow(title=label)
            e.set_text(info.get(key) or "")
            e.set_show_apply_button(True)
            e.connect("apply", lambda w, f=flag: self.run_root(
                ["hostnamectl", "hostname", f, w.get_text().strip()], "Name geändert"))
            g.add(e)
        chassis = ["desktop", "laptop", "convertible", "server", "tablet", "handset",
                   "watch", "embedded", "vm", "container"]
        c = Adw.ComboRow(title="Gerätetyp", model=Gtk.StringList.new(chassis))
        if info.get("Chassis") in chassis:
            c.set_selected(chassis.index(info["Chassis"]))
        c.connect("notify::selected", lambda w, _p: self.run_root(
            ["hostnamectl", "chassis", chassis[w.get_selected()]], "Gerätetyp geändert"))
        g.add(c)
        g = self.group("System")
        for key, label in (("OperatingSystemPrettyName", "Betriebssystem"),
                           ("KernelRelease", "Kernel"),
                           ("HardwareVendor", "Hersteller"),
                           ("HardwareModel", "Modell"),
                           ("FirmwareVersion", "Firmware"),
                           ("MachineID", "Machine-ID")):
            if info.get(key):
                g.add(label_row(label, "", info[key]))


# --------------------------------------------------------------------------
class Sysctl(Module):
    id = "sysctl"
    title = "Kernel-Einstellungen (sysctl)"
    icon = "preferences-other-symbolic"
    category = "System"
    description = "Kernel-Parameter anzeigen und dauerhaft setzen"
    keywords = "sysctl kernel swappiness ip_forward parameter tuning"
    requires = ("sysctl",)
    CONF = "/etc/sysctl.d/90-fast.conf"
    COMMON = [
        ("vm.swappiness", "Neigung zum Auslagern (0–200)"),
        ("vm.dirty_ratio", "Max. Anteil „dirty“ Speicher in %"),
        ("net.ipv4.ip_forward", "IPv4-Weiterleitung (Routing)"),
        ("net.ipv6.conf.all.forwarding", "IPv6-Weiterleitung"),
        ("kernel.sysrq", "Magic SysRq-Taste"),
        ("fs.inotify.max_user_watches", "Max. inotify-Watches"),
        ("vm.max_map_count", "Max. Memory-Maps (Spiele, Elasticsearch)"),
        ("net.core.default_qdisc", "Standard-Warteschlange"),
        ("net.ipv4.tcp_congestion_control", "TCP-Staukontrolle"),
        ("kernel.dmesg_restrict", "dmesg nur für root"),
    ]

    def __init__(self):
        super().__init__()
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def _custom(self):
        res = {}
        for line in read_file(self.CONF).splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                res[k.strip()] = v.strip()
        return res

    def refresh(self):
        self.clear()
        custom = self._custom()
        g = self.group("Häufig genutzt",
                       f"Änderungen werden sofort gesetzt und in {self.CONF} gespeichert")
        for key, desc in self.COMMON:
            ok, val, _ = run_sync(["sysctl", "-n", key])
            if not ok:
                continue
            e = Adw.EntryRow(title=f"{key} – {desc}")
            e.set_text(val.strip())
            e.set_show_apply_button(True)
            e.connect("apply", lambda w, k=key: self._set(k, w.get_text().strip()))
            g.add(e)
        g = self.group("Eigene dauerhafte Einstellungen")
        for k, v in custom.items():
            row = label_row(k, "", v)
            row.add_suffix(icon_button("user-trash-symbolic", "Entfernen", self._unset, k))
            g.add(row)
        e = Adw.EntryRow(title="Neu: schlüssel = wert")
        e.set_show_apply_button(True)
        e.connect("apply", lambda w: "=" in w.get_text() and self._set(
            *[x.strip() for x in w.get_text().split("=", 1)]))
        g.add(e)
        g = self.group("Alle Werte")
        exp = Adw.ExpanderRow(title="Alle Kernel-Parameter anzeigen")
        _, out, _ = run_sync(["sysctl", "-a"])
        tv = Gtk.TextView(editable=False, monospace=True)
        tv.get_buffer().set_text(out)
        exp.add_row(Gtk.ScrolledWindow(child=tv, min_content_height=400))
        g.add(exp)

    def _write(self, custom, msg):
        body = "# Verwaltet von FAST\n" + "".join(f"{k} = {v}\n" for k, v in custom.items())

        def after(ok, out, err):
            if ok:
                self.run_root(["sysctl", "-p", self.CONF], msg)
            else:
                error(self, "Fehler", err)
        write_root_file(self.CONF, body, after)

    def _set(self, key, val):
        if not re.fullmatch(r"[\w.\-/]+", key):
            error(self, "Ungültig", f"Ungültiger Schlüssel: {key}")
            return
        c = self._custom()
        c[key] = val
        self._write(c, f"{key} = {val}")

    def _unset(self, key):
        c = self._custom()
        c.pop(key, None)
        self._write(c, f"{key} entfernt (wirkt vollständig nach Neustart)")


# --------------------------------------------------------------------------
class Power(Module):
    id = "power"
    title = "Energie und Leistung"
    icon = "power-profile-balanced-symbolic"
    category = "System"
    description = "tuned-Profile, Neustart, Herunterfahren"
    keywords = "energie power tuned profil leistung herunterfahren neustart"
    requires = ("tuned-adm",)

    def refresh(self):
        self.clear()
        _, act, _ = run_sync(["tuned-adm", "active"])
        _, lst, _ = run_sync(["tuned-adm", "list"])
        _, rec, _ = run_sync(["tuned-adm", "recommend"])
        active = act.split(":", 1)[-1].strip()
        g = self.group("Leistungsprofil (tuned)", f"Empfohlen: {rec.strip()}")
        first = None
        for line in lst.splitlines():
            m = re.match(r"- (\S+)\s+- (.*)", line)
            if not m:
                continue
            row = Adw.ActionRow(title=esc(m[1]), subtitle=esc(m[2]))
            chk = Gtk.CheckButton(active=m[1] == active, valign=Gtk.Align.CENTER)
            if first:
                chk.set_group(first)
            first = first or chk
            chk.connect("toggled", lambda c, p=m[1]: c.get_active() and self.run_root(
                ["tuned-adm", "profile", p], f"Profil: {p}", then=lambda ok: None))
            row.add_prefix(chk)
            row.set_activatable_widget(chk)
            g.add(row)
        g = self.group("Sitzung")
        for title, cmd, icon in (("Neu starten", ["systemctl", "reboot"], "system-reboot-symbolic"),
                                 ("Herunterfahren", ["systemctl", "poweroff"], "system-shutdown-symbolic"),
                                 ("Bereitschaft", ["systemctl", "suspend"], "weather-clear-night-symbolic"),
                                 ("UEFI-Setup beim Neustart",
                                  ["systemctl", "reboot", "--firmware-setup"], "applications-system-symbolic")):
            r = Adw.ActionRow(title=title)
            r.add_prefix(Gtk.Image.new_from_icon_name(icon))
            r.add_suffix(text_button("Ausführen", lambda c=cmd, t=title: confirm(
                self, f"{t}?", "Nicht gespeicherte Arbeit geht verloren.", t,
                lambda: run(c))))
            g.add(r)


# --------------------------------------------------------------------------
class Snapshots(Module):
    id = "snapshots"
    title = "Snapshots (Snapper)"
    icon = "document-open-recent-symbolic"
    category = "System"
    description = "btrfs-Snapshots anlegen, vergleichen, zurücksetzen"
    keywords = "snapper snapshot btrfs backup rollback undochange"
    requires = ("snapper",)

    def __init__(self):
        super().__init__()
        self.add_header_button("list-add-symbolic", "Snapshot anlegen", self.create)

    def activate(self):
        self.clear()
        g = self.placeholder("Snapper braucht Root-Rechte zum Lesen.")
        b = text_button("Snapshots laden", self.refresh, css="suggested-action")
        b.set_halign(Gtk.Align.CENTER)
        g.add(b)

    def refresh(self):
        run(["snapper", "--jsonout", "list-configs"], self._configs, root=True)

    def _configs(self, ok, out, err):
        if not ok:
            error(self, "Snapper", err)
            return
        self.clear()
        try:
            configs = json.loads(out).get("configs", [])
        except ValueError:
            configs = []
        if not configs:
            g = self.placeholder("Keine Snapper-Konfiguration vorhanden.")
            g.add(text_button("Für / einrichten", lambda: self.run_root(
                ["snapper", "-c", "root", "create-config", "/"], "Konfiguration angelegt")))
            return
        for c in configs:
            run(["snapper", "--jsonout", "-c", c["config"], "list"],
                lambda ok, o, e, c=c: self._list(c, ok, o, e), root=True)

    def _list(self, conf, ok, out, err):
        g = self.group(f"{conf['config']} ({conf['subvolume']})")
        if not ok:
            g.add(label_row("Fehler", err))
            return
        try:
            snaps = json.loads(out).get(conf["config"], [])
        except ValueError:
            snaps = []
        for s in reversed(snaps):
            if s.get("number") == 0:
                continue
            n = str(s["number"])
            row = Adw.ActionRow(
                title=esc(f"#{n} {s.get('description') or s.get('type', '')}"),
                subtitle=esc(f"{s.get('date', '')} · {s.get('type', '')} · "
                             f"{s.get('cleanup', '')}"))
            row.add_suffix(icon_button("view-list-symbolic", "Änderungen anzeigen",
                                       self._status, conf["config"], n))
            row.add_suffix(icon_button("edit-undo-symbolic", "Änderungen rückgängig",
                                       self._undo, conf["config"], n))
            row.add_suffix(icon_button("user-trash-symbolic", "Löschen",
                                       self._delete, conf["config"], n))
            g.add(row)

    def _status(self, conf, n):
        run(["snapper", "-c", conf, "status", f"{n}..0"],
            lambda ok, o, e: error(self, f"Änderungen seit #{n}", (o or e)[:20000]),
            root=True)

    def _undo(self, conf, n):
        confirm(self, f"Auf Snapshot #{n} zurücksetzen?",
                "Alle Dateien, die sich seitdem geändert haben, werden auf den "
                "Stand des Snapshots gesetzt.", "Zurücksetzen",
                lambda: self.log("Rückgängig", ["snapper", "-c", conf,
                                                "undochange", f"{n}..0"]))

    def _delete(self, conf, n):
        confirm(self, f"Snapshot #{n} löschen?", "", "Löschen",
                lambda: self.run_root(["snapper", "-c", conf, "delete", n], "Gelöscht"))

    def create(self):
        ask(self, "Snapshot anlegen", [
            {"key": "desc", "label": "Beschreibung", "default": "Manuell (FAST)"},
            {"key": "conf", "label": "Konfiguration", "default": "root"}],
            lambda v: self.run_root(["snapper", "-c", v["conf"], "create", "-d",
                                     v["desc"]], "Snapshot angelegt"))


# --------------------------------------------------------------------------
class Timers(Module):
    id = "timers"
    title = "Geplante Aufgaben"
    icon = "alarm-symbolic"
    category = "System"
    description = "systemd-Timer und Cron-Jobs"
    keywords = "cron timer zeitplan aufgabe geplant crontab"
    requires = ("systemctl",)

    def refresh(self):
        self.clear()
        for title, extra in (("System-Timer", []), ("Benutzer-Timer", ["--user"])):
            _, out, _ = run_sync(["systemctl", *extra, "list-timers", "--all",
                                  "--output=json"])
            try:
                timers = json.loads(out)
            except ValueError:
                timers = []
            g = self.group(title)
            for t in timers:
                nxt = t.get("next") or 0
                last = t.get("last") or 0
                import datetime as dt
                fmt = lambda us: dt.datetime.fromtimestamp(us / 1e6).strftime(
                    "%d.%m.%Y %H:%M") if us else "–"
                g.add(label_row(t.get("unit", ""),
                                f"löst aus: {t.get('activates', '')}\n"
                                f"nächster Lauf: {fmt(nxt)} · letzter: {fmt(last)}"))
        g = self.group("Cron (eigener Benutzer)")
        _, cron, _ = run_sync(["crontab", "-l"])
        buf = Gtk.TextBuffer()
        buf.set_text(cron)
        tv = Gtk.TextView(buffer=buf, monospace=True)
        tv.set_size_request(-1, 160)
        g.add(Gtk.Frame(child=tv))
        b = text_button("Crontab speichern", lambda: self._save_cron(buf),
                        css="suggested-action")
        b.set_halign(Gtk.Align.END)
        b.set_margin_top(6)
        g.add(b)
        g = self.group("System-Cron (/etc/crontab, /etc/cron.d)")
        for path in ["/etc/crontab"] + sorted(
                os.path.join("/etc/cron.d", f) for f in os.listdir("/etc/cron.d")
                if os.path.isfile(os.path.join("/etc/cron.d", f))):
            lines = [l for l in read_file(path).splitlines()
                     if l.strip() and not l.startswith("#")]
            g.add(label_row(path, "\n".join(lines) or "(leer)"))

    def _save_cron(self, buf):
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        if text and not text.endswith("\n"):
            text += "\n"
        run(["crontab", "-"], lambda ok, o, e: toast(self, "Crontab gespeichert") if ok
            else error(self, "Crontab", e), input=text)


# --------------------------------------------------------------------------
class SysInfo(Module):
    id = "sysinfo"
    title = "Hardware-Informationen"
    icon = "applications-engineering-symbolic"
    category = "Hardware"
    description = "CPU, Speicher, PCI- und USB-Geräte, Sensoren"
    keywords = "hardware info cpu ram pci usb lspci lsusb sensor"

    def refresh(self):
        self.clear()
        cpu = read_file("/proc/cpuinfo")
        model = re.search(r"model name\s*:\s*(.*)", cpu)
        cores = len(re.findall(r"^processor", cpu, re.M))
        mem = read_file("/proc/meminfo")
        total = int(re.search(r"MemTotal:\s*(\d+)", mem)[1]) // 1024
        avail = int(re.search(r"MemAvailable:\s*(\d+)", mem)[1]) // 1024
        g = self.group("Übersicht")
        g.add(label_row("Prozessor", f"{model[1] if model else '?'} · {cores} Threads"))
        g.add(label_row("Arbeitsspeicher", f"{total / 1024:.1f} GiB gesamt · "
                                           f"{avail / 1024:.1f} GiB frei"))
        up = float(read_file("/proc/uptime").split()[0])
        g.add(label_row("Laufzeit", f"{int(up // 86400)} Tage {int(up % 86400 // 3600)} Std "
                                    f"{int(up % 3600 // 60)} Min"))
        g.add(label_row("Last (1/5/15 min)", " ".join(read_file("/proc/loadavg").split()[:3])))
        dmi = "/sys/class/dmi/id"
        for f, label in (("sys_vendor", "Hersteller"), ("product_name", "Produkt"),
                         ("board_name", "Mainboard"), ("bios_version", "BIOS")):
            v = read_file(os.path.join(dmi, f)).strip() if os.access(
                os.path.join(dmi, f), os.R_OK) else ""
            if v:
                g.add(label_row(label, v))
        sensors = self._sensors()
        if sensors:
            g = self.group("Temperaturen")
            for name, val in sensors:
                g.add(label_row(name, "", f"{val:.0f} °C"))
        for title, cmd in (("PCI-Geräte", ["lspci"]), ("USB-Geräte", ["lsusb"]),
                           ("Kernel-Module", ["lsmod"])):
            ok, out, _ = run_sync(cmd)
            if not ok:
                continue
            g = self.group(title)
            exp = Adw.ExpanderRow(title=f"{len(out.splitlines())} Einträge")
            for line in out.splitlines():
                if cmd[0] == "lspci":
                    addr, _, rest = line.partition(" ")
                    kind, _, name = rest.partition(": ")
                    exp.add_row(label_row(name or rest, f"{kind} · {addr}"))
                elif cmd[0] == "lsusb":
                    m = re.match(r"Bus (\d+) Device (\d+): ID (\S+) ?(.*)", line)
                    if m:
                        exp.add_row(label_row(m[4] or m[3], f"ID {m[3]} · Bus {m[1]}"))
                else:
                    p = line.split()
                    if p and p[0] != "Module":
                        exp.add_row(label_row(p[0], f"{int(p[1]) // 1024} KiB · "
                                                    f"genutzt von: {p[3] if len(p) > 3 else '-'}"))
            g.add(exp)

    def _sensors(self):
        res = []
        base = "/sys/class/hwmon"
        if not os.path.isdir(base):
            return res
        for hw in sorted(os.listdir(base)):
            d = os.path.join(base, hw)
            name = read_file(os.path.join(d, "name")).strip()
            for f in sorted(os.listdir(d)):
                if re.fullmatch(r"temp\d+_input", f):
                    try:
                        val = int(read_file(os.path.join(d, f)).strip()) / 1000
                    except ValueError:
                        continue
                    lbl = read_file(os.path.join(d, f.replace("_input", "_label"))).strip() \
                        if os.path.exists(os.path.join(d, f.replace("_input", "_label"))) else f
                    res.append((f"{name} {lbl}", val))
        return res


MODULES = [Services, Journal, Bootloader, DateTime, Language, Hostname, Sysctl,
           Power, Snapshots, Timers, SysInfo]
