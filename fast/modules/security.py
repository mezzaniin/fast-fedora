"""Sicherheit und Benutzer: Benutzer, Gruppen, SELinux, Sicherheitsüberblick."""
import grp
import pwd
import re

from gi.repository import Adw, Gtk

from ..util import (Module, ask, confirm, error, esc, icon_button, label_row,
                    read_file, run, run_sync, text_button, toast,
                    write_root_file)


def login_defs():
    res = {"UID_MIN": 1000, "UID_MAX": 60000}
    for line in read_file("/etc/login.defs").splitlines():
        p = line.split()
        if len(p) == 2 and p[0] in res and p[1].isdigit():
            res[p[0]] = int(p[1])
    return res


class Users(Module):
    id = "users"
    title = "Benutzer"
    icon = "system-users-symbolic"
    category = "Sicherheit und Benutzer"
    description = "Benutzer anlegen, bearbeiten, löschen, Passwörter, Admin-Rechte"
    keywords = "benutzer user konto passwort admin wheel sudo useradd"
    requires = ("useradd",)

    def __init__(self):
        super().__init__()
        self.show_system = Gtk.ToggleButton(icon_name="emblem-system-symbolic",
                                            tooltip_text="Systembenutzer anzeigen")
        self.show_system.connect("toggled", lambda *_: self.refresh())
        self.header_widgets.append(self.show_system)
        self.add_header_button("list-add-symbolic", "Benutzer anlegen", self.add)

    def refresh(self):
        self.clear()
        ld = login_defs()
        sysu = self.show_system.get_active()
        wheel = set(grp.getgrnam("wheel").gr_mem) if "wheel" in [g.gr_name for g in grp.getgrall()] else set()
        g = self.group("Systembenutzer" if sysu else "Benutzer")
        for u in sorted(pwd.getpwall(), key=lambda u: u.pw_uid):
            is_normal = ld["UID_MIN"] <= u.pw_uid <= ld["UID_MAX"]
            if is_normal == sysu:
                continue
            groups = [x.gr_name for x in grp.getgrall() if u.pw_name in x.gr_mem]
            admin = u.pw_name in wheel
            row = Adw.ActionRow(
                title=esc(f"{u.pw_gecos.split(',')[0] or u.pw_name}"),
                subtitle=esc(f"{u.pw_name} · UID {u.pw_uid} · {u.pw_dir} · {u.pw_shell}\n"
                             f"Gruppen: {', '.join(groups) or '–'}"))
            row.set_subtitle_lines(2)
            if admin:
                lbl = Gtk.Label(label="Administrator")
                lbl.add_css_class("accent")
                row.add_suffix(lbl)
            if is_normal:
                row.add_suffix(icon_button("dialog-password-symbolic", "Passwort setzen",
                                           self.password, u.pw_name))
                row.add_suffix(icon_button("document-edit-symbolic", "Bearbeiten",
                                           self.edit, u, groups, admin))
                row.add_suffix(icon_button("user-trash-symbolic", "Löschen",
                                           self.delete, u.pw_name))
            g.add(row)

    def add(self):
        def go(v):
            name = v["name"].strip()
            if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", name):
                error(self, "Ungültiger Name", "Kleinbuchstaben, Ziffern, _ und -")
                return
            cmd = ["useradd", "-m", "-c", v["full"], "-s", v["shell"]]
            if v["admin"]:
                cmd += ["-G", "wheel"]
            cmd.append(name)

            def then(ok):
                if ok and v["pw"]:
                    self.run_root(["chpasswd"], f"Benutzer {name} angelegt",
                                  input=f"{name}:{v['pw']}\n")
                else:
                    self.refresh()
            self.run_root(cmd, None if v["pw"] else f"Benutzer {name} angelegt", then=then)
        ask(self, "Benutzer anlegen", [
            {"key": "full", "label": "Vollständiger Name"},
            {"key": "name", "label": "Benutzername"},
            {"key": "pw", "label": "Passwort", "kind": "password"},
            {"key": "shell", "label": "Shell", "kind": "combo",
             "options": self._shells(), "default": "/bin/bash"},
            {"key": "admin", "label": "Administrator (Gruppe wheel)", "kind": "switch"},
        ], go, action_label="Anlegen")

    def _shells(self):
        return [l.strip() for l in read_file("/etc/shells").splitlines()
                if l.strip().startswith("/")] or ["/bin/bash"]

    def edit(self, u, groups, admin):
        def go(v):
            cmd = ["usermod", "-c", v["full"], "-s", v["shell"],
                   "-G", ",".join(x.strip() for x in v["groups"].split(",") if x.strip())]
            def then(ok):
                if ok and v["lock"]:
                    self.run_root(["usermod", "-L", u.pw_name], "Konto gesperrt")
                else:
                    self.refresh()
            self.run_root(cmd + [u.pw_name], "Benutzer geändert", then=then)
        ask(self, f"{u.pw_name} bearbeiten", [
            {"key": "full", "label": "Vollständiger Name", "default": u.pw_gecos.split(",")[0]},
            {"key": "shell", "label": "Shell", "kind": "combo", "options": self._shells(),
             "default": u.pw_shell},
            {"key": "groups", "label": "Zusätzliche Gruppen (Komma-getrennt)",
             "default": ",".join(groups)},
            {"key": "lock", "label": "Konto sperren", "kind": "switch"},
        ], go, body="„wheel“ in den Gruppen = Administrator", action_label="Speichern")

    def password(self, name):
        def go(v):
            if v["pw"] != v["pw2"]:
                error(self, "Passwort", "Die Passwörter stimmen nicht überein.")
                return
            if not v["pw"]:
                return
            self.run_root(["chpasswd"], "Passwort geändert", input=f"{name}:{v['pw']}\n")
        ask(self, f"Passwort für {name}", [
            {"key": "pw", "label": "Neues Passwort", "kind": "password"},
            {"key": "pw2", "label": "Wiederholen", "kind": "password"}],
            go, action_label="Setzen")

    def delete(self, name):
        def go(v):
            self.run_root(["userdel", *(["-r"] if v["home"] else []), name],
                          f"Benutzer {name} gelöscht")
        ask(self, f"Benutzer {name} löschen?", [
            {"key": "home", "label": "Persönlichen Ordner ebenfalls löschen", "kind": "switch"}],
            go, action_label="Löschen")


