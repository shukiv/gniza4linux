#!/usr/bin/env bash
# gniza4linux/lib/locking.sh — flock-based concurrency control

[[ -n "${_GNIZA4LINUX_LOCKING_LOADED:-}" ]] && return 0
_GNIZA4LINUX_LOCKING_LOADED=1

declare -g LOCK_FD=""

acquire_lock() {
    local lock_file="${LOCK_FILE:-/var/run/gniza.lock}"
    local lock_dir; lock_dir=$(dirname "$lock_file")
    mkdir -p "$lock_dir" || die "Cannot create lock directory: $lock_dir"

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
