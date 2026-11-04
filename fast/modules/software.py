"""Software: Pakete, Paketgruppen, Repositories, Online-Update, Flatpak."""
import re

from gi.repository import Adw, Gtk

from ..util import (Module, confirm, error, esc, icon_button, label_row, run,
                    run_sync, text_button, toast, ask)

ARCHES = "x86_64,noarch,i686"


class Packages(Module):
    id = "packages"
    title = "Software installieren/entfernen"
    icon = "system-software-install-symbolic"
    category = "Software"
    description = "RPM-Pakete suchen, installieren und entfernen (dnf5)"
    keywords = "dnf rpm paket software installieren entfernen suchen"
    requires = ("dnf5",)

    def __init__(self):
        super().__init__()
        self.query = ""
        bar = Gtk.Box(spacing=6)
        bar.set_margin_start(12)
        bar.set_margin_end(12)
        bar.set_margin_top(12)
        self.entry = Gtk.SearchEntry(placeholder_text="Paketname oder Teil davon …",
                                     hexpand=True)
        self.entry.connect("activate", lambda *_: self.search())
        self.only_installed = Gtk.CheckButton(label="Nur installierte")
        self.only_installed.connect("toggled", lambda *_: self.search())
        bar.append(self.entry)
        bar.append(self.only_installed)
        bar.append(text_button("Suchen", self.search, css="suggested-action"))
        self.prepend(bar)
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.search)

    def activate(self):
        self.clear()
        self.placeholder("Suchbegriff eingeben und Enter drücken.\n"
                         "Mit „Nur installierte“ und leerem Feld werden alle "
                         "installierten Pakete gelistet.")
        self.entry.grab_focus()

    def refresh(self):
        self.search()

    def search(self):
        q = self.entry.get_text().strip()
        installed_only = self.only_installed.get_active()
        if not q and not installed_only:
            return
        pattern = f"*{q}*" if q else "*"
        cmd = ["dnf5", "-q", "repoquery", "--latest-limit=1", f"--arch={ARCHES}",
               "--qf", "%{name}\t%{evr}\t%{arch}\t%{repoid}\t%{summary}\n"]
        if installed_only:
            cmd.append("--installed")
        cmd.append(pattern)
        self.clear()
        self.placeholder("Suche läuft …")
        run(cmd, self._show)

    def _show(self, ok, out, err):
        self.clear()
        if not ok:
            self.placeholder("Fehler bei der Suche:\n" + err)
            return
        _, inst, _ = run_sync(["rpm", "-qa", "--qf", "%{NAME}.%{ARCH}\n"])
        installed = set(inst.split())
        rows, seen = [], set()
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            name, evr, arch, repo, summary = parts[:5]
            key = f"{name}.{arch}"
            if key in seen:
                continue
            seen.add(key)
            is_inst = key in installed or repo in ("@System", "installed")
            rows.append((name, evr, arch, repo, summary, is_inst))
        rows.sort(key=lambda r: (not r[0].startswith(self.entry.get_text().strip()), r[0]))
        limit = 300
        g = self.group(f"{len(rows)} Pakete gefunden",
                       f"Zeige die ersten {limit}" if len(rows) > limit else "")
        for name, evr, arch, repo, summary, is_inst in rows[:limit]:
            row = Adw.ActionRow(title=esc(name),
                                subtitle=esc(f"{summary}\n{evr} · {arch} · {repo}"))
            row.set_subtitle_lines(2)
            if is_inst:
                badge = Gtk.Label(label="installiert")
                badge.add_css_class("success")
                row.add_suffix(badge)
                row.add_suffix(icon_button("user-trash-symbolic", "Entfernen",
                                           self.remove, name, css="destructive-action"))
            else:
                row.add_suffix(icon_button("list-add-symbolic", "Installieren",
                                           self.install, name))
            row.add_suffix(icon_button("dialog-information-symbolic", "Details",
                                       self.info, name))
            g.add(row)

    def install(self, name):
        self.log(f"Installiere {name}", ["dnf5", "install", "-y", name])

    def remove(self, name):
        confirm(self, f"{name} entfernen?",
                "Abhängige Pakete werden ebenfalls entfernt.",
                "Entfernen", lambda: self.log(f"Entferne {name}",
                                              ["dnf5", "remove", "-y", name]))

    def info(self, name):
        def cb(ok, out, err):
            error(self, name, out if ok else err)
        run(["dnf5", "-q", "info", name], cb)


