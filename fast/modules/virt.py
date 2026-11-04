"""Virtualisierung: virtuelle Maschinen (libvirt) und Container (Podman)."""
import json

from gi.repository import Adw, Gtk

from ..util import (Module, confirm, error, esc, have, icon_button, label_row,
                    launch, run, run_sync, text_button)


class VMs(Module):
    id = "vms"
    title = "Virtuelle Maschinen"
    icon = "computer-symbolic"
    category = "Virtualisierung"
    description = "libvirt/KVM-VMs starten, stoppen, Autostart"
    keywords = "vm virtuell kvm qemu libvirt virsh virt-manager"
    requires = ("virsh",)
    URI = "qemu:///system"

    def __init__(self):
        super().__init__()
        if have("virt-manager"):
            self.add_header_button("applications-system-symbolic", "Virt-Manager öffnen",
                                   lambda: launch(["virt-manager"]))
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def _v(self, *a):
        return ["virsh", "-c", self.URI, *a]

    def refresh(self):
        self.clear()
        ok, out, err = run_sync(self._v("list", "--all", "--name"))
        g = self.group("Virtuelle Maschinen (qemu:///system)")
        if not ok:
            g.add(label_row("libvirt nicht erreichbar", err.strip()))
            r = Adw.ActionRow(title="Virtualisierung installieren",
                              subtitle="dnf5 group install virtualization")
            r.add_suffix(text_button("Installieren", lambda: self.log(
                "Virtualisierung", ["dnf5", "group", "install", "-y", "virtualization"])))
            g.add(r)
            return
        names = [n for n in out.splitlines() if n.strip()]
        if not names:
            g.add(label_row("Keine VMs vorhanden"))
        for n in names:
            _, info, _ = run_sync(self._v("dominfo", n))
            d = dict((l.split(":", 1)[0].strip(), l.split(":", 1)[1].strip())
                     for l in info.splitlines() if ":" in l)
            running = d.get("State") == "running"
            row = Adw.ActionRow(title=esc(n),
                                subtitle=esc(f"{d.get('State', '?')} · {d.get('CPU(s)', '?')} vCPU"
                                             f" · {int(d.get('Max memory', '0 KiB').split()[0]) // 1024} MiB"))
            auto = Gtk.Switch(active=d.get("Autostart") == "enable", valign=Gtk.Align.CENTER,
                              tooltip_text="Autostart")
            auto.connect("state-set", lambda s, st, n=n: self.run_root(
                self._v("autostart", *([] if st else ["--disable"]), n), "Autostart geändert")
                or False)
            row.add_suffix(auto)
            if running:
                row.add_suffix(icon_button("system-shutdown-symbolic", "Herunterfahren",
                                           self.run_root, self._v("shutdown", n),
                                           "Herunterfahren gesendet"))
                row.add_suffix(icon_button("process-stop-symbolic", "Hart ausschalten",
                                           lambda n=n: confirm(
                                               self, f"{n} hart ausschalten?",
                                               "Entspricht Stecker ziehen.", "Ausschalten",
                                               lambda: self.run_root(self._v("destroy", n),
                                                                     "Ausgeschaltet"))))
                if have("virt-viewer"):
                    row.add_suffix(icon_button("video-display-symbolic", "Anzeige",
                                               lambda n=n: launch(["virt-viewer", "-c",
                                                                   self.URI, n])))
            else:
                row.add_suffix(icon_button("media-playback-start-symbolic", "Starten",
                                           self.run_root, self._v("start", n), "Gestartet"))
            g.add(row)
        _, nets, _ = run_sync(self._v("net-list", "--all"))
        g = self.group("Virtuelle Netzwerke")
        for line in nets.splitlines()[2:]:
            p = line.split()
            if len(p) >= 3:
                g.add(label_row(p[0], f"{p[1]} · Autostart {p[2]}"))


class Containers(Module):
    id = "containers"
    title = "Container (Podman)"
    icon = "package-x-generic-symbolic"
    category = "Virtualisierung"
    description = "Podman-Container und Images verwalten"
    keywords = "container podman docker image toolbox distrobox"
    requires = ("podman",)

    def __init__(self):
        super().__init__()
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        self.clear()
        _, out, _ = run_sync(["podman", "ps", "-a", "--format", "json"])
        try:
            cons = json.loads(out or "[]")
        except ValueError:
            cons = []
        g = self.group("Container (eigener Benutzer)")
        if not cons:
            g.add(label_row("Keine Container"))
        for c in cons:
            name = (c.get("Names") or ["?"])[0]
            state = c.get("State", "")
            row = Adw.ActionRow(title=esc(name),
                                subtitle=esc(f"{c.get('Image', '')}\n{c.get('Status', state)}"))
            row.set_subtitle_lines(2)
            if state == "running":
                row.add_suffix(icon_button("media-playback-stop-symbolic", "Stoppen",
                                           self.run_user, ["podman", "stop", name], "Gestoppt"))
                row.add_suffix(icon_button("view-refresh-symbolic", "Neu starten",
                                           self.run_user, ["podman", "restart", name],
                                           "Neu gestartet"))
            else:
                row.add_suffix(icon_button("media-playback-start-symbolic", "Starten",
                                           self.run_user, ["podman", "start", name], "Gestartet"))
            row.add_suffix(icon_button("text-x-generic-symbolic", "Logs", self.logs, name))
            row.add_suffix(icon_button("user-trash-symbolic", "Entfernen",
                                       lambda n=name: confirm(
                                           self, f"Container {n} entfernen?", "", "Entfernen",
                                           lambda: self.run_user(["podman", "rm", "-f", n],
                                                                 "Entfernt"))))
            g.add(row)
        _, imgs, _ = run_sync(["podman", "images", "--format", "json"])
        try:
            imgs = json.loads(imgs or "[]")
        except ValueError:
            imgs = []
        tools = text_button("Ungenutzte entfernen", lambda: self.run_user(
            ["podman", "image", "prune", "-af"], "Aufgeräumt"))
        g = self.group("Images", suffix=tools)
        for i in imgs:
            name = (i.get("Names") or [i.get("Id", "")[:12]])[0]
            size = int(i.get("Size", 0)) / 1e6
            row = label_row(name, f"{size:.0f} MB")
            row.add_suffix(icon_button("user-trash-symbolic", "Löschen", self.run_user,
                                       ["podman", "rmi", i.get("Id", "")], "Gelöscht"))
            g.add(row)

    def logs(self, name):
        run(["podman", "logs", "--tail", "200", name],
            lambda ok, o, e: error(self, f"Logs: {name}", (o + e)[-20000:]))


MODULES = [VMs, Containers]
