#!/usr/bin/env bash
# gniza4linux/lib/utils.sh — Core utility functions

[[ -n "${_GNIZA4LINUX_UTILS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UTILS_LOADED=1

die() {
    local code="${2:-$EXIT_FATAL}"
    echo "${C_RED}FATAL: $1${C_RESET}" >&2
    exit "$code"
}

timestamp() {
    date -u +"%Y-%m-%dT%H%M%S"
}

human_size() {
    local bytes="$1"
    if (( bytes >= 1073741824 )); then
        local whole=$(( bytes / 1073741824 ))
        local frac=$(( (bytes % 1073741824) * 10 / 1073741824 ))
        printf "%d.%d GB" "$whole" "$frac"
    elif (( bytes >= 1048576 )); then
        local whole=$(( bytes / 1048576 ))
        local frac=$(( (bytes % 1048576) * 10 / 1048576 ))
        printf "%d.%d MB" "$whole" "$frac"
    elif (( bytes >= 1024 )); then
        local whole=$(( bytes / 1024 ))
        local frac=$(( (bytes % 1024) * 10 / 1024 ))
        printf "%d.%d KB" "$whole" "$frac"
    else
        printf "%d B" "$bytes"
    fi
}

human_duration() {
    local seconds="$1"
    if (( seconds >= 3600 )); then
        printf "%dh %dm %ds" $((seconds/3600)) $((seconds%3600/60)) $((seconds%60))
    elif (( seconds >= 60 )); then
        printf "%dm %ds" $((seconds/60)) $((seconds%60))
    else
        printf "%ds" "$seconds"
    fi
}

require_cmd() {
    command -v "$1" &>/dev/null || die "Required command not found: $1"
}

validate_timestamp() {
    local ts="$1"
    if [[ ! "$ts" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}$ ]]; then
        log_error "Invalid timestamp format: $ts (expected YYYY-MM-DDTHHMMSS)"
        return 1
    fi
}

validate_target_name() {
    local name="$1"
    if [[ ! "$name" =~ ^[a-zA-Z][a-zA-Z0-9_-]{0,31}$ ]]; then
        log_error "Invalid target name: $name (must match ^[a-zA-Z][a-zA-Z0-9_-]{0,31}\$)"
        return 1
    fi
}

validate_path() {
    local path="$1"
    if [[ "$path" != /* ]]; then
        log_error "Path must be absolute: $path"
        return 1
    fi
    if [[ "$path" == *..* ]]; then
        log_error "Path must not contain '..': $path"
        return 1
    fi
    if [[ ! -e "$path" ]]; then
        log_error "Path does not exist: $path"
        return 1
    fi
}

detect_mode() {
    if [[ $EUID -eq 0 ]]; then
        GNIZA_MODE="root"
        CONFIG_DIR="/etc/gniza"
        LOG_DIR="/var/log/gniza"
        WORK_DIR="/usr/local/gniza/workdir"
        LOCK_FILE="/var/run/gniza.lock"
    else
        GNIZA_MODE="user"
        CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gniza"
        LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gniza/log"
        WORK_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/gniza/workdir"
        LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/gniza-${EUID}.lock"
    fi
    export GNIZA_MODE CONFIG_DIR LOG_DIR WORK_DIR LOCK_FILE
}

ensure_dirs() {
    mkdir -p "$CONFIG_DIR"          || die "Cannot create config directory: $CONFIG_DIR"
    mkdir -p "$CONFIG_DIR/targets.d"   || die "Cannot create targets.d directory"
    mkdir -p "$CONFIG_DIR/remotes.d"   || die "Cannot create remotes.d directory"
    mkdir -p "$CONFIG_DIR/schedules.d" || die "Cannot create schedules.d directory"
    mkdir -p "$LOG_DIR"             || die "Cannot create log directory: $LOG_DIR"
    mkdir -p "$WORK_DIR"            || die "Cannot create work directory: $WORK_DIR"
}
