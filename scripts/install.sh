#!/usr/bin/env bash
set -eo pipefail

REPO_URL="https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git"
DEBUG=false
[[ "${1:-}" == "--debug" ]] && DEBUG=true

# Colors - force enable when piped (curl | bash), since output still goes to terminal
C_GREEN=$'\033[0;32m'
C_RED=$'\033[0;31m'
C_YELLOW=$'\033[0;33m'
C_BOLD=$'\033[1m'
C_RESET=$'\033[0m'

info()  { echo "${C_GREEN}[INFO]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[WARN]${C_RESET} $*" >&2; }
error() { echo "${C_RED}[ERROR]${C_RESET} $*" >&2; }
die()   { error "$1"; exit 1; }

# -- Determine install mode -----------------------------------
if [[ $EUID -eq 0 ]]; then
    MODE="root"
    INSTALL_DIR="/usr/local/gniza"
    BIN_LINK="/usr/local/bin/gniza"
    CONFIG_DIR="/etc/gniza"
    LOG_DIR="/var/log/gniza"
    WORK_DIR="/usr/local/gniza/workdir"
else
    MODE="user"
    INSTALL_DIR="$HOME/.local/share/gniza"
    BIN_LINK="$HOME/.local/bin/gniza"
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gniza"
    LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gniza/log"
    WORK_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gniza/workdir"
fi

info "Install mode: ${C_BOLD}${MODE}${C_RESET}"
info "Install dir:  $INSTALL_DIR"
info "Config dir:   $CONFIG_DIR"
info "Log dir:      $LOG_DIR"
echo ""

# -- Install git if missing -----------------------------------
if ! command -v git &>/dev/null; then
    info "Installing git..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq git || die "Failed to install git"
    elif command -v yum &>/dev/null; then
        yum install -y -q git || die "Failed to install git"
    elif command -v dnf &>/dev/null; then
        dnf install -y -q git || die "Failed to install git"
    elif command -v pacman &>/dev/null; then
        pacman -Sy --noconfirm git || die "Failed to install git"
    else
        die "git is required but could not be installed automatically. Install it manually and retry."
    fi
fi

# -- Install system dependencies ------------------------------
info "Checking and installing system dependencies..."

# Detect package manager
_pkg_install() {
    if command -v apt-get &>/dev/null; then
        apt-get install -y -qq "$@"
    elif command -v yum &>/dev/null; then
        yum install -y -q "$@"
    elif command -v dnf &>/dev/null; then
        dnf install -y -q "$@"
    elif command -v pacman &>/dev/null; then
        pacman -Sy --noconfirm "$@"
    else
        return 1
    fi
}

_apt_updated=false
_apt_update() {
    if ! $_apt_updated && command -v apt-get &>/dev/null; then
        apt-get update -qq 2>/dev/null || true
        _apt_updated=true
    fi
}

# Required system packages
_to_install=()
for cmd in rsync ssh curl sshpass; do
    if ! command -v "$cmd" &>/dev/null; then
        case "$cmd" in
            ssh) _to_install+=(openssh-client) ;;
            *)   _to_install+=("$cmd") ;;
        esac
    fi
done

