#!/usr/bin/env bash
# gniza4linux/lib/config.sh — Shell-variable config loading & validation

[[ -n "${_GNIZA4LINUX_CONFIG_LOADED:-}" ]] && return 0
_GNIZA4LINUX_CONFIG_LOADED=1

# Safe config parser — reads KEY=VALUE lines without executing arbitrary code.
# Only processes lines matching ^[A-Z_][A-Z_0-9]*= and strips surrounding quotes.
_safe_source_config() {
    local filepath="$1"
    local line key value
    while IFS= read -r line || [[ -n "$line" ]]; do
        # Skip blank lines and comments
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # Match KEY=VALUE (optional quotes)
        if [[ "$line" =~ ^([A-Z_][A-Z_0-9]*)=(.*) ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            # Strip surrounding double or single quotes
            if [[ "$value" =~ ^\"(.*)\"$ ]]; then
                value="${BASH_REMATCH[1]}"
            elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
                value="${BASH_REMATCH[1]}"
            fi
            declare -g "$key=$value"
        fi
    done < "$filepath"
}

load_config() {
    local config_file="${1:-$CONFIG_DIR/gniza.conf}"

    if [[ ! -f "$config_file" ]]; then
        die "Config file not found: $config_file (copy gniza.conf.example to $CONFIG_DIR/gniza.conf)"
    fi

    # Parse the config (safe key=value reader, no code execution)
    _safe_source_config "$config_file" || die "Failed to parse config file: $config_file"

    # Apply defaults for optional settings
    BACKUP_MODE="${BACKUP_MODE:-$DEFAULT_BACKUP_MODE}"
    BWLIMIT="${BWLIMIT:-$DEFAULT_BWLIMIT}"
    RETENTION_COUNT="${RETENTION_COUNT:-$DEFAULT_RETENTION_COUNT}"
    LOG_LEVEL="${LOG_LEVEL:-$DEFAULT_LOG_LEVEL}"
    LOG_RETAIN="${LOG_RETAIN:-$DEFAULT_LOG_RETAIN}"
    NOTIFY_EMAIL="${NOTIFY_EMAIL:-}"
    NOTIFY_ON="${NOTIFY_ON:-$DEFAULT_NOTIFY_ON}"
    SMTP_HOST="${SMTP_HOST:-}"
    SMTP_PORT="${SMTP_PORT:-$DEFAULT_SMTP_PORT}"
    SMTP_USER="${SMTP_USER:-}"
    SMTP_PASSWORD="${SMTP_PASSWORD:-}"
    SMTP_FROM="${SMTP_FROM:-}"
    SMTP_SECURITY="${SMTP_SECURITY:-$DEFAULT_SMTP_SECURITY}"
    SSH_TIMEOUT="${SSH_TIMEOUT:-$DEFAULT_SSH_TIMEOUT}"
    SSH_RETRIES="${SSH_RETRIES:-$DEFAULT_SSH_RETRIES}"
    RSYNC_EXTRA_OPTS="${RSYNC_EXTRA_OPTS:-}"
    RSYNC_COMPRESS="${RSYNC_COMPRESS:-$DEFAULT_RSYNC_COMPRESS}"
    RSYNC_CHECKSUM="${RSYNC_CHECKSUM:-$DEFAULT_RSYNC_CHECKSUM}"
    DISK_USAGE_THRESHOLD="${DISK_USAGE_THRESHOLD:-$DEFAULT_DISK_USAGE_THRESHOLD}"

    # WORK_DIR from detect_mode takes precedence — ignore config value
    # to prevent root-mode paths leaking into user-mode sessions.
    # Re-run detect_mode to restore the correct value if config overrode it.
    detect_mode

    # --debug flag overrides config
    [[ "${GNIZA4LINUX_DEBUG:-false}" == "true" ]] && LOG_LEVEL="debug"

    export BACKUP_MODE BWLIMIT RETENTION_COUNT
    export LOG_LEVEL LOG_RETAIN NOTIFY_EMAIL NOTIFY_ON
    export SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM SMTP_SECURITY
    export SSH_TIMEOUT SSH_RETRIES RSYNC_EXTRA_OPTS RSYNC_COMPRESS RSYNC_CHECKSUM DISK_USAGE_THRESHOLD
}

validate_config() {
    local errors=0

    # Per-remote validation is handled by validate_remote() in remotes.sh.
    # Here we only validate local/global settings.

    case "$BACKUP_MODE" in
        full|incremental) ;;
        *) log_error "BACKUP_MODE must be full|incremental, got: $BACKUP_MODE"; ((errors++)) || true ;;
    esac

    case "$NOTIFY_ON" in
        always|failure|never) ;;
        *) log_error "NOTIFY_ON must be always|failure|never, got: $NOTIFY_ON"; ((errors++)) || true ;;
    esac

    case "$LOG_LEVEL" in
        debug|info|warn|error) ;;
        *) log_error "LOG_LEVEL must be debug|info|warn|error, got: $LOG_LEVEL"; ((errors++)) || true ;;
    esac

    # SMTP validation (only when SMTP_HOST is set)
    if [[ -n "${SMTP_HOST:-}" ]]; then
        case "$SMTP_SECURITY" in
            tls|ssl|none) ;;
            *) log_error "SMTP_SECURITY must be tls|ssl|none, got: $SMTP_SECURITY"; ((errors++)) || true ;;
        esac

        if [[ -n "${SMTP_PORT:-}" ]] && { [[ ! "$SMTP_PORT" =~ ^[0-9]+$ ]] || (( SMTP_PORT < 1 || SMTP_PORT > 65535 )); }; then
            log_error "SMTP_PORT must be 1-65535, got: $SMTP_PORT"
            ((errors++)) || true
        fi
    fi

    # Validate numeric fields
    if [[ -n "${SSH_TIMEOUT:-}" ]] && [[ ! "$SSH_TIMEOUT" =~ ^[0-9]+$ ]]; then
        log_error "SSH_TIMEOUT must be a non-negative integer, got: $SSH_TIMEOUT"
        ((errors++)) || true
    fi

    if [[ -n "${SSH_RETRIES:-}" ]] && [[ ! "$SSH_RETRIES" =~ ^[0-9]+$ ]]; then
        log_error "SSH_RETRIES must be a non-negative integer, got: $SSH_RETRIES"
        ((errors++)) || true
    fi

    if [[ -n "${LOG_RETAIN:-}" ]] && [[ ! "$LOG_RETAIN" =~ ^[0-9]+$ ]]; then
        log_error "LOG_RETAIN must be a non-negative integer, got: $LOG_RETAIN"
        ((errors++)) || true
    fi

    if [[ -n "${BWLIMIT:-}" ]] && [[ ! "$BWLIMIT" =~ ^[0-9]+$ ]]; then
        log_error "BWLIMIT must be a non-negative integer (KB/s), got: $BWLIMIT"
        ((errors++)) || true
    fi

    if [[ -n "${RETENTION_COUNT:-}" ]] && [[ ! "$RETENTION_COUNT" =~ ^[0-9]+$ ]]; then
        log_error "RETENTION_COUNT must be a non-negative integer, got: $RETENTION_COUNT"
        ((errors++)) || true
    fi

    if [[ -n "${DISK_USAGE_THRESHOLD:-}" ]] && [[ ! "$DISK_USAGE_THRESHOLD" =~ ^[0-9]+$ ]]; then
        log_error "DISK_USAGE_THRESHOLD must be a non-negative integer (0-100), got: $DISK_USAGE_THRESHOLD"
        ((errors++)) || true
    fi

    # Validate RSYNC_EXTRA_OPTS characters (prevent flag injection)
    if [[ -n "${RSYNC_EXTRA_OPTS:-}" ]] && [[ ! "$RSYNC_EXTRA_OPTS" =~ ^[a-zA-Z0-9\ ._=/,-]+$ ]]; then
        log_error "RSYNC_EXTRA_OPTS contains invalid characters: $RSYNC_EXTRA_OPTS"
        ((errors++)) || true
    fi

    if (( errors > 0 )); then
        log_error "Configuration has $errors error(s)"
        return 1
    fi
    return 0
}
