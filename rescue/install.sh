#!/bin/bash
# Richtet FAST Backup + FAST Rescue ein.
#   sudo ./rescue/install.sh            Installation / Aktualisierung
#   sudo ./rescue/install.sh --uninstall
#
# Erwartet die vorbereiteten Schlüssel in ~/.config/fast-backup-staging
# (borg, id_backup, id_rescue, known_hosts) des aufrufenden Benutzers.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

[ $EUID -eq 0 ] || exec sudo "$0" "$@"
USER_NAME=${SUDO_USER:-}
[ -n "$USER_NAME" ] || { echo "Bitte mit sudo als normaler Benutzer starten."; exit 1; }
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
STAGING="$USER_HOME/.config/fast-backup-staging"

UNRAID=192.168.178.66
REPO_DIR=/mnt/user/backup/Fedora-PC
REPO="ssh://root@$UNRAID$REPO_DIR/repo"
ETC=/etc/fast-backup
LIBEXEC=/usr/libexec/fast

as_user() { sudo -u "$USER_NAME" "$@"; }
unraid() { as_user ssh -o BatchMode=yes -o ConnectTimeout=10 "root@$UNRAID" "$@"; }
step() { echo; echo "== $*"; }

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now fast-backup.timer 2>/dev/null || true
    rm -f /etc/systemd/system/fast-backup.{service,timer}
    rm -rf /usr/lib/dracut/modules.d/99fastrescue /boot/fast-rescue
    rm -f /boot/loader/entries/fast-rescue.conf "$LIBEXEC"/{fast-backup,fast-rescue-build,borg}
    systemctl daemon-reload
    echo "Entfernt. /etc/fast-backup (Schlüssel, Passwort) wurde behalten – bei Bedarf selbst löschen."
    exit 0
fi

for f in borg id_backup id_rescue known_hosts; do
    [ -s "$STAGING/$f" ] || { echo "Fehlt: $STAGING/$f"; exit 1; }
done

# ------------------------------------------------------------------ Dateien
step "Programme installieren"
install -d -m 0755 "$LIBEXEC" /usr/lib/dracut/modules.d/99fastrescue
install -m 0755 "$STAGING/borg" "$LIBEXEC/borg"
install -m 0755 fast-backup "$LIBEXEC/fast-backup"
install -m 0755 fast-rescue-build "$LIBEXEC/fast-rescue-build"
install -m 0755 dracut/99fastrescue/module-setup.sh dracut/99fastrescue/fast-restore \
    /usr/lib/dracut/modules.d/99fastrescue/
install -m 0644 dracut/99fastrescue/fast-rescue.service dracut/99fastrescue/fast-rescue.target \
    /usr/lib/dracut/modules.d/99fastrescue/
install -m 0644 systemd/fast-backup.service systemd/fast-backup.timer /etc/systemd/system/
ln -sf "$LIBEXEC/fast-backup" /usr/local/sbin/fast-backup
"$LIBEXEC/borg" --version

install -d -m 0700 "$ETC"
install -m 0600 "$STAGING/id_backup" "$ETC/id_backup"
install -m 0600 "$STAGING/id_rescue" "$ETC/id_rescue"
grep -v '^#' "$STAGING/known_hosts" >"$ETC/known_hosts"; chmod 0644 "$ETC/known_hosts"
install -m 0644 excludes "$ETC/excludes"

