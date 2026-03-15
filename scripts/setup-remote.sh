#!/usr/bin/env bash
set -eo pipefail

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

# -- Parse arguments ------------------------------------------
BACKUP_USER="gniza"
BASE_DIR="/backups"
SSH_PORT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user=*)  BACKUP_USER="${1#*=}" ;;
        --user)    shift; BACKUP_USER="${1:-gniza}" ;;
        --base=*)  BASE_DIR="${1#*=}" ;;
        --base)    shift; BASE_DIR="${1:-/backups}" ;;
        --port=*)  SSH_PORT="${1#*=}" ;;
        --port)    shift; SSH_PORT="${1:-}" ;;
        --help|-h)
            cat <<EOF
Usage: setup-remote.sh [OPTIONS]

Prepare this server as a GNIZA backup destination and share
the configuration via croc for automatic import.

Options:
  --user=NAME   Backup user to create (default: gniza)
  --base=PATH   Base backup directory (default: /backups)
  --port=PORT   SSH port override (default: auto-detect from sshd_config)
  --help        Show this help
EOF
            exit 0
            ;;
        *) warn "Unknown option: $1" ;;
    esac
    shift
done

# -- Require root ---------------------------------------------
[[ $EUID -eq 0 ]] || die "This script must be run as root (use sudo)."

# -- Validate inputs ------------------------------------------
if [[ ! "$BACKUP_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    die "Invalid username: $BACKUP_USER (use lowercase letters, numbers, hyphens, underscores)"
fi

# -- Temp file cleanup ----------------------------------------
_TMPFILES=()
cleanup() {
    for f in "${_TMPFILES[@]}"; do
        rm -f "$f" 2>/dev/null || true
    done
}
trap cleanup EXIT

# -- Install dependencies -------------------------------------
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

if ! command -v sudo &>/dev/null; then
    info "Installing sudo..."
    _apt_update
    _pkg_install sudo || die "Failed to install sudo. Install it manually and retry."
fi

if ! command -v rsync &>/dev/null; then
    info "Installing rsync..."
    _apt_update
    _pkg_install rsync || die "Failed to install rsync. Install it manually and retry."
fi

if ! command -v croc &>/dev/null; then
    info "Installing croc..."
    if curl -fsSL https://getcroc.schollz.com | bash 2>/dev/null; then
        info "croc installed."
    else
        die "Failed to install croc. Install it manually: https://github.com/schollz/croc"
    fi
fi

# -- Create backup user ---------------------------------------
if ! id "$BACKUP_USER" &>/dev/null; then
    info "Creating user: $BACKUP_USER"
    adduser --disabled-password --gecos "GNIZA backup" "$BACKUP_USER" || die "Failed to create user $BACKUP_USER"
else
    info "User $BACKUP_USER already exists."
fi

USER_HOME=$(getent passwd "$BACKUP_USER" | cut -d: -f6)
[[ -z "$USER_HOME" ]] && die "Cannot determine home directory for user $BACKUP_USER"

# -- Generate SSH key pair ------------------------------------
SSH_DIR="$USER_HOME/.ssh"
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

KEY_PATH="$SSH_DIR/id_ed25519_gniza"
if [[ -f "$KEY_PATH" ]]; then
    info "SSH key already exists: $KEY_PATH"
else
    info "Generating Ed25519 SSH key pair..."
    ssh-keygen -t ed25519 -f "$KEY_PATH" -N "" -C "gniza@$(hostname)" || die "Failed to generate SSH key"
fi

# Install public key into authorized_keys
AUTH_KEYS="$SSH_DIR/authorized_keys"
PUB_KEY=$(cat "$KEY_PATH.pub")
if [[ -f "$AUTH_KEYS" ]] && grep -qF "$PUB_KEY" "$AUTH_KEYS" 2>/dev/null; then
    info "Public key already in authorized_keys."
else
    echo "$PUB_KEY" >> "$AUTH_KEYS"
    info "Public key added to authorized_keys."
fi
chmod 600 "$AUTH_KEYS"
chown -R "$BACKUP_USER:$BACKUP_USER" "$SSH_DIR"

# -- Configure sudoers ----------------------------------------
SUDOERS_LINE="$BACKUP_USER ALL = NOPASSWD: /usr/bin/rsync, /bin/mkdir, /bin/chown"
SUDOERS_FILE="/etc/sudoers.d/gniza-$BACKUP_USER"
if [[ -f "$SUDOERS_FILE" ]] && grep -qF "$SUDOERS_LINE" "$SUDOERS_FILE" 2>/dev/null; then
    info "Sudoers already configured."
else
    echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
    info "Sudoers configured: $SUDOERS_FILE"
fi

# -- Create base directory ------------------------------------
mkdir -p "$BASE_DIR"
chown "$BACKUP_USER:$BACKUP_USER" "$BASE_DIR"
info "Base directory ready: $BASE_DIR"

# -- Detect server info ---------------------------------------
HOSTNAME=$(hostname)
LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PUBLIC_IP=$(curl -s --connect-timeout 5 ifconfig.me 2>/dev/null || echo "")

if [[ -z "$SSH_PORT" ]]; then
    SSH_PORT=$(grep -E '^\s*Port\s+' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}' | head -1)
    SSH_PORT="${SSH_PORT:-22}"
fi

info "Hostname:   $HOSTNAME"
info "LAN IP:     $LAN_IP"
info "Public IP:  ${PUBLIC_IP:-(could not detect)}"
info "SSH port:   $SSH_PORT"

# -- Generate croc code --------------------------------------
CROC_CODE=$(head -c 500 /dev/urandom | LC_ALL=C tr -dc 'a-z' | head -c 15 | sed 's/.\{5\}/&-/g;s/-$//')

# -- Build JSON payload ---------------------------------------
PRIVATE_KEY_CONTENT=$(cat "$KEY_PATH")

JSON_TMP=$(mktemp /tmp/gniza-remote-XXXXXX.json)
_TMPFILES+=("$JSON_TMP")
chmod 600 "$JSON_TMP"

# Install jq if needed for safe JSON construction
if ! command -v jq &>/dev/null; then
    _apt_update
    _pkg_install jq || die "Failed to install jq. Install it manually and retry."
fi

jq -n \
    --argjson version 1 \
    --arg type "gniza-remote-setup" \
    --arg hostname "$HOSTNAME" \
    --arg host "$LAN_IP" \
    --arg host_public "$PUBLIC_IP" \
    --arg port "$SSH_PORT" \
    --arg user "$BACKUP_USER" \
    --arg private_key "$PRIVATE_KEY_CONTENT" \
    --arg base "$BASE_DIR" \
    --arg sudo "yes" \
    '{version:$version, type:$type, hostname:$hostname, host:$host, host_public:$host_public, port:$port, user:$user, private_key:$private_key, base:$base, sudo:$sudo}' \
    > "$JSON_TMP"

# -- Send via croc --------------------------------------------
echo ""
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo ""
echo "  Server is ready. Enter this code in the GNIZA dashboard"
echo "  or CLI to complete the configuration:"
echo ""
echo "  ${C_BOLD}${C_GREEN}$CROC_CODE${C_RESET}"
echo ""
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo ""
info "Waiting for the GNIZA server to receive the configuration..."
echo ""

croc send --code "$CROC_CODE" "$JSON_TMP"

echo ""
info "Configuration sent successfully. You can close this terminal."
