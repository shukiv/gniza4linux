#!/usr/bin/env bash
set -eo pipefail

# Colors
if [[ -t 1 ]]; then
    C_GREEN=$'\033[0;32m'
    C_RED=$'\033[0;31m'
    C_YELLOW=$'\033[0;33m'
    C_BOLD=$'\033[1m'
    C_RESET=$'\033[0m'
else
    C_GREEN="" C_RED="" C_YELLOW="" C_BOLD="" C_RESET=""
fi

info()  { echo "${C_GREEN}[INFO]${C_RESET} $*"; }
warn()  { echo "${C_YELLOW}[WARN]${C_RESET} $*" >&2; }
error() { echo "${C_RED}[ERROR]${C_RESET} $*" >&2; }
die()   { error "$1"; exit 1; }

# Parse flags
CHECK_ONLY=false
FORCE=false
NO_RESTART=false
for arg in "$@"; do
    case "$arg" in
        --check) CHECK_ONLY=true ;;
        --force) FORCE=true ;;
        --no-restart) NO_RESTART=true ;;
    esac
done

# Determine install mode (same pattern as uninstall.sh)
if [[ $EUID -eq 0 ]]; then
    MODE="root"
    INSTALL_DIR="/usr/local/gniza"
else
    MODE="user"
    INSTALL_DIR="$HOME/.local/share/gniza"
fi

# Read current version
CURRENT_VERSION=""
if [[ -f "$INSTALL_DIR/lib/constants.sh" ]]; then
    CURRENT_VERSION=$(grep '^readonly GNIZA4LINUX_VERSION=' "$INSTALL_DIR/lib/constants.sh" | sed 's/.*="\(.*\)"/\1/')
fi
CURRENT_VERSION="${CURRENT_VERSION:-unknown}"

# Git is required
command -v git &>/dev/null || die "git is required for updates"

# Clone latest to temp dir
# Source repo URL from constants if available, else use default
REPO_URL=""
if [[ -f "$INSTALL_DIR/lib/constants.sh" ]]; then
    REPO_URL=$(grep '^readonly GNIZA4LINUX_REPO=' "$INSTALL_DIR/lib/constants.sh" | sed 's/.*="\(.*\)"/\1/')
fi
REPO_URL="${REPO_URL:-https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git}"
UPDATE_TMPDIR=$(mktemp -d)
trap 'rm -rf "$UPDATE_TMPDIR"' EXIT
info "Checking for updates..."
git clone --depth 1 --quiet "$REPO_URL" "$UPDATE_TMPDIR/gniza4linux" || die "Failed to fetch latest version"

# Read remote version
REMOTE_VERSION=$(grep '^readonly GNIZA4LINUX_VERSION=' "$UPDATE_TMPDIR/gniza4linux/lib/constants.sh" | sed 's/.*="\(.*\)"/\1/')
REMOTE_VERSION="${REMOTE_VERSION:-unknown}"

info "Installed: v${CURRENT_VERSION}"
info "Latest:    v${REMOTE_VERSION}"

# Compare versions using sort -V
if [[ "$FORCE" == "false" ]]; then
    if [[ "$CURRENT_VERSION" == "$REMOTE_VERSION" ]]; then
        info "Already up to date."
        exit 0
    fi
    # Check if current >= remote (no update needed)
    _newer=$(printf '%s\n%s' "$CURRENT_VERSION" "$REMOTE_VERSION" | sort -V | tail -1)
    if [[ "$_newer" == "$CURRENT_VERSION" && "$CURRENT_VERSION" != "$REMOTE_VERSION" ]]; then
        info "Installed version is newer than remote. Use --force to reinstall."
        exit 0
    fi
fi

if [[ "$CHECK_ONLY" == "true" ]]; then
    echo "Update available: v${CURRENT_VERSION} → v${REMOTE_VERSION}"
    exit 0
fi

# Apply update
SOURCE_DIR="$UPDATE_TMPDIR/gniza4linux"
info "Updating gniza v${CURRENT_VERSION} → v${REMOTE_VERSION}..."

# Copy project files (same dirs as install.sh)
for dir in bin lib etc tui web daemon scripts tests; do
    if [[ -d "$SOURCE_DIR/$dir" ]]; then
        cp -r "$SOURCE_DIR/$dir" "$INSTALL_DIR/"
    fi
done

# Ensure entrypoint is executable
chmod +x "$INSTALL_DIR/bin/gniza"

# Restart running services (skip if --no-restart, e.g. when called from web/TUI)
if [[ "$NO_RESTART" == "false" ]]; then
    info "Restarting services..."
    if [[ "$MODE" == "root" ]]; then
        if systemctl is-active gniza-web &>/dev/null; then
            systemctl restart gniza-web && info "Web service restarted." || warn "Failed to restart web service."
        fi
        if systemctl is-active gniza-daemon &>/dev/null; then
            systemctl restart gniza-daemon && info "Daemon service restarted." || warn "Failed to restart daemon."
        fi
    else
        if systemctl --user is-active gniza-web &>/dev/null; then
            systemctl --user restart gniza-web && info "Web service restarted." || warn "Failed to restart web service."
        fi
        if systemctl --user is-active gniza-daemon &>/dev/null; then
            systemctl --user restart gniza-daemon && info "Daemon service restarted." || warn "Failed to restart daemon."
        fi
    fi
else
    info "Skipping service restart (--no-restart). Restart services manually to apply changes."
fi

echo ""
echo "${C_GREEN}${C_BOLD}Update complete!${C_RESET} v${CURRENT_VERSION} → v${REMOTE_VERSION}"
