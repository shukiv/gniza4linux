#!/usr/bin/env bash
# gniza4linux/lib/notify.sh — Email notifications (SMTP via curl or legacy mail/sendmail)

[[ -n "${_GNIZA4LINUX_NOTIFY_LOADED:-}" ]] && return 0
_GNIZA4LINUX_NOTIFY_LOADED=1

_log_email() {
    local status="$1"
    local recipients="$2"
    local subject="$3"
    local email_log="${LOG_DIR:-/var/log/gniza}/email.log"
    local timestamp; timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    echo "${timestamp} | ${status} | ${recipients} | ${subject}" >> "$email_log" 2>/dev/null
}

_send_via_smtp() {
    local subject="$1"
    local body="$2"

    local from="${SMTP_FROM:-$SMTP_USER}"
    if [[ -z "$from" ]]; then
        log_error "SMTP_FROM or SMTP_USER must be set for SMTP delivery"
        return 1
    fi

    # Build the RFC 2822 message
    local message=""
    message+="From: $from"$'\r\n'
    message+="To: $NOTIFY_EMAIL"$'\r\n'
    message+="Subject: $subject"$'\r\n'
    message+="Content-Type: text/plain; charset=UTF-8"$'\r\n'
    message+="Date: $(date -R)"$'\r\n'
    message+=$'\r\n'
    message+="$body"

    # Build curl command
    local -a curl_args=(
        'curl' '--silent' '--show-error'
        '--connect-timeout' '30'
        '--max-time' '60'
    )

    # Protocol URL based on security setting
    case "${SMTP_SECURITY:-tls}" in
        ssl)
            curl_args+=("--url" "smtps://${SMTP_HOST}:${SMTP_PORT}")
            ;;
        tls)
            curl_args+=("--url" "smtp://${SMTP_HOST}:${SMTP_PORT}" "--ssl-reqd")
            ;;
        none)
            curl_args+=("--url" "smtp://${SMTP_HOST}:${SMTP_PORT}")
            ;;
    esac

    # Auth credentials
    if [[ -n "${SMTP_USER:-}" ]]; then
        curl_args+=("--user" "${SMTP_USER}:${SMTP_PASSWORD}")
    fi

    # Sender
    curl_args+=("--mail-from" "$from")

    # Recipients (split NOTIFY_EMAIL on commas)
    local -a recipients
    IFS=',' read -ra recipients <<< "$NOTIFY_EMAIL"
    local rcpt
    for rcpt in "${recipients[@]}"; do
        rcpt="${rcpt## }"  # trim leading space
        rcpt="${rcpt%% }"  # trim trailing space
        [[ -n "$rcpt" ]] && curl_args+=("--mail-rcpt" "$rcpt")
    done

    # Upload the message from stdin
    curl_args+=("-T" "-")

    log_debug "Sending via SMTP to ${SMTP_HOST}:${SMTP_PORT} (${SMTP_SECURITY})"

    local curl_output
    curl_output=$(echo "$message" | "${curl_args[@]}" 2>&1)
    local rc=$?

    if (( rc == 0 )); then
        return 0
    else
        log_error "SMTP delivery failed (curl exit code: $rc): $curl_output"
        return 1
    fi
}

_send_via_legacy() {
    local subject="$1"
    local body="$2"

    # Split comma-separated emails for mail command
    local -a recipients
    IFS=',' read -ra recipients <<< "$NOTIFY_EMAIL"

    if command -v mail &>/dev/null; then
        echo "$body" | mail -s "$subject" "${recipients[@]}"
    elif command -v sendmail &>/dev/null; then
        {
            echo "To: $NOTIFY_EMAIL"
            echo "Subject: $subject"
            echo "Content-Type: text/plain; charset=UTF-8"
            echo ""
            echo "$body"
        } | sendmail -t
    else
        log_warn "No mail command available, cannot send notification"
        return 1
    fi
    return 0
}

send_notification() {
    local subject="$1"
    local body="$2"
    local success="${3:-true}"

    # Check if notifications are configured
    [[ -z "${NOTIFY_EMAIL:-}" ]] && return 0

    case "${NOTIFY_ON:-$DEFAULT_NOTIFY_ON}" in
        never) return 0 ;;
        failure) [[ "$success" == "true" ]] && return 0 ;;
        always) ;;
    esac

    local hostname; hostname=$(hostname -f)
    local full_subject="[gniza] [$hostname] $subject"

    log_debug "Sending notification to $NOTIFY_EMAIL: $full_subject"

    if [[ -n "${SMTP_HOST:-}" ]]; then
        _send_via_smtp "$full_subject" "$body"
    else
        _send_via_legacy "$full_subject" "$body"
    fi

    local rc=$?
    if (( rc == 0 )); then
        log_debug "Notification sent"
        _log_email "OK" "$NOTIFY_EMAIL" "$full_subject"
    else
        _log_email "FAIL" "$NOTIFY_EMAIL" "$full_subject"
    fi
    return $rc
}
