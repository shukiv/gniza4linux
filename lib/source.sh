#!/usr/bin/env bash
# gniza4linux/lib/source.sh — Pull files from remote sources

[[ -n "${_GNIZA4LINUX_SOURCE_LOADED:-}" ]] && return 0
_GNIZA4LINUX_SOURCE_LOADED=1

# Pull files from a remote source to a local staging directory.
# Usage: pull_from_source <remote_path> <local_dir>
pull_from_source() {
    local remote_path="$1"
    local local_dir="$2"

    mkdir -p "$local_dir" || {
        log_error "Failed to create staging directory: $local_dir"
        return 1
    }

    case "${TARGET_SOURCE_TYPE:-local}" in
        ssh)
            _rsync_from_source_ssh "$remote_path" "$local_dir"
            ;;
        s3)
            _build_source_rclone_config "s3"
            _rclone_from_source "$remote_path" "$local_dir"
            local rc=$?
            rm -f "${_SOURCE_RCLONE_CONF:-}"; _SOURCE_RCLONE_CONF=""
            return $rc
            ;;
        gdrive)
            _build_source_rclone_config "gdrive"
            _rclone_from_source "$remote_path" "$local_dir"
            local rc=$?
            rm -f "${_SOURCE_RCLONE_CONF:-}"; _SOURCE_RCLONE_CONF=""
            return $rc
            ;;
        rclone)
            _build_source_rclone_config "rclone"
            _rclone_from_source "$remote_path" "$local_dir"
            local rc=$?
            rm -f "${_SOURCE_RCLONE_CONF:-}"; _SOURCE_RCLONE_CONF=""
            return $rc
            ;;
        *)
            log_error "Unknown source type: ${TARGET_SOURCE_TYPE}"
            return 1
            ;;
    esac
}

# Pull from SSH source using rsync.
_rsync_from_source_ssh() {
    local remote_path="$1"
    local local_dir="$2"
    local attempt=0
    local max_retries="${SSH_RETRIES:-${DEFAULT_SSH_RETRIES:-3}}"

    # Build SSH command for source connection
    local ssh_opts=(-o StrictHostKeyChecking=accept-new)
    ssh_opts+=(-o ConnectTimeout="${SSH_TIMEOUT:-${DEFAULT_SSH_TIMEOUT:-30}}")
    ssh_opts+=(-p "${TARGET_SOURCE_PORT:-22}")

    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        ssh_opts+=(-o BatchMode=yes)
        [[ -n "${TARGET_SOURCE_KEY:-}" ]] && ssh_opts+=(-i "$TARGET_SOURCE_KEY")
    fi

    local rsync_ssh
    rsync_ssh="ssh $(printf '%s ' "${ssh_opts[@]}")"
    local rsync_path="rsync --fake-super"
    [[ "${TARGET_SOURCE_SUDO:-no}" == "yes" ]] && rsync_path="sudo rsync --fake-super"
    local rsync_opts=(-aHAX --numeric-ids --sparse --rsync-path="$rsync_path")
    rsync_opts+=(--info=progress2 --no-inc-recursive)

    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
        rsync_opts+=(--log-file="$_TRANSFER_LOG" --stats)
    fi

    # Ensure remote_path ends with /
    [[ "$remote_path" != */ ]] && remote_path="$remote_path/"
    # Ensure local_dir ends with /
    [[ "$local_dir" != */ ]] && local_dir="$local_dir/"

    local source_spec="${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}:${remote_path}"

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rsync (source pull) attempt $attempt/$max_retries: $source_spec -> $local_dir"
        log_info "CMD: rsync ${rsync_opts[*]} -e '$rsync_ssh' $source_spec $local_dir"

        local rsync_cmd=(rsync "${rsync_opts[@]}" -e "$rsync_ssh" "$source_spec" "$local_dir")
        if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
            export SSHPASS="$TARGET_SOURCE_PASSWORD"
            rsync_cmd=(sshpass -e "${rsync_cmd[@]}")
        fi

        local rc=0
        if [[ -n "${_TRANSFER_LOG:-}" ]]; then
            echo "=== rsync (source pull): $source_spec -> $local_dir ===" >> "$_TRANSFER_LOG"
            "${rsync_cmd[@]}" 2>&1 | _snaplog_tee; rc=${PIPESTATUS[0]}
        else
            "${rsync_cmd[@]}" || rc=$?
        fi
        unset SSHPASS

        if (( rc == 0 )); then
            log_debug "rsync (source pull) succeeded on attempt $attempt"
            return 0
        fi

        if (( rc == 23 )); then
            log_warn "rsync (source pull) partial transfer (exit 23): retrying to pick up failed files..."
            sleep 2
            local rc2=0
            if [[ -n "${_TRANSFER_LOG:-}" ]]; then
                echo "=== rsync (source pull retry): $source_spec -> $local_dir ===" >> "$_TRANSFER_LOG"
                "${rsync_cmd[@]}" 2>&1 | _snaplog_tee; rc2=${PIPESTATUS[0]}
            else
                "${rsync_cmd[@]}" || rc2=$?
            fi
            unset SSHPASS
            if (( rc2 == 0 )); then
                log_info "rsync (source pull) retry succeeded — all files transferred"
                return 0
            fi
            log_warn "rsync (source pull) retry completed (exit $rc2): some files could not be transferred"
            return 0
        fi
        if (( rc == 24 )); then
            log_warn "rsync (source pull) completed with warnings (exit $rc): vanished source files"
            return 0
        fi

        log_warn "rsync (source pull) failed (exit $rc), attempt $attempt/$max_retries"

        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rsync (source pull) failed after $max_retries attempts"
    return 1
}

