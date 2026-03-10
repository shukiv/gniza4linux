#!/usr/bin/env bash
# gniza4linux/lib/backup.sh — Backup orchestration per target

[[ -n "${_GNIZA4LINUX_BACKUP_LOADED:-}" ]] && return 0
_GNIZA4LINUX_BACKUP_LOADED=1

# Backup a single target to a remote.
# Usage: backup_target <target_name> [remote_name]
backup_target() {
    local target_name="$1"
    local remote_name="${2:-}"

    # 0. Per-target lock: prevent same target from running twice
    acquire_target_lock "$target_name" || {
        log_warn "Skipping target '$target_name': previous backup still running"
        return 2
    }

    # 1. Load and validate target
    load_target "$target_name" || {
        log_error "Failed to load target: $target_name"
        release_target_lock "$target_name"
        return 1
    }

    if [[ "${TARGET_ENABLED:-yes}" != "yes" ]]; then
        log_info "Target '$target_name' is disabled, skipping"
        release_target_lock "$target_name"
        return 0
    fi

    # 2. Determine which remote to use
    if [[ -z "$remote_name" ]]; then
        if [[ -n "${TARGET_REMOTE:-}" ]]; then
            remote_name="$TARGET_REMOTE"
        else
            remote_name=$(list_remotes | head -1)
        fi
    fi

    if [[ -z "$remote_name" ]]; then
        log_error "No remote specified and none configured"
        release_target_lock "$target_name"
        return 1
    fi

    # 3. Save/load remote context
    _save_remote_globals
    load_remote "$remote_name" || {
        log_error "Failed to load remote: $remote_name"
        _restore_remote_globals
        return 1
    }

    local rc=0
    _backup_target_impl "$target_name" "$remote_name" || rc=$?

    # 15. Restore remote globals
    _restore_remote_globals
    release_target_lock "$target_name"
    return "$rc"
}

