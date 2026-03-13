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
declare -g _SAVED_REMOTE_SUDO=""
declare -g _SAVED_REMOTE_BASE=""
declare -g _SAVED_BWLIMIT=""
declare -g _SAVED_RSYNC_EXTRA_OPTS=""
declare -g _SAVED_REMOTE_TYPE=""
declare -g _SAVED_S3_ACCESS_KEY_ID=""
declare -g _SAVED_S3_SECRET_ACCESS_KEY=""
declare -g _SAVED_S3_REGION=""
declare -g _SAVED_S3_ENDPOINT=""
declare -g _SAVED_S3_BUCKET=""
declare -g _SAVED_GDRIVE_SERVICE_ACCOUNT_FILE=""
declare -g _SAVED_GDRIVE_ROOT_FOLDER_ID=""
declare -g _SAVED_RCLONE_CONFIG_PATH=""
declare -g _SAVED_RCLONE_REMOTE_NAME=""
declare -g CURRENT_REMOTE_NAME=""

_save_remote_globals() {
    _SAVED_REMOTE_HOST="${REMOTE_HOST:-}"
    _SAVED_REMOTE_PORT="${REMOTE_PORT:-22}"
    _SAVED_REMOTE_USER="${REMOTE_USER:-gniza}"
    _SAVED_REMOTE_AUTH_METHOD="${REMOTE_AUTH_METHOD:-key}"
    _SAVED_REMOTE_KEY="${REMOTE_KEY:-}"
    _SAVED_REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"
    _SAVED_REMOTE_SUDO="${REMOTE_SUDO:-yes}"
    _SAVED_REMOTE_BASE="${REMOTE_BASE:-/backups}"
    _SAVED_BWLIMIT="${BWLIMIT:-0}"
    _SAVED_RSYNC_EXTRA_OPTS="${RSYNC_EXTRA_OPTS:-}"
    _SAVED_REMOTE_TYPE="${REMOTE_TYPE:-ssh}"
    _SAVED_S3_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-}"
    _SAVED_S3_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-}"
    _SAVED_S3_REGION="${S3_REGION:-}"
    _SAVED_S3_ENDPOINT="${S3_ENDPOINT:-}"
    _SAVED_S3_BUCKET="${S3_BUCKET:-}"
    _SAVED_GDRIVE_SERVICE_ACCOUNT_FILE="${GDRIVE_SERVICE_ACCOUNT_FILE:-}"
    _SAVED_GDRIVE_ROOT_FOLDER_ID="${GDRIVE_ROOT_FOLDER_ID:-}"
    _SAVED_RCLONE_CONFIG_PATH="${RCLONE_CONFIG_PATH:-}"
    _SAVED_RCLONE_REMOTE_NAME="${RCLONE_REMOTE_NAME:-}"
}

_restore_remote_globals() {
    REMOTE_HOST="$_SAVED_REMOTE_HOST"
    REMOTE_PORT="$_SAVED_REMOTE_PORT"
    REMOTE_USER="$_SAVED_REMOTE_USER"
    REMOTE_AUTH_METHOD="$_SAVED_REMOTE_AUTH_METHOD"
    REMOTE_KEY="$_SAVED_REMOTE_KEY"
    REMOTE_PASSWORD="$_SAVED_REMOTE_PASSWORD"
    REMOTE_SUDO="$_SAVED_REMOTE_SUDO"
    REMOTE_BASE="$_SAVED_REMOTE_BASE"
    BWLIMIT="$_SAVED_BWLIMIT"
    RSYNC_EXTRA_OPTS="$_SAVED_RSYNC_EXTRA_OPTS"
    REMOTE_TYPE="$_SAVED_REMOTE_TYPE"
    S3_ACCESS_KEY_ID="$_SAVED_S3_ACCESS_KEY_ID"
    S3_SECRET_ACCESS_KEY="$_SAVED_S3_SECRET_ACCESS_KEY"
    S3_REGION="$_SAVED_S3_REGION"
    S3_ENDPOINT="$_SAVED_S3_ENDPOINT"
    S3_BUCKET="$_SAVED_S3_BUCKET"
    GDRIVE_SERVICE_ACCOUNT_FILE="$_SAVED_GDRIVE_SERVICE_ACCOUNT_FILE"
    GDRIVE_ROOT_FOLDER_ID="$_SAVED_GDRIVE_ROOT_FOLDER_ID"
    RCLONE_CONFIG_PATH="$_SAVED_RCLONE_CONFIG_PATH"
    RCLONE_REMOTE_NAME="$_SAVED_RCLONE_REMOTE_NAME"
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
    REMOTE_KEY="${REMOTE_KEY:-${HOME:-/root}/.ssh/id_rsa}"
    REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"
    REMOTE_SUDO="${REMOTE_SUDO:-yes}"
    REMOTE_BASE="${REMOTE_BASE:-$DEFAULT_REMOTE_BASE}"
    BWLIMIT="${BWLIMIT:-$DEFAULT_BWLIMIT}"
    RSYNC_EXTRA_OPTS="${RSYNC_EXTRA_OPTS:-}"

    # Cloud-specific defaults
    S3_ACCESS_KEY_ID="${S3_ACCESS_KEY_ID:-}"
    S3_SECRET_ACCESS_KEY="${S3_SECRET_ACCESS_KEY:-}"
    S3_REGION="${S3_REGION:-$DEFAULT_S3_REGION}"
    S3_ENDPOINT="${S3_ENDPOINT:-}"
    S3_BUCKET="${S3_BUCKET:-}"
    GDRIVE_SERVICE_ACCOUNT_FILE="${GDRIVE_SERVICE_ACCOUNT_FILE:-}"
    GDRIVE_ROOT_FOLDER_ID="${GDRIVE_ROOT_FOLDER_ID:-}"

    # Generic rclone defaults
    RCLONE_CONFIG_PATH="${RCLONE_CONFIG_PATH:-}"
    RCLONE_REMOTE_NAME="${RCLONE_REMOTE_NAME:-}"

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
                if [[ ! -f "$REMOTE_KEY" ]]; then
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
        rclone)
            if ! command -v rclone &>/dev/null; then
                log_error "Remote '$name': rclone is required for rclone remotes (install: https://rclone.org/install/)"
                ((errors++)) || true
            fi
            if [[ -z "${RCLONE_REMOTE_NAME:-}" ]]; then
                log_error "Remote '$name': RCLONE_REMOTE_NAME is required"
                ((errors++)) || true
            elif [[ ! "$RCLONE_REMOTE_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
                log_error "Remote '$name': Invalid rclone remote name (use letters, numbers, hyphens, underscores)"
                ((errors++)) || true
            fi
            if [[ -n "${RCLONE_CONFIG_PATH:-}" && ! -f "${RCLONE_CONFIG_PATH}" ]]; then
                log_error "Remote '$name': RCLONE_CONFIG_PATH not found: $RCLONE_CONFIG_PATH"
                ((errors++)) || true
            fi
            ;;
        *)
            log_error "Remote '$name': REMOTE_TYPE must be 'ssh', 'local', 's3', 'gdrive', or 'rclone', got: $REMOTE_TYPE"
            ((errors++)) || true
            ;;
    esac

    (( errors > 0 )) && return 1
    return 0
}