class Groups(Module):
    id = "groups"
    title = "Paketgruppen"
    icon = "view-grid-symbolic"
    category = "Software"
    description = "Software-Gruppen (Desktops, Entwicklungs-Tools …) installieren"
    keywords = "group gruppe pattern muster desktop kde"
    requires = ("dnf5",)

    def __init__(self):
        super().__init__()
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        self.clear()
        self.placeholder("Lade Gruppen …")
        run(["dnf5", "-q", "group", "list"], self._show)

    def _show(self, ok, out, err):
        self.clear()
        if not ok:
            self.placeholder(err)
            return
        inst_g = self.group("Installiert")
        avail_g = self.group("Verfügbar")
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            gid, state, name = parts[0], parts[-1], " ".join(parts[1:-1])
            row = Adw.ActionRow(title=esc(name), subtitle=esc(gid))
            if state == "yes":
                row.add_suffix(icon_button("user-trash-symbolic", "Entfernen",
                                           self.remove, gid))
                inst_g.add(row)
            else:
                row.add_suffix(icon_button("list-add-symbolic", "Installieren",
                                           self.install, gid))
                avail_g.add(row)

    def install(self, gid):
        self.log(f"Installiere Gruppe {gid}", ["dnf5", "group", "install", "-y", gid])

    def remove(self, gid):
        confirm(self, f"Gruppe {gid} entfernen?", "", "Entfernen",
                lambda: self.log(f"Entferne Gruppe {gid}",
                                 ["dnf5", "group", "remove", "-y", gid]))


class Repos(Module):
    id = "repos"
    title = "Software-Repositories"
    icon = "folder-download-symbolic"
    category = "Software"
    description = "Paketquellen aktivieren, deaktivieren und hinzufügen"
    keywords = "repo repository quelle rpmfusion copr"
    requires = ("dnf5",)

    def __init__(self):
        super().__init__()
        self.add_header_button("list-add-symbolic", "Repository hinzufügen", self.add)
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        self.clear()
        self.placeholder("Lade Repositories …")
        run(["dnf5", "-q", "repo", "list", "--all"], self._show)

    def _show(self, ok, out, err):
        self.clear()
        if not ok:
            self.placeholder(err)
            return
        main, debug = [], []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            rid, status, name = parts[0], parts[-1], " ".join(parts[1:-1])
            (debug if re.search(r"debug|source|testing", rid) else main).append(
                (rid, name, status == "enabled"))
        tools = Gtk.Box(spacing=6)
        tools.append(text_button("RPM Fusion aktivieren", self.rpmfusion))
        tools.append(text_button("Cache leeren", self.clean))
        for title, items in (("Repositories", main),
                             ("Debug-, Quell- und Test-Repositories", debug)):
            g = self.group(title, suffix=tools if title == "Repositories" else None)
            for rid, name, enabled in items:
                row = Adw.SwitchRow(title=esc(name or rid), subtitle=esc(rid),
                                    active=enabled)
                row.connect("notify::active", self._toggle, rid)
                g.add(row)

    def _toggle(self, row, _p, rid):
        val = "1" if row.get_active() else "0"
        self.run_root(["dnf5", "config-manager", "setopt", f"{rid}.enabled={val}"],
                      f"{rid} {'aktiviert' if val == '1' else 'deaktiviert'}",
                      then=lambda ok: ok or self.refresh())

    def add(self):
        def go(v):
            url = v["url"].strip()
            if not url:
                return
            if v["kind"] == "COPR (user/projekt)":
                self.log("COPR aktivieren", ["dnf5", "copr", "enable", "-y", url])
            else:
                self.log("Repository hinzufügen",
                         ["dnf5", "config-manager", "addrepo", f"--from-repofile={url}"])
        ask(self, "Repository hinzufügen", [
            {"key": "kind", "label": "Art", "kind": "combo",
             "options": ["URL einer .repo-Datei", "COPR (user/projekt)"]},
            {"key": "url", "label": "URL / COPR-Name"},
        ], go)

    def rpmfusion(self):
        _, ver, _ = run_sync(["rpm", "-E", "%fedora"])
        ver = ver.strip()
        self.log("RPM Fusion aktivieren", [
            "dnf5", "install", "-y",
            f"https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-{ver}.noarch.rpm",
            f"https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-{ver}.noarch.rpm",
        ])

    def clean(self):
        self.log("Cache leeren", ["dnf5", "clean", "all"])


