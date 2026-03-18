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

# Helper: redirect stdin from /dev/null (prevents SSH from consuming stdin
# when running inside a while-read loop of folders).
_run_devnull() { "$@" </dev/null; }

# _rsync_with_retry <max_retries> <label> <cmd_array_name> [check_disk_space] [log_header]
#
# Shared retry wrapper for rsync commands.  Handles:
#   - Retry loop with exponential backoff
#   - Exit 23 (partial transfer): one extra retry, then accept as success
#   - Exit 24 (vanished source files): accept as success
#   - Optional disk-space check between retries
#   - Piping through _snaplog_tee when _TRANSFER_LOG is set
#
# Arguments:
#   max_retries       — number of attempts
#   label             — human-readable prefix for log messages (e.g. "rsync (local)")
#   cmd_array_name    — name of a bash array variable holding the full command
#   check_disk_space  — "true" to call _check_disk_space_or_abort on failure (default "false")
#   log_header        — optional header written to _TRANSFER_LOG before each attempt
#
# The command array is passed by nameref (requires bash 4.3+).
# Returns 0 on success (including 23/24 warnings), 1 on failure.
_rsync_with_retry() {
    local max_retries="$1"
    local label="$2"
    local -n _cmd_ref="$3"
    local check_disk_space="${4:-false}"
    local log_header="${5:-}"
    local attempt=0
    local rc=0

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "$label attempt $attempt/$max_retries"

        if [[ -n "$log_header" && -n "${_TRANSFER_LOG:-}" ]]; then
            echo "=== $log_header ===" >> "$_TRANSFER_LOG"
        fi

        rc=0
        if [[ -n "${_TRANSFER_LOG:-}" ]]; then
            "${_cmd_ref[@]}" 2>&1 | _snaplog_tee; rc=${PIPESTATUS[0]}
        else
            "${_cmd_ref[@]}" || rc=$?
        fi

        if (( rc == 0 )); then
            log_debug "$label succeeded on attempt $attempt"
            return 0
        fi

        # Exit 23 = partial transfer: retry once more to pick up failed files
        if (( rc == 23 )); then
            log_warn "$label partial transfer (exit 23): retrying to pick up failed files..."
            sleep 2
            if [[ -n "$log_header" && -n "${_TRANSFER_LOG:-}" ]]; then
                echo "=== ${log_header} (retry) ===" >> "$_TRANSFER_LOG"
            fi
            local rc2=0
            if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                "${_cmd_ref[@]}" 2>&1 | _snaplog_tee; rc2=${PIPESTATUS[0]}
            else
                "${_cmd_ref[@]}" || rc2=$?
            fi
            if (( rc2 == 0 )); then
                log_info "$label retry succeeded — all files transferred"
                return 0
            fi
            log_warn "$label retry completed (exit $rc2): some files could not be transferred"
            return 0
        fi

        # Exit 24 = vanished source files
        if (( rc == 24 )); then
            log_warn "$label completed with warnings (exit $rc): vanished source files"
            return 0
        fi

        log_warn "$label failed (exit $rc), attempt $attempt/$max_retries"

        if [[ "$check_disk_space" == "true" ]]; then
            _check_disk_space_or_abort || return 1
        fi

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "$label failed after $max_retries attempts"
    return 1
}