class Groups(Module):
    id = "usergroups"
    title = "Gruppen"
    icon = "system-users-symbolic"
    category = "Sicherheit und Benutzer"
    description = "Gruppen anlegen, löschen und Mitglieder verwalten"
    keywords = "gruppe group mitglied groupadd"
    requires = ("groupadd",)

    def __init__(self):
        super().__init__()
        self.add_header_button("list-add-symbolic", "Gruppe anlegen", self.add)

    def refresh(self):
        self.clear()
        ld = login_defs()
        primary = {}
        for u in pwd.getpwall():
            primary.setdefault(u.pw_gid, []).append(u.pw_name)
        normal = self.group("Eigene Gruppen")
        system = self.group("Systemgruppen")
        exp = Adw.ExpanderRow(title="Systemgruppen anzeigen")
        system.add(exp)
        for gr in sorted(grp.getgrall(), key=lambda g: g.gr_gid):
            members = sorted(set(gr.gr_mem))
            row = Adw.ActionRow(title=esc(gr.gr_name),
                                subtitle=esc(f"GID {gr.gr_gid} · Mitglieder: "
                                             f"{', '.join(members) or '–'}"))
            row.add_suffix(icon_button("document-edit-symbolic", "Mitglieder",
                                       self.members, gr.gr_name, members))
            if ld["UID_MIN"] <= gr.gr_gid <= ld["UID_MAX"] or gr.gr_name == "wheel":
                if gr.gr_gid not in primary:
                    row.add_suffix(icon_button("user-trash-symbolic", "Löschen",
                                               lambda n=gr.gr_name: confirm(
                                                   self, f"Gruppe {n} löschen?", "", "Löschen",
                                                   lambda: self.run_root(["groupdel", n],
                                                                         "Gelöscht"))))
                normal.add(row)
            else:
                exp.add_row(row)

    def add(self):
        ask(self, "Gruppe anlegen", [{"key": "name", "label": "Gruppenname"},
                                      {"key": "sys", "label": "Systemgruppe", "kind": "switch"}],
            lambda v: self.run_root(["groupadd", *(["-r"] if v["sys"] else []),
                                     v["name"].strip()], "Gruppe angelegt"),
            action_label="Anlegen")

    def members(self, name, members):
        ask(self, f"Mitglieder von {name}", [
            {"key": "m", "label": "Mitglieder (Komma-getrennt)", "default": ",".join(members)}],
            lambda v: self.run_root(["gpasswd", "-M", ",".join(
                x.strip() for x in v["m"].split(",") if x.strip()), name],
                "Mitglieder gespeichert"), action_label="Speichern")


