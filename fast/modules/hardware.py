"""Hardware: Datenträger, fstab, SMART, Drucker, Sound."""
import json
import re

from gi.repository import Adw, Gtk

from ..util import (Module, ask, confirm, error, esc, icon_button, label_row,
                    launch, read_file, run, run_sync, text_button, toast,
                    write_root_file, have)


def human(n):
    n = float(n or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


class Disks(Module):
    id = "disks"
    title = "Datenträger und Partitionen"
    icon = "drive-harddisk-symbolic"
    category = "Hardware"
    description = "Laufwerke, Partitionen, Einhängen, SMART-Status, Swap"
    keywords = "festplatte disk partition mount einhängen smart ssd nvme swap lsblk"
    requires = ("lsblk",)

    def __init__(self):
        super().__init__()
        if have("gnome-disks"):
            self.add_header_button("applications-utilities-symbolic",
                                   "Partitionieren (GNOME Laufwerke)",
                                   lambda: launch(["gnome-disks"]))
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        self.clear()
        _, out, _ = run_sync(["lsblk", "-J", "-b", "-o",
                              "NAME,PATH,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINTS,MODEL,"
                              "TRAN,ROTA,FSUSED,FSSIZE,UUID,RM,RO"])
        try:
            devs = json.loads(out).get("blockdevices", [])
        except ValueError:
            devs = []
        for d in devs:
            if d["type"] not in ("disk",) or d["name"].startswith(("zram", "loop")):
                continue
            kind = "SSD" if not d.get("rota") else "HDD"
            if d.get("tran") == "nvme":
                kind = "NVMe"
            if d.get("rm"):
                kind += " (Wechseldatenträger)"
            smart = icon_button("emblem-system-symbolic", "SMART-Status",
                                self.smart, d["path"]) if have("smartctl") else None
            g = self.group(f"{d.get('model') or d['name']} – {human(d['size'])}",
                           f"{d['path']} · {kind} · {d.get('tran') or ''}", suffix=smart)
            self._children(g, d.get("children") or [], 0)
            if not d.get("children"):
                self._part_row(g, d, 0)
        self._swap()

    def _children(self, g, children, depth):
        for c in children:
            self._part_row(g, c, depth)
            self._children(g, c.get("children") or [], depth + 1)

    def _part_row(self, g, p, depth):
        mps = [m for m in (p.get("mountpoints") or []) if m]
        usage = ""
        if p.get("fssize"):
            pct = int(p["fsused"] or 0) * 100 // max(int(p["fssize"]), 1)
            usage = f" · belegt {human(p['fsused'])} / {human(p['fssize'])} ({pct} %)"
        title = ("    " * depth) + p["name"] + (f"  „{p['label']}“" if p.get("label") else "")
        row = Adw.ActionRow(
            title=esc(title),
            subtitle=esc(f"{p['type']} · {p.get('fstype') or 'kein Dateisystem'} · "
                         f"{human(p['size'])}{usage}\n"
                         f"{'eingehängt: ' + ', '.join(mps) if mps else 'nicht eingehängt'}"))
        row.set_subtitle_lines(2)
        if p.get("fssize"):
            bar = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER,
                               value=int(p["fsused"] or 0) / max(int(p["fssize"]), 1))
            bar.set_size_request(100, -1)
            row.add_suffix(bar)
        fs = p.get("fstype") or ""
        if fs and fs not in ("swap", "crypto_LUKS", "LVM2_member", "btrfs" if mps else ""):
            if mps:
                if not any(m in ("/", "/boot", "/boot/efi", "/home", "/var") for m in mps):
                    row.add_suffix(icon_button("media-eject-symbolic", "Aushängen",
                                               self.unmount, p["path"]))
            else:
                row.add_suffix(icon_button("folder-open-symbolic", "Einhängen",
                                           self.mount, p["path"]))
        if fs == "crypto_LUKS" and not p.get("children"):
            row.add_suffix(icon_button("changes-allow-symbolic", "Entsperren",
                                       self.unlock, p["path"]))
        g.add(row)

    def _swap(self):
        _, out, _ = run_sync(["swapon", "--show=NAME,TYPE,SIZE,USED,PRIO", "--bytes",
                              "--noheadings"])
        g = self.group("Auslagerungsspeicher (Swap)")
        if not out.strip():
            g.add(label_row("Kein Swap aktiv"))
        for line in out.splitlines():
            p = line.split()
            if len(p) >= 5:
                g.add(label_row(p[0], f"{p[1]} · Priorität {p[4]}",
                                f"{human(p[3])} / {human(p[2])}"))

    def mount(self, path):
        self.run_user(["udisksctl", "mount", "-b", path], f"{path} eingehängt")

    def unmount(self, path):
        self.run_user(["udisksctl", "unmount", "-b", path], f"{path} ausgehängt")

    def unlock(self, path):
        ask(self, f"{path} entsperren", [
            {"key": "pw", "label": "Passphrase", "kind": "password"}],
            lambda v: run(["udisksctl", "unlock", "-b", path, "--key-file", "/dev/stdin"],
                          lambda ok, o, e: (toast(self, "Entsperrt"), self.refresh())
                          if ok else error(self, "Fehler", e), input=v["pw"]))

    def smart(self, path):
        run(["smartctl", "-H", "-A", "-i", path],
            lambda ok, o, e: error(self, f"SMART {path}", o or e), root=True)


