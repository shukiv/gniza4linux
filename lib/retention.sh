#!/usr/bin/env bash
# gniza4linux/lib/retention.sh — Delete old snapshots beyond RETENTION_COUNT on remote

[[ -n "${_GNIZA4LINUX_RETENTION_LOADED:-}" ]] && return 0
_GNIZA4LINUX_RETENTION_LOADED=1

enforce_retention() {
    local target_name="$1"
    local override="${2:-}"
    local keep="${override:-${RETENTION_COUNT:-$DEFAULT_RETENTION_COUNT}}"

    log_debug "Enforcing retention for $target_name: keeping $keep snapshots"

    # Get completed snapshots sorted newest first
    local snapshots; snapshots=$(list_remote_snapshots "$target_name")
    if [[ -z "$snapshots" ]]; then
        log_debug "No snapshots found for $target_name, nothing to prune"
        return 0
    fi

    local count=0
    local pruned=0
    while IFS= read -r snap; do
        [[ -z "$snap" ]] && continue
        ((count++)) || true
        if (( count > keep )); then
            # Skip pinned snapshots
            local is_pinned=false
            if _is_rclone_mode; then
                local meta; meta=$(rclone_cat "targets/${target_name}/snapshots/${snap}/meta.json" 2>/dev/null) || true
                if [[ -n "$meta" ]] && echo "$meta" | grep -q '"pinned":\s*true'; then
                    is_pinned=true
                fi
            elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
                local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
                local meta_file="$snap_dir/$snap/meta.json"
                if [[ -f "$meta_file" ]] && grep -q '"pinned":\s*true' "$meta_file" 2>/dev/null; then
                    is_pinned=true
                fi
            else
                local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
                local sq_meta; sq_meta="$(shquote "$snap_dir/$snap/meta.json")"
                local meta_content; meta_content=$(remote_exec "cat '${sq_meta}' 2>/dev/null" 2>/dev/null) || true
                if [[ -n "$meta_content" ]] && echo "$meta_content" | grep -q '"pinned":\s*true'; then
                    is_pinned=true
                fi
            fi

            if [[ "$is_pinned" == "true" ]]; then
                log_info "Skipping pinned snapshot for $target_name: $snap"
                continue
            fi

            log_info "Pruning old snapshot for $target_name: $snap"
            if _is_rclone_mode; then
                rclone_purge "targets/${target_name}/snapshots/${snap}" || {
                    log_warn "Failed to purge snapshot: $snap"
                }
            elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
                local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
                rm -rf "$snap_dir/$snap" || {
                    log_warn "Failed to prune snapshot: $snap_dir/$snap"
                }
            else
                local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
                local sq_snap_path; sq_snap_path="$(shquote "$snap_dir/$snap")"
                remote_exec "rm -rf '${sq_snap_path}'" || {
                    log_warn "Failed to prune snapshot: $snap_dir/$snap"
                }
            fi
            ((pruned++)) || true
        fi
    done <<< "$snapshots"

    if (( pruned > 0 )); then
        log_info "Pruned $pruned old snapshot(s) for $target_name"
    fi
}