class Updates(Module):
    id = "updates"
    title = "Online-Update"
    icon = "software-update-available-symbolic"
    category = "Software"
    description = "System-, Flatpak- und Firmware-Updates"
    keywords = "update aktualisieren upgrade firmware fwupd"
    requires = ("dnf5",)

    def __init__(self):
        super().__init__()
        self.add_header_button("view-refresh-symbolic", "Nach Updates suchen",
                               self.refresh)

    def refresh(self):
        self.clear()
        self.placeholder("Suche nach Updates …")
        run(["dnf5", "-q", "check-upgrade", "--refresh"], self._show)

    def _show(self, ok, out, err):
        # check-upgrade: Exit 100 = Updates vorhanden → ok ist dann False
        self.clear()
        pkgs = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and "." in parts[0] and not line.startswith(" "):
                pkgs.append(parts[:3])
        actions = Gtk.Box(spacing=6)
        actions.append(text_button("Alles aktualisieren", self.upgrade,
                                   css="suggested-action"))
        g = self.group("Systempakete",
                       f"{len(pkgs)} Updates verfügbar" if pkgs
                       else "Das System ist aktuell." if not err.strip()
                       else err.strip()[-300:],
                       suffix=actions if pkgs else None)
        for name, ver, repo in pkgs[:500]:
            g.add(label_row(name, f"{ver} · {repo}"))
        o = self.group("Weitere Aktualisierungen")
        r = Adw.ActionRow(title="Flatpak-Anwendungen", subtitle="flatpak update")
        r.add_suffix(text_button("Aktualisieren", self.flatpak))
        o.add(r)
        r = Adw.ActionRow(title="Firmware (LVFS)", subtitle="fwupdmgr refresh &amp;&amp; update")
        r.add_suffix(text_button("Prüfen", self.fw_check))
        r.add_suffix(text_button("Installieren", self.fw_update))
        o.add(r)
        r = Adw.ActionRow(title="Offline-Update (beim Neustart)",
                          subtitle="Sicherer für große Updates: dnf5 offline")
        r.add_suffix(text_button("Vorbereiten", self.offline))
        o.add(r)
        r = Adw.ActionRow(title="Systemversion upgraden",
                          subtitle="Auf die nächste Fedora-Version (system-upgrade)")
        r.add_suffix(text_button("Herunterladen …", self.release_upgrade))
        o.add(r)
        self._history()

    def _history(self):
        def cb(ok, out, err):
            if not ok:
                return
            g = self.group("Verlauf (dnf history)")
            for line in out.splitlines()[1:16]:
                m = re.match(r"\s*(\d+)\s+(.*?)\s+(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)"
                             r"\s+(.*?)\s*(\d+)\s*$", line)
                if m:
                    g.add(label_row(f"#{m[1]}  {m[2]}",
                                    f"{m[3]} · {m[5]} Pakete {m[4]}".strip()))
        run(["dnf5", "-q", "history", "list"], cb)

    def upgrade(self):
        self.log("Systemaktualisierung", ["dnf5", "upgrade", "-y", "--refresh"])

    def flatpak(self):
        self.log("Flatpak-Update", ["flatpak", "update", "-y", "--noninteractive"],
                 root=False)

    def fw_check(self):
        self.log("Firmware prüfen", ["fwupdmgr", "get-updates"], root=False)

    def fw_update(self):
        self.log("Firmware aktualisieren", ["fwupdmgr", "update", "-y",
                                            "--no-reboot-check"], root=True)

    def offline(self):
        self.log("Offline-Update vorbereiten (danach: dnf5 offline reboot)",
                 ["dnf5", "upgrade", "-y", "--offline"])

    def release_upgrade(self):
        _, ver, _ = run_sync(["rpm", "-E", "%fedora"])
        nxt = str(int(ver.strip() or 0) + 1)

        def go(v):
            self.log(f"Fedora {v['ver']} herunterladen",
                     ["dnf5", "system-upgrade", "download", "-y",
                      f"--releasever={v['ver']}"])
        ask(self, "Systemversion upgraden", [
            {"key": "ver", "label": "Ziel-Version", "default": nxt}],
            go, body="Danach mit „dnf5 offline reboot“ neu starten.",
            action_label="Herunterladen")


