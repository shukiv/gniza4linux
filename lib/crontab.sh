#!/usr/bin/env bash
# gniza4linux/lib/crontab.sh — Crontab backup support

[[ -n "${_GNIZA4LINUX_CRONTAB_LOADED:-}" ]] && return 0
_GNIZA4LINUX_CRONTAB_LOADED=1

# Build SSH prefix for remote crontab operations.
# Sets _CRONTAB_SSH array. Returns 1 if local (no SSH needed).
_crontab_is_remote() {
    [[ "${TARGET_SOURCE_TYPE:-local}" == "ssh" ]] || return 1
    _CRONTAB_SSH=(ssh -o StrictHostKeyChecking=accept-new -o "ConnectTimeout=${SSH_TIMEOUT:-30}" -p "${TARGET_SOURCE_PORT:-22}")
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        _CRONTAB_SSH+=(-o BatchMode=yes)
        [[ -n "${TARGET_SOURCE_KEY:-}" ]] && _CRONTAB_SSH+=(-i "$TARGET_SOURCE_KEY")
    fi
    _CRONTAB_SSH+=("${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}")
    return 0
}

# Run a command locally or via SSH. For remote, prepends sudo when SOURCE_SUDO is yes.
# Usage: _crontab_run_cmd "crontab -l -u root"
_crontab_run_cmd() {
    local cmd_str="$1"
    if _crontab_is_remote; then
        if [[ "${TARGET_SOURCE_SUDO:-yes}" == "yes" ]]; then
            cmd_str="sudo $cmd_str"
        fi
        if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
            SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_CRONTAB_SSH[@]}" "$cmd_str"
        else
            "${_CRONTAB_SSH[@]}" "$cmd_str"
        fi
    else
        # SAFETY: All interpolated values in $cmd_str are escaped via printf '%q'
        # in the calling functions (crontab_dump_all). Usernames are validated
        # against ^[a-zA-Z0-9._-]+$ and filenames against the same pattern
        # before interpolation. Do not pass unescaped user input.
        eval "$cmd_str"
    fi
}

# Dump all crontabs to a temp directory.
# Sets CRONTAB_DUMP_DIR global to the temp directory path containing _crontab/ subdir.
# Returns 0 on success, 1 on failure.
crontab_dump_all() {
    # Create temp directory (always local)
    CRONTAB_DUMP_DIR=$(mktemp -d "${WORK_DIR}/gniza-crontab-XXXXXX")
    mkdir -p "$CRONTAB_DUMP_DIR/_crontab"

    local failed=false

    # Dump per-user crontabs
    local -a users
    IFS=',' read -ra users <<< "${TARGET_CRONTAB_USERS:-root}"
    local user
    for user in "${users[@]}"; do
        user="${user#"${user%%[![:space:]]*}"}"
        user="${user%"${user##*[![:space:]]}"}"
        [[ -z "$user" ]] && continue

        # Validate username to prevent injection
        if [[ ! "$user" =~ ^[a-zA-Z0-9._-]+$ ]]; then
            log_error "Invalid crontab username, skipping: $user"
            failed=true
            continue
        fi

        log_info "Dumping crontab for user: $user"
        local outfile="$CRONTAB_DUMP_DIR/_crontab/${user}.crontab"
        local output
        output=$(_crontab_run_cmd "crontab -l -u $(printf '%q' "$user")" 2>&1)
        local rc=$?
        if (( rc == 0 )); then
            echo "$output" > "$outfile"
            log_debug "Dumped crontab for $user -> ${user}.crontab"
        elif (( rc == 1 )); then
            # Exit code 1 = no crontab for this user — skip gracefully
            log_debug "No crontab for user $user — skipping"
        else
            log_error "Failed to dump crontab for user: $user"
            failed=true
        fi
    done

    # Dump /etc/crontab
    log_info "Dumping /etc/crontab"
    local etc_crontab
    etc_crontab=$(_crontab_run_cmd "cat /etc/crontab" 2>&1)
    if (( $? == 0 )); then
        echo "$etc_crontab" > "$CRONTAB_DUMP_DIR/_crontab/etc-crontab"
        log_debug "Dumped /etc/crontab -> etc-crontab"
    else
        log_warn "Failed to read /etc/crontab — skipping"
    fi

    # Dump /etc/cron.d/ contents
    log_info "Dumping /etc/cron.d/ files"
    local cron_d_list
    cron_d_list=$(_crontab_run_cmd "ls -1 /etc/cron.d/ 2>/dev/null" 2>&1) || true
    if [[ -n "$cron_d_list" ]]; then
        while IFS= read -r cron_file; do
            cron_file="${cron_file#"${cron_file%%[![:space:]]*}"}"
            cron_file="${cron_file%"${cron_file##*[![:space:]]}"}"
            [[ -z "$cron_file" ]] && continue
            # Validate filename
            if [[ ! "$cron_file" =~ ^[a-zA-Z0-9._-]+$ ]]; then
                log_debug "Skipping unusual cron.d filename: $cron_file"
                continue
            fi
            local content
            content=$(_crontab_run_cmd "cat /etc/cron.d/$(printf '%q' "$cron_file")" 2>&1)
            if (( $? == 0 )); then
                echo "$content" > "$CRONTAB_DUMP_DIR/_crontab/cron.d-${cron_file}"
                log_debug "Dumped /etc/cron.d/$cron_file -> cron.d-${cron_file}"
            else
                log_debug "Failed to read /etc/cron.d/$cron_file — skipping"
            fi
        done <<< "$cron_d_list"
    fi

    if [[ "$failed" == "true" ]]; then
        log_error "One or more crontab dumps failed"
        return 1
    fi

    log_info "Crontab dumps completed in $CRONTAB_DUMP_DIR/_crontab/"
    return 0
}

# Restore crontabs — log that files are available for manual restore.
# Auto-installing with 'crontab -u' would overwrite existing crontabs.
crontab_restore_all() {
    local crontab_dir="$1"
    log_info "Crontab files restored to: $crontab_dir"
    log_info "To manually restore a user crontab: crontab -u <user> <file>.crontab"
    log_info "System files (etc-crontab, cron.d-*) can be manually copied to /etc/"
    return 0
}

# Clean up the temporary crontab dump directory.
crontab_cleanup_dump() {
    if [[ -n "${CRONTAB_DUMP_DIR:-}" && -d "$CRONTAB_DUMP_DIR" ]]; then
        rm -rf "$CRONTAB_DUMP_DIR"
        log_debug "Cleaned up crontab dump dir: $CRONTAB_DUMP_DIR"
        CRONTAB_DUMP_DIR=""
    fi
}
