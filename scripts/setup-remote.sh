#!/usr/bin/env bash
set -eo

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
MODE=""
BACKUP_USER="gniza"
BASE_DIR=""
SSH_PORT=""
FOLDERS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)      MODE="source" ;;
        --destination) MODE="destination" ;;
        --user=*)      BACKUP_USER="${1#*=}" ;;
        --user)        shift; BACKUP_USER="${1:-gniza}" ;;
        --base=*)      BASE_DIR="${1#*=}" ;;
        --base)        shift; BASE_DIR="${1:-/backups}" ;;
        --port=*)      SSH_PORT="${1#*=}" ;;
        --port)        shift; SSH_PORT="${1:-}" ;;
        --folders=*)   FOLDERS="${1#*=}" ;;
        --folders)     shift; FOLDERS="${1:-}" ;;
        --help|-h)
            cat <<EOF
Usage: setup-remote.sh --source|--destination [OPTIONS]

Prepare this server for GNIZA and share the configuration
via croc for automatic import.

Mode (required):
  --source        Set up as a backup source (what to back up)
  --destination   Set up as a backup destination (where to store)

Options:
  --user=NAME       Backup user to create (default: gniza)
  --base=PATH       Base backup directory (default: ~user/backups, destination only)
  --port=PORT       SSH port override (default: auto-detect from sshd_config)
  --folders=PATHS   Comma-separated folders to back up (source only)
  --help            Show this help
EOF
            exit 0
            ;;
        *) warn "Unknown option: $1" ;;
    esac
    shift
done

# -- Ask for mode if not specified ----------------------------
if [[ -z "$MODE" ]]; then
    echo ""
    echo "${C_BOLD}How will this server be used with GNIZA?${C_RESET}"
    echo ""
    echo "  1) ${C_BOLD}Source${C_RESET}       — back up files FROM this server"
    echo "  2) ${C_BOLD}Destination${C_RESET}  — store backups ON this server"
    echo ""
    read -rp "  Choose [1/2]: " _mode_choice </dev/tty || true
    case "${_mode_choice:-1}" in
        1|source)      MODE="source" ;;
        2|destination) MODE="destination" ;;
        *) die "Invalid choice. Use 1 (source) or 2 (destination)." ;;
    esac
fi

info "Mode: ${C_BOLD}${MODE}${C_RESET}"

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
    if command -v adduser &>/dev/null && [[ -f /etc/debian_version ]]; then
        adduser --disabled-password --gecos "GNIZA backup" "$BACKUP_USER"
    else
        useradd -m -s /bin/bash -c "GNIZA backup" "$BACKUP_USER" 2>/dev/null || true
        # Lock password (no login via password)
        passwd -l "$BACKUP_USER" 2>/dev/null || true
    fi
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

# -- Configure sudoers (will be updated after database prompts) --
SUDOERS_FILE="/etc/sudoers.d/gniza-$BACKUP_USER"

# -- Ask for base directory (destination only) -----------------
if [[ "$MODE" == "destination" ]]; then
    _default_base="$USER_HOME/backups"
    [[ -z "$BASE_DIR" ]] && BASE_DIR="$_default_base"
    echo ""
    echo "${C_BOLD}Where should backups be stored on this server?${C_RESET}"
    echo "  Enter a path, or press Enter for the default."
    echo ""
    read -rp "  Base directory [$BASE_DIR]: " _base_input </dev/tty || true
    BASE_DIR="${_base_input:-$BASE_DIR}"
    mkdir -p "$BASE_DIR"
    chown "$BACKUP_USER:$BACKUP_USER" "$BASE_DIR"
    info "Base directory: $BASE_DIR"
fi

