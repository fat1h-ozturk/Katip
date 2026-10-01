Name:           katip
Version:        %{_version}
Release:        1%{?dist}
Summary:        Ultra-fast AI voice dictation desktop assistant

License:        MIT
URL:            https://github.com/fat1h-ozturk/Katip
AutoReqProv:    no

%description
High-performance, low-latency cross-platform dictation assistant for Linux, Windows, and macOS.
Self-contained desktop application with system tray, global shortcut capture, and multi-model AI speech-to-text.

%install
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/256x256/apps

install -m 755 %{_sourcedir}/dist/Katip %{buildroot}%{_bindir}/katip
install -m 644 %{_sourcedir}/katip.desktop %{buildroot}%{_datadir}/applications/katip.desktop
install -m 644 %{_sourcedir}/assets/katip.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/katip.svg
install -m 644 %{_sourcedir}/assets/katip-256.png %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/katip.png

%files
%{_bindir}/katip
%{_datadir}/applications/katip.desktop
%{_datadir}/icons/hicolor/scalable/apps/katip.svg
%{_datadir}/icons/hicolor/256x256/apps/katip.png

%changelog
* Fri Oct 02 2026 Fatih Ozturk <fatih@example.com> - %{_version}-1
- Official RPM release for Fedora Linux
