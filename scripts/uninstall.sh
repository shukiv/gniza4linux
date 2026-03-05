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

# ── Determine uninstall mode ────────────────────────────────
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
    LOG_DIR="$HOME/.local/share/gniza/logs"
fi

info "Uninstall mode: ${C_BOLD}${MODE}${C_RESET}"
echo ""

# ── Remove cron entries ──────────────────────────────────────
info "Removing gniza cron entries..."
CRON_TAG="# gniza4linux:"
current_crontab=$(crontab -l 2>/dev/null) || current_crontab=""

if [[ -n "$current_crontab" ]]; then
    filtered=""
    skip_next=false
    removed=0
    while IFS= read -r line; do
        if [[ "$line" == "${CRON_TAG}"* ]]; then
            skip_next=true
            ((removed++)) || true
            continue
        fi
        if [[ "$skip_next" == "true" ]]; then
            skip_next=false
            continue
        fi
        filtered+="$line"$'\n'
    done <<< "$current_crontab"

    if (( removed > 0 )); then
        echo "$filtered" | crontab - 2>/dev/null || warn "Failed to update crontab"
        info "Removed $removed cron entry/entries"
    else
        info "No gniza cron entries found"
    fi
else
    info "No crontab entries to check"
fi

# ── Remove symlink ───────────────────────────────────────────
if [[ -L "$BIN_LINK" ]]; then
    rm -f "$BIN_LINK"
    info "Removed symlink: $BIN_LINK"
elif [[ -f "$BIN_LINK" ]]; then
    warn "Expected symlink but found regular file: $BIN_LINK (not removing)"
fi

# ── Remove install directory ─────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    info "Removed install directory: $INSTALL_DIR"
else
    info "Install directory not found: $INSTALL_DIR"
fi

# ── Notify about config and logs ─────────────────────────────
echo ""
echo "${C_GREEN}${C_BOLD}Uninstall complete!${C_RESET}"
echo ""
echo "The following directories were ${C_YELLOW}NOT${C_RESET} removed (may contain your data):"
echo ""
if [[ -d "$CONFIG_DIR" ]]; then
    echo "  Config:  $CONFIG_DIR"
    echo "           To remove: rm -rf $CONFIG_DIR"
fi
if [[ -d "$LOG_DIR" ]]; then
    echo "  Logs:    $LOG_DIR"
    echo "           To remove: rm -rf $LOG_DIR"
fi
echo ""
