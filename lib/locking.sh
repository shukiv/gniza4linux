#!/usr/bin/env bash
# gniza4linux/lib/locking.sh — flock-based per-target concurrency control

[[ -n "${_GNIZA4LINUX_LOCKING_LOADED:-}" ]] && return 0
_GNIZA4LINUX_LOCKING_LOADED=1

declare -g LOCK_FD=""
declare -gA _TARGET_LOCK_FDS=()

acquire_lock() {
    # Use WORK_DIR for locks — it's consistent regardless of how the process
    # is started (cron lacks XDG_RUNTIME_DIR, causing different LOCK_FILE paths).
    local lock_dir="${WORK_DIR:-/tmp}"
    mkdir -p "$lock_dir" || die "Cannot create lock directory: $lock_dir"
    local lock_file="${lock_dir}/gniza.lock"

    exec {LOCK_FD}>"$lock_file"

    if ! flock -n "$LOCK_FD"; then
        die "Another gniza process is running (lock: $lock_file)" "$EXIT_LOCKED"
    fi

    echo $$ >&"$LOCK_FD"
    log_debug "Lock acquired: $lock_file (PID $$)"
}

release_lock() {
    if [[ -n "$LOCK_FD" ]]; then
        flock -u "$LOCK_FD" 2>/dev/null
        exec {LOCK_FD}>&- 2>/dev/null
        LOCK_FD=""
        log_debug "Lock released"
    fi
}

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