rsync_to_remote() {
    local source_dir="$1"
    local remote_dest="$2"
    local link_dest="${3:-}"
    shift 3 || true
    # Remaining args are extra rsync options (e.g. --exclude, --include)
    local -a extra_filter_opts=("$@")
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local rsync_ssh; rsync_ssh=$(build_rsync_ssh_cmd)

    local rsync_opts=(-aHAX --numeric-ids --delete --sparse --mkpath)
    if [[ "${REMOTE_RESTRICTED_SHELL:-false}" == "true" ]]; then
        log_debug "Restricted shell — skipping --fake-super"
    elif [[ "${REMOTE_SUDO:-no}" == "yes" ]]; then
        rsync_opts+=(--rsync-path="sudo rsync --fake-super")
    else
        rsync_opts+=(--rsync-path="rsync --fake-super")
    fi

    if [[ -n "$link_dest" ]]; then
        rsync_opts+=(--link-dest="$link_dest")
    fi

    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        rsync_opts+=(--bwlimit="$BWLIMIT")
    fi

    case "${RSYNC_COMPRESS:-no}" in
        yes|zlib) rsync_opts+=(-z) ;;
        zstd)     rsync_opts+=(-z --compress-choice=zstd) ;;
    esac

    if [[ "${RSYNC_CHECKSUM:-no}" == "yes" ]]; then
        rsync_opts+=(--checksum)
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
        rsync_opts+=(--log-file="$_TRANSFER_LOG" --stats)
    fi

    # Overall progress for TUI progress bar
    rsync_opts+=(--info=progress2)
    if [[ "${RSYNC_INC_RECURSIVE:-no}" != "yes" ]]; then
        rsync_opts+=(--no-inc-recursive)
    fi

    rsync_opts+=(-e "$rsync_ssh")

    # Ensure source ends with /
    [[ "$source_dir" != */ ]] && source_dir="$source_dir/"

    log_info "CMD: rsync ${rsync_opts[*]} $source_dir ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}"

    local -a rsync_cmd=(rsync "${rsync_opts[@]}" "$source_dir" "${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}")
    if _is_password_mode; then
        export SSHPASS="$REMOTE_PASSWORD"
        rsync_cmd=(sshpass -e "${rsync_cmd[@]}")
    fi

    local _rc=0
    _rsync_with_retry "$max_retries" "rsync" rsync_cmd "true" \
        "rsync: $source_dir -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}" || _rc=$?
    unset SSHPASS
    return "$_rc"
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
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"

    local rsync_opts=(-aHAX --numeric-ids --delete --sparse)

    if [[ -n "$link_dest" ]]; then
        rsync_opts+=(--link-dest="$link_dest")
    fi

    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        rsync_opts+=(--bwlimit="$BWLIMIT")
    fi

    if [[ "${RSYNC_CHECKSUM:-no}" == "yes" ]]; then
        rsync_opts+=(--checksum)
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
        rsync_opts+=(--log-file="$_TRANSFER_LOG" --stats)
    fi

    # Overall progress for TUI progress bar
    rsync_opts+=(--info=progress2)
    if [[ "${RSYNC_INC_RECURSIVE:-no}" != "yes" ]]; then
        rsync_opts+=(--no-inc-recursive)
    fi

    # Ensure source ends with /
    [[ "$source_dir" != */ ]] && source_dir="$source_dir/"

    log_info "CMD: rsync ${rsync_opts[*]} $source_dir $local_dest"

    local -a rsync_cmd=(rsync "${rsync_opts[@]}" "$source_dir" "$local_dest")

    _rsync_with_retry "$max_retries" "rsync (local)" rsync_cmd "true" \
        "rsync (local): $source_dir -> $local_dest"
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
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"

    # --- Build the rsync command string to run ON the destination ---
    local -a ropts=(-aHAX --numeric-ids --delete --sparse)
    if [[ "${REMOTE_RESTRICTED_SHELL:-false}" == "true" ]]; then
        log_debug "Restricted destination shell — skipping --fake-super for ssh→ssh"
    else
        ropts+=(--fake-super)
        # --rsync-path controls what runs on the SOURCE side
        local src_rsync_path="rsync --fake-super"
        [[ "${TARGET_SOURCE_SUDO:-no}" == "yes" ]] && src_rsync_path="sudo rsync --fake-super"
        ropts+=(--rsync-path="$src_rsync_path")
    fi

    if [[ -n "$link_dest" ]]; then
        ropts+=(--link-dest="$link_dest")
    fi

    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        ropts+=(--bwlimit="$BWLIMIT")
    fi

    case "${RSYNC_COMPRESS:-no}" in
        yes|zlib) ropts+=(-z) ;;
        zstd)     ropts+=(-z --compress-choice=zstd) ;;
    esac

    if [[ "${RSYNC_CHECKSUM:-no}" == "yes" ]]; then
        ropts+=(--checksum)
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

    ropts+=(--info=progress2)
    if [[ "${RSYNC_INC_RECURSIVE:-no}" != "yes" ]]; then
        ropts+=(--no-inc-recursive)
    fi

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

    local source_spec="${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}:${source_path}"

    # Assemble the remote command string with safe quoting
    # REMOTE_SUDO controls what runs on the DESTINATION side
    local remote_cmd="rsync"
    [[ "${REMOTE_SUDO:-no}" == "yes" ]] && remote_cmd="sudo rsync"
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

    # Source key auth: start an ephemeral ssh-agent so agent forwarding
    # works even from cron (which has no agent). The key never leaves
    # the local machine.
    local _own_agent=""
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        # Only start our own agent if there isn't one already
        if ! ssh-add -l &>/dev/null; then
            eval "$(ssh-agent -s)" >/dev/null 2>&1
            _own_agent="yes"
        fi
        if [[ -n "${TARGET_SOURCE_KEY:-}" ]]; then
            ssh-add "$TARGET_SOURCE_KEY" 2>/dev/null || log_warn "Failed to add source key to agent"
        else
            # No explicit key — add default keys so they can be forwarded
            ssh-add 2>/dev/null || true
        fi
    fi

    # --- Build the SSH command to the destination ---
    local -a dst_ssh=()
    if _is_password_mode; then
        dst_ssh+=(sshpass -e)
        export SSHPASS="$REMOTE_PASSWORD"
    fi
    dst_ssh+=(ssh)
    # Enable agent forwarding when source uses key auth
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        dst_ssh+=(-A)
    fi
    if ! _is_password_mode; then
        [[ -n "$REMOTE_KEY" ]] && dst_ssh+=(-i "$REMOTE_KEY")
        dst_ssh+=(-o BatchMode=yes)
    fi
    dst_ssh+=(-p "$REMOTE_PORT")
    dst_ssh+=(-o "StrictHostKeyChecking=yes")
    dst_ssh+=(-o "ConnectTimeout=${SSH_TIMEOUT:-${DEFAULT_SSH_TIMEOUT:-30}}")
    dst_ssh+=(-o "ServerAliveInterval=60" -o "ServerAliveCountMax=3")
    dst_ssh+=("${REMOTE_USER}@${REMOTE_HOST}")
    dst_ssh+=("$remote_cmd")

    # Cleanup helper: kill ephemeral agent, unset SSHPASS
    _ssh_to_ssh_cleanup() {
        if [[ -n "$_own_agent" && -n "${SSH_AGENT_PID:-}" ]]; then
            eval "$(ssh-agent -k)" >/dev/null 2>&1
            _own_agent=""
        fi
        unset SSHPASS
    }

    log_info "CMD (ssh→ssh): rsync ${ropts[*]} -e '...' $source_spec $remote_dest (via ${REMOTE_USER}@${REMOTE_HOST})"

    if _is_password_mode; then
        export SSHPASS="$REMOTE_PASSWORD"
    fi

    # _run_devnull prevents SSH from consuming stdin (which may be a
    # process substitution feeding a while-read loop of folders).
    local -a rsync_cmd=(_run_devnull "${dst_ssh[@]}")

    local _rc=0
    _rsync_with_retry "$max_retries" "rsync (ssh→ssh)" rsync_cmd "true" \
        "rsync (ssh→ssh): $source_spec -> ${REMOTE_USER}@${REMOTE_HOST}:${remote_dest}" || _rc=$?
    _ssh_to_ssh_cleanup
    return "$_rc"
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

