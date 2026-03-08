#!/usr/bin/env bash
# gniza4linux/lib/rclone.sh — Rclone transport layer for S3 and Google Drive remotes

[[ -n "${_GNIZA4LINUX_RCLONE_LOADED:-}" ]] && return 0
_GNIZA4LINUX_RCLONE_LOADED=1

# ── Mode Detection ────────────────────────────────────────────

_is_rclone_mode() {
    [[ "${REMOTE_TYPE:-ssh}" == "s3" || "${REMOTE_TYPE:-ssh}" == "gdrive" ]]
}

# ── Rclone Config Generation ─────────────────────────────────

_build_rclone_config() {
    local tmpfile
    local old_umask
    old_umask=$(umask)
    umask 077
    tmpfile=$(mktemp "${WORK_DIR}/gniza-rclone-XXXXXX.conf") || {
        umask "$old_umask"
        log_error "Failed to create temp rclone config"
        return 1
    }
    umask "$old_umask"

    case "${REMOTE_TYPE}" in
        s3)
            cat > "$tmpfile" <<EOF
[remote]
type = s3
provider = ${S3_PROVIDER:-AWS}
access_key_id = ${S3_ACCESS_KEY_ID}
secret_access_key = ${S3_SECRET_ACCESS_KEY}
region = ${S3_REGION:-$DEFAULT_S3_REGION}
EOF
            if [[ -n "${S3_ENDPOINT:-}" ]]; then
                echo "endpoint = ${S3_ENDPOINT}" >> "$tmpfile"
            fi
            ;;
        gdrive)
            cat > "$tmpfile" <<EOF
[remote]
type = drive
scope = drive
service_account_file = ${GDRIVE_SERVICE_ACCOUNT_FILE}
EOF
            if [[ -n "${GDRIVE_ROOT_FOLDER_ID:-}" ]]; then
                echo "root_folder_id = ${GDRIVE_ROOT_FOLDER_ID}" >> "$tmpfile"
            fi
            ;;
        *)
            rm -f "$tmpfile"
            log_error "Unknown REMOTE_TYPE for rclone: ${REMOTE_TYPE}"
            return 1
            ;;
    esac

    echo "$tmpfile"
}

_cleanup_rclone_config() {
    local path="$1"
    [[ -n "$path" && -f "$path" ]] && rm -f "$path"
}

# ── Path Construction ─────────────────────────────────────────

_rclone_remote_path() {
    local subpath="${1:-}"
    local hostname; hostname=$(hostname -f)

    case "${REMOTE_TYPE}" in
        s3)
            echo "remote:${S3_BUCKET}${REMOTE_BASE}/${hostname}${subpath:+/$subpath}"
            ;;
        gdrive)
            echo "remote:${REMOTE_BASE}/${hostname}${subpath:+/$subpath}"
            ;;
    esac
}

# ── Core Command Runner ──────────────────────────────────────

# Run an rclone subcommand with auto config lifecycle.
# Usage: _rclone_cmd <subcmd> [args...]
_rclone_cmd() {
    local subcmd="$1"; shift
    local conf
    conf=$(_build_rclone_config) || return 1

    # Ensure temp config is cleaned up on crash/signal (preserve existing traps)
    local _prev_exit_trap _prev_hup_trap _prev_int_trap _prev_term_trap
    _prev_exit_trap=$(trap -p EXIT)
    _prev_hup_trap=$(trap -p HUP)
    _prev_int_trap=$(trap -p INT)
    _prev_term_trap=$(trap -p TERM)
    trap '_cleanup_rclone_config "'"$conf"'"; '"${_prev_exit_trap:+eval \"\$_prev_exit_trap\"}" EXIT
    trap '_cleanup_rclone_config "'"$conf"'"; '"${_prev_hup_trap:+eval \"\$_prev_hup_trap\"}" HUP
    trap '_cleanup_rclone_config "'"$conf"'"; '"${_prev_int_trap:+eval \"\$_prev_int_trap\"}" INT
    trap '_cleanup_rclone_config "'"$conf"'"; '"${_prev_term_trap:+eval \"\$_prev_term_trap\"}" TERM

    local rclone_opts=(--config "$conf")
    if [[ "${BWLIMIT:-0}" -gt 0 ]]; then
        rclone_opts+=(--bwlimit "${BWLIMIT}k")
    fi

    log_debug "rclone $subcmd ${rclone_opts[*]} $*"
    local rc=0
    if [[ -n "${_TRANSFER_LOG:-}" && "$subcmd" == "copy" ]]; then
        echo "=== rclone copy $* ===" >> "$_TRANSFER_LOG"
        rclone "$subcmd" "${rclone_opts[@]}" --verbose "$@" > >(_snaplog_tee) 2>&1 || rc=$?
    else
        rclone "$subcmd" "${rclone_opts[@]}" "$@" || rc=$?
    fi

    _cleanup_rclone_config "$conf"
    # Restore previous traps
    eval "${_prev_exit_trap:-trap - EXIT}"
    eval "${_prev_hup_trap:-trap - HUP}"
    eval "${_prev_int_trap:-trap - INT}"
    eval "${_prev_term_trap:-trap - TERM}"
    return "$rc"
}

