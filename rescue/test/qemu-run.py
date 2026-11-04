#!/usr/bin/python3
"""Startet das Test-Rettungssystem in QEMU und bedient es per Tastatur-Emulation.
Screenshots: $T/shot-*.png, Prüf-Ausgabe: $T/serial.log"""
import os, socket, subprocess, sys, time
T = os.environ.get("FAST_TEST_DIR", "/tmp/fast-rescue-test")
SOCK = f"{T}/mon.sock"
args = ["qemu-kvm", "-m", "2048", "-smp", "2", "-no-reboot",
        "-kernel", f"{T}/vmlinuz", "-initrd", f"{T}/initramfs.img",
        "-append", "rd.systemd.unit=fast-rescue.target rd.plymouth=0 plymouth.enable=0 "
                   "vconsole.keymap=de console=tty1 loglevel=3 systemd.show_status=error",
        "-display", "none", "-vga", "std", "-monitor", f"unix:{SOCK},server,nowait",
        "-serial", f"file:{T}/serial.log",
        "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0,mac=52:54:00:12:34:56"]
for img in ("efi", "boot", "root", "repo"):
    args += ["-drive", f"file={T}/{img}.img,if=virtio,format=raw"]
if os.path.exists(SOCK):
    os.unlink(SOCK)
vm = subprocess.Popen(args)
time.sleep(2)
mon = socket.socket(socket.AF_UNIX)
mon.connect(SOCK)

def hmp(cmd):
    if vm.poll() is not None:
        return
    mon.sendall((cmd + "\n").encode()); time.sleep(0.15)
    try:
        mon.setblocking(False); mon.recv(65536)
    except BlockingIOError:
        pass
    mon.setblocking(True)

KEYS = {" ": "spc", "\n": "ret", "-": "slash"}
def type_text(s):
    for ch in s:
        if ch.isupper():
            hmp(f"sendkey shift-{ch.lower()}")
        else:
            hmp(f"sendkey {KEYS.get(ch, ch)}")

def shot(name):
    if vm.poll() is not None:
        return
    ppm = f"{T}/shot-{name}.ppm"
    hmp(f"screendump {ppm}"); time.sleep(0.5)
    import gi; gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    GdkPixbuf.Pixbuf.new_from_file(ppm).savev(f"{T}/shot-{name}.png", "png", [], [])
    os.unlink(ppm)

def wait(s):
    for _ in range(int(s * 2)):
        if vm.poll() is not None:
            return
        time.sleep(0.5)

wait(30); shot("1-start")
type_text("test123\n"); wait(10); shot("2-liste")
type_text("1\n"); wait(6); shot("3-bestaetigen")
type_text("WIEDERHERSTELLEN\n"); wait(25); shot("4-fertig")
type_text("\n")
for _ in range(120):
    if vm.poll() is not None:
        break
    time.sleep(1)
else:
    shot("5-haengt"); vm.kill(); print("VM hat nicht neu gestartet"); sys.exit(1)
print("VM beendet (Neustart erkannt)")
