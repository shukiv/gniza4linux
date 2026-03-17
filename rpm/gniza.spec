Name:           gniza
Version:        %{VERSION}
Release:        1%{?dist}
Summary:        Linux Backup Manager
License:        MIT
URL:            https://git.linux-hosting.co.il/shukivaknin/gniza4linux
BuildArch:      noarch

Requires:       bash >= 4.0
Requires:       rsync
Requires:       python3
Recommends:     openssh-clients
Recommends:     sshpass
Recommends:     curl

%description
A complete Linux backup solution with incremental rsync snapshots,
hardlink deduplication, MySQL/PostgreSQL dumps, and multi-channel notifications.
Manage via Terminal UI, web dashboard, or CLI.

%install
mkdir -p %{buildroot}/usr/local/gniza
for dir in bin lib tui web daemon etc scripts data; do
    if [ -d %{_sourcedir}/$dir ]; then
        cp -a %{_sourcedir}/$dir %{buildroot}/usr/local/gniza/
    fi
done
[ -f %{_sourcedir}/LICENSE ] && cp %{_sourcedir}/LICENSE %{buildroot}/usr/local/gniza/
mkdir -p %{buildroot}/usr/local/bin
ln -s /usr/local/gniza/bin/gniza %{buildroot}/usr/local/bin/gniza

# Strip unwanted files
rm -rf %{buildroot}/usr/local/gniza/.git
find %{buildroot} -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find %{buildroot} -name "*.pyc" -delete 2>/dev/null || true
rm -f %{buildroot}/usr/local/gniza/scripts/install.sh
rm -f %{buildroot}/usr/local/gniza/scripts/uninstall.sh
rm -f %{buildroot}/usr/local/gniza/scripts/deploy.sh
rm -f %{buildroot}/usr/local/gniza/scripts/build-deb.sh
rm -f %{buildroot}/usr/local/gniza/scripts/build-rpm.sh
rm -f %{buildroot}/usr/local/gniza/README.md
rm -f %{buildroot}/usr/local/gniza/DOCUMENTATION.md
rm -rf %{buildroot}/usr/local/gniza/tests

%post
# Create config directories
mkdir -p /etc/gniza/targets.d /etc/gniza/remotes.d /etc/gniza/schedules.d
chmod 700 /etc/gniza /etc/gniza/targets.d /etc/gniza/remotes.d /etc/gniza/schedules.d

# Create log and work directories
mkdir -p /var/log/gniza
mkdir -p /usr/local/gniza/workdir

# Copy example config if not present
if [ ! -f /etc/gniza/gniza.conf ]; then
    cp /usr/local/gniza/etc/gniza.conf.example /etc/gniza/gniza.conf
    chmod 600 /etc/gniza/gniza.conf
fi

# Set up Python venv
if command -v python3 >/dev/null 2>&1; then
    if [ ! -d /usr/local/gniza/venv ]; then
        python3 -m venv /usr/local/gniza/venv 2>/dev/null || true
    fi
    if [ -d /usr/local/gniza/venv ]; then
        /usr/local/gniza/venv/bin/pip install --quiet "textual>=0.40" textual-serve flask flask-wtf waitress psutil 2>/dev/null || true
    fi
fi

# Install systemd services
if [ -d /etc/systemd/system ]; then
    cp /usr/local/gniza/etc/gniza-web.service /etc/systemd/system/ 2>/dev/null || true
    cp /usr/local/gniza/etc/gniza-daemon.service /etc/systemd/system/ 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true
fi

chmod +x /usr/local/gniza/bin/gniza

%preun
if [ $1 -eq 0 ]; then
    systemctl stop gniza-web 2>/dev/null || true
    systemctl stop gniza-daemon 2>/dev/null || true
    systemctl disable gniza-web 2>/dev/null || true
    systemctl disable gniza-daemon 2>/dev/null || true
fi

%postun
if [ $1 -eq 0 ]; then
    rm -f /etc/systemd/system/gniza-web.service
    rm -f /etc/systemd/system/gniza-daemon.service
    systemctl daemon-reload 2>/dev/null || true
    rm -rf /usr/local/gniza
    rm -f /usr/local/bin/gniza
fi

%files
/usr/local/gniza
/usr/local/bin/gniza
