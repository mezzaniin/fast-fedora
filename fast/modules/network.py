"""Netzwerk: Verbindungen (NetworkManager), WLAN, VPN, Firewall, Hosts, SSH-Server."""
import os
import re

from gi.repository import Adw, Gio, Gtk

from ..util import (Module, ask, confirm, error, esc, icon_button, label_row,
                    read_file, run, run_sync, text_button, toast,
                    write_root_file)


def nm_split(line):
    """nmcli -t trennt mit ':' und maskiert '\\:'."""
    return [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]


class Network(Module):
    id = "network"
    title = "Netzwerkeinstellungen"
    icon = "network-wired-symbolic"
    category = "Netzwerk"
    description = "Netzwerkkarten, Verbindungen, IP-Adressen, DNS, WLAN"
    keywords = "netzwerk network ip dhcp dns gateway lan wlan wifi ethernet nmcli"
    requires = ("nmcli",)

    def __init__(self):
        super().__init__()
        self.add_header_button("list-add-symbolic", "Verbindung hinzufügen", self.add)
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def refresh(self):
        self.clear()
        _, devs, _ = run_sync(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev"])
        g = self.group("Netzwerkgeräte")
        for line in devs.splitlines():
            dev, typ, state, con = (nm_split(line) + ["", "", "", ""])[:4]
            if typ in ("loopback",):
                continue
            _, det, _ = run_sync(["nmcli", "-t", "-f",
                                  "GENERAL.HWADDR,IP4.ADDRESS,IP4.GATEWAY,IP4.DNS,"
                                  "IP6.ADDRESS", "dev", "show", dev])
            info = {}
            for l in det.splitlines():
                k, _, v = l.partition(":")
                info.setdefault(re.sub(r"\[\d+\]", "", k), []).append(v)
            ips = ", ".join(info.get("IP4.ADDRESS", []))
            sub = (f"{typ} · {state}{' · ' + con if con else ''}\n"
                   f"IPv4: {ips or '–'} · GW: {', '.join(info.get('IP4.GATEWAY', [])) or '–'}"
                   f" · DNS: {', '.join(info.get('IP4.DNS', [])) or '–'}\n"
                   f"MAC: {''.join(info.get('GENERAL.HWADDR', []))}")
            row = Adw.ActionRow(title=esc(dev), subtitle=esc(sub))
            row.set_subtitle_lines(3)
            if state.startswith("connected"):
                row.add_suffix(text_button("Trennen", self.run_user,
                                           ["nmcli", "dev", "disconnect", dev], "Getrennt"))
            elif state != "unavailable":
                row.add_suffix(text_button("Verbinden", self.run_user,
                                           ["nmcli", "dev", "connect", dev], "Verbunden"))
            g.add(row)

        _, cons, _ = run_sync(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE,ACTIVE",
                               "con", "show"])
        g = self.group("Verbindungsprofile")
        for line in cons.splitlines():
            name, uuid, typ, dev, active = (nm_split(line) + [""] * 5)[:5]
            if typ == "loopback":
                continue
            row = Adw.ActionRow(title=esc(name),
                                subtitle=esc(f"{typ}{' · ' + dev if dev else ''}"
                                             f"{' · aktiv' if active == 'yes' else ''}"))
            if active == "yes":
                row.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
                row.add_suffix(icon_button("media-playback-stop-symbolic", "Deaktivieren",
                                           self.run_user, ["nmcli", "con", "down", uuid],
                                           "Deaktiviert"))
            else:
                row.add_suffix(icon_button("media-playback-start-symbolic", "Aktivieren",
                                           self.run_user, ["nmcli", "con", "up", uuid],
                                           "Aktiviert"))
            row.add_suffix(icon_button("document-edit-symbolic", "Bearbeiten",
                                       self.edit, uuid, name))
            row.add_suffix(icon_button("user-trash-symbolic", "Löschen",
                                       lambda u=uuid, n=name: confirm(
                                           self, f"„{n}“ löschen?", "", "Löschen",
                                           lambda: self.run_user(["nmcli", "con", "delete", u],
                                                                 "Gelöscht"))))
            g.add(row)
        self._wifi()

    def _wifi(self):
        _, radio, _ = run_sync(["nmcli", "radio", "wifi"])
        g = self.group("WLAN")
        sw = Adw.SwitchRow(title="WLAN eingeschaltet", active=radio.strip() == "enabled")
        sw.connect("notify::active", lambda r, _p: self.run_user(
            ["nmcli", "radio", "wifi", "on" if r.get_active() else "off"], "WLAN umgeschaltet"))
        g.add(sw)
        if radio.strip() != "enabled":
            return
        _, nets, _ = run_sync(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev",
                               "wifi", "list"], timeout=20)
        seen = set()
        for line in nets.splitlines():
            inuse, ssid, sig, sec = (nm_split(line) + [""] * 4)[:4]
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            row = Adw.ActionRow(title=esc(ssid), subtitle=esc(f"Signal {sig} % · {sec or 'offen'}"))
            if inuse == "*":
                row.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
            else:
                row.add_suffix(text_button("Verbinden", self._wifi_connect, ssid, bool(sec)))
            g.add(row)

    def _wifi_connect(self, ssid, secured):
        if not secured:
            self.run_user(["nmcli", "dev", "wifi", "connect", ssid], f"Verbunden mit {ssid}")
            return
        ask(self, f"Mit „{ssid}“ verbinden", [
            {"key": "pw", "label": "Passwort", "kind": "password"}],
            lambda v: self.run_user(["nmcli", "dev", "wifi", "connect", ssid, "password",
                                     v["pw"]], f"Verbunden mit {ssid}"),
            action_label="Verbinden")

    def edit(self, uuid, name):
        _, out, _ = run_sync(["nmcli", "-t", "-g",
                              "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,"
                              "ipv6.method,connection.autoconnect,connection.zone,"
                              "802-3-ethernet.wake-on-lan", "con", "show", uuid])
        vals = (out.split("\n") + [""] * 8)[:8]
        method, addr, gw, dns, v6, auto, zone, wol = [v.strip() for v in vals]

        def go(v):
            m = "auto" if v["method"] == "DHCP (automatisch)" else "manual"
            cmd = ["nmcli", "con", "mod", uuid, "ipv4.method", m,
                   "ipv4.addresses", v["addr"] if m == "manual" else "",
                   "ipv4.gateway", v["gw"] if m == "manual" else "",
                   "ipv4.dns", v["dns"].replace(" ", ","),
                   "ipv4.ignore-auto-dns", "yes" if v["dns"].strip() and m == "auto" else "no",
                   "ipv6.method", v["v6"],
                   "connection.autoconnect", "yes" if v["auto"] else "no",
                   "connection.zone", v["zone"]]
            self.run_user(cmd, "Gespeichert – Verbindung neu aktivieren, damit es wirkt",
                          then=lambda ok: ok and run(["nmcli", "con", "up", uuid],
                                                     lambda *a: self.refresh()))
        _, zones, _ = run_sync(["firewall-cmd", "--get-zones"])
        zones = [""] + zones.split()
        ask(self, f"„{name}“ bearbeiten", [
            {"key": "method", "label": "IPv4", "kind": "combo",
             "options": ["DHCP (automatisch)", "Statisch (manuell)"],
             "default": "Statisch (manuell)" if method == "manual" else "DHCP (automatisch)"},
            {"key": "addr", "label": "Adresse/Präfix (z. B. 192.168.178.95/24)", "default": addr},
            {"key": "gw", "label": "Gateway", "default": gw},
            {"key": "dns", "label": "DNS-Server (Komma-getrennt)", "default": dns},
            {"key": "v6", "label": "IPv6", "kind": "combo",
             "options": ["auto", "dhcp", "manual", "link-local", "ignore", "disabled"],
             "default": v6 or "auto"},
            {"key": "zone", "label": "Firewall-Zone", "kind": "combo", "options": zones,
             "default": zone},
            {"key": "auto", "label": "Automatisch verbinden", "kind": "switch",
             "default": auto == "yes"},
        ], go, action_label="Speichern")

    def add(self):
        def go(v):
            t = {"Ethernet": "ethernet", "WLAN": "wifi", "Bridge": "bridge",
                 "VLAN": "vlan"}[v["type"]]
            cmd = ["nmcli", "con", "add", "type", t, "con-name", v["name"],
                   "ifname", v["ifname"] or "*"]
            if t == "wifi":
                cmd += ["ssid", v["extra"]]
            if t == "vlan":
                parent, _, vid = v["extra"].partition(".")
                cmd += ["dev", parent, "id", vid]
            self.run_user(cmd, "Verbindung angelegt")
        ask(self, "Verbindung hinzufügen", [
            {"key": "type", "label": "Typ", "kind": "combo",
             "options": ["Ethernet", "WLAN", "Bridge", "VLAN"]},
            {"key": "name", "label": "Name"},
            {"key": "ifname", "label": "Schnittstelle (leer = beliebig)"},
            {"key": "extra", "label": "SSID (WLAN) bzw. eltern.vlanid (VLAN, z. B. enp5s0.10)"},
        ], go, action_label="Anlegen")


