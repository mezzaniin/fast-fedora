# FAST Backup & FAST Rescue

Komplettes System-Backup von Fedora auf den Unraid-Server und Wiederherstellung
über einen eigenen Eintrag im Bootmenü, auch wenn Fedora nicht mehr startet.

## Ablauf

**Backup**, jeden Montag um 14:00 (`fast-backup.timer`; war der PC aus, wird es
beim nächsten Start nachgeholt):

1. Nur-Lese-Snapshots von `/` und `/home` (btrfs), dadurch ein konsistenter Stand
2. Dazu kommen `/boot` und `/boot/efi`
3. `borg create` per SSH ins Repo `/mnt/user/backup/Fedora-PC/repo` auf Unraid
   (verschlüsselt mit `repokey-blake2`, komprimiert mit zstd)
4. Meldung per Telegram bei Start, Erfolg (mit Größe und Dauer) und Fehler

Nicht gesichert werden Caches, der Papierkorb und die Steam-Spieldateien
(`steamapps/common`). Spielstände und Proton-Prefixe sind enthalten. Die Liste
steht in `excludes`.

**Aufräumen** übernimmt Unraid (dienstags 04:00, `fedora-prune.sh`): Behalten
werden 8 wöchentliche und 6 monatliche Stände. Der PC darf nur **anhängen**
(append-only, eingeschränkter SSH-Schlüssel), er kann also keine Backups löschen.

**Wiederherstellung:**

1. PC starten und im Bootmenü **„FAST Rescue – System aus Backup
   wiederherstellen“** wählen
2. Das Rettungssystem lädt komplett in den RAM und verbindet sich mit Unraid
3. Backup-Passwort eingeben und ein Backup aus der Liste wählen (neuestes oben)
4. Zur Bestätigung `WIEDERHERSTELLEN` eintippen
5. Wiederhergestellt werden `/` und `/home` als neue Subvolumes, danach `/boot`
   und die EFI-Partition
6. Der bisherige Stand wird **nicht gelöscht**, sondern als
   `root.vor-restore-DATUM` bzw. `home.vor-restore-DATUM` aufgehoben. Steam-Spiele
   werden per Reflink aus dem alten `/home` übernommen; das geht sofort und kostet
   keinen Platz.
7. Automatischer Neustart, danach läuft das System auf dem Stand des Backups

Ist das Dateisystem so beschädigt, dass es sich nicht mehr einhängen lässt,
bietet das Rettungssystem an, es mit derselben UUID neu zu formatieren.
`/boot` und EFI werden in dem Fall automatisch neu angelegt.

## Installation

Einmalig ausführen. Das Skript fragt das neue Backup-Passwort ab:

```bash
sudo ./rescue/install.sh
```

Was es tut:
- installiert Programme, das dracut-Modul und den Timer
- trägt auf Unraid zwei eingeschränkte SSH-Schlüssel ein (Backup und Rescue,
  beide nur `borg serve --append-only` für `/mnt/user/backup/Fedora-PC`)
- übernimmt die Telegram-Daten vom vorhandenen Unraid-Bot
- legt das Repo an und sichert den Repo-Schlüssel
- baut das Rettungssystem nach `/boot/fast-rescue` und blendet das Bootmenü ein

Vorher müssen die Schlüssel in `~/.config/fast-backup-staging` liegen: `borg`
(1.4.3 standalone, Prüfsumme verifiziert), `id_backup`, `id_rescue` und
`known_hosts`.

## Bedienung

```bash
sudo systemctl start fast-backup        # Backup sofort
journalctl -u fast-backup -f            # Fortschritt
systemctl list-timers fast-backup.timer # nächster Termin
cat /var/lib/fast-backup/status.json    # letztes Ergebnis
sudo /usr/libexec/fast/fast-rescue-build  # Rettungssystem neu bauen (z. B. nach Netz-Änderung)
```

Ein alter Stand nach einer erfolgreichen Wiederherstellung wird nicht mehr
gebraucht? Dann so löschen:

```bash
sudo mount -o subvolid=5 /dev/nvme1n1p3 /mnt
sudo btrfs subvolume delete -R /mnt/root.vor-restore-* /mnt/home.vor-restore-*
sudo umount /mnt
```

## Sicherheit

- In `/boot` liegt nur der Rescue-SSH-Schlüssel. Er darf ausschließlich
  `borg serve --append-only` im Fedora-Ordner auf Unraid ausführen, also weder
  eine Shell öffnen noch löschen. Ohne das Passwort sind die Backups damit nicht
  lesbar.
- Das Passwort liegt auf dem PC in `/etc/fast-backup/passphrase` (nur root) und
  auf Unraid für das Aufräumen. Den Repo-Schlüssel gibt es zusätzlich in
  `/etc/fast-backup/repo-key.txt` und auf Unraid unter
  `/boot/config/borg/fedora-pc-repo-key.txt`.
- **Ohne Passwort und Repo-Schlüssel ist das Backup verloren.** Das Passwort
  gehört in den Passwortmanager.

## Test

```bash
./rescue/test/qemu-test.sh && python3 ./rescue/test/qemu-run.py
```

Der Test baut Test-Datenträger und ein Test-Backup, bootet das Rettungssystem in
QEMU, bedient es per Tastatur-Emulation und prüft das Ergebnis in `serial.log`.
Das echte System bleibt dabei unberührt.