class SELinux(Module):
    id = "selinux"
    title = "SELinux"
    icon = "security-medium-symbolic"
    category = "Sicherheit und Benutzer"
    description = "Modus, Booleans, letzte Zugriffsverweigerungen"
    keywords = "selinux enforcing permissive boolean avc denial setsebool"
    requires = ("getenforce",)

    def refresh(self):
        self.clear()
        _, mode, _ = run_sync(["getenforce"])
        mode = mode.strip()
        conf = read_file("/etc/selinux/config")
        cfg = re.search(r"^SELINUX=(\w+)", conf, re.M)
        cfg = cfg[1] if cfg else "?"
        g = self.group("Modus")
        live = Adw.SwitchRow(title="Erzwingen (enforcing) – sofort",
                             subtitle=f"Aktuell: {mode}. Aus = permissive (nur protokollieren)",
                             active=mode == "Enforcing", sensitive=mode != "Disabled")
        live.connect("notify::active", lambda r, _p: self.run_root(
            ["setenforce", "1" if r.get_active() else "0"], "Modus geändert"))
        g.add(live)
        opts = ["enforcing", "permissive", "disabled"]
        boot = Adw.ComboRow(title="Modus beim Systemstart", subtitle="/etc/selinux/config",
                            model=Gtk.StringList.new(opts))
        boot.set_selected(opts.index(cfg) if cfg in opts else 0)

        def set_boot(r, _p):
            new = re.sub(r"^SELINUX=\w+", f"SELINUX={opts[r.get_selected()]}", conf, flags=re.M)
            write_root_file("/etc/selinux/config", new, lambda ok, o, e: toast(
                self, "Gespeichert (wirkt nach Neustart)") if ok else error(self, "Fehler", e))
        boot.connect("notify::selected", set_boot)
        g.add(boot)
        r = Adw.ActionRow(title="Dateisystem beim nächsten Start neu labeln",
                          subtitle="Bei Problemen nach Moduswechsel (touch /.autorelabel)")
        r.add_suffix(text_button("Planen", lambda: self.run_root(
            ["fixfiles", "-F", "onboot"], "Neu-Labeling geplant")))
        g.add(r)

        g = self.group("Booleans")
        self.filter = Gtk.SearchEntry(placeholder_text="Booleans filtern (z. B. httpd, samba) …")
        g.add(self.filter)
        self.bool_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.bool_box.add_css_class("boxed-list")
        self.bool_box.set_margin_top(6)
        g.add(self.bool_box)
        _, out, _ = run_sync(["getsebool", "-a"])
        self.bools = []
        for line in out.splitlines():
            m = re.match(r"(\S+) --> (on|off)", line)
            if m:
                self.bools.append((m[1], m[2] == "on"))
        self.filter.connect("search-changed", lambda *_: self._bools())
        self._bools()

        g = self.group("Letzte Zugriffsverweigerungen (AVC)")
        b = text_button("Laden (root)", self._avc)
        g.set_header_suffix(b)
        self.avc_buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self.avc_buf, editable=False, monospace=True,
                          wrap_mode=Gtk.WrapMode.WORD_CHAR)
        g.add(Gtk.Frame(child=Gtk.ScrolledWindow(child=tv, min_content_height=200)))

    def _bools(self):
        while (child := self.bool_box.get_first_child()) is not None:
            self.bool_box.remove(child)
        f = self.filter.get_text().lower()
        shown = [b for b in self.bools if f in b[0]] if f else self.bools[:0]
        if not f:
            self.bool_box.append(label_row(f"{len(self.bools)} Booleans – Suchbegriff eingeben"))
        for name, on in shown[:200]:
            r = Adw.SwitchRow(title=esc(name), active=on)
            r.connect("notify::active", lambda w, _p, n=name: self.run_root(
                ["setsebool", "-P", n, "on" if w.get_active() else "off"], f"{n} geändert",
                then=lambda ok: None))
            self.bool_box.append(r)

    def _avc(self):
        run(["ausearch", "-m", "AVC,USER_AVC", "-ts", "recent", "-i"],
            lambda ok, o, e: self.avc_buf.set_text(o or e or "Keine Einträge"), root=True)