class VPN(Module):
    id = "vpn"
    title = "VPN"
    icon = "network-vpn-symbolic"
    category = "Netzwerk"
    description = "WireGuard- und VPN-Verbindungen, Tailscale"
    keywords = "vpn wireguard openvpn tailscale tunnel"
    requires = ("nmcli",)

    def __init__(self):
        super().__init__()
        self.add_header_button("document-open-symbolic", "WireGuard-/OpenVPN-Datei importieren",
                               self.import_file)

    def refresh(self):
        self.clear()
        _, cons, _ = run_sync(["nmcli", "-t", "-f", "NAME,UUID,TYPE,ACTIVE", "con", "show"])
        g = self.group("VPN-Verbindungen")
        n = 0
        for line in cons.splitlines():
            name, uuid, typ, active = (nm_split(line) + [""] * 4)[:4]
            if typ not in ("wireguard", "vpn"):
                continue
            n += 1
            row = Adw.SwitchRow(title=esc(name), subtitle=esc(typ), active=active == "yes")
            row.connect("notify::active", lambda r, _p, u=uuid: self.run_user(
                ["nmcli", "con", "up" if r.get_active() else "down", u],
                "Verbunden" if r.get_active() else "Getrennt"))
            g.add(row)
        if not n:
            g.add(label_row("Keine VPN-Verbindungen",
                            "Über das Ordner-Symbol oben eine .conf (WireGuard) oder "
                            ".ovpn-Datei importieren."))
        ok, ts, _ = run_sync(["tailscale", "status"])
        if ok or ts:
            g = self.group("Tailscale")
            tv = Gtk.TextView(editable=False, monospace=True)
            tv.get_buffer().set_text(ts)
            g.add(Gtk.Frame(child=tv))

    def import_file(self):
        dlg = Gtk.FileDialog(title="VPN-Konfiguration importieren")
        f = Gtk.FileFilter()
        f.set_name("WireGuard / OpenVPN")
        for p in ("*.conf", "*.ovpn"):
            f.add_pattern(p)
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dlg.set_filters(store)

        def done(d, res):
            try:
                path = d.open_finish(res).get_path()
            except Exception:
                return
            typ = "openvpn" if path.endswith(".ovpn") else "wireguard"
            self.run_user(["nmcli", "con", "import", "type", typ, "file", path],
                          "VPN importiert")
        dlg.open(self.get_root(), None, done)