# ── Live connectivity test ────────────────────────────────────

# Test actual connectivity to the current remote.
# Assumes load_remote() has already been called.
test_remote_connection() {
    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            test_ssh_connection
            ;;
        local)
            _test_local_connection
            ;;
        s3|gdrive|rclone)
            test_rclone_connection
            ;;
        *)
            log_error "Unknown remote type: ${REMOTE_TYPE:-ssh}"
            return 1
            ;;
    esac
}

_test_local_connection() {
    local base="${REMOTE_BASE:-/backups}"
    if [[ ! -d "$base" ]]; then
        log_error "Base directory does not exist: $base"
        return 1
    fi
    local testfile="$base/.gniza_write_test_$$"
    if echo "gniza validation" > "$testfile" 2>/dev/null; then
        rm -f "$testfile"
        log_info "Local connection test passed: $base"
        return 0
    else
        log_error "Cannot write to base directory: $base"
        return 1
    fi
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

# ── Disk info ────────────────────────────────────────────────

# Return the disk usage percentage (integer, no %) for REMOTE_BASE.
# Returns 0 (unknown) on unsupported remote types.
remote_disk_usage_pct() {
    local base; base="$(shquote "${REMOTE_BASE:-/}")"
    local df_out=""
    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            # Plain "df" without pipes/redirects — works on restricted shells (e.g. Hetzner)
            df_out=$(remote_exec "df '$base'" 2>/dev/null) || df_out=$(remote_exec "df" 2>/dev/null) || return 1
            ;;
        local)
            df_out=$(df "$base" 2>/dev/null || df / 2>/dev/null) || return 1
            ;;
        s3|gdrive|rclone)
            rclone_disk_usage_pct
            return
            ;;
        *)
            echo "0"
            return 0
            ;;
    esac
    # Extract last line with %, then parse percentage locally
    local df_line
    df_line=$(echo "$df_out" | grep '%' | tail -1) || return 1
    local pct_raw
    pct_raw=$(echo "$df_line" | grep -oP '[0-9]+%' | head -1) || return 1
    echo "${pct_raw%%%}"
}

# Check remote disk space. Fail if usage >= threshold (default 95%).
# Usage: check_remote_disk_space [threshold]
check_remote_disk_space() {
    local threshold="${1:-95}"
    local pct
    pct=$(remote_disk_usage_pct) || {
        log_warn "Could not check remote disk space, proceeding anyway"
        return 0
    }
    if [[ "$pct" =~ ^[0-9]+$ ]] && (( pct >= threshold )); then
        log_error "Remote disk usage is ${pct}% (threshold: ${threshold}%). Aborting backup."
        return 1
    fi
    log_debug "Remote disk usage: ${pct}% (threshold: ${threshold}%)"
    return 0
}

# Compact one-line disk info: "USED/TOTAL (FREE free) PCT"
remote_disk_info_short() {
    local base; base="$(shquote "${REMOTE_BASE:-/}")"
    local df_out=""
    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            # Plain "df -h" without pipes/redirects — works on restricted shells
            df_out=$(remote_exec "df -h '$base'" 2>/dev/null) || df_out=$(remote_exec "df -h" 2>/dev/null) || return 1
            ;;
        local)
            df_out=$(df -h "$base" 2>/dev/null || df -h / 2>/dev/null) || return 1
            ;;
        s3|gdrive|rclone)
            rclone_disk_info_short
            ;;
        *)
            echo "N/A"
            return 0
            ;;
    esac
    # Strip carriage returns, squeeze whitespace, find line with %
    local data_line
    data_line=$(echo "$df_out" | tr '\r' ' ' | tr -s ' ' | grep '%' | tail -1)
    if [[ -z "$data_line" ]]; then
        echo "N/A"
        return 0
    fi
    # Find the % field and extract Size/Used/Avail from the 3 fields before it
    local size used avail pct
    read -r size used avail pct < <(
        echo "$data_line" | awk '{for(i=1;i<=NF;i++){if($i~/%/){print $(i-3),$(i-2),$(i-1),$i;exit}}}'
    )
    if [[ -n "$size" ]]; then
        echo "${used}/${size} (${avail} free) ${pct}"
    else
        echo "N/A"
    fi
}

