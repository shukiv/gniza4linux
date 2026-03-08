#!/usr/bin/env bash
# gniza4linux/lib/transfer.sh — rsync --link-dest to remote, .partial atomicity, retries

[[ -n "${_GNIZA4LINUX_TRANSFER_LOADED:-}" ]] && return 0
_GNIZA4LINUX_TRANSFER_LOADED=1

_check_disk_space_or_abort() {
    local threshold="${DISK_USAGE_THRESHOLD:-${DEFAULT_DISK_USAGE_THRESHOLD:-95}}"
    if [[ "$threshold" -gt 0 ]]; then
        check_remote_disk_space "$threshold" || {
            log_error "Disk space threshold exceeded during transfer — aborting backup"
            return 1
        }
    fi
    return 0
}

rsync_to_remote() {
    local source_dir="$1"
    local remote_dest="$2"
    local link_dest="${3:-}"
    shift 3 || true
    # Remaining args are extra rsync options (e.g. --exclude, --include)
    local -a extra_filter_opts=("$@")
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local rsync_ssh; rsync_ssh=$(build_rsync_ssh_cmd)

    local rsync_opts=(-aHAX --numeric-ids --delete --sparse --rsync-path="rsync --fake-super")

    if [[ -n "$link_dest" ]]; then
        rsync_opts+=(--link-dest="$link_dest")
    fi

    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        rsync_opts+=(--bwlimit="$BWLIMIT")
    fi

    if [[ "${RSYNC_COMPRESS:-no}" == "yes" ]]; then
        rsync_opts+=(-z)
    fi

    if [[ -n "${RSYNC_EXTRA_OPTS:-}" ]]; then
        # shellcheck disable=SC2206
        rsync_opts+=($RSYNC_EXTRA_OPTS)
    fi

    # Append include/exclude filters
    if [[ ${#extra_filter_opts[@]} -gt 0 ]]; then
        rsync_opts+=("${extra_filter_opts[@]}")
    fi

    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
        rsync_opts+=(--verbose --stats)
    fi

    # Overall progress for TUI progress bar
    rsync_opts+=(--info=progress2 --no-inc-recursive)

    rsync_opts+=(-e "$rsync_ssh")

    # Ensure source ends with /
    [[ "$source_dir" != */ ]] && source_dir="$source_dir/"

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rsync attempt $attempt/$max_retries: $source_dir -> $remote_dest"

        log_debug "CMD: rsync ${rsync_opts[*]} $source_dir ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}"
        local rsync_cmd=(rsync "${rsync_opts[@]}" "$source_dir" "${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}")
        if _is_password_mode; then
            export SSHPASS="$REMOTE_PASSWORD"
            rsync_cmd=(sshpass -e "${rsync_cmd[@]}")
        fi
        local rc=0
        if [[ -n "${_TRANSFER_LOG:-}" ]]; then
            echo "=== rsync: $source_dir -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest} ===" >> "$_TRANSFER_LOG"
            "${rsync_cmd[@]}" > >(_snaplog_tee) 2>&1 || rc=$?
        else
            "${rsync_cmd[@]}" || rc=$?
        fi
        if (( rc == 0 )); then
            log_debug "rsync succeeded on attempt $attempt"
            return 0
        fi

        # Exit 23 = partial transfer (some files failed)
        # Exit 24 = vanished source files (deleted during transfer)
        if (( rc == 23 )); then
            log_warn "rsync partial transfer (exit 23): retrying to pick up failed files..."
            sleep 2
            local rc2=0
            if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                echo "=== rsync (retry): $source_dir -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest} ===" >> "$_TRANSFER_LOG"
                "${rsync_cmd[@]}" > >(_snaplog_tee) 2>&1 || rc2=$?
            else
                "${rsync_cmd[@]}" || rc2=$?
            fi
            if (( rc2 == 0 )); then
                log_info "rsync retry succeeded — all files transferred"
                return 0
            fi
            log_warn "rsync retry completed (exit $rc2): some files could not be transferred"
            return 0
        fi
        if (( rc == 24 )); then
            log_warn "rsync completed with warnings (exit $rc): vanished source files"
            return 0
        fi

        log_warn "rsync failed (exit $rc), attempt $attempt/$max_retries"
        _check_disk_space_or_abort || return 1

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rsync failed after $max_retries attempts"
    return 1
}

# rsync locally (no SSH), with --link-dest support.
# Used for REMOTE_TYPE=local remotes (USB, NFS mount, etc.).
rsync_local() {
    local source_dir="$1"
    local local_dest="$2"
    local link_dest="${3:-}"
    shift 3 || true
    # Remaining args are extra rsync options (e.g. --exclude, --include)
    local -a extra_filter_opts=("$@")
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"

    local rsync_opts=(-aHAX --numeric-ids --delete --sparse)

    if [[ -n "$link_dest" ]]; then
        rsync_opts+=(--link-dest="$link_dest")
    fi

    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        rsync_opts+=(--bwlimit="$BWLIMIT")
    fi

    if [[ -n "${RSYNC_EXTRA_OPTS:-}" ]]; then
        # shellcheck disable=SC2206
        rsync_opts+=($RSYNC_EXTRA_OPTS)
    fi

    # Append include/exclude filters
    if [[ ${#extra_filter_opts[@]} -gt 0 ]]; then
        rsync_opts+=("${extra_filter_opts[@]}")
    fi

    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
        rsync_opts+=(--verbose --stats)
    fi

    # Overall progress for TUI progress bar
    rsync_opts+=(--info=progress2 --no-inc-recursive)

    # Ensure source ends with /
    [[ "$source_dir" != */ ]] && source_dir="$source_dir/"

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rsync (local) attempt $attempt/$max_retries: $source_dir -> $local_dest"

        local rc=0
        if [[ -n "${_TRANSFER_LOG:-}" ]]; then
            echo "=== rsync (local): $source_dir -> $local_dest ===" >> "$_TRANSFER_LOG"
            rsync "${rsync_opts[@]}" "$source_dir" "$local_dest" > >(_snaplog_tee) 2>&1 || rc=$?
        else
            rsync "${rsync_opts[@]}" "$source_dir" "$local_dest" || rc=$?
        fi
        if (( rc == 0 )); then
            log_debug "rsync (local) succeeded on attempt $attempt"
            return 0
        fi

        if (( rc == 23 )); then
            log_warn "rsync (local) partial transfer (exit 23): retrying to pick up failed files..."
            sleep 2
            local rc2=0
            if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                echo "=== rsync (local retry): $source_dir -> $local_dest ===" >> "$_TRANSFER_LOG"
                rsync "${rsync_opts[@]}" "$source_dir" "$local_dest" > >(_snaplog_tee) 2>&1 || rc2=$?
            else
                rsync "${rsync_opts[@]}" "$source_dir" "$local_dest" || rc2=$?
            fi
            if (( rc2 == 0 )); then
                log_info "rsync (local) retry succeeded — all files transferred"
                return 0
            fi
            log_warn "rsync (local) retry completed (exit $rc2): some files could not be transferred"
            return 0
        fi
        if (( rc == 24 )); then
            log_warn "rsync (local) completed with warnings (exit $rc): vanished source files"
            return 0
        fi

        log_warn "rsync (local) failed (exit $rc), attempt $attempt/$max_retries"
        _check_disk_space_or_abort || return 1

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rsync (local) failed after $max_retries attempts"
    return 1
}

# Pipelined SSH→SSH rsync: SSH into the destination and run rsync there,
# pulling directly from the SSH source.  Data flows source→destination
# without touching local disk.
# Usage: rsync_ssh_to_ssh <source_path> <remote_dest> <link_dest> [extra_filter_opts...]
rsync_ssh_to_ssh() {
    local source_path="$1"
    local remote_dest="$2"
    local link_dest="${3:-}"
    shift 3 || true
    local -a extra_filter_opts=("$@")
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local _added_key=""

    # --- Build the rsync command string to run ON the destination ---
    # --fake-super on source side (rsync-path) AND locally on dest (--fake-super flag)
    local -a ropts=(-aHAX --numeric-ids --delete --sparse --fake-super)
    ropts+=(--rsync-path="rsync --fake-super")

    if [[ -n "$link_dest" ]]; then
        ropts+=(--link-dest="$link_dest")
    fi

    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        ropts+=(--bwlimit="$BWLIMIT")
    fi

    if [[ "${RSYNC_COMPRESS:-no}" == "yes" ]]; then
        ropts+=(-z)
    fi

    if [[ -n "${RSYNC_EXTRA_OPTS:-}" ]]; then
        # shellcheck disable=SC2206
        ropts+=($RSYNC_EXTRA_OPTS)
    fi

    if [[ ${#extra_filter_opts[@]} -gt 0 ]]; then
        ropts+=("${extra_filter_opts[@]}")
    fi

    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
        ropts+=(--verbose --stats)
    fi

    ropts+=(--info=progress2 --no-inc-recursive)

    # Build the SSH command the remote rsync will use to reach the source
    local src_ssh_e="ssh"
    src_ssh_e+=" -p ${TARGET_SOURCE_PORT:-22}"
    src_ssh_e+=" -o StrictHostKeyChecking=accept-new"
    src_ssh_e+=" -o ConnectTimeout=${SSH_TIMEOUT:-${DEFAULT_SSH_TIMEOUT:-30}}"
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" != "password" ]]; then
        src_ssh_e+=" -o BatchMode=yes"
    fi

    # Ensure source_path ends with /
    [[ "$source_path" != */ ]] && source_path="$source_path/"

    local source_spec="${TARGET_SOURCE_USER:-root}@${TARGET_SOURCE_HOST}:${source_path}"

    # Assemble the remote command string with safe quoting
    local remote_cmd="rsync"
    for opt in "${ropts[@]}"; do
        remote_cmd+=" $(printf '%q' "$opt")"
    done
    remote_cmd+=" -e $(printf '%q' "$src_ssh_e")"
    remote_cmd+=" $(printf '%q' "$source_spec") $(printf '%q' "$remote_dest")"

    # Source password auth: write password to a temp file on destination,
    # use sshpass -f to read it, then clean up
    local _src_is_password=false
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
        _src_is_password=true
        local _pw_escaped; _pw_escaped=$(printf '%q' "$TARGET_SOURCE_PASSWORD")
        remote_cmd="_GNIZA_PW=\$(mktemp /tmp/.gniza-pw-XXXXXX) && chmod 600 \"\$_GNIZA_PW\" && printf '%s' ${_pw_escaped} > \"\$_GNIZA_PW\" && sshpass -f \"\$_GNIZA_PW\" ${remote_cmd}; _rc=\$?; rm -f \"\$_GNIZA_PW\"; exit \$_rc"
    fi

    # Source key auth: add key to local agent for forwarding, track for cleanup
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" && -n "${TARGET_SOURCE_KEY:-}" ]]; then
        if ssh-add "$TARGET_SOURCE_KEY" 2>/dev/null; then
            _added_key="$TARGET_SOURCE_KEY"
        fi
    fi

    # --- Build the SSH command to the destination ---
    local -a dst_ssh=()
    if _is_password_mode; then
        dst_ssh+=(sshpass -e)
        export SSHPASS="$REMOTE_PASSWORD"
    fi
    dst_ssh+=(ssh)
    # Only enable agent forwarding when source uses key auth (needs the agent)
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        dst_ssh+=(-A)
    fi
    if ! _is_password_mode; then
        dst_ssh+=(-i "$REMOTE_KEY" -o BatchMode=yes)
    fi
    dst_ssh+=(-p "$REMOTE_PORT")
    dst_ssh+=(-o "StrictHostKeyChecking=yes")
    dst_ssh+=(-o "ConnectTimeout=${SSH_TIMEOUT:-${DEFAULT_SSH_TIMEOUT:-30}}")
    dst_ssh+=(-o "ServerAliveInterval=60" -o "ServerAliveCountMax=3")
    dst_ssh+=("${REMOTE_USER}@${REMOTE_HOST}")
    dst_ssh+=("$remote_cmd")

    # Cleanup helper: remove agent key and unset SSHPASS
    _ssh_to_ssh_cleanup() {
        [[ -n "$_added_key" ]] && ssh-add -d "$_added_key" 2>/dev/null || true
        unset SSHPASS
    }

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rsync (ssh→ssh) attempt $attempt/$max_retries: $source_spec -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}"

        if _is_password_mode; then
            export SSHPASS="$REMOTE_PASSWORD"
        fi

        local rc=0
        if [[ -n "${_TRANSFER_LOG:-}" ]]; then
            echo "=== rsync (ssh→ssh): $source_spec -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest} ===" >> "$_TRANSFER_LOG"
            "${dst_ssh[@]}" > >(_snaplog_tee) 2>&1 || rc=$?
        else
            "${dst_ssh[@]}" || rc=$?
        fi
        unset SSHPASS

        if (( rc == 0 )); then
            log_debug "rsync (ssh→ssh) succeeded on attempt $attempt"
            _ssh_to_ssh_cleanup
            return 0
        fi

        if (( rc == 23 )); then
            log_warn "rsync (ssh→ssh) partial transfer (exit 23): retrying to pick up failed files..."
            sleep 2
            if _is_password_mode; then export SSHPASS="$REMOTE_PASSWORD"; fi
            local rc2=0
            if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                echo "=== rsync (ssh→ssh retry): $source_spec -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest} ===" >> "$_TRANSFER_LOG"
                "${dst_ssh[@]}" > >(_snaplog_tee) 2>&1 || rc2=$?
            else
                "${dst_ssh[@]}" || rc2=$?
            fi
            unset SSHPASS
            if (( rc2 == 0 )); then
                log_info "rsync (ssh→ssh) retry succeeded — all files transferred"
                _ssh_to_ssh_cleanup
                return 0
            fi
            log_warn "rsync (ssh→ssh) retry completed (exit $rc2): some files could not be transferred"
            _ssh_to_ssh_cleanup
            return 0
        fi
        if (( rc == 24 )); then
            log_warn "rsync (ssh→ssh) completed with warnings (exit $rc): vanished source files"
            _ssh_to_ssh_cleanup
            return 0
        fi

        # SSH connection failure (255) — retry with backoff
        if (( rc == 255 )); then
            log_warn "rsync (ssh→ssh) SSH connection failed (exit 255), attempt $attempt/$max_retries"
        else
            log_warn "rsync (ssh→ssh) failed (exit $rc), attempt $attempt/$max_retries"
        fi
        _check_disk_space_or_abort || { _ssh_to_ssh_cleanup; return 1; }

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    _ssh_to_ssh_cleanup
    log_error "rsync (ssh→ssh) failed after $max_retries attempts"
    return 1
}

# Pipelined folder transfer: SSH source → SSH destination (no local staging).
# Usage: transfer_folder_pipelined <target_name> <source_remote_path> <timestamp> [prev_snapshot] [dest_name]
transfer_folder_pipelined() {
    local target_name="$1"
    local source_remote_path="$2"
    local timestamp="$3"
    local prev_snapshot="${4:-}"
    local dest_name="${5:-}"

    # Strip leading / to create relative subpath in snapshot
    local rel_path="${dest_name:-${source_remote_path#/}}"

    # Build include/exclude filter args for rsync
    local -a filter_opts=()
    if [[ -n "${TARGET_INCLUDE:-}" ]]; then
        filter_opts+=(--include="*/")
        local -a inc_patterns
        IFS=',' read -ra inc_patterns <<< "$TARGET_INCLUDE"
        for pat in "${inc_patterns[@]}"; do
            pat="${pat#"${pat%%[![:space:]]*}"}"
            pat="${pat%"${pat##*[![:space:]]}"}"
            [[ -z "$pat" ]] && continue
            filter_opts+=(--include="$pat")
            if [[ "$pat" == */ ]]; then
                filter_opts+=(--include="${pat}**")
            fi
        done
        filter_opts+=(--exclude="*")
        filter_opts+=(--prune-empty-dirs)
    elif [[ -n "${TARGET_EXCLUDE:-}" ]]; then
        local -a exc_patterns
        IFS=',' read -ra exc_patterns <<< "$TARGET_EXCLUDE"
        for pat in "${exc_patterns[@]}"; do
            pat="${pat#"${pat%%[![:space:]]*}"}"
            pat="${pat%"${pat##*[![:space:]]}"}"
            [[ -n "$pat" ]] && filter_opts+=(--exclude="$pat")
        done
    fi

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
    local dest="$snap_dir/${timestamp}.partial/${rel_path}/"
    local link_dest=""

    if [[ -n "$prev_snapshot" ]]; then
        link_dest="$snap_dir/$prev_snapshot/${rel_path}"
    fi

    ensure_remote_dir "$dest" || return 1

    log_info "Transferring $source_remote_path for $target_name (ssh→ssh pipeline)..."
    rsync_ssh_to_ssh "$source_remote_path" "$dest" "$link_dest" "${filter_opts[@]}"
}

# Transfer a single folder to a remote snapshot.
# Usage: transfer_folder <target_name> <folder_path> <timestamp> [prev_snapshot] [dest_name]
# If dest_name is given, use it as the remote subpath instead of deriving from folder_path.
transfer_folder() {
    local target_name="$1"
    local folder_path="$2"
    local timestamp="$3"
    local prev_snapshot="${4:-}"
    local dest_name="${5:-}"

    if [[ ! -d "$folder_path" ]]; then
        log_info "Folder not found, creating: $folder_path"
        if ! mkdir -p "$folder_path" 2>/dev/null; then
            log_warn "Cannot create folder, skipping: $folder_path"
            return 1
        fi
    fi

    # Strip leading / to create relative subpath in snapshot
    local rel_path="${dest_name:-${folder_path#/}}"

    # Build include/exclude filter args for rsync
    local -a filter_opts=()
    if [[ -n "${TARGET_INCLUDE:-}" ]]; then
        # Include mode: allow directory traversal, include matched patterns, exclude rest
        filter_opts+=(--include="*/")
        local -a inc_patterns
        IFS=',' read -ra inc_patterns <<< "$TARGET_INCLUDE"
        for pat in "${inc_patterns[@]}"; do
            pat="${pat#"${pat%%[![:space:]]*}"}"
            pat="${pat%"${pat##*[![:space:]]}"}"
            [[ -z "$pat" ]] && continue
            filter_opts+=(--include="$pat")
            # For directory patterns, also include their contents
            if [[ "$pat" == */ ]]; then
                filter_opts+=(--include="${pat}**")
            fi
        done
        filter_opts+=(--exclude="*")
        # Prune empty dirs left by directory traversal
        filter_opts+=(--prune-empty-dirs)
    elif [[ -n "${TARGET_EXCLUDE:-}" ]]; then
        local -a exc_patterns
        IFS=',' read -ra exc_patterns <<< "$TARGET_EXCLUDE"
        for pat in "${exc_patterns[@]}"; do
            pat="${pat#"${pat%%[![:space:]]*}"}"
            pat="${pat%"${pat##*[![:space:]]}"}"
            [[ -n "$pat" ]] && filter_opts+=(--exclude="$pat")
        done
    fi

    if _is_rclone_mode; then
        local snap_subpath="targets/${target_name}/snapshots/${timestamp}/${rel_path}"
        log_info "Transferring $folder_path for $target_name (rclone)..."
        rclone_to_remote "$folder_path" "$snap_subpath"
        return
    fi

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")
    local dest="$snap_dir/${timestamp}.partial/${rel_path}/"
    local link_dest=""

    if [[ -n "$prev_snapshot" ]]; then
        link_dest="$snap_dir/$prev_snapshot/${rel_path}"
    fi

    if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        mkdir -p "$dest" || {
            log_error "Failed to create local destination directory: $dest"
            return 1
        }

        log_info "Transferring $folder_path for $target_name (local)..."
        rsync_local "$folder_path" "$dest" "$link_dest" "${filter_opts[@]}"
        return
    fi

    # SSH remote
    ensure_remote_dir "$dest" || return 1

    log_info "Transferring $folder_path for $target_name..."
    rsync_to_remote "$folder_path" "$dest" "$link_dest" "${filter_opts[@]}"
}

# Finalize a snapshot: rename .partial -> final, update latest symlink.
# Usage: finalize_snapshot <target_name> <timestamp>
finalize_snapshot() {
    local target_name="$1"
    local timestamp="$2"

    if _is_rclone_mode; then
        log_info "Finalizing snapshot for $target_name: $timestamp (rclone)"
        rclone_finalize_snapshot "$target_name" "$timestamp"
        return
    fi

    local snap_dir; snap_dir=$(get_snapshot_dir "$target_name")

    log_info "Finalizing snapshot for $target_name: $timestamp"

    if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
        mv "$snap_dir/${timestamp}.partial" "$snap_dir/$timestamp" || {
            log_error "Failed to finalize snapshot for $target_name: $timestamp"
            return 1
        }
    else
        local sq_partial; sq_partial="$(shquote "$snap_dir/${timestamp}.partial")"
        local sq_final; sq_final="$(shquote "$snap_dir/$timestamp")"
        remote_exec "mv '$sq_partial' '$sq_final'" || {
            log_error "Failed to finalize snapshot for $target_name: $timestamp"
            return 1
        }
    fi

    update_latest_symlink "$target_name" "$timestamp"
}