if [[ ${#_to_install[@]} -gt 0 ]]; then
    info "Installing system packages: ${_to_install[*]}"
    _apt_update
    _pkg_install "${_to_install[@]}" || warn "Could not install some packages: ${_to_install[*]}"
fi

# Verify critical deps
for cmd in bash rsync; do
    if ! command -v "$cmd" &>/dev/null; then
        die "Required dependency not found: $cmd"
    fi
done

# -- Install files (git clone/pull) ----------------------------
info "Installing to $INSTALL_DIR..."

if [[ -d "$INSTALL_DIR/.git" ]]; then
    # Already a git repo — just pull latest
    info "Updating existing installation..."
    git -C "$INSTALL_DIR" fetch origin
    git -C "$INSTALL_DIR" reset --hard origin/main
else
    # Fresh install — clone directly into install dir
    if [[ -d "$INSTALL_DIR" && "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        # Non-git install dir exists (e.g. old cp-based install) — preserve venv, replace rest
        info "Converting existing installation to git..."
        _tmp_venv=""
        if [[ -d "$INSTALL_DIR/venv" ]]; then
            _tmp_venv=$(mktemp -d)
            mv "$INSTALL_DIR/venv" "$_tmp_venv/venv"
        fi
        trash "$INSTALL_DIR" 2>/dev/null || rm -rf "$INSTALL_DIR"
        if $DEBUG; then
            git clone "$REPO_URL" "$INSTALL_DIR" || die "Failed to clone repository"
        else
            git clone --quiet "$REPO_URL" "$INSTALL_DIR" || die "Failed to clone repository"
        fi
        if [[ -n "${_tmp_venv:-}" && -d "$_tmp_venv/venv" ]]; then
            mv "$_tmp_venv/venv" "$INSTALL_DIR/venv"
            rm -rf "$_tmp_venv"
        fi
    else
        mkdir -p "$(dirname "$INSTALL_DIR")"
        if $DEBUG; then
            git clone "$REPO_URL" "$INSTALL_DIR" || die "Failed to clone repository"
        else
            git clone --quiet "$REPO_URL" "$INSTALL_DIR" || die "Failed to clone repository"
        fi
    fi
fi

# Make entrypoint executable
chmod +x "$INSTALL_DIR/bin/gniza"

# -- Install Python TUI dependencies -------------------------
if ! command -v python3 &>/dev/null; then
    info "Installing python3..."
    _apt_update
    _pkg_install python3 || die "Failed to install python3. Install it manually and retry."
fi
if command -v python3 &>/dev/null; then
    _pip_quiet="--quiet"
    $DEBUG && _pip_quiet=""
    _pip_pkgs=("textual>=0.40" textual-serve flask waitress)
    _venv_dir="$INSTALL_DIR/venv"

    # Ensure python3-venv is available (--help succeeds even without ensurepip,
    # so we test with an actual temp venv creation)
    _test_venv=$(mktemp -d)
    if ! python3 -m venv "$_test_venv" &>/dev/null; then
        rm -rf "$_test_venv"
        info "Installing python3-venv..."
        _apt_update
        # Try generic python3-venv first, then versioned (e.g. python3.9-venv on Debian 11)
        _pyver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "")
        if command -v apt-get &>/dev/null; then
            apt-get install -y -qq python3-venv 2>/dev/null || true
            if [[ -n "$_pyver" ]] && ! python3 -m venv "$_test_venv" &>/dev/null; then
                rm -rf "$_test_venv"
                apt-get install -y -qq "python${_pyver}-venv" 2>/dev/null || true
            fi
        else
            _pkg_install python3-virtualenv 2>/dev/null || true
        fi
    fi
    rm -rf "$_test_venv"

    # Create venv and install deps (avoids PEP 668 / externally-managed conflicts)
    info "Setting up Python virtual environment..."
    if ! python3 -m venv "$_venv_dir"; then
        die "Failed to create Python venv. Install python3-venv manually: apt-get install python3-venv"
    fi

    info "Installing Python dependencies in venv..."
    if ! "$_venv_dir/bin/pip" install $_pip_quiet "${_pip_pkgs[@]}"; then
        die "Failed to install Python dependencies. Check network connectivity and retry."
    fi
    info "Python dependencies installed."
else
    die "python3 is required but not found. Install Python 3 and retry."
fi

# -- Create symlink -------------------------------------------
info "Creating symlink: $BIN_LINK -> $INSTALL_DIR/bin/gniza"
mkdir -p "$(dirname "$BIN_LINK")"
ln -sf "$INSTALL_DIR/bin/gniza" "$BIN_LINK"

# -- Create config directories -------------------------------
info "Setting up config directory: $CONFIG_DIR"
mkdir -p "$CONFIG_DIR/targets.d"
mkdir -p "$CONFIG_DIR/remotes.d"
mkdir -p "$CONFIG_DIR/schedules.d"

if [[ "$MODE" == "root" ]]; then
    chmod 700 "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR/targets.d"
    chmod 700 "$CONFIG_DIR/remotes.d"
    chmod 700 "$CONFIG_DIR/schedules.d"
fi

# -- Create log directory -------------------------------------
info "Setting up log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"

# -- Create work directory -----------------------------------
info "Setting up work directory: $WORK_DIR"
mkdir -p "$WORK_DIR"

# -- Copy example configs (if not already present) ------------
if [[ ! -f "$CONFIG_DIR/gniza.conf" ]]; then
    cp "$INSTALL_DIR/etc/gniza.conf.example" "$CONFIG_DIR/gniza.conf"
    info "Created default config: $CONFIG_DIR/gniza.conf"
else
    info "Config already exists, not overwriting: $CONFIG_DIR/gniza.conf"
fi

for example in target.conf.example remote.conf.example schedule.conf.example; do
    if [[ -f "$INSTALL_DIR/etc/$example" ]]; then
        cp "$INSTALL_DIR/etc/$example" "$CONFIG_DIR/$example"
    fi
done

# -- Web dashboard setup --
echo ""
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo "${C_BOLD}  Web Dashboard${C_RESET} — manage backups from your browser"
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo ""
enable_web="y"
read -rp "Enable web dashboard? (y/n) [y]: " enable_web </dev/tty || true
enable_web="${enable_web:-y}"
if [ "$enable_web" = "y" ] || [ "$enable_web" = "Y" ]; then
    # Set up web password (preserve existing value)
    api_key="$(grep '^WEB_API_KEY=' "$CONFIG_DIR/gniza.conf" 2>/dev/null | sed 's/^WEB_API_KEY="//' | sed 's/"$//' || true)"
    if [[ -z "$api_key" ]]; then
        api_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    fi
    if ! grep -q "^WEB_API_KEY=" "$CONFIG_DIR/gniza.conf" 2>/dev/null; then
        echo "WEB_API_KEY=\"${api_key}\"" >> "$CONFIG_DIR/gniza.conf"
    fi
    # Ask about network access
    web_host="0.0.0.0"
    echo ""
    echo "  1) ${C_BOLD}Network${C_RESET}   — accessible from other machines (0.0.0.0)"
    echo "  2) ${C_BOLD}Localhost${C_RESET}  — only this machine (127.0.0.1)"
    echo ""
    read -rp "Listen on [1]: " _listen_choice </dev/tty || true
    _listen_choice="${_listen_choice:-1}"
    if [ "$_listen_choice" = "2" ]; then
        web_host="127.0.0.1"
    fi

    WEB_INSTALLED="yes"
    WEB_PASS="$api_key"
    WEB_HOST="$web_host"
    # Install systemd service
    if [ "$MODE" = "root" ]; then
        if "$INSTALL_DIR/bin/gniza" web install-service 2>/dev/null; then
            info "Web dashboard systemd service installed."
        else
            warn "Failed to install web service. Start manually: gniza web start"
        fi
    else
        # User-level systemd service
        _user_service_dir="$HOME/.config/systemd/user"
        mkdir -p "$_user_service_dir"
        cat > "$_user_service_dir/gniza-web.service" <<SVCEOF
[Unit]
Description=GNIZA Web Dashboard
After=network.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/bin/gniza web start --host=$web_host
WorkingDirectory=$INSTALL_DIR
Environment=GNIZA_DIR=$INSTALL_DIR
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable gniza-web 2>/dev/null || true
        systemctl --user restart gniza-web 2>/dev/null || true
        if systemctl --user is-active gniza-web &>/dev/null; then
            info "Web dashboard user service installed and started."
        else
            warn "Could not start user service. Start manually: gniza web start"
        fi
    fi
fi

# -- Daemon setup (always enabled) --
if true; then
    if [ "$MODE" = "root" ]; then
        if "$INSTALL_DIR/bin/gniza" daemon install-service 2>/dev/null; then
            info "Daemon systemd service installed."
        else
            warn "Failed to install daemon service. Start manually: gniza daemon start"
        fi
    else
        _user_service_dir="$HOME/.config/systemd/user"
        mkdir -p "$_user_service_dir"
        cat > "$_user_service_dir/gniza-daemon.service" <<SVCEOF
[Unit]
Description=GNIZA Background Health Daemon
After=network.target

[Service]
Type=simple
ExecStart=$INSTALL_DIR/bin/gniza daemon start
WorkingDirectory=$INSTALL_DIR
Environment=GNIZA_DIR=$INSTALL_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
SVCEOF
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable gniza-daemon 2>/dev/null || true
        systemctl --user restart gniza-daemon 2>/dev/null || true
        if systemctl --user is-active gniza-daemon &>/dev/null; then
            info "Daemon user service installed and started."
        else
            warn "Could not start daemon service. Start manually: gniza daemon start"
        fi
    fi
    DAEMON_INSTALLED="yes"
fi

# -- Restart existing services --------------------------------
if [[ $EUID -eq 0 ]]; then
    systemctl restart gniza-web 2>/dev/null && info "Web service restarted." || true
    systemctl restart gniza-daemon 2>/dev/null && info "Daemon restarted." || true
else
    systemctl --user restart gniza-web 2>/dev/null || true
    systemctl --user restart gniza-daemon 2>/dev/null || true
fi

# -- Done -----------------------------------------------------
echo ""
echo "${C_GREEN}${C_BOLD}Installation complete!${C_RESET}"
echo ""
echo "  Binary:   $BIN_LINK"
echo "  Config:   $CONFIG_DIR/gniza.conf"
echo "  Logs:     $LOG_DIR"
echo "  Work dir: $WORK_DIR"
echo ""
if [ "${WEB_INSTALLED:-}" = "yes" ]; then
    echo "${C_GREEN}Web Dashboard:${C_RESET}"
    if [ "$WEB_HOST" = "127.0.0.1" ]; then
        echo "  URL:      http://127.0.0.1:2323"
    else
        echo "  URL:      http://$(hostname -I 2>/dev/null | awk '{print $1}'):2323"
    fi
    echo "  Password: $WEB_PASS"
    echo ""
fi
echo "Get started:"
echo "  gniza --help        Show CLI help"
echo "  gniza               Launch TUI"
echo ""
