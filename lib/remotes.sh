#!/usr/bin/env bash
# gniza4linux/lib/remotes.sh — Remote discovery and context switching
#
# Remote destinations are configured in $CONFIG_DIR/remotes.d/<name>.conf.
# Each config overrides REMOTE_* globals so existing functions (ssh,
# transfer, snapshot, retention) work unchanged.

[[ -n "${_GNIZA4LINUX_REMOTES_LOADED:-}" ]] && return 0
_GNIZA4LINUX_REMOTES_LOADED=1

# ── Saved state for legacy globals ─────────────────────────────

declare -g _SAVED_REMOTE_HOST=""
declare -g _SAVED_REMOTE_PORT=""
declare -g _SAVED_REMOTE_USER=""
declare -g _SAVED_REMOTE_AUTH_METHOD=""
declare -g _SAVED_REMOTE_KEY=""
declare -g _SAVED_REMOTE_PASSWORD=""
declare -g _SAVED_REMOTE_BASE=""
declare -g _SAVED_BWLIMIT=""
declare -g _SAVED_RETENTION_COUNT=""
declare -g _SAVED_RSYNC_EXTRA_OPTS=""
declare -g _SAVED_REMOTE_TYPE=""
declare -g _SAVED_S3_ACCESS_KEY_ID=""
declare -g _SAVED_S3_SECRET_ACCESS_KEY=""
declare -g _SAVED_S3_REGION=""
declare -g _SAVED_S3_ENDPOINT=""
declare -g _SAVED_S3_BUCKET=""
declare -g _SAVED_GDRIVE_SERVICE_ACCOUNT_FILE=""
declare -g _SAVED_GDRIVE_ROOT_FOLDER_ID=""
declare -g CURRENT_REMOTE_NAME=""

_save_remote_globals() {
    _SAVED_REMOTE_HOST="${REMOTE_HOST:-}"
    _SAVED_REMOTE_PORT="${REMOTE_PORT:-22}"
    _SAVED_REMOTE_USER="${REMOTE_USER:-root}"
    _SAVED_REMOTE_AUTH_METHOD="${REMOTE_AUTH_METHOD:-key}"
    _SAVED_REMOTE_KEY="${REMOTE_KEY:-}"
    _SAVED_REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"
    _SAVED_REMOTE_BASE="${REMOTE_BASE:-/backups}"
    _SAVED_BWLIMIT="${BWLIMIT:-0}"
    _SAVED_RETENTION_COUNT="${RETENTION_COUNT:-30}"
    _SAVED_RSYNC_EXTRA_OPTS="${RSYNC_EXTRA_OPTS:-}"
    _SAVED_REMOTE_TYPE="${REMOTE_TYPE:-ssh}"
    _SAVED_S3_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-}"
    _SAVED_S3_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-}"
    _SAVED_S3_REGION="${S3_REGION:-}"
    _SAVED_S3_ENDPOINT="${S3_ENDPOINT:-}"
    _SAVED_S3_BUCKET="${S3_BUCKET:-}"
    _SAVED_GDRIVE_SERVICE_ACCOUNT_FILE="${GDRIVE_SERVICE_ACCOUNT_FILE:-}"
    _SAVED_GDRIVE_ROOT_FOLDER_ID="${GDRIVE_ROOT_FOLDER_ID:-}"
}

_restore_remote_globals() {
    REMOTE_HOST="$_SAVED_REMOTE_HOST"
    REMOTE_PORT="$_SAVED_REMOTE_PORT"
    REMOTE_USER="$_SAVED_REMOTE_USER"
    REMOTE_AUTH_METHOD="$_SAVED_REMOTE_AUTH_METHOD"
    REMOTE_KEY="$_SAVED_REMOTE_KEY"
    REMOTE_PASSWORD="$_SAVED_REMOTE_PASSWORD"
    REMOTE_BASE="$_SAVED_REMOTE_BASE"
    BWLIMIT="$_SAVED_BWLIMIT"
    RETENTION_COUNT="$_SAVED_RETENTION_COUNT"
    RSYNC_EXTRA_OPTS="$_SAVED_RSYNC_EXTRA_OPTS"
    REMOTE_TYPE="$_SAVED_REMOTE_TYPE"
    S3_ACCESS_KEY_ID="$_SAVED_S3_ACCESS_KEY_ID"
    S3_SECRET_ACCESS_KEY="$_SAVED_S3_SECRET_ACCESS_KEY"
    S3_REGION="$_SAVED_S3_REGION"
    S3_ENDPOINT="$_SAVED_S3_ENDPOINT"
    S3_BUCKET="$_SAVED_S3_BUCKET"
    GDRIVE_SERVICE_ACCOUNT_FILE="$_SAVED_GDRIVE_SERVICE_ACCOUNT_FILE"
    GDRIVE_ROOT_FOLDER_ID="$_SAVED_GDRIVE_ROOT_FOLDER_ID"
    CURRENT_REMOTE_NAME=""
}

