#!/usr/bin/env bash
# gniza4linux/lib/restore.sh — Restore flows for targets

[[ -n "${_GNIZA4LINUX_RESTORE_LOADED:-}" ]] && return 0
_GNIZA4LINUX_RESTORE_LOADED=1

# Helper: rsync download from SSH remote to local.
_rsync_download() {
    local remote_path="$1"
    local local_path="$2"
    local rsync_ssh; rsync_ssh=$(build_rsync_ssh_cmd)
    if _is_password_mode; then
        export SSHPASS="$REMOTE_PASSWORD"
        sshpass -e rsync -aHAX --numeric-ids --rsync-path="rsync --fake-super" \
            -e "$rsync_ssh" \
            "${REMOTE_USER}@${REMOTE_HOST}:${remote_path}" \
            "$local_path"
    else
        rsync -aHAX --numeric-ids --rsync-path="rsync --fake-super" \
            -e "$rsync_ssh" \
            "${REMOTE_USER}@${REMOTE_HOST}:${remote_path}" \
            "$local_path"
    fi
}

# Restore all folders from a snapshot.
# Usage: restore_target <target_name> <snapshot_timestamp|"latest"> <remote_name> [dest_dir]
restore_target() {
    local target_name="$1"
    local snapshot_ts="${2:-latest}"
    local remote_name="$3"
    local dest_dir="${4:-}"

    load_target "$target_name" || {
        log_error "Failed to load target: $target_name"
        return 1
    }

    _save_remote_globals
    load_remote "$remote_name" || {
        log_error "Failed to load remote: $remote_name"
        _restore_remote_globals
        return 1
    }

    # Resolve snapshot timestamp
    local ts; ts=$(resolve_snapshot_timestamp "$target_name" "$snapshot_ts") || {
        log_error "Cannot resolve snapshot: $snapshot_ts"
        _restore_remote_globals
        return 1
    }

    log_info "Restoring target '$target_name' from snapshot $ts (remote: $remote_name)"

    if [[ -z "$dest_dir" ]]; then
        log_warn "No destination specified; restoring to original locations (IN-PLACE)"
    fi

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
    local folder
    local errors=0

    while IFS= read -r folder; do
        [[ -z "$folder" ]] && continue
        local rel_path="${folder#/}"
        local restore_dest
        if [[ -n "$dest_dir" ]]; then
            restore_dest="$dest_dir/$rel_path"
        else
            restore_dest="$folder"
        fi

        mkdir -p "$restore_dest" || {
            log_error "Failed to create destination: $restore_dest"
            ((errors++)) || true
            continue
        }

        log_info "Restoring $rel_path -> $restore_dest"

        if _is_rclone_mode; then
            # Incremental rclone: current/ has latest mirror, snapshots/ have diffs
            local current_subpath="targets/${target_name}/current/${rel_path}"
            rclone_from_remote "$current_subpath" "$restore_dest" || {
                log_error "Restore failed for folder: $folder"
                ((errors++)) || true
            }
        elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
            local source_path="$snap_dir/$ts/$rel_path/"
            rsync -aHAX --numeric-ids "$source_path" "$restore_dest/" || {
                log_error "Restore failed for folder: $folder"
                ((errors++)) || true
            }
        else
            local source_path="$snap_dir/$ts/$rel_path/"
            _rsync_download "$source_path" "$restore_dest/" || {
                log_error "Restore failed for folder: $folder"
                ((errors++)) || true
            }
        fi
    done < <(get_target_folders)

    # Restore MySQL databases if snapshot contains _mysql/ and target has MySQL enabled
    if [[ "${TARGET_MYSQL_ENABLED:-no}" == "yes" && "${SKIP_MYSQL_RESTORE:-}" != "yes" ]]; then
        log_info "Checking for MySQL dumps in snapshot..."
        local mysql_restore_dir
        mysql_restore_dir=$(mktemp -d "${WORK_DIR:-/tmp}/gniza-mysql-restore-XXXXXX")
        mkdir -p "$mysql_restore_dir/_mysql"

        local mysql_found=false
        if _is_rclone_mode; then
            local mysql_subpath="targets/${target_name}/current/_mysql"
            if rclone_from_remote "$mysql_subpath" "$mysql_restore_dir/_mysql" 2>/dev/null; then
                mysql_found=true
            fi
        elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
            local mysql_source="$snap_dir/$ts/_mysql/"
            if [[ -d "$mysql_source" ]]; then
                rsync -aHAX "$mysql_source" "$mysql_restore_dir/_mysql/" && mysql_found=true
            fi
        else
            local mysql_source="$snap_dir/$ts/_mysql/"
            if _rsync_download "$mysql_source" "$mysql_restore_dir/_mysql/" 2>/dev/null; then
                mysql_found=true
            fi
        fi

        if [[ "$mysql_found" == "true" ]] && ls "$mysql_restore_dir/_mysql/"*.sql.gz &>/dev/null || \
           [[ -f "$mysql_restore_dir/_mysql/grants.sql" ]]; then
            log_info "Found MySQL dumps in snapshot, restoring..."
            if ! mysql_restore_databases "$mysql_restore_dir/_mysql"; then
                log_error "MySQL restore had errors"
                ((errors++)) || true
            fi
        else
            log_debug "No MySQL dumps found in snapshot"
        fi
        rm -rf "$mysql_restore_dir"
    elif [[ "${SKIP_MYSQL_RESTORE:-}" == "yes" ]]; then
        log_info "Skipping MySQL restore (--skip-mysql)"
    fi

    _restore_remote_globals

    if (( errors > 0 )); then
        log_error "Restore completed with $errors error(s)"
        return 1
    fi

    log_info "Restore completed successfully for $target_name"
    return 0
}

