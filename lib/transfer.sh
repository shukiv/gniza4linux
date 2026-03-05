#!/usr/bin/env bash
# gniza4linux/lib/transfer.sh — rsync --link-dest to remote, .partial atomicity, retries

[[ -n "${_GNIZA4LINUX_TRANSFER_LOADED:-}" ]] && return 0
_GNIZA4LINUX_TRANSFER_LOADED=1

rsync_to_remote() {
    local source_dir="$1"
    local remote_dest="$2"
    local link_dest="${3:-}"
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local rsync_ssh; rsync_ssh=$(build_rsync_ssh_cmd)

    local rsync_opts=(-aHAX --numeric-ids --delete --rsync-path="rsync --fake-super")

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
        "${rsync_cmd[@]}" || rc=$?
        if (( rc == 0 )); then
            log_debug "rsync succeeded on attempt $attempt"
            return 0
        fi

        log_warn "rsync failed (exit $rc), attempt $attempt/$max_retries"

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
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"

    local rsync_opts=(-aHAX --numeric-ids --delete)

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

    # Ensure source ends with /
    [[ "$source_dir" != */ ]] && source_dir="$source_dir/"

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rsync (local) attempt $attempt/$max_retries: $source_dir -> $local_dest"

        local rc=0
        rsync "${rsync_opts[@]}" "$source_dir" "$local_dest" || rc=$?
        if (( rc == 0 )); then
            log_debug "rsync (local) succeeded on attempt $attempt"
            return 0
        fi

        log_warn "rsync (local) failed (exit $rc), attempt $attempt/$max_retries"

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rsync (local) failed after $max_retries attempts"
    return 1
}

# Transfer a single folder to a remote snapshot.
# Usage: transfer_folder <target_name> <folder_path> <timestamp> [prev_snapshot]
transfer_folder() {
    local target_name="$1"
    local folder_path="$2"
    local timestamp="$3"
    local prev_snapshot="${4:-}"

    if [[ ! -d "$folder_path" ]]; then
        log_warn "Folder not found, skipping: $folder_path"
        return 1
    fi

    # Strip leading / to create relative subpath in snapshot
    local rel_path="${folder_path#/}"

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
        rsync_local "$folder_path" "$dest" "$link_dest"
        return
    fi

    # SSH remote
    ensure_remote_dir "$dest" || return 1

    log_info "Transferring $folder_path for $target_name..."
    rsync_to_remote "$folder_path" "$dest" "$link_dest"
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
        remote_exec "mv '$snap_dir/${timestamp}.partial' '$snap_dir/$timestamp'" || {
            log_error "Failed to finalize snapshot for $target_name: $timestamp"
            return 1
        }
    fi

    update_latest_symlink "$target_name" "$timestamp"
}
