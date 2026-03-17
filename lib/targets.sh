#!/usr/bin/env bash
# gniza4linux/lib/targets.sh — Target CRUD for managing backup profiles

[[ -n "${_GNIZA4LINUX_TARGETS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_TARGETS_LOADED=1

# ── Discovery ─────────────────────────────────────────────────

# List target names (filenames without .conf) sorted alphabetically.
list_targets() {
    local targets_dir="$CONFIG_DIR/targets.d"
    if [[ ! -d "$targets_dir" ]]; then
        return 0
    fi
    local f
    for f in "$targets_dir"/*.conf; do
        [[ -f "$f" ]] || continue
        basename "$f" .conf
    done
}

# Return 0 if at least one target config exists.
has_targets() {
    local targets
    targets=$(list_targets)
    [[ -n "$targets" ]]
}

# ── Loading ───────────────────────────────────────────────────

# Source a target config and set TARGET_* globals.
# Usage: load_target <name>
load_target() {
    local name="$1"
    if [[ ! "$name" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ ]]; then
        log_error "Invalid target name: $name"
        return 1
    fi
    local conf="$CONFIG_DIR/targets.d/${name}.conf"

    if [[ ! -f "$conf" ]]; then
        log_error "Target config not found: $conf"
        return 1
    fi

    _safe_source_config "$conf" || {
        log_error "Failed to parse target config: $conf"
        return 1
    }

    # Apply defaults for optional fields
    TARGET_NAME="${TARGET_NAME:-$name}"
    TARGET_FOLDERS="${TARGET_FOLDERS:-}"
    TARGET_EXCLUDE="${TARGET_EXCLUDE:-}"
    TARGET_INCLUDE="${TARGET_INCLUDE:-}"
    TARGET_REMOTE="${TARGET_REMOTE:-}"
    TARGET_PRE_HOOK="${TARGET_PRE_HOOK:-}"
    TARGET_POST_HOOK="${TARGET_POST_HOOK:-}"
    TARGET_ENABLED="${TARGET_ENABLED:-yes}"
    TARGET_MYSQL_ENABLED="${TARGET_MYSQL_ENABLED:-no}"
    TARGET_MYSQL_MODE="${TARGET_MYSQL_MODE:-all}"
    TARGET_MYSQL_DATABASES="${TARGET_MYSQL_DATABASES:-}"
    TARGET_MYSQL_EXCLUDE="${TARGET_MYSQL_EXCLUDE:-}"
    TARGET_MYSQL_USER="${TARGET_MYSQL_USER:-}"
    TARGET_MYSQL_PASSWORD="${TARGET_MYSQL_PASSWORD:-}"
    TARGET_MYSQL_HOST="${TARGET_MYSQL_HOST:-localhost}"
    TARGET_MYSQL_PORT="${TARGET_MYSQL_PORT:-3306}"
    TARGET_MYSQL_EXTRA_OPTS="${TARGET_MYSQL_EXTRA_OPTS:---single-transaction --routines --triggers}"
    TARGET_POSTGRESQL_ENABLED="${TARGET_POSTGRESQL_ENABLED:-no}"
    TARGET_POSTGRESQL_MODE="${TARGET_POSTGRESQL_MODE:-all}"
    TARGET_POSTGRESQL_DATABASES="${TARGET_POSTGRESQL_DATABASES:-}"
    TARGET_POSTGRESQL_EXCLUDE="${TARGET_POSTGRESQL_EXCLUDE:-}"
    TARGET_POSTGRESQL_USER="${TARGET_POSTGRESQL_USER:-}"
    TARGET_POSTGRESQL_PASSWORD="${TARGET_POSTGRESQL_PASSWORD:-}"
    TARGET_POSTGRESQL_HOST="${TARGET_POSTGRESQL_HOST:-localhost}"
    TARGET_POSTGRESQL_PORT="${TARGET_POSTGRESQL_PORT:-5432}"
    TARGET_POSTGRESQL_EXTRA_OPTS="${TARGET_POSTGRESQL_EXTRA_OPTS:---no-owner --no-privileges}"
    TARGET_CRONTAB_ENABLED="${TARGET_CRONTAB_ENABLED:-no}"
    TARGET_CRONTAB_USERS="${TARGET_CRONTAB_USERS:-root}"
    TARGET_SOURCE_TYPE="${TARGET_SOURCE_TYPE:-local}"
    TARGET_SOURCE_HOST="${TARGET_SOURCE_HOST:-}"
    TARGET_SOURCE_PORT="${TARGET_SOURCE_PORT:-22}"
    TARGET_SOURCE_USER="${TARGET_SOURCE_USER:-gniza}"
    TARGET_SOURCE_AUTH_METHOD="${TARGET_SOURCE_AUTH_METHOD:-key}"
    TARGET_SOURCE_KEY="${TARGET_SOURCE_KEY:-}"
    TARGET_SOURCE_PASSWORD="${TARGET_SOURCE_PASSWORD:-}"
    TARGET_SOURCE_SUDO="${TARGET_SOURCE_SUDO:-yes}"
    TARGET_SOURCE_S3_BUCKET="${TARGET_SOURCE_S3_BUCKET:-}"
    TARGET_SOURCE_S3_REGION="${TARGET_SOURCE_S3_REGION:-us-east-1}"
    TARGET_SOURCE_S3_ENDPOINT="${TARGET_SOURCE_S3_ENDPOINT:-}"
    TARGET_SOURCE_S3_ACCESS_KEY_ID="${TARGET_SOURCE_S3_ACCESS_KEY_ID:-}"
    TARGET_SOURCE_S3_SECRET_ACCESS_KEY="${TARGET_SOURCE_S3_SECRET_ACCESS_KEY:-}"
    TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE="${TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE:-}"
    TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID="${TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID:-}"
    TARGET_SOURCE_RCLONE_CONFIG_PATH="${TARGET_SOURCE_RCLONE_CONFIG_PATH:-}"
    TARGET_SOURCE_RCLONE_REMOTE_NAME="${TARGET_SOURCE_RCLONE_REMOTE_NAME:-}"

    log_debug "Loaded target '$name': folders=${TARGET_FOLDERS} enabled=${TARGET_ENABLED}"
}

# ── Validation ────────────────────────────────────────────────

# Validate a loaded target config.
# Usage: validate_target <name>
validate_target() {
    local name="$1"
    load_target "$name" || return 1

    local errors=0

    if [[ -z "$TARGET_NAME" ]]; then
        log_error "Target '$name': TARGET_NAME is required"
        ((errors++)) || true
    fi

    if [[ -z "$TARGET_FOLDERS" && "${TARGET_MYSQL_ENABLED:-no}" != "yes" && "${TARGET_POSTGRESQL_ENABLED:-no}" != "yes" ]]; then
        log_error "Target '$name': TARGET_FOLDERS is required (or enable MySQL/PostgreSQL backup)"
        ((errors++)) || true
    elif [[ -n "$TARGET_FOLDERS" ]]; then
        if [[ "${TARGET_SOURCE_TYPE:-local}" == "local" ]]; then
            # Validate each folder exists locally
            local -a folders
            IFS=',' read -ra folders <<< "$TARGET_FOLDERS"
            local folder
            for folder in "${folders[@]}"; do
                folder="${folder#"${folder%%[![:space:]]*}"}"
                folder="${folder%"${folder##*[![:space:]]}"}"
                [[ -z "$folder" ]] && continue
                if [[ "$folder" != /* ]]; then
                    log_error "Target '$name': folder path must be absolute: $folder"
                    ((errors++)) || true
                elif [[ ! -d "$folder" ]]; then
                    log_error "Target '$name': folder does not exist: $folder"
                    ((errors++)) || true
                fi
            done
        else
            # Remote source: validate connection fields
            case "${TARGET_SOURCE_TYPE}" in
                ssh)
                    if [[ -z "${TARGET_SOURCE_HOST}" ]]; then
                        log_error "Target '$name': TARGET_SOURCE_HOST is required for SSH source"
                        ((errors++)) || true
                    fi
                    ;;
                s3)
                    if [[ -z "${TARGET_SOURCE_S3_BUCKET}" ]]; then
                        log_error "Target '$name': TARGET_SOURCE_S3_BUCKET is required for S3 source"
                        ((errors++)) || true
                    fi
                    if [[ -z "${TARGET_SOURCE_S3_ACCESS_KEY_ID}" || -z "${TARGET_SOURCE_S3_SECRET_ACCESS_KEY}" ]]; then
                        log_error "Target '$name': S3 credentials are required for S3 source"
                        ((errors++)) || true
                    fi
                    ;;
                gdrive)
                    if [[ -z "${TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE}" ]]; then
                        log_error "Target '$name': service account file is required for Google Drive source"
                        ((errors++)) || true
                    fi
                    ;;
                rclone)
                    if ! command -v rclone &>/dev/null; then
                        log_error "Target '$name': rclone is required for rclone source (install: https://rclone.org/install/)"
                        ((errors++)) || true
                    fi
                    if [[ -z "${TARGET_SOURCE_RCLONE_REMOTE_NAME:-}" ]]; then
                        log_error "Target '$name': TARGET_SOURCE_RCLONE_REMOTE_NAME is required for rclone source"
                        ((errors++)) || true
                    elif [[ ! "$TARGET_SOURCE_RCLONE_REMOTE_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
                        log_error "Target '$name': Invalid rclone remote name (use letters, numbers, hyphens, underscores)"
                        ((errors++)) || true
                    fi
                    if [[ -n "${TARGET_SOURCE_RCLONE_CONFIG_PATH:-}" && ! -f "${TARGET_SOURCE_RCLONE_CONFIG_PATH}" ]]; then
                        log_error "Target '$name': TARGET_SOURCE_RCLONE_CONFIG_PATH not found: $TARGET_SOURCE_RCLONE_CONFIG_PATH"
                        ((errors++)) || true
                    fi
                    ;;
                *)
                    log_error "Target '$name': unknown TARGET_SOURCE_TYPE: ${TARGET_SOURCE_TYPE}"
                    ((errors++)) || true
                    ;;
            esac
            # Validate paths are absolute (even on remote)
            local -a folders
            IFS=',' read -ra folders <<< "$TARGET_FOLDERS"
            local folder
            for folder in "${folders[@]}"; do
                folder="${folder#"${folder%%[![:space:]]*}"}"
                folder="${folder%"${folder##*[![:space:]]}"}"
                [[ -z "$folder" ]] && continue
                if [[ "$folder" != /* ]]; then
                    log_error "Target '$name': folder path must be absolute: $folder"
                    ((errors++)) || true
                fi
            done
        fi
    fi

    if [[ -n "$TARGET_ENABLED" && "$TARGET_ENABLED" != "yes" && "$TARGET_ENABLED" != "no" ]]; then
        log_error "Target '$name': TARGET_ENABLED must be 'yes' or 'no', got: $TARGET_ENABLED"
        ((errors++)) || true
    fi

    (( errors > 0 )) && return 1
    return 0
}

# ── CRUD ──────────────────────────────────────────────────────

# Write a target .conf file.
# Usage: create_target <name> <folders> [exclude] [pre_hook] [post_hook] [enabled]
create_target() {
    local name="$1"
    local folders="$2"
    local exclude="${3:-}"
    local pre_hook="${4:-}"
    local post_hook="${5:-}"
    local enabled="${6:-yes}"

    validate_target_name "$name" || return 1

    local conf="$CONFIG_DIR/targets.d/${name}.conf"

    cat > "$conf" <<EOF
TARGET_NAME="$name"
TARGET_FOLDERS="$folders"
TARGET_EXCLUDE="$exclude"
TARGET_PRE_HOOK="$pre_hook"
TARGET_POST_HOOK="$post_hook"
TARGET_ENABLED="$enabled"
EOF

    chmod 600 "$conf"
    log_info "Created target config: $conf"
}

# Remove a target .conf file.
# Usage: delete_target <name>
delete_target() {
    local name="$1"
    local conf="$CONFIG_DIR/targets.d/${name}.conf"

    if [[ ! -f "$conf" ]]; then
        log_error "Target config not found: $conf"
        return 1
    fi

    rm -f "$conf"
    log_info "Deleted target config: $conf"
}

# ── Helpers ───────────────────────────────────────────────────

# Parse TARGET_FOLDERS into an array (IFS=,).
# Usage: get_target_folders
#   Reads from the current TARGET_FOLDERS global.
#   Outputs one folder per line (trimmed).
get_target_folders() {
    local -a folders
    IFS=',' read -ra folders <<< "$TARGET_FOLDERS"
    local folder
    for folder in "${folders[@]}"; do
        # Trim whitespace
        folder="${folder#"${folder%%[![:space:]]*}"}"
        folder="${folder%"${folder##*[![:space:]]}"}"
        [[ -n "$folder" ]] && echo "$folder"
    done
}