class Firewall(Module):
    id = "firewall"
    title = "Firewall"
    icon = "security-high-symbolic"
    category = "Sicherheit und Benutzer"
    description = "firewalld: Zonen, Dienste, Ports, Schnittstellen"
    keywords = "firewall firewalld port dienst zone öffnen blockieren"
    requires = ("firewall-cmd",)

    def __init__(self):
        super().__init__()
        self.zone = None
        self.add_header_button("view-refresh-symbolic", "Neu laden", self.refresh)

    def _q(self, *args):
        return run_sync(["firewall-cmd", *args])[1].strip()

    def refresh(self):
        self.clear()
        state = self._q("--state")
        g = self.group("Status")
        sw = Adw.SwitchRow(title="Firewall aktiv", active=state == "running",
                           subtitle="firewalld.service")
        sw.connect("notify::active", lambda r, _p: self.run_root(
            ["systemctl", "enable" if r.get_active() else "disable", "--now",
             "firewalld"], "Firewall umgeschaltet"))
        g.add(sw)
        if state != "running":
            return
        panic = Adw.SwitchRow(title="Panik-Modus", subtitle="Blockiert sämtlichen Netzverkehr",
                              active=self._q("--query-panic") == "yes")
        panic.connect("notify::active", lambda r, _p: self.run_root(
            ["firewall-cmd", "--panic-on" if r.get_active() else "--panic-off"],
            "Panik-Modus geändert"))
        g.add(panic)
        zones = self._q("--get-zones").split()
        default = self._q("--get-default-zone")
        dz = Adw.ComboRow(title="Standardzone", model=Gtk.StringList.new(zones))
        if default in zones:
            dz.set_selected(zones.index(default))
        dz.connect("notify::selected", lambda r, _p: self.run_root(
            ["firewall-cmd", "--set-default-zone", zones[r.get_selected()]],
            "Standardzone geändert"))
        g.add(dz)
        g.add(label_row("Aktive Zonen", self._q("--get-active-zones").replace("\n", " ")))
        self.zone = self.zone or default
        zsel = Adw.ComboRow(title="Zone bearbeiten", model=Gtk.StringList.new(zones))
        zsel.set_selected(zones.index(self.zone) if self.zone in zones else 0)

        def change_zone(r, _p):
            self.zone = zones[r.get_selected()]
            self.refresh()
        zsel.connect("notify::selected", change_zone)
        g.add(zsel)
        self._zone(self.zone)

    def _perm(self, *args, msg="Gespeichert"):
        z = ["--zone", self.zone]
        self.run_root(["firewall-cmd", "--permanent", *z, *args], msg,
                      then=lambda ok: ok and self.run_root(["firewall-cmd", "--reload"]))

    def _zone(self, zone):
        services = self._q("--zone", zone, "--list-services").split()
        ports = self._q("--zone", zone, "--list-ports").split()
        ifaces = self._q("--zone", zone, "--list-interfaces").split()
        sources = self._q("--zone", zone, "--list-sources").split()
        rich = [r for r in self._q("--zone", zone, "--list-rich-rules").splitlines() if r]
        g = self.group(f"Zone „{zone}“: freigegebene Dienste")
        for s in services:
            row = label_row(s)
            row.add_suffix(icon_button("list-remove-symbolic", "Entfernen", self._perm,
                                       "--remove-service", s))
            g.add(row)
        allsvc = sorted(self._q("--get-services").split())
        add = Adw.ComboRow(title="Dienst freigeben", model=Gtk.StringList.new(allsvc),
                           enable_search=True)
        add.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        add.add_suffix(icon_button("list-add-symbolic", "Freigeben",
                                   lambda: self._perm("--add-service",
                                                      allsvc[add.get_selected()])))
        g.add(add)
        g = self.group("Offene Ports")
        for p in ports:
            row = label_row(p)
            row.add_suffix(icon_button("list-remove-symbolic", "Schließen", self._perm,
                                       "--remove-port", p))
            g.add(row)
        e = Adw.EntryRow(title="Port öffnen (z. B. 8080/tcp oder 6000-6010/udp)")
        e.set_show_apply_button(True)
        e.connect("apply", lambda w: re.fullmatch(r"\d+(-\d+)?/(tcp|udp|sctp|dccp)",
                                                  w.get_text().strip()) and
                  self._perm("--add-port", w.get_text().strip()))
        g.add(e)
        g = self.group("Schnittstellen und Quellen")
        for i in ifaces:
            g.add(label_row(i, "Schnittstelle"))
        for s in sources:
            row = label_row(s, "Quelle")
            row.add_suffix(icon_button("list-remove-symbolic", "Entfernen", self._perm,
                                       "--remove-source", s))
            g.add(row)
        e = Adw.EntryRow(title="Quelle hinzufügen (IP/Netz, z. B. 192.168.178.0/24)")
        e.set_show_apply_button(True)
        e.connect("apply", lambda w: self._perm("--add-source", w.get_text().strip()))
        g.add(e)
        g = self.group("Erweiterte Regeln (Rich Rules)")
        for r in rich:
            row = label_row(r)
            row.add_suffix(icon_button("list-remove-symbolic", "Entfernen", self._perm,
                                       "--remove-rich-rule", r))
            g.add(row)
        e = Adw.EntryRow(title='z. B. rule family="ipv4" source address="1.2.3.4" drop')
        e.set_show_apply_button(True)
        e.connect("apply", lambda w: self._perm("--add-rich-rule", w.get_text().strip()))
        g.add(e)
        g = self.group("Weitere Einstellungen")
        masq = Adw.SwitchRow(title="Masquerading (NAT)",
                             active=self._q("--zone", zone, "--query-masquerade") == "yes")
        masq.connect("notify::active", lambda r, _p: self._perm(
            "--add-masquerade" if r.get_active() else "--remove-masquerade"))
        g.add(masq)


