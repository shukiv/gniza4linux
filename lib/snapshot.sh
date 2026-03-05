#!/usr/bin/env bash
# gniza4linux/lib/snapshot.sh — Timestamp naming, list/resolve snapshots, latest symlink

[[ -n "${_GNIZA4LINUX_SNAPSHOT_LOADED:-}" ]] && return 0
_GNIZA4LINUX_SNAPSHOT_LOADED=1

get_remote_target_base() {
    local target_name="$1"
    local hostname; hostname=$(hostname -f)
    echo "${REMOTE_BASE}/${hostname}/targets/${target_name}"
}

get_snapshot_dir() {
    local target_name="$1"
    echo "$(get_remote_target_base "$target_name")/snapshots"
}

list_remote_snapshots() {
    local target_name="$1"

    if _is_rclone_mode; then
        rclone_list_remote_snapshots "$target_name"
        return
    fi

    if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        local raw
        raw=$(ls -1d "$snap_dir"/[0-9]* 2>/dev/null | grep -v '\.partial$' | sort -r) || true
        if [[ -n "$raw" ]]; then
            echo "$raw" | xargs -I{} basename {} | sort -r
        fi
        return
    fi

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")

    # List completed snapshots (no .partial suffix), sorted newest first
    local raw; raw=$(remote_exec "ls -1d '$snap_dir'/[0-9]* 2>/dev/null | grep -v '\\.partial$' | sort -r" 2>/dev/null) || true
    if [[ -n "$raw" ]]; then
        echo "$raw" | xargs -I{} basename {} | sort -r
    fi
}

get_latest_snapshot() {
    local target_name="$1"

    if _is_rclone_mode; then
        rclone_get_latest_snapshot "$target_name"
        return
    fi

    list_remote_snapshots "$target_name" | head -1
}

resolve_snapshot_timestamp() {
    local target_name="$1"
    local requested="$2"

    if [[ -z "$requested" || "$requested" == "LATEST" || "$requested" == "latest" ]]; then
        get_latest_snapshot "$target_name"
    elif _is_rclone_mode; then
        rclone_resolve_snapshot "$target_name" "$requested"
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        if [[ -d "$snap_dir/$requested" ]]; then
            echo "$requested"
        else
            log_error "Snapshot not found for $target_name: $requested"
            return 1
        fi
    else
        # Verify it exists on SSH remote
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        if remote_exec "test -d '$snap_dir/$requested'" 2>/dev/null; then
            echo "$requested"
        else
            log_error "Snapshot not found for $target_name: $requested"
            return 1
        fi
    fi
}

update_latest_symlink() {
    local target_name="$1"
    local timestamp="$2"

    if _is_rclone_mode; then
        rclone_update_latest "$target_name" "$timestamp"
        return
    fi

    local base; base=$(get_remote_target_base "$target_name")
    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")

    if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        ln -sfn "$snap_dir/$timestamp" "$base/latest" || {
            log_warn "Failed to update latest symlink for $target_name"
            return 1
        }
    else
        remote_exec "ln -sfn '$snap_dir/$timestamp' '$base/latest'" || {
            log_warn "Failed to update latest symlink for $target_name"
            return 1
        }
    fi
    log_debug "Updated latest symlink for $target_name -> $timestamp"
}

clean_partial_snapshots() {
    local target_name="$1"

    if _is_rclone_mode; then
        rclone_clean_partial_snapshots "$target_name"
        return
    fi

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")

    if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local partials
        partials=$(ls -1d "$snap_dir"/*.partial 2>/dev/null) || true
        if [[ -n "$partials" ]]; then
            log_info "Cleaning partial snapshots for $target_name..."
            rm -rf "$snap_dir"/*.partial || {
                log_warn "Failed to clean partial snapshots for $target_name"
            }
        fi
        return
    fi

    local partials; partials=$(remote_exec "ls -1d '$snap_dir'/*.partial 2>/dev/null" 2>/dev/null) || true
    if [[ -n "$partials" ]]; then
        log_info "Cleaning partial snapshots for $target_name..."
        remote_exec "rm -rf '$snap_dir'/*.partial" || {
            log_warn "Failed to clean partial snapshots for $target_name"
        }
    fi
}

list_remote_targets() {
    if _is_rclone_mode; then
        rclone_list_dirs "targets"
        return
    fi

    local hostname; hostname=$(hostname -f)
    local targets_dir="${REMOTE_BASE}/${hostname}/targets"

    if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        ls -1 "$targets_dir" 2>/dev/null || true
        return
    fi

    remote_exec "ls -1 '$targets_dir' 2>/dev/null" 2>/dev/null || true
}
