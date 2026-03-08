#!/usr/bin/env bash
# gniza4linux/lib/snaplog.sh — Per-snapshot backup logs (dirvish-style)

[[ -n "${_GNIZA4LINUX_SNAPLOG_LOADED:-}" ]] && return 0
_GNIZA4LINUX_SNAPLOG_LOADED=1

# Tee helper: copies stdin to the transfer log, app log, and stderr (TUI).
# Used as process substitution target: cmd > >(_snaplog_tee) 2>&1
# The raw transfer log gets everything; LOG_FILE only gets structured
# log lines — skips rsync progress percentages and verbose file listings
# to keep the app log small and readable.
_snaplog_tee() {
    # With --log-file, rsync writes per-file details directly to _TRANSFER_LOG.
    # Stdout only has --info=progress2 lines and stats.
    # Everything goes to stderr (→ LOG_FILE) so the progress bar can read it.
    # Progress lines are stripped from LOG_FILE after the job finishes
    # (see _gniza_strip_progress_lines).
    cat >&2
}

# Initialize snapshot log directory and transfer log file.
snaplog_init() {
    _SNAP_LOG_DIR=$(mktemp -d "${WORK_DIR}/gniza-snaplog-XXXXXX")
    _TRANSFER_LOG="$_SNAP_LOG_DIR/rsync_raw.log"
    touch "$_TRANSFER_LOG"
}

# Generate snapshot log files (log, rsync_error, summary, index).
# Usage: snaplog_generate <target> <remote> <ts> <start_time> <status>
snaplog_generate() {
    local target="$1"
    local remote="$2"
    local ts="$3"
    local start_time="$4"
    local status="$5"

    # Copy raw transfer log
    cp "$_TRANSFER_LOG" "$_SNAP_LOG_DIR/log"

    # Extract errors/warnings
    grep -iE '(error|warning|failed|cannot|denied|vanished|rsync:)' "$_TRANSFER_LOG" > "$_SNAP_LOG_DIR/rsync_error" || true

    # Generate summary
    local end_time; end_time=$(date +%s)
    local duration=$(( end_time - start_time ))
    local start_fmt; start_fmt=$(date -u -d "@$start_time" "+%Y-%m-%d %H:%M:%S UTC")
    local end_fmt; end_fmt=$(date -u -d "@$end_time" "+%Y-%m-%d %H:%M:%S UTC")
    local mysql_flag="no"
    [[ "${TARGET_MYSQL_ENABLED:-no}" == "yes" ]] && mysql_flag="yes"

    cat > "$_SNAP_LOG_DIR/summary" <<EOF
== gniza backup summary ==
Target:     ${target}
Remote:     ${remote}
Hostname:   $(hostname -f)
Timestamp:  ${ts}
Started:    ${start_fmt}
Finished:   ${end_fmt}
Duration:   $(human_duration "$duration")
Status:     ${status}
Folders:    ${TARGET_FOLDERS}
MySQL:      ${mysql_flag}
EOF

    # Generate index
    snaplog_generate_index "$target" "$ts"
}

# Generate file index for the snapshot.
# Usage: snaplog_generate_index <target> <ts>
snaplog_generate_index() {
    local target="$1"
    local ts="$2"

    if _is_rclone_mode; then
        _rclone_cmd lsl "$(_rclone_remote_path "targets/${target}/snapshots/${ts}")" 2>/dev/null > "$_SNAP_LOG_DIR/index" || true
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target")
        find "$snap_dir/${ts}.partial" -printf '%M %n %u %g %8s %T+ %P\n' 2>/dev/null | sort > "$_SNAP_LOG_DIR/index"
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target")
        remote_exec "find '$(shquote "$snap_dir/${ts}.partial")' -printf '%M %n %u %g %8s %T+ %P\n' 2>/dev/null | sort" > "$_SNAP_LOG_DIR/index"
    fi
}

# Upload snapshot logs to the remote.
# Usage: snaplog_upload <target> <ts>
snaplog_upload() {
    local target="$1"
    local ts="$2"

    if _is_rclone_mode; then
        local snap_subpath="targets/${target}/snapshots/${ts}"
        for f in log rsync_error summary index; do
            local remote_dest; remote_dest=$(_rclone_remote_path "${snap_subpath}/${f}")
            _rclone_cmd copyto "$_SNAP_LOG_DIR/$f" "$remote_dest" || log_warn "Failed to upload $f"
        done
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target")
        cp "$_SNAP_LOG_DIR"/{log,rsync_error,summary,index} "$snap_dir/${ts}.partial/" || log_warn "Failed to copy snapshot logs"
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target")
        local rsync_ssh; rsync_ssh=$(build_rsync_ssh_cmd)
        local rsync_cmd=(rsync -e "$rsync_ssh" "$_SNAP_LOG_DIR/log" "$_SNAP_LOG_DIR/rsync_error" "$_SNAP_LOG_DIR/summary" "$_SNAP_LOG_DIR/index" "${REMOTE_USER}@${REMOTE_HOST}:${snap_dir}/${ts}.partial/")
        if _is_password_mode; then
            export SSHPASS="$REMOTE_PASSWORD"
            rsync_cmd=(sshpass -e "${rsync_cmd[@]}")
        fi
        "${rsync_cmd[@]}" || log_warn "Failed to upload snapshot logs"
    fi
}

# Clean up temporary snapshot log directory.
snaplog_cleanup() {
    [[ -n "${_SNAP_LOG_DIR:-}" && -d "$_SNAP_LOG_DIR" ]] && rm -rf "$_SNAP_LOG_DIR"
    _SNAP_LOG_DIR=""
    _TRANSFER_LOG=""
}