class Hosts(Module):
    id = "hosts"
    title = "Hosts-Datei"
    icon = "network-server-symbolic"
    category = "Netzwerk"
    description = "Statische Namensauflösung in /etc/hosts"
    keywords = "hosts dns name auflösung"

    def refresh(self):
        self.clear()
        self.lines = read_file("/etc/hosts").splitlines()
        g = self.group("Einträge in /etc/hosts")
        for idx, line in enumerate(self.lines):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            p = line.split()
            row = label_row(p[0], " ".join(p[1:]))
            row.add_suffix(icon_button("user-trash-symbolic", "Entfernen", self._del, idx))
            g.add(row)
        e = Adw.EntryRow(title="Neu: IP-Adresse  name [alias …]")
        e.set_show_apply_button(True)
        e.connect("apply", lambda w: len(w.get_text().split()) >= 2 and self._save(
            self.lines + [w.get_text().strip()]))
        g.add(e)
        g = self.group("DNS-Auflösung (systemd-resolved)")
        _, st, _ = run_sync(["resolvectl", "status", "--no-pager"])
        tv = Gtk.TextView(editable=False, monospace=True)
        tv.get_buffer().set_text(st)
        g.add(Gtk.Frame(child=tv))

    def _save(self, lines):
        write_root_file("/etc/hosts", "\n".join(lines).rstrip("\n") + "\n",
                        lambda ok, o, e: (toast(self, "Gespeichert"), self.refresh())
                        if ok else error(self, "Fehler", e))

    def _del(self, idx):
        confirm(self, "Eintrag entfernen?", self.lines[idx], "Entfernen",
                lambda: self._save(self.lines[:idx] + self.lines[idx + 1:]))