# Internal implementation after remote context is loaded.
_backup_target_impl() {
    local target_name="$1"
    local remote_name="$2"

    # 4. Test remote connectivity
    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            test_ssh_connection || {
                log_error "Cannot connect to remote '$remote_name'"
                return 1
            }
            ;;
        local)
            if [[ ! -d "$REMOTE_BASE" ]]; then
                log_info "Creating local remote base directory: $REMOTE_BASE"
                mkdir -p "$REMOTE_BASE" || {
                    log_error "Failed to create remote base directory: $REMOTE_BASE"
                    return 1
                }
            fi
            ;;
        s3|gdrive)
            test_rclone_connection || {
                log_error "Cannot connect to remote '$remote_name' (${REMOTE_TYPE})"
                return 1
            }
            ;;
    esac

    # 4.5. Check remote disk space
    local threshold="${DISK_USAGE_THRESHOLD:-$DEFAULT_DISK_USAGE_THRESHOLD}"
    if [[ "$threshold" -gt 0 ]]; then
        check_remote_disk_space "$threshold" || {
            log_error "Remote '$remote_name' has insufficient disk space"
            return 1
        }
    fi

    local start_time; start_time=$(date +%s)

    # 5. Get timestamp
    local ts; ts=$(timestamp)

    # 5.5. Initialize snapshot logging
    snaplog_init

    # 6. Get previous snapshot for --link-dest
    local prev; prev=$(get_latest_snapshot "$target_name") || prev=""
    if [[ -n "$prev" ]]; then
        log_debug "Previous snapshot for $target_name: $prev"
    fi

    # 7. Clean partial snapshots
    clean_partial_snapshots "$target_name"

    # 8. Run pre-hook
    if [[ -n "${TARGET_PRE_HOOK:-}" ]]; then
        log_info "Running pre-hook for $target_name..."
        if ! bash -c "$TARGET_PRE_HOOK"; then
            log_error "Pre-hook failed for $target_name"
            snaplog_cleanup
            return 1
        fi
    fi

    # 8.5. Dump MySQL databases (if enabled)
    local mysql_dump_dir=""
    if [[ "${TARGET_MYSQL_ENABLED:-no}" == "yes" && "${TARGET_SOURCE_TYPE:-local}" != "s3" && "${TARGET_SOURCE_TYPE:-local}" != "gdrive" ]]; then
        log_info "Dumping MySQL databases for $target_name..."
        if mysql_dump_databases; then
            mysql_dump_grants || log_warn "Grants dump failed, continuing with database dumps"
            mysql_dump_dir="${MYSQL_DUMP_DIR:-}"
        else
            log_warn "MySQL dump failed for $target_name — continuing with file backup"
            mysql_cleanup_dump
        fi
    fi

    # 9. Transfer each folder
    local folder
    local transfer_failed=false
    local folder_index=0
    local staging_dir=""
    while IFS= read -r folder; do
        [[ -z "$folder" ]] && continue
        if (( folder_index > 0 )) && [[ "$threshold" -gt 0 ]]; then
            check_remote_disk_space "$threshold" || {
                log_error "Disk space threshold exceeded — aborting after $folder_index folder(s)"
                transfer_failed=true
                break
            }
        fi
        ((folder_index++)) || true
        if [[ "${TARGET_SOURCE_TYPE:-local}" != "local" ]]; then
            if [[ "${TARGET_SOURCE_TYPE}" == "ssh" && "${REMOTE_TYPE:-ssh}" == "ssh" ]]; then
                # Pipelined: direct SSH source -> SSH destination (no local staging)
                log_info "Pipelined transfer from ${TARGET_SOURCE_HOST}: $folder"
                if ! transfer_folder_pipelined "$target_name" "$folder" "$ts" "$prev"; then
                    log_error "Pipelined transfer failed for folder: $folder"
                    transfer_failed=true
                fi
            else
                # Two-hop: pull to local staging, then transfer
                staging_dir=$(mktemp -d "${WORK_DIR:-/tmp}/gniza-source-XXXXXX")
                log_info "Pulling from ${TARGET_SOURCE_TYPE} source: $folder"
                if ! pull_from_source "$folder" "$staging_dir/${folder#/}"; then
                    log_error "Source pull failed for: $folder"
                    rm -rf "$staging_dir"
                    transfer_failed=true
                    continue
                fi
                if ! transfer_folder "$target_name" "$staging_dir/${folder#/}" "$ts" "$prev" "${folder#/}"; then
                    log_error "Transfer failed for folder: $folder"
                    transfer_failed=true
                fi
                rm -rf "$staging_dir"
            fi
        else
            if ! transfer_folder "$target_name" "$folder" "$ts" "$prev"; then
                log_error "Transfer failed for folder: $folder"
                transfer_failed=true
            fi
        fi
    done < <(get_target_folders)

    # 9.5. Transfer MySQL dumps
    if [[ -n "$mysql_dump_dir" && -d "$mysql_dump_dir/_mysql" ]]; then
        if [[ "$transfer_failed" != "true" ]] && [[ "$threshold" -gt 0 ]]; then
            check_remote_disk_space "$threshold" || {
                log_error "Disk space threshold exceeded — aborting before MySQL dump transfer"
                transfer_failed=true
            }
        fi
        if [[ "$transfer_failed" != "true" ]]; then
            log_info "Transferring MySQL dumps for $target_name..."
            if ! transfer_folder "$target_name" "$mysql_dump_dir/_mysql" "$ts" "$prev" "_mysql"; then
                log_error "Transfer failed for MySQL dumps"
                transfer_failed=true
            fi
        fi
    fi

    # Cleanup MySQL temp dir
    mysql_cleanup_dump

    if [[ "$transfer_failed" == "true" ]]; then
        log_error "One or more folder transfers failed for $target_name"
        snaplog_generate "$target_name" "$remote_name" "$ts" "$start_time" "Failed"
        snaplog_upload "$target_name" "$ts"
        snaplog_cleanup
        return 1
    fi

    # 9.9. Generate snapshot logs
    snaplog_generate "$target_name" "$remote_name" "$ts" "$start_time" "Success"

    # 10. Generate meta.json
    local end_time; end_time=$(date +%s)
    local duration=$(( end_time - start_time ))
    local hostname; hostname=$(hostname -f)
    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
    local total_size=0

    local meta_json
    local esc_target; esc_target=$(printf '%s' "$target_name" | sed 's/["\]/\\&/g')
    local esc_hostname; esc_hostname=$(printf '%s' "$hostname" | sed 's/["\]/\\&/g')
    local esc_folders; esc_folders=$(printf '%s' "$TARGET_FOLDERS" | sed 's/["\]/\\&/g')
    local mysql_val; mysql_val=$([ "${TARGET_MYSQL_ENABLED:-no}" = "yes" ] && echo "true" || echo "false")
    meta_json=$(printf '{
  "target": "%s",
  "hostname": "%s",
  "timestamp": "%s",
  "duration": %d,
  "folders": "%s",
  "mysql_dumps": %s,
  "total_size": %d,
  "mode": "%s",
  "pinned": false
}' "$esc_target" "$esc_hostname" "$ts" "$duration" "$esc_folders" "$mysql_val" "$total_size" "${BACKUP_MODE:-$DEFAULT_BACKUP_MODE}")

    if _is_rclone_mode; then
        local meta_subpath="targets/${target_name}/snapshots/${ts}/meta.json"
        rclone_rcat "$meta_subpath" "$meta_json" || log_warn "Failed to write meta.json"
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        echo "$meta_json" > "$snap_dir/${ts}.partial/meta.json" || log_warn "Failed to write meta.json"
    else
        local sq_partial; sq_partial="$(shquote "$snap_dir/${ts}.partial")"
        echo "$meta_json" | remote_exec "cat > '${sq_partial}/meta.json'" || log_warn "Failed to write meta.json"
    fi

    # 11. Generate manifest.txt
    if _is_rclone_mode; then
        local manifest; manifest=$(rclone_list_files "targets/${target_name}/snapshots/${ts}" 2>/dev/null) || manifest=""
        if [[ -n "$manifest" ]]; then
            rclone_rcat "targets/${target_name}/snapshots/${ts}/manifest.txt" "$manifest" || log_warn "Failed to write manifest.txt"
        fi
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        find "$snap_dir/${ts}.partial" -type f 2>/dev/null > "$snap_dir/${ts}.partial/manifest.txt" || log_warn "Failed to write manifest.txt"
    else
        local sq_partial; sq_partial="$(shquote "$snap_dir/${ts}.partial")"
        remote_exec "find '${sq_partial}' -type f > '${sq_partial}/manifest.txt'" 2>/dev/null || log_warn "Failed to write manifest.txt"
    fi

    # 11.5. Upload snapshot logs
    snaplog_upload "$target_name" "$ts"

    # 12. Finalize snapshot
    if ! finalize_snapshot "$target_name" "$ts"; then
        log_error "Failed to finalize snapshot for $target_name"
        snaplog_cleanup
        return 1
    fi

    # Calculate total_size after finalization for accurate reporting
    if _is_rclone_mode; then
        local size_json; size_json=$(rclone_size "targets/${target_name}/snapshots/${ts}" 2>/dev/null) || true
        if [[ -n "$size_json" ]]; then
            total_size=$(echo "$size_json" | grep -oP '"bytes":\s*\K[0-9]+' || echo 0)
        fi
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        total_size=$(du -sb "$snap_dir/$ts" 2>/dev/null | cut -f1) || total_size=0
    else
        local sq_snap; sq_snap="$(shquote "$snap_dir/$ts")"
        total_size=$(remote_exec "du -sb '$sq_snap' 2>/dev/null | cut -f1" 2>/dev/null) || total_size=0
    fi

    log_info "Backup completed for $target_name: $ts ($(human_size "${total_size:-0}") in $(human_duration "$duration"))"

    # 13. Run post-hook
    if [[ -n "${TARGET_POST_HOOK:-}" ]]; then
        log_info "Running post-hook for $target_name..."
        bash -c "$TARGET_POST_HOOK" || log_warn "Post-hook failed for $target_name"
    fi

    # 14. Enforce retention
    enforce_retention "$target_name" "${SCHEDULE_RETENTION_COUNT:-}"

    snaplog_cleanup
    return 0
}

