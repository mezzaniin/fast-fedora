#!/bin/bash
# End-to-End-Test des Rettungssystems in QEMU – ändert nichts am echten System.
# Baut Test-Datenträger (EFI/boot/btrfs) und ein lokales Test-Backup, bootet das
# Rettungs-Initramfs, bedient das Menü per Tastatur-Emulation und prüft das Ergebnis.
#   ./rescue/test/qemu-test.sh   (braucht: qemu-kvm, dracut, mkfs.*, borg in staging)
set -euo pipefail
HERE=$(cd "$(dirname "$0")/.." && pwd)
T=${FAST_TEST_DIR:-/tmp/fast-rescue-test}
BORG=${BORG:-$HOME/.config/fast-backup-staging/borg}
KVER=$(uname -r)
chmod -R u+w "$T" 2>/dev/null; rm -rf "$T"; mkdir -p "$T"/{src,old,etc,dracut,repodisk}
export BORG_PASSPHRASE=test123 BORG_BASE_DIR="$T/borgbase"
EFI_ID=1234ABCD; EFI_UUID=1234-ABCD
BOOT_UUID=11111111-2222-3333-4444-555555555555
ROOT_UUID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee

echo "== Test-Backup erzeugen"
S=$T/src
mkdir -p $S/root/etc $S/root/usr/bin $S/root/.snapshots $S/home/mezzanin/Documents \
         $S/boot/loader/entries $S/boot/grub2 $S/efi/EFI/fedora
echo 'NAME="Fedora Backup-Stand"' >$S/root/etc/os-release
echo "backup-version" >$S/root/usr/bin/marker
echo "Dokument aus dem Backup" >$S/home/mezzanin/Documents/doc.txt
echo "kernel-aus-backup" >$S/boot/vmlinuz-backup
echo "title Fedora (backup)" >$S/boot/loader/entries/fedora-backup.conf
echo "grubcfg" >$S/boot/grub2/grub.cfg
echo "efi-aus-backup" >$S/efi/EFI/fedora/grubx64.efi
"$BORG" init --encryption=repokey-blake2 "$T/repodisk/repo"
(cd $S && "$BORG" create "$T/repodisk/repo::fedora-2026-11-02_14-00" root home boot efi)
echo "neuere-version" >$S/root/usr/bin/marker
(cd $S && "$BORG" create "$T/repodisk/repo::fedora-2026-11-09_14-00" root home boot efi)
mkfs.ext4 -q -L fastrepo -d "$T/repodisk" "$T/repo.img" 256M

echo "== „Kaputtes“ System als Datenträger erzeugen"
O=$T/old
mkdir -p $O/btrfs/root/etc $O/btrfs/root/usr/bin $O/btrfs/home/mezzanin/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Spiel \
         $O/boot/fast-rescue $O/boot/loader/entries $O/efi/EFI/fedora
echo "KAPUTT" >$O/btrfs/root/etc/os-release
echo "alt" >$O/btrfs/root/usr/bin/marker
echo "spieldaten" >$O/btrfs/home/mezzanin/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Spiel/game.bin
echo "rettung" >$O/boot/fast-rescue/vmlinuz
echo "title FAST Rescue" >$O/boot/loader/entries/fast-rescue.conf
echo "kaputter-kernel" >$O/boot/vmlinuz-kaputt
echo "alt-efi" >$O/efi/EFI/fedora/grubx64.efi
mkfs.btrfs -q -f -U $ROOT_UUID -L fedora --rootdir $O/btrfs --subvol rw:root --subvol rw:home "$T/root.img" -b 512M >/dev/null 2>&1 \
  || { truncate -s 512M "$T/root.img"; mkfs.btrfs -q -f -U $ROOT_UUID -L fedora --rootdir $O/btrfs --subvol rw:root --subvol rw:home "$T/root.img"; }