class SecurityOverview(Module):
    id = "security"
    title = "Sicherheitsüberblick"
    icon = "security-low-symbolic"
    category = "Sicherheit und Benutzer"
    description = "Prüft wichtige Sicherheitseinstellungen auf einen Blick"
    keywords = "sicherheit audit check prüfung secure boot verschlüsselung"

    def refresh(self):
        self.clear()
        checks = []

        def chk(title, ok, detail, fix=None):
            checks.append((title, ok, detail, fix))

        _, fw, _ = run_sync(["firewall-cmd", "--state"])
        chk("Firewall läuft", fw.strip() == "running", fw.strip() or "nicht aktiv")
        _, se, _ = run_sync(["getenforce"])
        chk("SELinux erzwingt", se.strip() == "Enforcing", se.strip())
        _, sb, _ = run_sync(["mokutil", "--sb-state"])
        chk("Secure Boot", "enabled" in sb, sb.strip() or "unbekannt")
        enc = "crypto_LUKS" in run_sync(["lsblk", "-no", "FSTYPE"])[1]
        chk("Festplattenverschlüsselung (LUKS)", enc,
            "LUKS-Container gefunden" if enc else "Keine LUKS-Verschlüsselung gefunden")
        _, ssh, _ = run_sync(["systemctl", "is-active", "sshd"])
        chk("SSH-Server", True,
            "läuft – Einstellungen im Modul SSH-Server prüfen" if ssh.strip() == "active"
            else "aus")
        _, upd, _ = run_sync(["systemctl", "is-enabled", "dnf5-automatic.timer"])
        chk("Automatische Updates", upd.strip() == "enabled",
            "dnf5-automatic.timer " + (upd.strip() or "nicht installiert"))
        ok, ports, _ = run_sync(["ss", "-Htlnu"])
        public = [l.split()[4] for l in ports.splitlines()
                  if len(l.split()) > 4 and not re.match(r"(127\.|\[::1\]|::1)", l.split()[4])]
        chk("Offene Netzwerk-Ports", len(public) < 6,
            ", ".join(sorted(set(public))) or "keine")
        _, failed, _ = run_sync(["systemctl", "--failed", "--no-legend", "--plain"])
        chk("Fehlgeschlagene Dienste", not failed.strip(),
            ", ".join(l.split()[0] for l in failed.splitlines()) or "keine")
        g = self.group("Prüfungen")
        for title, ok, detail, _fix in checks:
            row = label_row(title, detail)
            icon = Gtk.Image.new_from_icon_name("object-select-symbolic" if ok
                                                else "dialog-warning-symbolic")
            icon.add_css_class("success" if ok else "warning")
            row.add_prefix(icon)
            g.add(row)
        g = self.group("Schnellaktionen")
        r = Adw.ActionRow(title="Automatische Sicherheitsupdates einrichten",
                          subtitle="Installiert dnf5-plugin-automatic und aktiviert den Timer")
        r.add_suffix(text_button("Einrichten", lambda: self.log(
            "Automatische Updates", ["dnf5", "install", "-y", "dnf5-plugin-automatic"])))
        r.add_suffix(text_button("Timer an", lambda: self.run_root(
            ["systemctl", "enable", "--now", "dnf5-automatic.timer"], "Timer aktiviert")))
        g.add(r)


MODULES = [SecurityOverview, Users, Groups, SELinux]