class Fstab(Module):
    id = "fstab"
    title = "Einhängepunkte (fstab)"
    icon = "folder-remote-symbolic"
    category = "Hardware"
    description = "/etc/fstab bearbeiten – dauerhafte Einhängepunkte, Netzlaufwerke"
    keywords = "fstab mount nfs smb cifs netzlaufwerk einhängen automount"

    def refresh(self):
        self.clear()
        self.text = read_file("/etc/fstab")
        g = self.group("Einträge", "Gerät · Ziel · Typ · Optionen")
        lines = self.text.splitlines()
        for idx, line in enumerate(lines):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            p = line.split()
            if len(p) < 4:
                continue
            row = Adw.ActionRow(title=esc(p[1]), subtitle=esc(f"{p[0]}\n{p[2]} · {p[3]}"))
            row.set_subtitle_lines(2)
            row.add_suffix(icon_button("document-edit-symbolic", "Bearbeiten",
                                       self.edit, idx))
            row.add_suffix(icon_button("user-trash-symbolic", "Entfernen",
                                       self.delete, idx))
            g.add(row)
        add = text_button("Eintrag hinzufügen", self.edit, None, css="suggested-action")
        add.set_halign(Gtk.Align.END)
        add.set_margin_top(6)
        g.add(add)
        g = self.group("Hinweis")
        g.add(label_row("Netzlaufwerk-Beispiele",
                        "//server/share  /mnt/share  cifs  credentials=/root/.smb,"
                        "uid=1000,_netdev,nofail  0 0\n"
                        "server:/export  /mnt/nfs  nfs  defaults,_netdev,nofail  0 0"))

    def _save(self, lines, msg):
        content = "\n".join(lines).rstrip("\n") + "\n"

        def after(ok, o, e):
            if ok:
                run(["systemctl", "daemon-reload"], None, root=True)
                toast(self, msg + " (Backup: /etc/fstab.fast-bak)")
                self.refresh()
            else:
                error(self, "Fehler", e)
        write_root_file("/etc/fstab", content, after)

    def edit(self, idx):
        lines = self.text.splitlines()
        cur = lines[idx].split() if idx is not None else ["", "", "auto", "defaults,nofail",
                                                          "0", "0"]
        cur += ["0"] * (6 - len(cur))

        def go(v):
            entry = "  ".join([v["dev"], v["mp"], v["fs"], v["opts"], v["dump"], v["pass"]])
            if not v["dev"].strip() or not v["mp"].strip():
                return
            if idx is None:
                lines.append(entry)
            else:
                lines[idx] = entry
            self._save(lines, "fstab gespeichert")
        ask(self, "fstab-Eintrag", [
            {"key": "dev", "label": "Gerät (UUID=…, /dev/…, //server/share)", "default": cur[0]},
            {"key": "mp", "label": "Einhängepunkt", "default": cur[1]},
            {"key": "fs", "label": "Dateisystem", "default": cur[2]},
            {"key": "opts", "label": "Optionen", "default": cur[3]},
            {"key": "dump", "label": "Dump", "default": cur[4]},
            {"key": "pass", "label": "Prüfreihenfolge (fsck)", "default": cur[5]},
        ], go, action_label="Speichern")

    def delete(self, idx):
        lines = self.text.splitlines()
        confirm(self, "Eintrag entfernen?", lines[idx], "Entfernen",
                lambda: self._save(lines[:idx] + lines[idx + 1:], "Eintrag entfernt"))