mkfs.ext4 -q -U $BOOT_UUID -d $O/boot "$T/boot.img" 128M
truncate -s 64M "$T/efi.img"; mkfs.vfat -F 32 -i $EFI_ID "$T/efi.img" >/dev/null
mcopy -s -i "$T/efi.img" $O/efi/EFI ::/ 2>/dev/null || echo "(mtools fehlt – EFI-Image bleibt leer)"

echo "== Test-Konfiguration"
cat >"$T/etc/rescue.conf" <<EOT
REPO="/mnt/testrepo/repo"
REPO_HOST="127.0.0.1"
ROOT_UUID="$ROOT_UUID"
ROOT_LABEL="fedora"
ROOT_PART="/dev/vdc"
LUKS_UUID=""
SUBVOL_ROOT="root"
SUBVOL_HOME="home"
BOOT_UUID="$BOOT_UUID"
BOOT_PART="/dev/vdb"
EFI_UUID="$EFI_UUID"
EFI_PART="/dev/vda"
NET_MAC="52:54:00:12:34:56"
NET_ADDR="10.0.2.15/24"
NET_GW="10.0.2.2"
NET_DNS="10.0.2.3"
CARRY_OVER=( "*/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common" )
EOT
: >"$T/etc/id_rescue"; : >"$T/etc/known_hosts"
cat >"$T/etc/test.sh" <<'EOT'
mkdir -p /mnt/testrepo
for i in $(seq 1 20); do blkid -L fastrepo >/dev/null 2>&1 && break; sleep 0.5; done
mount -t ext4 "$(blkid -L fastrepo)" /mnt/testrepo
fast_test_verify() {
    exec >/dev/ttyS0 2>&1
    echo "=== VERIFY START"
    mount -t btrfs -o subvolid=5 /dev/vdc /mnt/top
    btrfs subvolume list /mnt/top | awk '{print "SUBVOL " $NF}'
    echo "OS: $(cat /mnt/top/root/etc/os-release)"
    echo "MARKER: $(cat /mnt/top/root/usr/bin/marker)"
    echo "DOC: $(cat /mnt/top/home/mezzanin/Documents/doc.txt)"
    echo "STEAM: $(cat /mnt/top/home/mezzanin/.var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Spiel/game.bin 2>&1)"
    echo "OLDROOT: $(cat /mnt/top/root.vor-restore-*/etc/os-release 2>&1)"
    umount /mnt/top
    mount /dev/vdb /mnt/boot
    echo "BOOT: $(ls /mnt/boot | tr '\n' ' ')"
    echo "ENTRIES: $(ls /mnt/boot/loader/entries | tr '\n' ' ')"
    echo "RESCUE: $(cat /mnt/boot/fast-rescue/vmlinuz 2>&1)"
    umount /mnt/boot
    mount /dev/vda /mnt/efi
    echo "EFI: $(cat /mnt/efi/EFI/fedora/grubx64.efi 2>&1)"
    umount /mnt/efi
    echo "=== VERIFY END"
}
EOT

echo "== Initramfs bauen (als Benutzer, eigener dracut-Modulordner)"
cp -a /usr/lib/dracut/. "$T/dracut/"
mkdir -p "$T/dracut/modules.d/99fastrescue"
cp "$HERE"/dracut/99fastrescue/* "$T/dracut/modules.d/99fastrescue/"
FAST_RESCUE_ETC="$T/etc" FAST_RESCUE_BORG="$BORG" FAST_RESCUE_TEST="$T/etc/test.sh" \
dracutbasedir="$T/dracut" bash /usr/bin/dracut --quiet --force --no-hostonly --no-hostonly-cmdline \
    --add "fastrescue" \
    --omit "plymouth resume nfs iscsi multipath fcoe fcoe-uefi lvm mdraid dmraid nvdimm network-manager" \
    --compress zstd --kver "$KVER" --tmpdir "$T" "$T/initramfs.img" 2>"$T/dracut.err" || { tail -20 "$T/dracut.err"; exit 1; }
ls -lh "$T/initramfs.img"
cp /boot/vmlinuz-"$KVER" "$T/vmlinuz"
echo "OK – Test-Umgebung in $T"
