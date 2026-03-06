#!/usr/bin/env bash
set -eo pipefail

REPO_URL="https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git"

# Colors — force enable when piped (curl | bash), since output still goes to terminal
C_GREEN=$'\033[0;32m'
C_RED=$'\033[0;31m'
C_YELLOW=$'\033[0;33m'
C_BOLD=$'\033[1m'
C_RESET=$'\033[0m'

info()  { echo "${C_GREEN}[INFO]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[WARN]${C_RESET} $*" >&2; }
error() { echo "${C_RED}[ERROR]${C_RESET} $*" >&2; }
die()   { error "$1"; exit 1; }

# ── Determine install mode ───────────────────────────────────
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

# ── Determine source ────────────────────────────────────────
SOURCE_DIR=""

# Check if running from a local clone (won't work when piped via curl)
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" || true
    if [[ -n "${SCRIPT_DIR:-}" && -f "$SCRIPT_DIR/../lib/constants.sh" && -f "$SCRIPT_DIR/../bin/gniza" ]]; then
        SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
        info "Installing from local clone: $SOURCE_DIR"
    fi
fi

if [[ -z "$SOURCE_DIR" ]]; then
    # Clone from git
    if ! command -v git &>/dev/null; then
        die "git is required to install gniza4linux (or run from a local clone)"
    fi
    TMPDIR=$(mktemp -d)
    trap 'rm -rf "$TMPDIR"' EXIT
    info "Cloning from $REPO_URL..."
    git clone --depth 1 "$REPO_URL" "$TMPDIR/gniza4linux" || die "Failed to clone repository"
    SOURCE_DIR="$TMPDIR/gniza4linux"
fi

# ── Check dependencies ──────────────────────────────────────
info "Checking dependencies..."
for cmd in bash rsync; do
    if ! command -v "$cmd" &>/dev/null; then
        die "Required dependency not found: $cmd"
    fi
done

for cmd in ssh curl; do
    if ! command -v "$cmd" &>/dev/null; then
        warn "Optional dependency not found: $cmd"
    fi
done

# ── Install files ────────────────────────────────────────────
info "Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy project files
cp -r "$SOURCE_DIR/bin"  "$INSTALL_DIR/"
cp -r "$SOURCE_DIR/lib"  "$INSTALL_DIR/"
cp -r "$SOURCE_DIR/etc"  "$INSTALL_DIR/"

if [[ -d "$SOURCE_DIR/tui" ]]; then
    cp -r "$SOURCE_DIR/tui" "$INSTALL_DIR/"
fi

if [[ -d "$SOURCE_DIR/web" ]]; then
    cp -r "$SOURCE_DIR/web" "$INSTALL_DIR/"
fi

if [[ -d "$SOURCE_DIR/scripts" ]]; then
    cp -r "$SOURCE_DIR/scripts" "$INSTALL_DIR/"
fi

if [[ -d "$SOURCE_DIR/tests" ]]; then
    cp -r "$SOURCE_DIR/tests" "$INSTALL_DIR/"
fi

# Make entrypoint executable
chmod +x "$INSTALL_DIR/bin/gniza"

# ── Install Python TUI dependencies ─────────────────────────
if command -v python3 &>/dev/null; then
    info "Installing Python TUI dependencies (textual, textual-serve, flask)..."
    if python3 -m pip install --break-system-packages textual textual-serve flask 2>/dev/null; then
        info "Python TUI dependencies installed."
    elif python3 -m pip install textual textual-serve flask 2>/dev/null; then
        info "Python TUI dependencies installed."
    else
        warn "Could not install Python TUI dependencies. TUI/web mode may not work."
        warn "Install manually: pip3 install textual textual-serve flask"
    fi
else
    warn "python3 not found. TUI mode will not be available."
fi

# ── Create symlink ───────────────────────────────────────────
info "Creating symlink: $BIN_LINK -> $INSTALL_DIR/bin/gniza"
mkdir -p "$(dirname "$BIN_LINK")"
ln -sf "$INSTALL_DIR/bin/gniza" "$BIN_LINK"

# ── Create config directories ───────────────────────────────
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

# ── Create log directory ─────────────────────────────────────
info "Setting up log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"

# ── Create work directory ───────────────────────────────────
info "Setting up work directory: $WORK_DIR"
mkdir -p "$WORK_DIR"

# ── Copy example configs (if not already present) ────────────
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

# ── Web dashboard setup ─────────────────────────────────────
_update_conf_key() {
    local file="$1" key="$2" val="$3"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=\"${val}\"|" "$file"
    else
        echo "${key}=\"${val}\"" >> "$file"
    fi
}

read -rp "Enable web dashboard? (y/n) [n]: " enable_web
if [[ "${enable_web,,}" == "y" ]]; then
    _update_conf_key "$CONFIG_DIR/gniza.conf" "WEB_ENABLED" "yes"
    # Generate random API key
    api_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    _update_conf_key "$CONFIG_DIR/gniza.conf" "WEB_API_KEY" "$api_key"
    echo "Web API key: $api_key"
    echo "Save this key — you'll need it to log into the dashboard."
    # Install systemd service
    if [[ "$MODE" == "root" ]]; then
        "$INSTALL_DIR/bin/gniza" web install-service
    else
        warn "Systemd service installation requires root. Start manually: gniza web start"
    fi
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "${C_GREEN}${C_BOLD}Installation complete!${C_RESET}"
echo ""
echo "  Binary:   $BIN_LINK"
echo "  Config:   $CONFIG_DIR/gniza.conf"
echo "  Logs:     $LOG_DIR"
echo "  Work dir: $WORK_DIR"
echo ""
echo "Get started:"
echo "  gniza --help        Show CLI help"
echo "  gniza               Launch TUI"
echo ""
