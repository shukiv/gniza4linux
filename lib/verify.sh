#!/usr/bin/env bash
# gniza4linux/lib/verify.sh — Remote backup integrity checks

[[ -n "${_GNIZA4LINUX_VERIFY_LOADED:-}" ]] && return 0
_GNIZA4LINUX_VERIFY_LOADED=1

verify_target_backup() {
    local target_name="$1"
    local snapshot_ts="${2:-}"
    local errors=0

    # Resolve timestamp
    local ts; ts=$(resolve_snapshot_timestamp "$target_name" "$snapshot_ts") || return 1

    log_info "Verifying backup for $target_name (snapshot: $ts)..."

    if _is_rclone_mode; then
        local snap_subpath="targets/${target_name}/snapshots/${ts}"

        # Check .complete marker
        if ! rclone_exists "${snap_subpath}/.complete"; then
            log_error "Snapshot missing .complete marker: $snap_subpath"
            return 1
        fi

        # Check meta.json
        local meta; meta=$(rclone_cat "${snap_subpath}/meta.json" 2>/dev/null) || true
        if [[ -z "$meta" ]]; then
            log_warn "meta.json not found in snapshot"
            ((errors++)) || true
        else
            log_info "  meta.json: present"
        fi

        # Check manifest.txt
        if rclone_exists "${snap_subpath}/manifest.txt"; then
            log_info "  manifest.txt: present"
        else
            log_warn "  manifest.txt: missing"
            ((errors++)) || true
        fi

        # Count files
        local file_list; file_list=$(rclone_list_files "$snap_subpath" 2>/dev/null) || true
        local file_count=0
        [[ -n "$file_list" ]] && file_count=$(echo "$file_list" | wc -l)
        if (( file_count == 0 )); then
            log_warn "No files found in snapshot"
            ((errors++)) || true
        else
            log_info "  files: $file_count file(s)"
        fi

        # Report size
        local size_json; size_json=$(rclone_size "$snap_subpath" 2>/dev/null) || true
        local bytes=0
        if [[ -n "$size_json" ]]; then
            bytes=$(echo "$size_json" | grep -oP '"bytes":\s*\K[0-9]+' || echo 0)
        fi
        log_info "  size: $(human_size "$bytes")"

        # Check latest.txt
        local latest; latest=$(rclone_cat "targets/${target_name}/snapshots/latest.txt" 2>/dev/null) || true
        if [[ -n "$latest" ]]; then
            log_info "  latest -> $latest"
        else
            log_warn "  latest.txt not set"
        fi
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
        local snap_path="$snap_dir/$ts"

        if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
            # Check snapshot directory exists
            if [[ ! -d "$snap_path" ]]; then
                log_error "Snapshot directory not found: $snap_path"
                return 1
            fi

            # Check meta.json
            if [[ -f "$snap_path/meta.json" ]]; then
                log_info "  meta.json: present"
            else
                log_warn "  meta.json: missing"
                ((errors++)) || true
            fi

            # Check manifest.txt
            if [[ -f "$snap_path/manifest.txt" ]]; then
                log_info "  manifest.txt: present"
            else
                log_warn "  manifest.txt: missing"
                ((errors++)) || true
            fi

            # Count files
            local file_count; file_count=$(find "$snap_path" -type f 2>/dev/null | wc -l)
            if (( file_count == 0 )); then
                log_warn "No files found in snapshot"
                ((errors++)) || true
            else
                log_info "  files: $file_count file(s)"
            fi

            # Report size
            local total_size; total_size=$(du -sb "$snap_path" 2>/dev/null | cut -f1) || total_size=0
            log_info "  size: $(human_size "${total_size:-0}")"

            # Check latest symlink
            local base; base=$(get_remote_target_base "$target_name")
            if [[ -L "$base/latest" ]]; then
                local latest_target; latest_target=$(readlink "$base/latest" 2>/dev/null)
                log_info "  latest -> $(basename "$latest_target")"
            else
                log_warn "  latest symlink not set"
            fi
        else
            # SSH remote
            if ! remote_exec "test -d '$snap_path'" 2>/dev/null; then
                log_error "Snapshot directory not found: $snap_path"
                return 1
            fi

            # Check meta.json
            if remote_exec "test -f '$snap_path/meta.json'" 2>/dev/null; then
                log_info "  meta.json: present"
            else
                log_warn "  meta.json: missing"
                ((errors++)) || true
            fi

            # Check manifest.txt
            if remote_exec "test -f '$snap_path/manifest.txt'" 2>/dev/null; then
                log_info "  manifest.txt: present"
            else
                log_warn "  manifest.txt: missing"
                ((errors++)) || true
            fi

            # Count files
            local file_count; file_count=$(remote_exec "find '$snap_path' -type f | wc -l" 2>/dev/null)
            if [[ "${file_count:-0}" -eq 0 ]]; then
                log_warn "No files found in snapshot"
                ((errors++)) || true
            else
                log_info "  files: $file_count file(s)"
            fi

            # Report size
            local total_size; total_size=$(remote_exec "du -sb '$snap_path' | cut -f1" 2>/dev/null)
            log_info "  size: $(human_size "${total_size:-0}")"

            # Check latest symlink
            local base; base=$(get_remote_target_base "$target_name")
            local latest_target; latest_target=$(remote_exec "readlink '$base/latest' 2>/dev/null" 2>/dev/null)
            if [[ -n "$latest_target" ]]; then
                log_info "  latest -> $(basename "$latest_target")"
            else
                log_warn "  latest symlink not set"
            fi
        fi
    fi

    if (( errors > 0 )); then
        log_error "Verification found $errors issue(s) for $target_name"
        return 1
    fi

    log_info "Verification passed for $target_name"
    return 0
}

verify_all_targets() {
    local targets; targets=$(list_remote_targets)
    local total=0 passed=0 failed=0

    if [[ -z "$targets" ]]; then
        log_warn "No remote targets found to verify"
        return 0
    fi

    while IFS= read -r target_name; do
        [[ -z "$target_name" ]] && continue
        ((total++)) || true
        if verify_target_backup "$target_name"; then
            ((passed++)) || true
        else
            ((failed++)) || true
        fi
    done <<< "$targets"

    echo ""
    log_info "Verification complete: $passed/$total passed, $failed failed"
    (( failed > 0 )) && return 1
    return 0
}