class Printers(Module):
    id = "printers"
    title = "Drucker"
    icon = "printer-symbolic"
    category = "Hardware"
    description = "Drucker hinzufügen, entfernen, Standarddrucker, Warteschlangen"
    keywords = "drucker printer cups druck warteschlange ipp"
    requires = ("lpstat",)

    def __init__(self):
        super().__init__()
        self.add_header_button("list-add-symbolic", "Drucker hinzufügen", self.add)
        self.add_header_button("web-browser-symbolic", "CUPS-Weboberfläche",
                               lambda: launch(["xdg-open", "http://localhost:631"]))

    def refresh(self):
        self.clear()
        _, devs, _ = run_sync(["lpstat", "-v"])
        _, default, _ = run_sync(["lpstat", "-d"])
        _, states, _ = run_sync(["lpstat", "-p"])
        _, jobs, _ = run_sync(["lpstat", "-o"])
        default = default.split(":")[-1].strip()
        g = self.group("Drucker")
        found = False
        for line in devs.splitlines():
            m = re.match(r"device for (\S+): (.*)", line)
            if not m:
                continue
            found = True
            name, uri = m[1], m[2]
            st = re.search(rf"printer {re.escape(name)} (.*)", states)
            row = Adw.ActionRow(title=esc(name + (" (Standard)" if name == default else "")),
                                subtitle=esc(f"{uri}\n{st[1] if st else ''}"))
            row.set_subtitle_lines(2)
            if name != default:
                row.add_suffix(text_button("Als Standard", self.run_root,
                                           ["lpadmin", "-d", name], "Standarddrucker gesetzt"))
            row.add_suffix(icon_button("document-print-symbolic", "Testseite",
                                       self.test, name))
            row.add_suffix(icon_button("user-trash-symbolic", "Entfernen",
                                       lambda n=name: confirm(
                                           self, f"{n} entfernen?", "", "Entfernen",
                                           lambda: self.run_root(["lpadmin", "-x", n],
                                                                 "Drucker entfernt"))))
            g.add(row)
        if not found:
            g.add(label_row("Keine Drucker eingerichtet",
                            "Netzwerkdrucker mit IPP Everywhere werden meist automatisch "
                            "erkannt. Sonst über + hinzufügen."))
        g = self.group("Druckaufträge")
        if not jobs.strip():
            g.add(label_row("Keine Aufträge"))
        for line in jobs.splitlines():
            jid = line.split()[0]
            row = label_row(jid, line)
            row.add_suffix(icon_button("process-stop-symbolic", "Abbrechen",
                                       self.run_user, ["cancel", jid], "Abgebrochen"))
            g.add(row)
        _, found_devs, _ = run_sync(["lpinfo", "--include-schemes", "dnssd,ipp,usb",
                                     "-v"], timeout=15)
        g = self.group("Gefundene Geräte")
        for line in found_devs.splitlines():
            p = line.split(None, 1)
            if len(p) == 2 and "://" in p[1]:
                row = label_row(p[1], p[0])
                row.add_suffix(text_button("Einrichten", self.add, p[1]))
                g.add(row)

    def add(self, uri=""):
        ask(self, "Drucker hinzufügen", [
            {"key": "name", "label": "Name (ohne Leerzeichen)", "default": "Drucker"},
            {"key": "uri", "label": "Geräte-URI (ipp://…, usb://…)", "default": uri},
            {"key": "model", "label": "Treiber", "default": "everywhere"},
        ], lambda v: self.run_root(["lpadmin", "-p", v["name"], "-E", "-v", v["uri"],
                                    "-m", v["model"]], "Drucker eingerichtet"),
            action_label="Hinzufügen")

    def test(self, name):
        self.run_user(["lp", "-d", name, "/usr/share/cups/data/testprint"], "Testseite gesendet")


