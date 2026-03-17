#!/usr/bin/env bash
# gniza4linux/lib/logging.sh — Per-run log files, log_info/warn/error/debug

[[ -n "${_GNIZA4LINUX_LOGGING_LOADED:-}" ]] && return 0
_GNIZA4LINUX_LOGGING_LOADED=1

declare -g LOG_FILE=""
# fd 3 = original stderr for console output (before any redirect)
exec 3>&2

_log_level_num() {
    case "$1" in
        debug) echo 0 ;;
        info)  echo 1 ;;
        warn)  echo 2 ;;
        error) echo 3 ;;
        *)     echo 1 ;;
    esac
}

init_logging() {
    # When tracked by daemon/web job system, don't create a separate log file
    # (all output is already captured in the job's log file)
    if [[ -n "${GNIZA_DAEMON_TRACKED:-}" ]]; then
        LOG_FILE=""
        _CONFIGURED_LOG_LEVEL_NUM=$(_log_level_num "${LOG_LEVEL:-$DEFAULT_LOG_LEVEL}")
        return 0
    fi

    local log_dir="${LOG_DIR:-/var/log/gniza}"
    mkdir -p "$log_dir" || die "Cannot create log directory: $log_dir"

    LOG_FILE="$log_dir/gniza-$(date +%Y%m%d-%H%M%S).log"
    touch "$LOG_FILE" || die "Cannot write to log file: $LOG_FILE"

    # Cache the configured log level number to avoid repeated subshell calls in _log()
    _CONFIGURED_LOG_LEVEL_NUM=$(_log_level_num "${LOG_LEVEL:-$DEFAULT_LOG_LEVEL}")

    # Redirect stdout+stderr into the log file so rsync progress output
    # (and any other subprocess output) is captured for the web UI.
    # fd 3 (saved above) preserves original stderr for console messages.
    exec >>"$LOG_FILE" 2>&1

    # On unexpected exit, ensure the log captures why
    trap '_gniza_log_exit_trap' EXIT

    # Clean old logs
    local retain="${LOG_RETAIN:-$DEFAULT_LOG_RETAIN}"
    find "$log_dir" -name "gniza-*.log" -mtime +"$retain" -delete 2>/dev/null || true
}

_gniza_log_exit_trap() {
    local rc="${1:-$?}"
    if [[ -n "${LOG_FILE:-}" && -f "$LOG_FILE" && ! -s "$LOG_FILE" ]]; then
        # SIGPIPE (141) with empty log = cron pipe noise; clean up silently
        if [[ $rc -eq 141 || $rc -eq 0 ]]; then
            rm -f "$LOG_FILE" 2>/dev/null
        else
            echo "[$(date -u +"%d/%m/%Y %H:%M:%S")] [ERROR] Process exited with code $rc (no other output captured)" >> "$LOG_FILE"
        fi
    fi
}

_log() {
    local level="$1"; shift
    local msg="$*"

    local ts; ts=$(date -u +"%d/%m/%Y %H:%M:%S")
    local upper="${level^^}"
    local line="[$ts] [$upper] $msg"

    local level_num; level_num=$(_log_level_num "$level")
    local configured_num="${_CONFIGURED_LOG_LEVEL_NUM:-1}"

    # Log file: always write info/warn/error; debug only when LOG_LEVEL=debug
    if [[ -n "$LOG_FILE" ]]; then
        if [[ "$level" != "debug" ]] || (( level_num >= configured_num )); then
            echo "$line" >> "$LOG_FILE"
        fi
    fi

    # Console: only print if level meets configured threshold
    (( level_num < configured_num )) && return 0

    # Write to fd 3 (original stderr, preserved before redirect)
    case "$level" in
        error) echo "${C_RED}${line}${C_RESET}" >&3 ;;
        warn)  echo "${C_YELLOW}${line}${C_RESET}" >&3 ;;
        info)  echo "${line}" >&3 ;;
        debug) echo "${C_BLUE}${line}${C_RESET}" >&3 ;;
    esac
}

log_info()  { _log info "$@"; }
log_warn()  { _log warn "$@"; }
log_error() { _log error "$@"; }
log_debug() { _log debug "$@"; }