class Flatpaks(Module):
    id = "flatpak"
    title = "Flatpak-Anwendungen"
    icon = "package-x-generic-symbolic"
    category = "Software"
    description = "Installierte Flatpaks und Remotes verwalten"
    keywords = "flatpak flathub app"
    requires = ("flatpak",)

    def __init__(self):
        super().__init__()
        self.add_header_button("list-add-symbolic", "Flatpak installieren", self.install)
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        self.clear()
        _, apps, _ = run_sync(["flatpak", "list", "--app",
                               "--columns=name,application,version,branch,installation,origin"])
        _, rts, _ = run_sync(["flatpak", "list", "--runtime",
                              "--columns=name,application,branch,installation"])
        _, remotes, _ = run_sync(["flatpak", "remotes", "--columns=name,url,options"])
        g = self.group("Anwendungen")
        for line in apps.splitlines():
            p = line.split("\t")
            if len(p) < 6:
                continue
            row = Adw.ActionRow(title=esc(p[0]),
                                subtitle=esc(f"{p[1]} · {p[2]} · {p[4]} · {p[5]}"))
            row.add_suffix(icon_button("media-playback-start-symbolic", "Starten",
                                       self.launch_app, p[1]))
            row.add_suffix(icon_button("user-trash-symbolic", "Deinstallieren",
                                       self.uninstall, p[1], p[4]))
            g.add(row)
        g = self.group("Remotes")
        for line in remotes.splitlines():
            p = line.split("\t")
            if len(p) >= 2:
                g.add(label_row(p[0], p[1], p[2] if len(p) > 2 else ""))
        tools = text_button("Ungenutzte entfernen", self.unused)
        g = self.group(f"Laufzeitumgebungen ({len(rts.splitlines())})", suffix=tools)
        exp = Adw.ExpanderRow(title="Runtimes anzeigen")
        for line in rts.splitlines():
            p = line.split("\t")
            if len(p) >= 3:
                exp.add_row(label_row(p[1], f"{p[2]} · {p[3] if len(p) > 3 else ''}"))
        g.add(exp)

    def launch_app(self, appid):
        from ..util import launch
        launch(["flatpak", "run", appid])

    def uninstall(self, appid, inst):
        flag = "--system" if inst == "system" else "--user"
        confirm(self, f"{appid} deinstallieren?", "", "Deinstallieren",
                lambda: self.log(f"Entferne {appid}",
                                 ["flatpak", "uninstall", "-y", flag, appid],
                                 root=False))

    def unused(self):
        self.log("Ungenutzte Runtimes entfernen",
                 ["flatpak", "uninstall", "--unused", "-y"], root=False)

    def install(self):
        def go(v):
            if v["id"].strip():
                self.log("Flatpak installieren",
                         ["flatpak", "install", "-y", "--noninteractive",
                          v["remote"], v["id"].strip()], root=False)
        ask(self, "Flatpak installieren", [
            {"key": "remote", "label": "Remote", "default": "flathub"},
            {"key": "id", "label": "App-ID (z. B. org.videolan.VLC)"},
        ], go, action_label="Installieren")


MODULES = [Packages, Groups, Repos, Updates, Flatpaks]