# ------------------------------------------------------------------ Systemdaten
step "System erkennen"
ROOT_SRC=$(findmnt -no SOURCE / | sed 's/\[.*//')
ROOT_UUID=$(findmnt -no UUID /)
ROOT_LABEL=$(blkid -s LABEL -o value "$ROOT_SRC" || true)
SUBVOL_ROOT=$(findmnt -no OPTIONS / | tr , '\n' | sed -n 's/^subvol=\/\{0,1\}//p')
SUBVOL_HOME=$(findmnt -no OPTIONS /home | tr , '\n' | sed -n 's/^subvol=\/\{0,1\}//p')
BOOT_SRC=$(findmnt -no SOURCE /boot); BOOT_UUID=$(findmnt -no UUID /boot)
EFI_SRC=$(findmnt -no SOURCE /boot/efi); EFI_UUID=$(findmnt -no UUID /boot/efi)
ROOT_PART=$ROOT_SRC; LUKS_UUID=""
if [[ "$ROOT_SRC" == /dev/mapper/* ]] || [[ "$ROOT_SRC" == /dev/dm-* ]]; then
    ROOT_PART=/dev/$(lsblk -no PKNAME "$ROOT_SRC" | head -1)
    LUKS_UUID=$(blkid -s UUID -o value "$ROOT_PART")
fi
[ "$(findmnt -no FSTYPE /)" = btrfs ] || { echo "/ ist kein btrfs – nicht unterstützt."; exit 1; }
[ -n "$SUBVOL_ROOT" ] && [ -n "$SUBVOL_HOME" ] || { echo "Subvolumes nicht erkannt."; exit 1; }
IFACE=$(ip route show default | awk '{print $5; exit}')
NET_MAC=$(cat "/sys/class/net/$IFACE/address")
NET_ADDR=$(ip -4 -o addr show "$IFACE" | awk '{print $4; exit}')
NET_GW=$(ip route show default | awk '{print $3; exit}')
echo "  /       $ROOT_SRC  (UUID $ROOT_UUID, Subvolumes $SUBVOL_ROOT + $SUBVOL_HOME)"
echo "  /boot   $BOOT_SRC  (UUID $BOOT_UUID)"
echo "  EFI     $EFI_SRC   (UUID $EFI_UUID)"
echo "  Netz    $IFACE $NET_MAC $NET_ADDR via $NET_GW"

cat >"$ETC/rescue.conf" <<EOF
# FAST Rescue – erzeugt von install.sh am $(date +%F). Enthält KEINE Passwörter.
REPO="$REPO"
REPO_HOST="$UNRAID"
ROOT_UUID="$ROOT_UUID"
ROOT_LABEL="${ROOT_LABEL:-fedora}"
ROOT_PART="$ROOT_PART"
LUKS_UUID="$LUKS_UUID"
SUBVOL_ROOT="$SUBVOL_ROOT"
SUBVOL_HOME="$SUBVOL_HOME"
BOOT_UUID="$BOOT_UUID"
BOOT_PART="$BOOT_SRC"
EFI_UUID="$EFI_UUID"
EFI_PART="$EFI_SRC"
NET_MAC="$NET_MAC"
NET_ADDR="$NET_ADDR"
NET_GW="$NET_GW"
NET_DNS="$NET_GW"
# Ordner, die nicht gesichert werden und beim Restore aus dem alten /home übernommen werden
CARRY_OVER=(
  "*/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common"
  "*/.local/share/Steam/steamapps/common"
)
EOF
chmod 0644 "$ETC/rescue.conf"

# ------------------------------------------------------------------ Unraid
step "Unraid vorbereiten ($UNRAID)"
CMD="docker run --rm -i --network none --entrypoint borg -v $REPO_DIR:$REPO_DIR local/borgbackup:1.4-alpine3.22 serve --append-only --restrict-to-path $REPO_DIR"
KEYS="command=\"$CMD\",restrict $(cat "$STAGING/id_backup.pub")
command=\"$CMD\",restrict $(cat "$STAGING/id_rescue.pub")"
printf '%s\n' "$KEYS" | unraid "set -e
mkdir -p $REPO_DIR
AK=/boot/config/ssh/root/authorized_keys
[ -f \$AK.bak-fast ] || cp \$AK \$AK.bak-fast
grep -v 'fast-backup@fedora\|fast-rescue@fedora' \$AK > /tmp/ak.new || true
cat >> /tmp/ak.new
cp /tmp/ak.new \$AK
cp /tmp/ak.new /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
rm -f /tmp/ak.new
echo '  Schlüssel eingetragen (append-only, nur $REPO_DIR)'"

# Telegram-Daten vom vorhandenen Unraid-Bot übernehmen
TG_TOKEN=$(unraid "sed -n 's/^BOT_TOKEN=\"\\(.*\\)\"/\\1/p' '/boot/config/plugins/user.scripts/scripts/Backup/script'" | head -1)
TG_CHAT=$(unraid "sed -n 's/^CHAT_ID=\"\\(.*\\)\"/\\1/p' '/boot/config/plugins/user.scripts/scripts/Backup/script'" | head -1)
[ -n "$TG_TOKEN" ] && echo "  Telegram-Bot übernommen (Chat $TG_CHAT)" || echo "  Telegram-Daten nicht gefunden – keine Benachrichtigung"

umask 077
cat >"$ETC/config" <<EOF
REPO="$REPO"
REPO_HOST="$UNRAID"
TELEGRAM_TOKEN="$TG_TOKEN"
TELEGRAM_CHAT="$TG_CHAT"
EOF
umask 022

# ------------------------------------------------------------------ Passwort + Repo
step "Backup-Passwort"
if [ ! -s "$ETC/passphrase" ]; then
    while true; do
        read -r -s -p "Neues Backup-Passwort (wird beim Wiederherstellen abgefragt): " P1; echo
        read -r -s -p "Wiederholen: " P2; echo
        [ -n "$P1" ] && [ "$P1" = "$P2" ] && break
        echo "Leer oder nicht gleich – nochmal."
    done
    (umask 077; printf '%s' "$P1" >"$ETC/passphrase")
    unset P1 P2
else
    echo "  vorhanden ($ETC/passphrase)"
fi
# Für das Aufräumen alter Backups auf Unraid (prune läuft dort, nicht vom PC aus)
unraid "umask 077; cat > /boot/config/borg/fedora-pc-pass" <"$ETC/passphrase"

export BORG_REPO="$REPO" BORG_PASSCOMMAND="cat $ETC/passphrase" BORG_BASE_DIR=/var/lib/fast-backup/borg
export BORG_RSH="ssh -i $ETC/id_backup -o BatchMode=yes -o UserKnownHostsFile=$ETC/known_hosts -o StrictHostKeyChecking=yes"
mkdir -p /var/lib/fast-backup
if "$LIBEXEC/borg" info >/dev/null 2>&1; then
    echo "  Repository existiert bereits"
else
    echo "  Lege Repository an …"
    "$LIBEXEC/borg" init --encryption=repokey-blake2 --make-parent-dirs
fi
"$LIBEXEC/borg" key export "$REPO" "$ETC/repo-key.txt"
chmod 600 "$ETC/repo-key.txt"
unraid "umask 077; cat > /boot/config/borg/fedora-pc-repo-key.txt" <"$ETC/repo-key.txt"
echo "  Repo-Schlüssel gesichert: $ETC/repo-key.txt und Unraid /boot/config/borg/fedora-pc-repo-key.txt"

# Aufräumen alter Stände auf Unraid: dienstags 04:00 (8 Wochen + 6 Monate behalten)
unraid "cat > /boot/config/borg/fedora-prune.sh" <unraid/fedora-prune.sh
unraid "chmod 755 /boot/config/borg/fedora-prune.sh 2>/dev/null; echo '0 4 * * 2 bash /boot/config/borg/fedora-prune.sh >/dev/null 2>&1' > /boot/config/plugins/dynamix/fast-fedora-prune.cron; update_cron"
echo "  Aufräum-Job auf Unraid eingerichtet (dienstags 04:00)"

# ------------------------------------------------------------------ Rettungssystem + Timer
step "Rettungssystem bauen"
"$LIBEXEC/fast-rescue-build"

step "Zeitplan aktivieren"
systemctl daemon-reload
systemctl enable --now fast-backup.timer
systemctl list-timers fast-backup.timer --no-pager | head -3

rm -f "$STAGING/id_backup" "$STAGING/id_rescue"
echo
echo "Fertig. Backup jeden Montag 14:00 (wird nachgeholt, falls der PC aus war)."
read -r -p "Erstes Backup jetzt starten? [J/n] " a
if [ "${a:-j}" != "n" ]; then
    systemctl start --no-block fast-backup.service
    echo "Läuft im Hintergrund. Fortschritt: journalctl -fu fast-backup  (Telegram meldet das Ende)"
fi