# Build a temporary rclone config for source pulling.
# Usage: _build_source_rclone_config <type>
_build_source_rclone_config() {
    local src_type="$1"
    _SOURCE_RCLONE_CONF=$(mktemp "${WORK_DIR:-/tmp}/gniza-source-rclone-XXXXXX.conf")

    if [[ "$src_type" == "s3" ]]; then
        cat > "$_SOURCE_RCLONE_CONF" <<EOF
[gniza-source]
type = s3
provider = ${TARGET_SOURCE_S3_PROVIDER:-AWS}
access_key_id = ${TARGET_SOURCE_S3_ACCESS_KEY_ID:-}
secret_access_key = ${TARGET_SOURCE_S3_SECRET_ACCESS_KEY:-}
region = ${TARGET_SOURCE_S3_REGION:-us-east-1}
endpoint = ${TARGET_SOURCE_S3_ENDPOINT:-}
EOF
    elif [[ "$src_type" == "gdrive" ]]; then
        cat > "$_SOURCE_RCLONE_CONF" <<EOF
[gniza-source]
type = drive
service_account_file = ${TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE:-}
root_folder_id = ${TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID:-}
EOF
    elif [[ "$src_type" == "rclone" ]]; then
        # Extract named remote section from user's rclone.conf, rename to [gniza-source]
        local src_conf="${TARGET_SOURCE_RCLONE_CONFIG_PATH:-}"
        if [[ -z "$src_conf" ]]; then
            src_conf=$(rclone config file 2>/dev/null | tail -1) || {
                log_error "Cannot determine rclone config path for source"
                return 1
            }
        fi
        if [[ ! -f "$src_conf" ]]; then
            log_error "Source rclone config file not found: $src_conf"
            return 1
        fi
        local remote_name="${TARGET_SOURCE_RCLONE_REMOTE_NAME}"
        awk -v name="$remote_name" '
            BEGIN { found=0 }
            /^\[/ { found = ($0 == "[" name "]") ? 1 : 0 }
            found { if ($0 == "[" name "]") print "[gniza-source]"; else print }
        ' "$src_conf" > "$_SOURCE_RCLONE_CONF"
        if ! grep -q '^\[gniza-source\]' "$_SOURCE_RCLONE_CONF"; then
            log_error "Remote section [${remote_name}] not found in $src_conf"
            return 1
        fi
    fi

    chmod 600 "$_SOURCE_RCLONE_CONF"
}

# Pull from S3/GDrive source using rclone.
_rclone_from_source() {
    local remote_path="$1"
    local local_dir="$2"

    if [[ -z "${_SOURCE_RCLONE_CONF:-}" || ! -f "${_SOURCE_RCLONE_CONF:-}" ]]; then
        log_error "Source rclone config not found"
        return 1
    fi

    local rclone_src="gniza-source:${remote_path}"
    if [[ "${TARGET_SOURCE_TYPE}" == "s3" && -n "${TARGET_SOURCE_S3_BUCKET:-}" ]]; then
        rclone_src="gniza-source:${TARGET_SOURCE_S3_BUCKET}/${remote_path#/}"
    elif [[ "${TARGET_SOURCE_TYPE}" == "rclone" ]]; then
        rclone_src="gniza-source:${remote_path#/}"
    fi

    log_debug "rclone (source pull): $rclone_src -> $local_dir"

    local rc=0
    if [[ -n "${_TRANSFER_LOG:-}" ]]; then
        echo "=== rclone (source pull): $rclone_src -> $local_dir ===" >> "$_TRANSFER_LOG"
        rclone copy --config "$_SOURCE_RCLONE_CONF" "$rclone_src" "$local_dir" \
            --progress 2>&1 | tee -a "$_TRANSFER_LOG" || rc=$?
    else
        rclone copy --config "$_SOURCE_RCLONE_CONF" "$rclone_src" "$local_dir" || rc=$?
    fi

    # Cleanup temp config
    rm -f "$_SOURCE_RCLONE_CONF"
    _SOURCE_RCLONE_CONF=""

    if (( rc != 0 )); then
        log_error "rclone (source pull) failed (exit $rc)"
        return 1
    fi

    return 0
}
