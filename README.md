# FAST – Fedora Administration & Setup Tool

Eine grafische Systemverwaltung für Fedora im Stil von **YaST**: alle wichtigen
Einstellungen in einem Kontrollzentrum. Gebaut mit Python, GTK 4 und libadwaita.
Das Look & Feel entspricht GNOME.

FAST bringt keine eigene Systemlogik mit. Jedes Modul ist eine Oberfläche für die
Standardwerkzeuge von Fedora (dnf5, systemd, NetworkManager, firewalld,
grubby, …). Was du in FAST änderst, siehst du deshalb genauso in der
Kommandozeile und in den GNOME-Einstellungen.

<img width="1552" height="1042" alt="image" src="https://github.com/user-attachments/assets/793da5e3-cc68-4685-8ddf-7410ab186367" />

## Module

| Kategorie | Modul | Werkzeug dahinter |
|---|---|---|
| **Software** | Software installieren/entfernen | `dnf5 repoquery/install/remove` |
| | Paketgruppen | `dnf5 group` |
| | Software-Repositories (inkl. RPM Fusion, COPR) | `dnf5 config-manager`, `dnf5 copr` |
| | Online-Update (System, Flatpak, Firmware, Offline-Update, Versions-Upgrade, Verlauf) | `dnf5`, `flatpak`, `fwupdmgr` |
| | Flatpak-Anwendungen | `flatpak` |
| **System** | Dienste-Verwaltung (System + Benutzer) | `systemctl` |
| | Systemprotokolle | `journalctl` |
| | Bootloader (Standard-Kernel, Kernel-Parameter, Timeout, Secure Boot) | `grubby`, `grub2-mkconfig` |
| | Datum und Uhrzeit | `timedatectl` |
| | Sprache und Tastatur | `localectl` |
| | Rechnername | `hostnamectl` |
| | Kernel-Einstellungen | `sysctl` → `/etc/sysctl.d/90-fast.conf` |
| | Energie und Leistung | `tuned-adm`, `systemctl reboot/poweroff` |
| | Snapshots | `snapper` |
| | Geplante Aufgaben | systemd-Timer, `crontab` |
| **Hardware** | Hardware-Informationen (CPU, RAM, Sensoren, PCI, USB, Module) | `/proc`, `/sys`, `lspci`, `lsusb` |
| | Datenträger und Partitionen (Einhängen, LUKS, SMART, Swap) | `lsblk`, `udisksctl`, `smartctl` |
| | Einhängepunkte | `/etc/fstab` |
| | Drucker | CUPS (`lpadmin`, `lpstat`, `lpinfo`) |
| | Sound (Geräte, Lautstärke, Kartenprofile) | `pactl` (PipeWire) |
| **Netzwerk** | Netzwerkeinstellungen (Geräte, Profile, IP/DNS, WLAN) | `nmcli` |
| | VPN (WireGuard/OpenVPN importieren, Tailscale-Status) | `nmcli` |
| | Hosts-Datei | `/etc/hosts`, `resolvectl` |
| | SSH-Server | `/etc/ssh/sshd_config.d/50-fast.conf` |
| **Sicherheit und Benutzer** | Sicherheitsüberblick | diverse Prüfungen |
| | Firewall (Zonen, Dienste, Ports, Quellen, Rich Rules, Panik-Modus) | `firewall-cmd` |
| | Benutzer | `useradd`, `usermod`, `userdel`, `chpasswd` |
| | Gruppen | `groupadd`, `gpasswd` |
| | SELinux (Modus, Booleans, AVC-Meldungen) | `setenforce`, `setsebool`, `ausearch` |
| **Virtualisierung** | Virtuelle Maschinen | `virsh` (libvirt) |
| | Container | `podman` |

Module, deren Werkzeug nicht installiert ist, blendet FAST automatisch aus.

## Installation

Empfohlen ist das RPM-Paket. Damit erscheint FAST mit Icon im App-Raster und
als installierte App in GNOME Software, und `dnf` kann es sauber
aktualisieren und entfernen:

```bash
git clone git@github.com:mezzaniin/fast-fedora.git
cd fast-fedora
./build-rpm.sh                                  # baut nach ./dist/ (ohne root)
sudo dnf install ./dist/fast-fedora-*.noarch.rpm
```

Alternativ ohne Paket: `sudo ./install.sh`

Danach findest du **FAST Systemverwaltung** im App-Menü. Im Terminal startest du
es mit `fast`. Ein Modul lässt sich auch direkt öffnen, ähnlich wie
`yast2 <modul>`:

```bash
fast --list        # alle Module
fast firewall      # direkt die Firewall öffnen
fast packages
```

Ohne Installation läuft FAST auch direkt aus dem Quellordner: `./bin/fast`.
Root-Aktionen fragen dann allerdings jedes Mal nach dem Passwort, weil die
polkit-Regel fehlt.

Deinstallieren: `sudo dnf remove fast-fedora` (bzw. `sudo ./install.sh --uninstall`)

## Wie Root-Rechte funktionieren

FAST selbst läuft als normaler Benutzer. Braucht eine Aktion Root-Rechte, wird
sie über **pkexec** an den kleinen Helfer `/usr/libexec/fast/fast-helper`
übergeben:

- Der Helfer startet nur Programme aus einer festen Liste (dnf5, systemctl,
  firewall-cmd, …) mit einer bereinigten Umgebung.
- Dateien schreibt er nur, wenn sie auf einer festen Liste stehen (`/etc/hosts`,
  `/etc/fstab`, `/etc/default/grub`, …). Vor jedem Schreiben legt er eine
  Sicherung `<datei>.fast-bak` an und setzt danach den SELinux-Kontext neu.
- Die polkit-Regel `de.pattiit.fast.helper` nutzt `auth_admin_keep`: Nach einer
  Passworteingabe kommen ein paar Minuten lang keine weiteren Abfragen.

NetworkManager, udisks, flatpak und podman prüfen ihre Rechte selbst über
polkit. Diese Aufrufe laufen ohne den Helfer.

## Entwicklung

```
fast/
  app.py            Hauptfenster, Seitenleiste, Übersicht, Kommandozeile
  util.py           Prozesse (async), Root-Aufrufe, Dialoge, Basisklasse Module
  modules/          ein Python-Modul je Kategorie
helper/fast-helper  Root-Helfer (pkexec)
data/               polkit-Policy, .desktop-Datei
tests/smoke_test.py öffnet jedes Modul und meldet Ausnahmen
```

Ein neues Modul anlegen:

```python
from ..util import Module, label_row

class MeinModul(Module):
    id = "meinmodul"
    title = "Mein Modul"
    icon = "applications-system-symbolic"
    category = "System"
    description = "Kurzbeschreibung"
    keywords = "suchbegriffe"
    requires = ("programm",)      # optional

    def refresh(self):
        self.clear()
        g = self.group("Überschrift")
        g.add(label_row("Titel", "Untertitel"))
```

Danach trägst du die Klasse in die `MODULES`-Liste der passenden Datei unter
`fast/modules/` ein.

Test, ohne etwas am System zu ändern (keine Root-Aufrufe):

```bash
FAST_NO_ROOT=1 python3 tests/smoke_test.py
```

## Grenzen gegenüber YaST

- **Kein Installer und keine Partitionierung:** Partitionen anlegen, löschen oder
  verkleinern übernimmt *GNOME Laufwerke* (Knopf im Modul Datenträger). Die
  Neuinstallation macht Anaconda.
- **Kein AutoYaST:** Unbeaufsichtigte Installationen laufen auf Fedora über
  Kickstart.
- **Nur Bildschirm:** Es gibt keine Text-Oberfläche (ncurses) wie bei YaST.
  Für Server ohne Bildschirm eignet sich Cockpit besser.

## Lizenz

MIT
