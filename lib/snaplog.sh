#!/usr/bin/env bash
# gniza4linux/lib/snaplog.sh — Per-snapshot backup logs (dirvish-style)

[[ -n "${_GNIZA4LINUX_SNAPLOG_LOADED:-}" ]] && return 0
_GNIZA4LINUX_SNAPLOG_LOADED=1

# Tee helper: filters rsync output, sending progress to a separate file
# and non-progress lines to stderr (which flows to LOG_FILE or job log).
# Usage: rsync ... 2>&1 | _snaplog_tee
# Per-file details go to _TRANSFER_LOG via rsync --log-file.
# Progress lines go to a small .progress file (for the TUI/web progress bar).
# Everything else (stats, errors) goes to stderr.
_snaplog_tee() {
    # With --log-file, rsync writes per-file details directly to _TRANSFER_LOG.
    # Stdout only has --info=progress2 lines and stats/errors.
    # Progress lines go to a small .progress file (for the TUI/web progress bar).
    # Everything else (stats, errors) goes to stderr → LOG_FILE / job log.
    local progress_file="${WORK_DIR}/gniza-progress-${GNIZA_JOB_ID:-$$}.txt"
    local buf=""
    # Read character-by-character to handle \r (rsync --info=progress2) and \n
    while IFS= read -r -d '' -n 1 ch || [[ -n "$buf" ]]; do
        if [[ "$ch" == $'\n' || "$ch" == $'\r' || -z "$ch" ]]; then
            if [[ -n "$buf" ]]; then
                if [[ "$buf" =~ [0-9]+% ]] && [[ "$buf" == *xfr#* || "$buf" == *to-chk=* || "$buf" == *B/s* ]]; then
                    printf '%s\n' "$buf" > "$progress_file"
                else
                    echo "$buf" >&2
                    # Also append non-progress output to transfer log for ssh→ssh
                    # (which uses --verbose instead of --log-file)
                    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                        echo "$buf" >> "$_TRANSFER_LOG"
                    fi
                fi
                buf=""
            fi
            [[ -z "$ch" ]] && break
        else
            buf+="$ch"
        fi
    done
    # Don't delete progress file here — snaplog_cleanup handles it
}

# Initialize snapshot log directory and transfer log file.
snaplog_init() {
    _SNAP_LOG_DIR=$(mktemp -d "${WORK_DIR}/gniza-snaplog-XXXXXX")
    _TRANSFER_LOG="$_SNAP_LOG_DIR/rsync_raw.log"
    touch "$_TRANSFER_LOG"
    # Write transfer log path so web/TUI can find it for this job
    if [[ -n "${GNIZA_JOB_ID:-}" ]]; then
        printf '%s\n' "$_TRANSFER_LOG" > "${WORK_DIR}/gniza-transferlog-${GNIZA_JOB_ID}.txt"
    fi
}

# Generate snapshot log files (log, rsync_error, summary).
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

    # Extract rsync commands from the transfer log
    local rsync_cmds=""
    rsync_cmds=$(grep -oP '(?<=CMD: ).*' "$_TRANSFER_LOG" 2>/dev/null || true)
    if [[ -z "$rsync_cmds" ]]; then
        rsync_cmds=$(grep '^=== rsync' "$_TRANSFER_LOG" 2>/dev/null | sed 's/^=== //;s/ ===$//' || true)
    fi

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

    if [[ -n "$rsync_cmds" ]]; then
        {
            echo ""
            echo "== rsync commands =="
            echo "$rsync_cmds"
        } >> "$_SNAP_LOG_DIR/summary"
    fi

}

# Upload snapshot logs to the remote.
# Usage: snaplog_upload <target> <ts>
snaplog_upload() {
    local target="$1"
    local ts="$2"

    if _is_rclone_mode; then
        local snap_subpath="targets/${target}/snapshots/${ts}"
        for f in log rsync_error summary; do
            local remote_dest; remote_dest=$(_rclone_remote_path "${snap_subpath}/${f}")
            _rclone_cmd copyto "$_SNAP_LOG_DIR/$f" "$remote_dest" || log_warn "Failed to upload $f"
        done
    elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        local snap_dir; snap_dir=$(get_snapshot_dir "$target")
        cp "$_SNAP_LOG_DIR"/{log,rsync_error,summary} "$snap_dir/${ts}.partial/" || log_warn "Failed to copy snapshot logs"
    else
        local snap_dir; snap_dir=$(get_snapshot_dir "$target")
        local rsync_ssh; rsync_ssh=$(build_rsync_ssh_cmd)
        local rsync_cmd=(rsync -e "$rsync_ssh" "$_SNAP_LOG_DIR/log" "$_SNAP_LOG_DIR/rsync_error" "$_SNAP_LOG_DIR/summary" "${REMOTE_USER}@${REMOTE_HOST}:${snap_dir}/${ts}.partial/")
        if _is_password_mode; then
            export SSHPASS="$REMOTE_PASSWORD"
            rsync_cmd=(sshpass -e "${rsync_cmd[@]}")
        fi
        "${rsync_cmd[@]}" || log_warn "Failed to upload snapshot logs"
    fi
}

# Append transferred file list from rsync --log-file to the job log.
# This preserves the per-file details in the permanent log (visible in Logs page).
# When GNIZA_DAEMON_TRACKED=1, LOG_FILE is empty but stdout goes to the job log.
_snaplog_append_transfer_log() {
    [[ -z "${_TRANSFER_LOG:-}" || ! -s "$_TRANSFER_LOG" ]] && return 0
    # Count transferred files from rsync log format:
    # "2026/03/09 05:03:07 [719348] <f+++++++++ path/to/file"
    local count=0
    while IFS= read -r line; do
        if [[ "$line" =~ \[([0-9]+)\]\ [\<\>][fd][[:alnum:].+]+\ (.+) ]]; then
            (( count++ ))
        fi
    done < "$_TRANSFER_LOG"
    # Append full transfer log content (timestamps, change indicators, separators)
    local output
    output=$(printf '\n=== Transfer details (%d files) ===\n' "$count"; cat "$_TRANSFER_LOG"; echo "=== End transfer details ===")
    if [[ -n "${LOG_FILE:-}" ]]; then
        echo "$output" >> "$LOG_FILE"
    else
        # Daemon-tracked: stdout is redirected to the job log file
        echo "$output"
    fi
}

# Remove stale temp files from WORK_DIR left by crashed/killed backups.
# Removes gniza-snaplog-*, gniza-source-*, gniza-mysql-*, gniza-pgsql-*,
# gniza-progress-*, gniza-transferlog-* older than 24 hours.
workdir_cleanup_stale() {
    local wd="${WORK_DIR:-/tmp}"
    [[ -d "$wd" ]] || return 0
    find "$wd" -maxdepth 1 -name 'gniza-snaplog-*' -mmin +1440 -exec rm -rf {} + 2>/dev/null || true
    find "$wd" -maxdepth 1 -name 'gniza-source-*' -mmin +1440 -exec rm -rf {} + 2>/dev/null || true
    find "$wd" -maxdepth 1 -name 'gniza-mysql-*' -mmin +1440 -exec rm -rf {} + 2>/dev/null || true
    find "$wd" -maxdepth 1 -name 'gniza-pgsql-*' -mmin +1440 -exec rm -rf {} + 2>/dev/null || true
    find "$wd" -maxdepth 1 -name 'gniza-progress-*.txt' -mmin +1440 -delete 2>/dev/null || true
    find "$wd" -maxdepth 1 -name 'gniza-transferlog-*.txt' -mmin +1440 -delete 2>/dev/null || true
}

# Clean up temporary snapshot log directory.
snaplog_cleanup() {
    _snaplog_append_transfer_log
    [[ -n "${_SNAP_LOG_DIR:-}" && -d "$_SNAP_LOG_DIR" ]] && rm -rf "$_SNAP_LOG_DIR"
    if [[ -n "${GNIZA_JOB_ID:-}" ]]; then
        rm -f "${WORK_DIR}/gniza-transferlog-${GNIZA_JOB_ID}.txt" 2>/dev/null
        rm -f "${WORK_DIR}/gniza-progress-${GNIZA_JOB_ID}.txt" 2>/dev/null
    fi
    _SNAP_LOG_DIR=""
    _TRANSFER_LOG=""
}
