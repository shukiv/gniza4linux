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
    local sq_snap; sq_snap="$(shquote "$snap_dir")"

    # List completed snapshots (no .partial suffix), sorted newest first
    local raw; raw=$(remote_exec "ls -1d '${sq_snap}'/[0-9]* 2>/dev/null | grep -v '\\.partial$' | sort -r" 2>/dev/null) || true
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
        local sq_path; sq_path="$(shquote "$snap_dir/$requested")"
        if remote_exec "test -d '${sq_path}'" 2>/dev/null; then
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
        local sq_snap_ts; sq_snap_ts="$(shquote "$snap_dir/$timestamp")"
        local sq_latest; sq_latest="$(shquote "$base/latest")"
        remote_exec "ln -sfn '${sq_snap_ts}' '${sq_latest}'" || {
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

    local sq_snap; sq_snap="$(shquote "$snap_dir")"
    local partials; partials=$(remote_exec "ls -1d '${sq_snap}'/*.partial 2>/dev/null" 2>/dev/null) || true
    if [[ -n "$partials" ]]; then
        log_info "Cleaning partial snapshots for $target_name..."
        remote_exec "rm -rf '${sq_snap}'/*.partial" || {
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

    local sq_targets; sq_targets="$(shquote "$targets_dir")"
    remote_exec "ls -1 '${sq_targets}' 2>/dev/null" 2>/dev/null || true
}

# ── Health Check Helpers ─────────────────────────────────────

# Find target names that have snapshots on the remote but no
# corresponding config in targets.d/.
# Outputs one orphan name per line. Returns 0 even if none found.
find_orphaned_targets() {
    local remote_targets; remote_targets=$(list_remote_targets) || true
    [[ -z "$remote_targets" ]] && return 0

    local configured; configured=$(list_targets) || true
    while IFS= read -r rt; do
        [[ -z "$rt" ]] && continue
        if ! echo "$configured" | grep -qxF "$rt"; then
            echo "$rt"
        fi
    done <<< "$remote_targets"
}

# Count partial (incomplete) snapshots for a target.
# Outputs the count (integer). Does NOT delete anything.
count_partial_snapshots() {
    local target_name="$1"
    local count=0

    if _is_rclone_mode; then
        local snap_subpath="targets/${target_name}/snapshots"
        local all_dirs; all_dirs=$(rclone_list_dirs "$snap_subpath") || true
        [[ -z "$all_dirs" ]] && { echo "0"; return 0; }
        while IFS= read -r dir; do
            [[ -z "$dir" ]] && continue
            if ! rclone_exists "${snap_subpath}/${dir}/.complete"; then
                ((count++)) || true
            fi
        done <<< "$all_dirs"
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        local partials; partials=$(ls -1d "$snap_dir"/*.partial 2>/dev/null | wc -l) || true
        count="${partials:-0}"
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        local sq_snap; sq_snap="$(shquote "$snap_dir")"
        local partials; partials=$(remote_exec "ls -1d '${sq_snap}'/*.partial 2>/dev/null | wc -l" 2>/dev/null) || true
        count="${partials:-0}"
    fi

    echo "$count"
}
