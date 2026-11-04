#!/bin/bash
# dracut-Modul für das FAST-Rettungssystem.
# Wird nur von fast-rescue-build verwendet (nicht in normale Initramfs eingebaut).

check() { return 255; }   # nur auf ausdrücklichen Wunsch (--add fastrescue)

depends() { echo systemd btrfs crypt i18n; }

installkernel() {
    hostonly='' instmods nvme ahci sd_mod usb_storage uas xhci_pci btrfs ext4 vfat \
        nls_cp437 nls_ascii nls_iso8859-1 dm_crypt igc e1000e r8169 r8125 tg3 \
        atlantic alx virtio_pci virtio_blk virtio_net
}

install() {
    local etc=${FAST_RESCUE_ETC:-/etc/fast-backup}
    local borg=${FAST_RESCUE_BORG:-/usr/libexec/fast/borg}
    inst_multiple bash ip ping ssh blkid lsblk findmnt mount umount mkdir rm cp mv \
        ls cat tac grep sed awk sort df du sync sleep seq date clear less tail head \
        timeout basename dirname chmod rmdir find wc tr cut \
        mkfs.btrfs btrfs mkfs.ext4 mke2fs mkfs.vfat mkfs.fat e2fsck fsck.vfat \
        cryptsetup reboot udevadm stty setsid
    inst_simple "$moddir/fast-restore" /usr/bin/fast-restore
    inst_simple "$borg" /usr/bin/borg
    inst_simple "$etc/rescue.conf" /etc/fast-rescue.conf
    inst_simple "$etc/id_rescue" /etc/fast-rescue/id_rescue
    inst_simple "$etc/known_hosts" /etc/fast-rescue/known_hosts
    # nur für automatische Tests (test/qemu-test.sh)
    [ -n "${FAST_RESCUE_TEST:-}" ] && inst_simple "$FAST_RESCUE_TEST" /etc/fast-rescue-test.sh
    chmod 600 "$initdir/etc/fast-rescue/id_rescue"
    inst_simple "$moddir/fast-rescue.service" "$systemdsystemunitdir/fast-rescue.service"
    inst_simple "$moddir/fast-rescue.target" "$systemdsystemunitdir/fast-rescue.target"
    # Zeitzone/Uhrzeit-Anzeige
    [ -e /etc/localtime ] && inst_simple /etc/localtime
    # borg (PyInstaller) entpackt sich nach TMPDIR
    mkdir -p "$initdir/run/fast-rescue" "$initdir/root"
    # NSS für ssh (Benutzer root muss auflösbar sein)
    grep '^root:' /etc/passwd >>"$initdir/etc/passwd"
    inst_libdir_file 'libnss_files*'
    # borg ist ein PyInstaller-Programm und lädt diese Systembibliotheken nach
    inst_libdir_file libutil.so.1 libdl.so.2 libpthread.so.0 librt.so.1 libz.so.1 \
        libgcc_s.so.1 libm.so.6
}