# Backup all enabled targets.
# Usage: backup_all_targets [remote_flag]
backup_all_targets() {
    local remote_flag="${1:-}"

    local targets; targets=$(list_targets)
    if [[ -z "$targets" ]]; then
        log_error "No targets configured"
        return 1
    fi

    # Resolve remotes
    local remotes=""
    remotes=$(get_target_remotes "$remote_flag") || {
        log_error "Invalid remote specification"
        return 1
    }

    local start_time; start_time=$(date +%s)
    local total=0 succeeded=0 failed=0
    local failed_targets=""

    while IFS= read -r target_name; do
        [[ -z "$target_name" ]] && continue

        load_target "$target_name" || { log_warn "Cannot load target: $target_name"; continue; }
        if [[ "${TARGET_ENABLED:-yes}" != "yes" ]]; then
            log_debug "Target '$target_name' is disabled, skipping"
            continue
        fi

        ((total++)) || true
        log_info "=== Backing up target: $target_name ($total) ==="

        local target_failed=false
        local target_skipped=false
        while IFS= read -r rname; do
            [[ -z "$rname" ]] && continue
            log_info "--- Transferring $target_name to remote '$rname' ---"
            local _brc=0
            backup_target "$target_name" "$rname" || _brc=$?
            if (( _brc == 2 )); then
                target_skipped=true
            elif (( _brc != 0 )); then
                log_error "Backup to remote '$rname' failed for $target_name"
                failed_targets+="  - $target_name ($rname: failed)"$'\n'
                target_failed=true
            fi
        done <<< "$remotes"

        if [[ "$target_failed" == "true" ]]; then
            ((failed++)) || true
        elif [[ "$target_skipped" == "true" ]]; then
            log_info "Target '$target_name' skipped: previous backup still running"
        else
            ((succeeded++)) || true
            log_info "Backup completed for $target_name (all remotes)"
        fi
    done <<< "$targets"

    local end_time; end_time=$(date +%s)
    local duration=$(( end_time - start_time ))

    # Print summary
    echo ""
    echo "============================================"
    echo "Backup Summary"
    echo "============================================"
    echo "Timestamp:   $(timestamp)"
    echo "Duration:    $(human_duration $duration)"
    echo "Destinations: $(echo "$remotes" | tr '\n' ' ')"
    echo "Total:       $total"
    echo "Succeeded:   ${C_GREEN}${succeeded}${C_RESET}"
    if (( failed > 0 )); then
        echo "Failed:      ${C_RED}${failed}${C_RESET}"
        echo ""
        echo "Failed sources:"
        echo "$failed_targets"
    else
        echo "Failed:      0"
    fi
    echo "============================================"

    if (( failed > 0 && succeeded > 0 )); then
        return "$EXIT_PARTIAL"
    elif (( failed > 0 )); then
        return 1
    fi
    return 0
}
