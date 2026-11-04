Name:           fast-fedora
Version:        0.1.0
Release:        1%{?dist}
Summary:        FAST – Fedora-Systemverwaltung im Stil von YaST
License:        MIT
URL:            https://github.com/mezzaniin/fast-fedora
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  desktop-file-utils
BuildRequires:  appstream
Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita
Requires:       polkit
Recommends:     gnome-disk-utility

%description
FAST (Fedora Administration & Setup Tool) bündelt die Systemverwaltung von
Fedora in einem grafischen Kontrollzentrum: Software, Updates, Dienste,
Bootloader, Netzwerk, Firewall, Benutzer, SELinux, Datenträger, Drucker,
Sound, Snapshots, VMs und Container.

%prep
%autosetup

%build

%install
install -d %{buildroot}%{_datadir}/fast %{buildroot}%{_libexecdir}/fast
cp -r fast %{buildroot}%{_datadir}/fast/
install -Dm0755 bin/fast %{buildroot}%{_bindir}/fast
install -Dm0755 helper/fast-helper %{buildroot}%{_libexecdir}/fast/fast-helper
install -Dm0644 data/de.pattiit.fast.policy %{buildroot}%{_datadir}/polkit-1/actions/de.pattiit.fast.policy
install -Dm0644 data/de.pattiit.Fast.desktop %{buildroot}%{_datadir}/applications/de.pattiit.Fast.desktop
install -Dm0644 data/de.pattiit.Fast.metainfo.xml %{buildroot}%{_metainfodir}/de.pattiit.Fast.metainfo.xml
install -Dm0644 data/icons/de.pattiit.Fast.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/de.pattiit.Fast.svg
install -Dm0644 data/icons/de.pattiit.Fast-symbolic.svg %{buildroot}%{_datadir}/icons/hicolor/symbolic/apps/de.pattiit.Fast-symbolic.svg
python3 -m compileall -q -d %{_datadir}/fast/fast %{buildroot}%{_datadir}/fast/fast

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/de.pattiit.Fast.desktop
appstreamcli validate --no-net %{buildroot}%{_metainfodir}/de.pattiit.Fast.metainfo.xml

%files
%license LICENSE
%doc README.md
%{_bindir}/fast
%{_datadir}/fast/
%{_libexecdir}/fast/
%{_datadir}/polkit-1/actions/de.pattiit.fast.policy
%{_datadir}/applications/de.pattiit.Fast.desktop
%{_metainfodir}/de.pattiit.Fast.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/de.pattiit.Fast.svg
%{_datadir}/icons/hicolor/symbolic/apps/de.pattiit.Fast-symbolic.svg

%changelog
* Wed Nov 04 2026 mezzaniin <mezzaniin@users.noreply.github.com> - 0.1.0-1
- Erste Version
