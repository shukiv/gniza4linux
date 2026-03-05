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
else
    MODE="user"
    INSTALL_DIR="$HOME/.local/share/gniza"
    BIN_LINK="$HOME/.local/bin/gniza"
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gniza"
    LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gniza/log"
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

# ── Install bundled gum binary ───────────────────────────────
GUM_VERSION="0.17.0"

_detect_arch() {
    local arch; arch=$(uname -m)
    case "$arch" in
        x86_64)  echo "x86_64" ;;
        aarch64) echo "arm64" ;;
        armv7*)  echo "armv7" ;;
        i386|i686) echo "i386" ;;
        *)       echo "" ;;
    esac
}

if command -v gum &>/dev/null; then
    info "gum already installed: $(command -v gum)"
else
    GUM_ARCH=$(_detect_arch)
    if [[ -n "$GUM_ARCH" ]] && command -v curl &>/dev/null; then
        GUM_URL="https://github.com/charmbracelet/gum/releases/download/v${GUM_VERSION}/gum_${GUM_VERSION}_Linux_${GUM_ARCH}.tar.gz"
        info "Downloading gum v${GUM_VERSION} (${GUM_ARCH})..."
        GUM_TMP=$(mktemp -d)
        if curl -fsSL "$GUM_URL" | tar xz -C "$GUM_TMP" 2>/dev/null; then
            mkdir -p "$INSTALL_DIR/bin"
            # The tarball extracts to a subdirectory
            if [[ -f "$GUM_TMP/gum_${GUM_VERSION}_Linux_${GUM_ARCH}/gum" ]]; then
                cp "$GUM_TMP/gum_${GUM_VERSION}_Linux_${GUM_ARCH}/gum" "$INSTALL_DIR/bin/gum"
            elif [[ -f "$GUM_TMP/gum" ]]; then
                cp "$GUM_TMP/gum" "$INSTALL_DIR/bin/gum"
            fi
            if [[ -f "$INSTALL_DIR/bin/gum" ]]; then
                chmod +x "$INSTALL_DIR/bin/gum"
                info "Installed gum to $INSTALL_DIR/bin/gum"
            else
                warn "Failed to locate gum binary in archive"
            fi
        else
            warn "Failed to download gum (TUI will not be available)"
        fi
        rm -rf "$GUM_TMP"
    else
        if [[ -z "${GUM_ARCH:-}" ]]; then
            warn "Unsupported architecture for gum: $(uname -m)"
        else
            warn "curl not found, cannot download gum (TUI will not be available)"
        fi
    fi
fi

# ── Install files ────────────────────────────────────────────
info "Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Copy project files
cp -r "$SOURCE_DIR/bin"  "$INSTALL_DIR/"
cp -r "$SOURCE_DIR/lib"  "$INSTALL_DIR/"
cp -r "$SOURCE_DIR/etc"  "$INSTALL_DIR/"

if [[ -d "$SOURCE_DIR/scripts" ]]; then
    cp -r "$SOURCE_DIR/scripts" "$INSTALL_DIR/"
fi

if [[ -d "$SOURCE_DIR/tests" ]]; then
    cp -r "$SOURCE_DIR/tests" "$INSTALL_DIR/"
fi

# Make entrypoint executable
chmod +x "$INSTALL_DIR/bin/gniza"

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

# ── Done ─────────────────────────────────────────────────────
echo ""
echo "${C_GREEN}${C_BOLD}Installation complete!${C_RESET}"
echo ""
echo "  Binary:  $BIN_LINK"
echo "  Config:  $CONFIG_DIR/gniza.conf"
echo "  Logs:    $LOG_DIR"
echo ""
echo "Get started:"
echo "  gniza --help        Show CLI help"
echo "  gniza               Launch TUI"
echo ""
