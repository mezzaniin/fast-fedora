"""Modul-Registry. Neue Module: Klasse von util.Module ableiten und in MODULES eintragen."""
from . import hardware, network, security, software, system, virt

CATEGORIES = [
    ("Software", "system-software-install-symbolic"),
    ("System", "preferences-system-symbolic"),
    ("Hardware", "computer-symbolic"),
    ("Netzwerk", "network-workgroup-symbolic"),
    ("Sicherheit und Benutzer", "security-high-symbolic"),
    ("Virtualisierung", "computer-symbolic"),
]

ALL_MODULES = [
    *software.MODULES,
    *system.MODULES,
    *hardware.MODULES,
    *network.MODULES,
    *security.MODULES,
    *virt.MODULES,
]


def available_modules():
    return [m for m in ALL_MODULES if m.available()]