# ── Transfer Functions ────────────────────────────────────────

rclone_to_remote() {
    local source_dir="$1"
    local remote_subpath="$2"
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local remote_dest; remote_dest=$(_rclone_remote_path "$remote_subpath")

    [[ "$source_dir" != */ ]] && source_dir="$source_dir/"

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rclone copy attempt $attempt/$max_retries: $source_dir -> $remote_dest"

        if _rclone_cmd copy "$source_dir" "$remote_dest"; then
            log_debug "rclone copy succeeded on attempt $attempt"
            return 0
        fi

        log_warn "rclone copy failed, attempt $attempt/$max_retries"
        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rclone copy failed after $max_retries attempts"
    return 1
}

rclone_from_remote() {
    local remote_subpath="$1"
    local local_dir="$2"
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local remote_src; remote_src=$(_rclone_remote_path "$remote_subpath")

    mkdir -p "$local_dir" || {
        log_error "Failed to create local dir: $local_dir"
        return 1
    }

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rclone copy attempt $attempt/$max_retries: $remote_src -> $local_dir"

        if _rclone_cmd copy "$remote_src" "$local_dir"; then
            log_debug "rclone download succeeded on attempt $attempt"
            return 0
        fi

        log_warn "rclone download failed, attempt $attempt/$max_retries"
        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rclone download failed after $max_retries attempts"
    return 1
}

# Like rclone_from_remote but passes extra args (e.g. --exclude) to rclone copy.
# Usage: rclone_from_remote_filtered <remote_subpath> <local_dir> [extra_args...]
rclone_from_remote_filtered() {
    local remote_subpath="$1"
    local local_dir="$2"
    shift 2
    local -a extra_args=("$@")
    local attempt=0
    local max_retries="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    local remote_src; remote_src=$(_rclone_remote_path "$remote_subpath")

    mkdir -p "$local_dir" || {
        log_error "Failed to create local dir: $local_dir"
        return 1
    }

    while (( attempt < max_retries )); do
        ((attempt++)) || true
        log_debug "rclone copy (filtered) attempt $attempt/$max_retries: $remote_src -> $local_dir"

        if _rclone_cmd copy "$remote_src" "$local_dir" "${extra_args[@]}"; then
            log_debug "rclone download succeeded on attempt $attempt"
            return 0
        fi

        log_warn "rclone download failed, attempt $attempt/$max_retries"
        if (( attempt < max_retries )); then
            local backoff=$(( attempt * 10 ))
            log_info "Retrying in ${backoff}s..."
            sleep "$backoff"
        fi
    done

    log_error "rclone download failed after $max_retries attempts"
    return 1
}

# ── Snapshot Management ───────────────────────────────────────

rclone_list_dirs() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd lsf --dirs-only "$remote_path" 2>/dev/null | sed 's|/$||'
}

rclone_list_remote_snapshots() {
    local target_name="$1"
    local snap_subpath="targets/${target_name}/snapshots"
    local all_dirs; all_dirs=$(rclone_list_dirs "$snap_subpath") || true
    [[ -z "$all_dirs" ]] && return 0

    # Filter to dirs with .complete marker, sorted newest first
    local completed=""
    while IFS= read -r dir; do
        [[ -z "$dir" ]] && continue
        if rclone_exists "${snap_subpath}/${dir}/.complete"; then
            completed+="${dir}"$'\n'
        fi
    done <<< "$all_dirs"

    [[ -n "$completed" ]] && echo "$completed" | sort -r
}

rclone_get_latest_snapshot() {
    local target_name="$1"
    local snap_subpath="targets/${target_name}/snapshots"

    # Try reading latest.txt first
    local latest; latest=$(rclone_cat "${snap_subpath}/latest.txt" 2>/dev/null) || true
    if [[ -n "$latest" ]]; then
        # Verify it still exists with .complete marker
        if rclone_exists "${snap_subpath}/${latest}/.complete"; then
            echo "$latest"
            return 0
        fi
    fi

    # Fall back to sorted list
    rclone_list_remote_snapshots "$target_name" | head -1
}

rclone_clean_partial_snapshots() {
    local target_name="$1"
    local snap_subpath="targets/${target_name}/snapshots"
    local all_dirs; all_dirs=$(rclone_list_dirs "$snap_subpath") || true
    [[ -z "$all_dirs" ]] && return 0

    while IFS= read -r dir; do
        [[ -z "$dir" ]] && continue
        if ! rclone_exists "${snap_subpath}/${dir}/.complete"; then
            log_info "Purging incomplete snapshot for $target_name: $dir"
            rclone_purge "${snap_subpath}/${dir}" || {
                log_warn "Failed to purge incomplete snapshot: $dir"
            }
        fi
    done <<< "$all_dirs"
}

