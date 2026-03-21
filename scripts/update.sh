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

# Determine install dir
if [[ $EUID -eq 0 ]]; then
    MODE="root"
    INSTALL_DIR="/usr/local/gniza"
else
    MODE="user"
    INSTALL_DIR="$HOME/.local/share/gniza"
fi

command -v git &>/dev/null || die "git is required for updates"

# Read current version
CURRENT_VERSION=""
if [[ -f "$INSTALL_DIR/lib/constants.sh" ]]; then
    CURRENT_VERSION=$(grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' "$INSTALL_DIR/lib/constants.sh" 2>/dev/null || echo "")
fi
CURRENT_VERSION="${CURRENT_VERSION:-unknown}"

# Check if install dir is a git repo
if [[ -d "$INSTALL_DIR/.git" ]]; then
    # Git-based install — use fetch + compare
    info "Checking for updates..."
    cd "$INSTALL_DIR"

    git fetch origin --quiet 2>/dev/null || die "Failed to fetch from remote"

    LOCAL_HEAD=$(git rev-parse HEAD)
    REMOTE_HEAD=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

    if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]] && [[ "$FORCE" == "false" ]]; then
        info "Already up to date (v${CURRENT_VERSION})."
        exit 0
    fi

    # Count commits behind
    BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
    REMOTE_VERSION=$(git show origin/main:lib/constants.sh 2>/dev/null | grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' || echo "unknown")

    info "Installed: v${CURRENT_VERSION} (${LOCAL_HEAD:0:7})"
    info "Latest:    v${REMOTE_VERSION} (${REMOTE_HEAD:0:7}), ${BEHIND} commit(s) behind"

    if [[ "$CHECK_ONLY" == "true" ]]; then
        echo ""
        echo "Changes:"
        git log --oneline HEAD..origin/main 2>/dev/null | head -20
        echo ""
        echo "Run ${C_BOLD}gniza update${C_RESET} to apply."
        exit 0
    fi

    # Apply update
    info "Updating v${CURRENT_VERSION} → v${REMOTE_VERSION}..."
    git reset --hard origin/main --quiet
    chmod +x "$INSTALL_DIR/bin/gniza"

    # Update Python venv if present
    if [[ -d "$INSTALL_DIR/venv" && -f "$INSTALL_DIR/pyproject.toml" ]]; then
        info "Updating Python dependencies..."
        "$INSTALL_DIR/venv/bin/pip" install --quiet "textual>=0.40" textual-serve flask flask-wtf waitress psutil markdown markupsafe 2>/dev/null || warn "Failed to update Python deps"
    fi
else
    # Non-git install (old cp-based or deb) — clone to temp and copy
    REPO_URL="${GNIZA4LINUX_REPO:-https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git}"
    UPDATE_TMPDIR=$(mktemp -d)
    trap 'rm -rf "$UPDATE_TMPDIR"' EXIT

    info "Checking for updates..."
    git clone --depth 1 --quiet "$REPO_URL" "$UPDATE_TMPDIR/gniza4linux" || die "Failed to fetch latest version"

    REMOTE_VERSION=$(grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' "$UPDATE_TMPDIR/gniza4linux/lib/constants.sh" 2>/dev/null || echo "unknown")

    info "Installed: v${CURRENT_VERSION}"
    info "Latest:    v${REMOTE_VERSION}"

    if [[ "$FORCE" == "false" && "$CURRENT_VERSION" == "$REMOTE_VERSION" ]]; then
        info "Already up to date."
        exit 0
    fi

    if [[ "$CHECK_ONLY" == "true" ]]; then
        echo "Update available: v${CURRENT_VERSION} → v${REMOTE_VERSION}"
        exit 0
    fi

    info "Updating v${CURRENT_VERSION} → v${REMOTE_VERSION}..."
    for dir in bin lib etc tui web daemon scripts tests; do
        if [[ -d "$UPDATE_TMPDIR/gniza4linux/$dir" ]]; then
            cp -r "$UPDATE_TMPDIR/gniza4linux/$dir" "$INSTALL_DIR/"
        fi
    done
    chmod +x "$INSTALL_DIR/bin/gniza"
fi

# Restart services
if [[ "$NO_RESTART" == "false" ]]; then
    info "Restarting services..."
    if [[ "$MODE" == "root" ]]; then
        # Kill any orphan process on the web port
        _web_port=$(grep -oP 'WEB_PORT="\K[^"]+' /etc/gniza/gniza.conf 2>/dev/null || echo "2323")
        fuser -k "${_web_port:-2323}/tcp" 2>/dev/null || true
        sleep 1
        if systemctl is-active gniza-web &>/dev/null || systemctl is-enabled gniza-web &>/dev/null; then
            systemctl restart gniza-web && info "Web service restarted." || warn "Failed to restart web service."
        fi
        if systemctl is-active gniza-daemon &>/dev/null || systemctl is-enabled gniza-daemon &>/dev/null; then
            systemctl restart gniza-daemon && info "Daemon restarted." || warn "Failed to restart daemon."
        fi
    else
        _web_port=$(grep -oP 'WEB_PORT="\K[^"]+' "${XDG_CONFIG_HOME:-$HOME/.config}/gniza/gniza.conf" 2>/dev/null || echo "2323")
        fuser -k "${_web_port:-2323}/tcp" 2>/dev/null || true
        sleep 1
        if systemctl --user is-active gniza-web &>/dev/null || systemctl --user is-enabled gniza-web &>/dev/null; then
            systemctl --user restart gniza-web && info "Web service restarted." || warn "Failed to restart web service."
        fi
        if systemctl --user is-active gniza-daemon &>/dev/null || systemctl --user is-enabled gniza-daemon &>/dev/null; then
            systemctl --user restart gniza-daemon && info "Daemon restarted." || warn "Failed to restart daemon."
        fi
    fi
else
    info "Skipping service restart (--no-restart)."
fi

# Show result
FINAL_VERSION=$(grep -oP 'GNIZA4LINUX_VERSION="\K[^"]+' "$INSTALL_DIR/lib/constants.sh" 2>/dev/null || echo "$REMOTE_VERSION")
echo ""
echo "${C_GREEN}${C_BOLD}Update complete!${C_RESET} v${CURRENT_VERSION} → v${FINAL_VERSION}"