# -- Ask which folders to back up (source only) ----------------
if [[ "$MODE" == "source" ]]; then
    if [[ -z "$FOLDERS" ]]; then
        echo ""
        echo "${C_BOLD}Which folders should be backed up from this server?${C_RESET}"
        echo "  Enter comma-separated paths, or press Enter for the default."
        echo ""
        read -rp "  Folders [/etc,/home,/var]: " FOLDERS </dev/tty || true
        FOLDERS="${FOLDERS:-/etc,/home,/var}"
    fi
    info "Folders:    $FOLDERS"

    # -- Ask about MySQL backup --
    MYSQL_ENABLED="no"
    if command -v mysql &>/dev/null || command -v mysqldump &>/dev/null || command -v mariadb-dump &>/dev/null; then
        echo ""
        read -rp "  MySQL/MariaDB detected. Back up databases? (y/n) [y]: " _mysql_choice </dev/tty || true
        _mysql_choice="${_mysql_choice:-y}"
        if [[ "$_mysql_choice" == "y" || "$_mysql_choice" == "Y" ]]; then
            MYSQL_ENABLED="yes"
            info "MySQL:      enabled"
        fi
    fi

    # -- Ask about PostgreSQL backup --
    POSTGRESQL_ENABLED="no"
    if command -v psql &>/dev/null || command -v pg_dump &>/dev/null; then
        echo ""
        read -rp "  PostgreSQL detected. Back up databases? (y/n) [y]: " _pg_choice </dev/tty || true
        _pg_choice="${_pg_choice:-y}"
        if [[ "$_pg_choice" == "y" || "$_pg_choice" == "Y" ]]; then
            POSTGRESQL_ENABLED="yes"
            info "PostgreSQL: enabled"
        fi
    fi
fi

# -- Write sudoers (after database prompts so we know what's needed) --
SUDOERS_CMDS="/usr/bin/rsync, /bin/mkdir, /bin/chown"
if [[ "${MYSQL_ENABLED:-no}" == "yes" ]]; then
    SUDOERS_CMDS+=", /usr/bin/mysqldump, /usr/bin/mysql"
    # Also add mariadb paths if they exist
    [[ -x /usr/bin/mariadb-dump ]] && SUDOERS_CMDS+=", /usr/bin/mariadb-dump"
fi
if [[ "${POSTGRESQL_ENABLED:-no}" == "yes" ]]; then
    SUDOERS_CMDS+=", /usr/bin/pg_dump, /usr/bin/pg_dumpall, /usr/bin/psql"
fi
SUDOERS_LINE="$BACKUP_USER ALL = NOPASSWD: $SUDOERS_CMDS"
echo "$SUDOERS_LINE" > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"
info "Sudoers:    $SUDOERS_FILE"

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

# -- Generate croc code (no pipes — pipefail+SIGPIPE kills pipe chains)
_chars="abcdefghijklmnopqrstuvwxyz"
_code=""
for _ in $(seq 15); do _code+="${_chars:RANDOM%26:1}"; done
CROC_CODE="${_code:0:5}-${_code:5:5}-${_code:10:5}"

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
    --arg mode "$MODE" \
    --arg hostname "$HOSTNAME" \
    --arg host "$LAN_IP" \
    --arg host_public "$PUBLIC_IP" \
    --arg port "$SSH_PORT" \
    --arg user "$BACKUP_USER" \
    --arg private_key "$PRIVATE_KEY_CONTENT" \
    --arg base "$BASE_DIR" \
    --arg sudo "yes" \
    --arg folders "${FOLDERS:-}" \
    --arg mysql_enabled "${MYSQL_ENABLED:-no}" \
    --arg postgresql_enabled "${POSTGRESQL_ENABLED:-no}" \
    '{version:$version, type:$type, mode:$mode, hostname:$hostname, host:$host, host_public:$host_public, port:$port, user:$user, private_key:$private_key, base:$base, sudo:$sudo, folders:$folders, mysql_enabled:$mysql_enabled, postgresql_enabled:$postgresql_enabled}' \
    > "$JSON_TMP"

# -- Send via croc --------------------------------------------
if [[ "$MODE" == "source" ]]; then
    _nav="Sources > Auto-Configure"
else
    _nav="Destinations > Auto-Configure"
fi

echo ""
echo "${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo ""
echo "  ${C_BOLD}${C_GREEN}SETUP COMPLETE${C_RESET}"
echo ""
echo "  Now go to your GNIZA dashboard and complete the connection:"
echo ""
echo "  1. Open ${C_BOLD}${_nav}${C_RESET}"
echo "  2. Enter a name for this server"
echo "  3. Paste this code and click ${C_BOLD}Receive & Configure${C_RESET}:"
echo ""
echo "             ${C_BOLD}${C_GREEN}${CROC_CODE}${C_RESET}"
echo ""
echo "  ${C_YELLOW}The code expires when the transfer completes"
echo "  or when you close this terminal.${C_RESET}"
echo ""
echo "${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
echo ""
info "Waiting for the GNIZA server to receive..."
echo ""

CROC_SECRET="$CROC_CODE" croc send "$JSON_TMP" < /dev/null 2>/dev/null

echo ""
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
info "Configuration sent successfully! You can close this terminal."
echo "${C_BOLD}${C_GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