class Sound(Module):
    id = "sound"
    title = "Sound"
    icon = "audio-speakers-symbolic"
    category = "Hardware"
    description = "Soundkarten-Profile, Standardausgabe und -eingabe, Lautstärke"
    keywords = "sound audio lautsprecher mikrofon pipewire pulseaudio hdmi profil"
    requires = ("pactl",)

    def __init__(self):
        super().__init__()
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def _json(self, what):
        ok, out, _ = run_sync(["pactl", "-f", "json", "list", what])
        try:
            return json.loads(out) if ok else []
        except ValueError:
            return []

    def refresh(self):
        self.clear()
        _, dsink, _ = run_sync(["pactl", "get-default-sink"])
        _, dsrc, _ = run_sync(["pactl", "get-default-source"])
        for title, kind, default, setcmd in (
                ("Ausgabegeräte", "sinks", dsink.strip(), "set-default-sink"),
                ("Eingabegeräte", "sources", dsrc.strip(), "set-default-source")):
            g = self.group(title)
            first = None
            for d in self._json(kind):
                if kind == "sources" and d.get("monitor_source") is not None \
                        and d["name"].endswith(".monitor"):
                    continue
                vols = [int(v["value_percent"].rstrip("%")) for v in
                        d.get("volume", {}).values()] or [0]
                row = Adw.ActionRow(title=esc(d.get("description", d["name"])),
                                    subtitle=esc(d["name"]))
                chk = Gtk.CheckButton(active=d["name"] == default, valign=Gtk.Align.CENTER)
                if first:
                    chk.set_group(first)
                first = first or chk
                chk.connect("toggled", lambda c, n=d["name"], s=setcmd:
                            c.get_active() and run(["pactl", s, n]))
                row.add_prefix(chk)
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
                scale.set_value(max(vols))
                scale.set_size_request(180, -1)
                scale.add_mark(100, Gtk.PositionType.BOTTOM, None)
                vcmd = "set-sink-volume" if kind == "sinks" else "set-source-volume"
                scale.connect("value-changed", lambda s, n=d["name"], c=vcmd:
                              run(["pactl", c, n, f"{int(s.get_value())}%"]))
                row.add_suffix(scale)
                mute = Gtk.ToggleButton(icon_name="audio-volume-muted-symbolic",
                                        active=d.get("mute", False), valign=Gtk.Align.CENTER,
                                        tooltip_text="Stumm")
                mcmd = "set-sink-mute" if kind == "sinks" else "set-source-mute"
                mute.connect("toggled", lambda b, n=d["name"], c=mcmd:
                             run(["pactl", c, n, "1" if b.get_active() else "0"]))
                row.add_suffix(mute)
                g.add(row)
        g = self.group("Soundkarten und Profile")
        for c in self._json("cards"):
            profiles = c.get("profiles", {})
            names = list(profiles.keys())
            labels = [f"{profiles[n].get('description', n)}"
                      f"{'' if profiles[n].get('available', True) else ' (nicht verfügbar)'}"
                      for n in names]
            row = Adw.ComboRow(title=esc(c.get("properties", {}).get("device.description",
                                                                     c["name"])),
                               subtitle=esc(c["name"]), model=Gtk.StringList.new(labels))
            if c.get("active_profile") in names:
                row.set_selected(names.index(c["active_profile"]))
            row.connect("notify::selected", lambda r, _p, cn=c["name"], ns=names:
                        run(["pactl", "set-card-profile", cn, ns[r.get_selected()]],
                            lambda ok, o, e: toast(self, "Profil gesetzt") if ok
                            else error(self, "Fehler", e)))
            g.add(row)
        if have("pavucontrol"):
            b = text_button("Erweitert (pavucontrol)", lambda: launch(["pavucontrol"]))
            b.set_halign(Gtk.Align.END)
            g.add(b)


MODULES = [Disks, Fstab, Printers, Sound]