# ── Discovery ──────────────────────────────────────────────────

# List remote names (filenames without .conf) sorted alphabetically.
list_remotes() {
    local remotes_dir="$CONFIG_DIR/remotes.d"
    if [[ ! -d "$remotes_dir" ]]; then
        return 0
    fi
    local f
    for f in "$remotes_dir"/*.conf; do
        [[ -f "$f" ]] || continue
        basename "$f" .conf
    done
}

# Return 0 if at least one remote config exists.
has_remotes() {
    local remotes
    remotes=$(list_remotes)
    [[ -n "$remotes" ]]
}

# ── Context switching ──────────────────────────────────────────

# Source a remote config and override REMOTE_* globals.
# Usage: load_remote <name>
load_remote() {
    local name="$1"
    local conf="$CONFIG_DIR/remotes.d/${name}.conf"

    if [[ ! -f "$conf" ]]; then
        log_error "Remote config not found: $conf"
        return 1
    fi

    _safe_source_config "$conf" || {
        log_error "Failed to parse remote config: $conf"
        return 1
    }

    # Apply defaults for optional fields
    REMOTE_TYPE="${REMOTE_TYPE:-$DEFAULT_REMOTE_TYPE}"
    REMOTE_PORT="${REMOTE_PORT:-$DEFAULT_REMOTE_PORT}"
    REMOTE_USER="${REMOTE_USER:-$DEFAULT_REMOTE_USER}"
    REMOTE_AUTH_METHOD="${REMOTE_AUTH_METHOD:-$DEFAULT_REMOTE_AUTH_METHOD}"
    REMOTE_KEY="${REMOTE_KEY:-}"
    REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"
    REMOTE_BASE="${REMOTE_BASE:-$DEFAULT_REMOTE_BASE}"
    BWLIMIT="${BWLIMIT:-$DEFAULT_BWLIMIT}"
    RETENTION_COUNT="${RETENTION_COUNT:-$DEFAULT_RETENTION_COUNT}"
    RSYNC_EXTRA_OPTS="${RSYNC_EXTRA_OPTS:-}"

    # Cloud-specific defaults
    S3_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-}"
    S3_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-}"
    S3_REGION="${S3_REGION:-$DEFAULT_S3_REGION}"
    S3_ENDPOINT="${S3_ENDPOINT:-}"
    S3_BUCKET="${S3_BUCKET:-}"
    GDRIVE_SERVICE_ACCOUNT_FILE="${GDRIVE_SERVICE_ACCOUNT_FILE:-}"
    GDRIVE_ROOT_FOLDER_ID="${GDRIVE_ROOT_FOLDER_ID:-}"

    # shellcheck disable=SC2034  # used by callers
    CURRENT_REMOTE_NAME="$name"
    case "$REMOTE_TYPE" in
        ssh)
            log_debug "Loaded remote '$name': ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT} -> ${REMOTE_BASE}"
            ;;
        local)
            log_debug "Loaded remote '$name': type=local -> ${REMOTE_BASE}"
            ;;
        *)
            log_debug "Loaded remote '$name': type=${REMOTE_TYPE} -> ${REMOTE_BASE}"
            ;;
    esac
}

# Load + validate a remote config.
validate_remote() {
    local name="$1"
    load_remote "$name" || return 1

    local errors=0

    # Common validations
    if ! [[ "$RETENTION_COUNT" =~ ^[0-9]+$ ]] || (( RETENTION_COUNT < 1 )); then
        log_error "Remote '$name': RETENTION_COUNT must be >= 1, got: $RETENTION_COUNT"
        ((errors++)) || true
    fi

    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            if [[ -z "$REMOTE_HOST" ]]; then
                log_error "Remote '$name': REMOTE_HOST is required"
                ((errors++)) || true
            fi

            if [[ "${REMOTE_AUTH_METHOD:-key}" != "key" && "${REMOTE_AUTH_METHOD:-key}" != "password" ]]; then
                log_error "Remote '$name': REMOTE_AUTH_METHOD must be 'key' or 'password', got: $REMOTE_AUTH_METHOD"
                ((errors++)) || true
            fi

            if [[ "${REMOTE_AUTH_METHOD:-key}" == "password" ]]; then
                if [[ -z "${REMOTE_PASSWORD:-}" ]]; then
                    log_error "Remote '$name': REMOTE_PASSWORD is required when REMOTE_AUTH_METHOD=password"
                    ((errors++)) || true
                fi
                if ! command -v sshpass &>/dev/null; then
                    log_error "Remote '$name': sshpass is required for password authentication (install: apt install sshpass)"
                    ((errors++)) || true
                fi
            else
                if [[ -z "$REMOTE_KEY" ]]; then
                    log_error "Remote '$name': REMOTE_KEY is required"
                    ((errors++)) || true
                elif [[ ! -f "$REMOTE_KEY" ]]; then
                    log_error "Remote '$name': REMOTE_KEY file not found: $REMOTE_KEY"
                    ((errors++)) || true
                fi
            fi

            if ! [[ "$REMOTE_PORT" =~ ^[0-9]+$ ]] || (( REMOTE_PORT < 1 || REMOTE_PORT > 65535 )); then
                log_error "Remote '$name': REMOTE_PORT must be 1-65535, got: $REMOTE_PORT"
                ((errors++)) || true
            fi
            ;;
        local)
            if [[ -z "${REMOTE_BASE:-}" ]]; then
                log_error "Remote '$name': REMOTE_BASE is required for local remotes"
                ((errors++)) || true
            elif [[ ! -d "$REMOTE_BASE" ]]; then
                log_error "Remote '$name': REMOTE_BASE directory does not exist: $REMOTE_BASE"
                ((errors++)) || true
            fi
            ;;
        s3)
            if ! command -v rclone &>/dev/null; then
                log_error "Remote '$name': rclone is required for S3 remotes (install: https://rclone.org/install/)"
                ((errors++)) || true
            fi
            if [[ -z "${S3_ACCESS_KEY_ID:-}" ]]; then
                log_error "Remote '$name': S3_ACCESS_KEY_ID is required"
                ((errors++)) || true
            fi
            if [[ -z "${S3_SECRET_ACCESS_KEY:-}" ]]; then
                log_error "Remote '$name': S3_SECRET_ACCESS_KEY is required"
                ((errors++)) || true
            fi
            if [[ -z "${S3_BUCKET:-}" ]]; then
                log_error "Remote '$name': S3_BUCKET is required"
                ((errors++)) || true
            fi
            ;;
        gdrive)
            if ! command -v rclone &>/dev/null; then
                log_error "Remote '$name': rclone is required for Google Drive remotes (install: https://rclone.org/install/)"
                ((errors++)) || true
            fi
            if [[ -z "${GDRIVE_SERVICE_ACCOUNT_FILE:-}" ]]; then
                log_error "Remote '$name': GDRIVE_SERVICE_ACCOUNT_FILE is required"
                ((errors++)) || true
            elif [[ ! -f "${GDRIVE_SERVICE_ACCOUNT_FILE}" ]]; then
                log_error "Remote '$name': GDRIVE_SERVICE_ACCOUNT_FILE not found: $GDRIVE_SERVICE_ACCOUNT_FILE"
                ((errors++)) || true
            fi
            ;;
        *)
            log_error "Remote '$name': REMOTE_TYPE must be 'ssh', 'local', 's3', or 'gdrive', got: $REMOTE_TYPE"
            ((errors++)) || true
            ;;
    esac

    (( errors > 0 )) && return 1
    return 0
}

# Resolve which remotes to operate on.
# - If --remote=NAME was given, return just that name.
# - Otherwise return all remotes from remotes.d/.
# - Errors if no remotes are configured.
#
# Usage: get_target_remotes "$remote_flag_value"
# Outputs one name per line.
get_target_remotes() {
    local flag="${1:-}"
    local remotes_dir="$CONFIG_DIR/remotes.d"

    if [[ -n "$flag" ]]; then
        # Split on commas, verify each remote exists
        local IFS=','
        local names
        read -ra names <<< "$flag"
        for name in "${names[@]}"; do
            # Trim whitespace
            name="${name#"${name%%[![:space:]]*}"}"
            name="${name%"${name##*[![:space:]]}"}"
            [[ -z "$name" ]] && continue
            if [[ ! -f "$remotes_dir/${name}.conf" ]]; then
                log_error "Remote not found: $name (expected $remotes_dir/${name}.conf)"
                return 1
            fi
            echo "$name"
        done
        return 0
    fi

    if has_remotes; then
        list_remotes
        return 0
    fi

    # No remotes configured
    log_error "No remotes configured. Create one in $CONFIG_DIR/remotes.d/"
    return 1
}
