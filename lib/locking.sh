#!/usr/bin/env bash
# gniza4linux/lib/locking.sh — flock-based per-target concurrency control

[[ -n "${_GNIZA4LINUX_LOCKING_LOADED:-}" ]] && return 0
_GNIZA4LINUX_LOCKING_LOADED=1

declare -gA _TARGET_LOCK_FDS=()

# Per-target lock: prevents the same target from running twice,
# but allows different targets to run concurrently.
acquire_target_lock() {
    local target_name="$1"
    local lock_dir="${WORK_DIR:-/tmp}"
    mkdir -p "$lock_dir" || die "Cannot create lock directory: $lock_dir"

    local lock_file="${lock_dir}/gniza-target-${target_name}.lock"
    local fd
    exec {fd}>"$lock_file"

    if ! flock -n "$fd"; then
        log_error "Target '$target_name' is already running (lock: $lock_file)"
        exec {fd}>&- 2>/dev/null
        return 1
    fi

    echo $$ >&"$fd"
    _TARGET_LOCK_FDS["$target_name"]="$fd"
    log_debug "Target lock acquired: $target_name (PID $$)"
}

release_target_lock() {
    local target_name="$1"
    local fd="${_TARGET_LOCK_FDS[$target_name]:-}"
    if [[ -n "$fd" ]]; then
        flock -u "$fd" 2>/dev/null
        exec {fd}>&- 2>/dev/null
        unset '_TARGET_LOCK_FDS[$target_name]'
        log_debug "Target lock released: $target_name"
    fi
}

release_all_target_locks() {
    local name
    for name in "${!_TARGET_LOCK_FDS[@]}"; do
        release_target_lock "$name"
    done
}