rclone_finalize_snapshot() {
    local target_name="$1"
    local ts="$2"
    local snap_subpath="targets/${target_name}/snapshots"

    # Create .complete marker
    rclone_rcat "${snap_subpath}/${ts}/.complete" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" || {
        log_error "Failed to create .complete marker for $target_name/$ts"
        return 1
    }

    # Update latest.txt
    rclone_update_latest "$target_name" "$ts"
}

rclone_update_latest() {
    local target_name="$1"
    local ts="$2"
    local snap_subpath="targets/${target_name}/snapshots"

    rclone_rcat "${snap_subpath}/latest.txt" "$ts" || {
        log_warn "Failed to update latest.txt for $target_name"
        return 1
    }
    log_debug "Updated latest.txt for $target_name -> $ts"
}

rclone_resolve_snapshot() {
    local target_name="$1"
    local requested="$2"
    local snap_subpath="targets/${target_name}/snapshots"

    if rclone_exists "${snap_subpath}/${requested}/.complete"; then
        echo "$requested"
    else
        log_error "Snapshot not found or incomplete for $target_name: $requested"
        return 1
    fi
}

# ── Remote Operations ─────────────────────────────────────────

rclone_ensure_dir() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd mkdir "$remote_path"
}

rclone_purge() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd purge "$remote_path"
}

rclone_exists() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd lsf "$remote_path" &>/dev/null
}

rclone_size() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd size --json "$remote_path" 2>/dev/null
}

rclone_list_files() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd lsf "$remote_path" 2>/dev/null
}

rclone_cat() {
    local remote_subpath="$1"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    _rclone_cmd cat "$remote_path" 2>/dev/null
}

rclone_rcat() {
    local remote_subpath="$1"
    local content="$2"
    local remote_path; remote_path=$(_rclone_remote_path "$remote_subpath")
    echo -n "$content" | _rclone_cmd rcat "$remote_path"
}

test_rclone_connection() {
    local remote_path
    case "${REMOTE_TYPE}" in
        s3)
            remote_path="remote:${S3_BUCKET}"
            ;;
        gdrive)
            remote_path="remote:${REMOTE_BASE}"
            ;;
        *)
            log_error "Unknown REMOTE_TYPE: ${REMOTE_TYPE}"
            return 1
            ;;
    esac

    log_debug "Testing rclone connection to ${REMOTE_TYPE}..."
    if _rclone_cmd lsd "$remote_path" &>/dev/null; then
        log_debug "Rclone connection test passed"
        return 0
    else
        log_error "Rclone connection test failed for ${REMOTE_TYPE}"
        return 1
    fi
}

# ── Disk/Quota Info ──────────────────────────────────────────

# Return disk usage percentage for rclone remotes.
# gdrive: computed from about --json. s3: returns 0 (no quota concept).
rclone_disk_usage_pct() {
    case "${REMOTE_TYPE}" in
        gdrive)
            local about_json
            about_json=$(_rclone_cmd about "remote:" --json 2>/dev/null) || { echo "0"; return 0; }
            python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
total = d.get('total', 0)
used = d.get('used', 0)
print(int(used * 100 / total) if total > 0 else 0)
" <<< "$about_json" 2>/dev/null || echo "0"
            ;;
        s3)
            # S3 has no quota concept
            echo "0"
            ;;
    esac
}

# Compact one-line disk info for rclone remotes.
# gdrive: "USED/TOTAL (FREE free) PCT%". s3: "SIZE used (no quota)".
rclone_disk_info_short() {
    case "${REMOTE_TYPE}" in
        gdrive)
            local about_json
            about_json=$(_rclone_cmd about "remote:" --json 2>/dev/null) || { echo "N/A"; return 0; }
            python3 -c "
import json, sys
def fmt(b):
    for u in ['B','K','M','G','T']:
        if b < 1024: return f'{b:.1f}{u}'
        b /= 1024
    return f'{b:.1f}P'
d = json.loads(sys.stdin.read())
total = d.get('total', 0)
used = d.get('used', 0)
free = d.get('free', total - used)
pct = int(used * 100 / total) if total > 0 else 0
print(f'{fmt(used)}/{fmt(total)} ({fmt(free)} free) {pct}%')
" <<< "$about_json" 2>/dev/null || echo "N/A"
            ;;
        s3)
            local bucket_path
            bucket_path="remote:${S3_BUCKET}${REMOTE_BASE}"
            local size_json
            size_json=$(_rclone_cmd size --json "$bucket_path" 2>/dev/null) || { echo "N/A"; return 0; }
            python3 -c "
import json, sys
def fmt(b):
    for u in ['B','K','M','G','T']:
        if b < 1024: return f'{b:.1f}{u}'
        b /= 1024
    return f'{b:.1f}P'
d = json.loads(sys.stdin.read())
total_bytes = d.get('bytes', 0)
count = d.get('count', 0)
print(f'{fmt(total_bytes)} used, {count} objects (no quota)')
" <<< "$size_json" 2>/dev/null || echo "N/A"
            ;;
    esac
}