# Direct SSH source → local .partial transfer (no staging).
# Rsyncs from SSH source directly into the local .partial dir with --link-dest.
# Usage: transfer_folder_ssh_to_local <target_name> <source_remote_path> <timestamp> [prev_snapshot] [dest_name]
transfer_folder_ssh_to_local() {
    local target_name="$1"
    local source_remote_path="$2"
    local timestamp="$3"
    local prev_snapshot="${4:-}"
    local dest_name="${5:-}"

    local rel_path="${dest_name:-${source_remote_path#/}}"

    # Build include/exclude filter args
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
            [[ "$pat" == */ ]] && filter_opts+=(--include="${pat}**")
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

    mkdir -p "$dest" || {
        log_error "Failed to create local destination: $dest"
        return 1
    }

    # Build SSH command for source
    local ssh_opts=(-o StrictHostKeyChecking=accept-new)
    ssh_opts+=(-o "ConnectTimeout=${SSH_TIMEOUT:-${DEFAULT_SSH_TIMEOUT:-30}}")
    ssh_opts+=(-p "${TARGET_SOURCE_PORT:-22}")
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        ssh_opts+=(-o BatchMode=yes)
        [[ -n "${TARGET_SOURCE_KEY:-}" ]] && ssh_opts+=(-i "$TARGET_SOURCE_KEY")
    fi
    local rsync_ssh
    rsync_ssh="ssh $(printf '%s ' "${ssh_opts[@]}")"

    # --rsync-path controls what runs on the SOURCE side
    local rsync_path="rsync --fake-super"
    [[ "${TARGET_SOURCE_SUDO:-no}" == "yes" ]] && rsync_path="sudo rsync --fake-super"

    local -a rsync_opts=(-aHAX --numeric-ids --delete --sparse --rsync-path="$rsync_path")

    if [[ -n "$link_dest" ]]; then
        rsync_opts+=(--link-dest="$link_dest")
    fi
    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        rsync_opts+=(--bwlimit="$BWLIMIT")
    fi
    if [[ "${RSYNC_CHECKSUM:-no}" == "yes" ]]; then
        rsync_opts+=(--checksum)
    fi
    if [[ -n "${RSYNC_EXTRA_OPTS:-}" ]]; then
        # shellcheck disable=SC2206
        rsync_opts+=($RSYNC_EXTRA_OPTS)
    fi
    if [[ ${#filter_opts[@]} -gt 0 ]]; then
        rsync_opts+=("${filter_opts[@]}")
    fi
    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
        rsync_opts+=(--log-file="$_TRANSFER_LOG" --stats)
    fi
    rsync_opts+=(--info=progress2)
    if [[ "${RSYNC_INC_RECURSIVE:-no}" != "yes" ]]; then
        rsync_opts+=(--no-inc-recursive)
    fi

    [[ "$source_remote_path" != */ ]] && source_remote_path="$source_remote_path/"
    local source_spec="${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}:${source_remote_path}"

    local attempt=0
    local max_retries="${SSH_RETRIES:-${DEFAULT_SSH_RETRIES:-3}}"

    log_info "Transferring $source_remote_path for $target_name (ssh→local direct)..."

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rsync (ssh→local) attempt $attempt/$max_retries: $source_spec -> $dest"
        log_info "CMD: rsync ${rsync_opts[*]} -e '$rsync_ssh' $source_spec $dest"

        local -a rsync_cmd=(rsync "${rsync_opts[@]}" -e "$rsync_ssh" "$source_spec" "$dest")
        if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
            export SSHPASS="$TARGET_SOURCE_PASSWORD"
            rsync_cmd=(sshpass -e "${rsync_cmd[@]}")
        fi

        local rc=0
        if [[ -n "${_TRANSFER_LOG:-}" ]]; then
            echo "=== rsync (ssh→local): $source_spec -> $dest ===" >> "$_TRANSFER_LOG"
            "${rsync_cmd[@]}" 2>&1 | _snaplog_tee; rc=${PIPESTATUS[0]}
        else
            "${rsync_cmd[@]}" || rc=$?
        fi
        unset SSHPASS

        if (( rc == 0 )); then
            log_debug "rsync (ssh→local) succeeded on attempt $attempt"
            return 0
        fi
        if (( rc == 23 )); then
            log_warn "rsync (ssh→local) partial transfer (exit 23): retrying..."
            sleep 2
            local rc2=0
            if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                echo "=== rsync (ssh→local retry): $source_spec -> $dest ===" >> "$_TRANSFER_LOG"
                "${rsync_cmd[@]}" 2>&1 | _snaplog_tee; rc2=${PIPESTATUS[0]}
            else
                "${rsync_cmd[@]}" || rc2=$?
            fi
            unset SSHPASS
            if (( rc2 == 0 )); then
                log_info "rsync (ssh→local) retry succeeded"
                return 0
            fi
            log_warn "rsync (ssh→local) retry completed (exit $rc2): some files could not be transferred"
            return 0
        fi
        if (( rc == 24 )); then
            log_warn "rsync (ssh→local) completed with warnings (exit $rc): vanished source files"
            return 0
        fi

        log_warn "rsync (ssh→local) failed (exit $rc), attempt $attempt/$max_retries"
        _check_disk_space_or_abort || return 1

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rsync (ssh→local) failed after $max_retries attempts"
    return 1
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
        log_info "Transferring $folder_path for $target_name (rclone incremental)..."
        rclone_sync_incremental "$folder_path" "$target_name" "$rel_path" "$timestamp"
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
