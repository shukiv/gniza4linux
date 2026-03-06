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
    TARGET_REMOTE="${TARGET_REMOTE:-}"
    TARGET_RETENTION="${TARGET_RETENTION:-}"
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

    if [[ -z "$TARGET_FOLDERS" && "${TARGET_MYSQL_ENABLED:-no}" != "yes" ]]; then
        log_error "Target '$name': TARGET_FOLDERS is required (or enable MySQL backup)"
        ((errors++)) || true
    elif [[ -n "$TARGET_FOLDERS" ]]; then
        # Validate each folder exists
        local -a folders
        IFS=',' read -ra folders <<< "$TARGET_FOLDERS"
        local folder
        for folder in "${folders[@]}"; do
            # Trim whitespace
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
# Usage: create_target <name> <folders> [exclude] [remote] [retention] [pre_hook] [post_hook] [enabled]
create_target() {
    local name="$1"
    local folders="$2"
    local exclude="${3:-}"
    local remote="${4:-}"
    local retention="${5:-}"
    local pre_hook="${6:-}"
    local post_hook="${7:-}"
    local enabled="${8:-yes}"

    validate_target_name "$name" || return 1

    local conf="$CONFIG_DIR/targets.d/${name}.conf"

    cat > "$conf" <<EOF
TARGET_NAME="$name"
TARGET_FOLDERS="$folders"
TARGET_EXCLUDE="$exclude"
TARGET_REMOTE="$remote"
TARGET_RETENTION="$retention"
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