class SSHServer(Module):
    id = "sshd"
    title = "SSH-Server"
    icon = "utilities-terminal-symbolic"
    category = "Netzwerk"
    description = "sshd ein/aus, Root-Login, Passwort-Anmeldung, Port"
    keywords = "ssh sshd fernzugriff remote port root passwort"
    requires = ("sshd",)
    CONF = "/etc/ssh/sshd_config.d/50-fast.conf"

    def refresh(self):
        self.clear()
        _, active, _ = run_sync(["systemctl", "is-active", "sshd"])
        _, enabled, _ = run_sync(["systemctl", "is-enabled", "sshd"])
        g = self.group("Dienst")
        sw = Adw.SwitchRow(title="SSH-Server aktiv und beim Start aktivieren",
                           subtitle=f"{active.strip()} · {enabled.strip()}",
                           active=active.strip() == "active")
        sw.connect("notify::active", lambda r, _p: self.run_root(
            ["systemctl", "enable" if r.get_active() else "disable", "--now", "sshd"],
            "sshd umgeschaltet"))
        g.add(sw)
        cur = {}
        for line in read_file(self.CONF, root=True).splitlines():
            p = line.split(None, 1)
            if len(p) == 2 and not p[0].startswith("#"):
                cur[p[0]] = p[1].strip()
        g = self.group("Einstellungen", f"Gespeichert in {self.CONF}. "
                       "Andere Dateien in sshd_config.d mit niedrigerer Nummer haben Vorrang.")
        self.rows = {}
        for key, label, opts, default in (
                ("PermitRootLogin", "Root-Anmeldung", ["no", "prohibit-password", "yes"],
                 "prohibit-password"),
                ("PasswordAuthentication", "Passwort-Anmeldung", ["yes", "no"], "yes"),
                ("PubkeyAuthentication", "Schlüssel-Anmeldung", ["yes", "no"], "yes"),
                ("X11Forwarding", "X11-Weiterleitung", ["no", "yes"], "no")):
            r = Adw.ComboRow(title=label, subtitle=key, model=Gtk.StringList.new(opts))
            v = cur.get(key, default)
            r.set_selected(opts.index(v) if v in opts else 0)
            self.rows[key] = (r, opts)
            g.add(r)
        self.port = Adw.EntryRow(title="Port")
        self.port.set_text(cur.get("Port", "22"))
        g.add(self.port)
        self.extra = {k: v for k, v in cur.items() if k not in self.rows and k != "Port"}
        b = text_button("Speichern und sshd neu laden", self.save, css="suggested-action")
        b.set_halign(Gtk.Align.END)
        b.set_margin_top(6)
        g.add(b)
        keys = os.path.expanduser("~/.ssh/authorized_keys")
        g = self.group("Autorisierte Schlüssel (eigener Benutzer)")
        for line in read_file(keys).splitlines():
            if line.strip() and not line.startswith("#"):
                p = line.split()
                g.add(label_row(p[-1] if len(p) > 2 else "Schlüssel", p[0]))

    def save(self):
        lines = ["# Verwaltet von FAST"]
        for key, (r, opts) in self.rows.items():
            lines.append(f"{key} {opts[r.get_selected()]}")
        port = self.port.get_text().strip()
        if port.isdigit():
            lines.append(f"Port {port}")
        for k, v in self.extra.items():
            lines.append(f"{k} {v}")

        def after(ok, o, e):
            if not ok:
                error(self, "Fehler", e)
                return
            run(["sshd", "-t"], lambda ok2, o2, e2: self.run_root(
                ["systemctl", "reload-or-restart", "sshd"], "sshd neu geladen")
                if ok2 else error(self, "Konfiguration ungültig", e2), root=True)
        if port.isdigit() and port != "22":
            run(["semanage", "port", "-a", "-t", "ssh_port_t", "-p", "tcp", port],
                None, root=True)
        write_root_file(self.CONF, "\n".join(lines) + "\n", after)


MODULES = [Network, VPN, Firewall, Hosts, SSHServer]