# Restore a single folder from a snapshot.
# Usage: restore_folder <target_name> <folder_path> <snapshot_timestamp> <remote_name> [dest_dir]
restore_folder() {
    local target_name="$1"
    local folder_path="$2"
    local snapshot_ts="${3:-latest}"
    local remote_name="$4"
    local dest_dir="${5:-}"

    load_target "$target_name" || {
        log_error "Failed to load target: $target_name"
        return 1
    }

    _save_remote_globals
    load_remote "$remote_name" || {
        log_error "Failed to load remote: $remote_name"
        _restore_remote_globals
        return 1
    }

    local ts; ts=$(resolve_snapshot_timestamp "$target_name" "$snapshot_ts") || {
        log_error "Cannot resolve snapshot: $snapshot_ts"
        _restore_remote_globals
        return 1
    }

    local rel_path="${folder_path#/}"
    local restore_dest
    if [[ -n "$dest_dir" ]]; then
        restore_dest="$dest_dir/$rel_path"
    else
        restore_dest="$folder_path"
        log_warn "No destination specified; restoring to original location (IN-PLACE): $folder_path"
    fi

    mkdir -p "$restore_dest" || {
        log_error "Failed to create destination: $restore_dest"
        _restore_remote_globals
        return 1
    }

    log_info "Restoring $rel_path -> $restore_dest (snapshot: $ts)"

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
    local rc=0

    if _is_rclone_mode; then
        # Incremental rclone: current/ has latest mirror
        local current_subpath="targets/${target_name}/current/${rel_path}"
        rclone_from_remote "$current_subpath" "$restore_dest" || rc=$?
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local source_path="$snap_dir/$ts/$rel_path/"
        rsync -aHAX --numeric-ids "$source_path" "$restore_dest/" || rc=$?
    else
        local source_path="$snap_dir/$ts/$rel_path/"
        _rsync_download "$source_path" "$restore_dest/" || rc=$?
    fi

    _restore_remote_globals

    if (( rc != 0 )); then
        log_error "Restore failed for $folder_path"
        return 1
    fi

    log_info "Restore completed for $folder_path"
    return 0
}

# List files in a snapshot.
# Usage: list_snapshot_contents <target_name> <snapshot_timestamp> <remote_name>
list_snapshot_contents() {
    local target_name="$1"
    local snapshot_ts="${2:-latest}"
    local remote_name="$3"

    _save_remote_globals
    load_remote "$remote_name" || {
        log_error "Failed to load remote: $remote_name"
        _restore_remote_globals
        return 1
    }

    local ts; ts=$(resolve_snapshot_timestamp "$target_name" "$snapshot_ts") || {
        log_error "Cannot resolve snapshot: $snapshot_ts"
        _restore_remote_globals
        return 1
    }

    if _is_rclone_mode; then
        local current_subpath="targets/${target_name}/current"
        rclone_list_files "$current_subpath"
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        find "$snap_dir/$ts" -type f 2>/dev/null
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        local sq_path; sq_path="$(shquote "$snap_dir/$ts")"
        remote_exec "find '${sq_path}' -type f 2>/dev/null" 2>/dev/null
    fi

    _restore_remote_globals
}

# Read meta.json from a snapshot.
# Usage: get_snapshot_meta <target_name> <snapshot_timestamp> <remote_name>
get_snapshot_meta() {
    local target_name="$1"
    local snapshot_ts="${2:-latest}"
    local remote_name="$3"

    _save_remote_globals
    load_remote "$remote_name" || {
        log_error "Failed to load remote: $remote_name"
        _restore_remote_globals
        return 1
    }

    local ts; ts=$(resolve_snapshot_timestamp "$target_name" "$snapshot_ts") || {
        log_error "Cannot resolve snapshot: $snapshot_ts"
        _restore_remote_globals
        return 1
    }

    if _is_rclone_mode; then
        local snap_subpath="targets/${target_name}/snapshots/${ts}/meta.json"
        rclone_cat "$snap_subpath"
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        cat "$snap_dir/$ts/meta.json" 2>/dev/null
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        local sq_meta; sq_meta="$(shquote "$snap_dir/$ts/meta.json")"
        remote_exec "cat '${sq_meta}'" 2>/dev/null
    fi

    _restore_remote_globals
}
