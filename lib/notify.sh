#!/usr/bin/env bash
# gniza4linux/lib/notify.sh — Email notifications (SMTP via curl or legacy mail/sendmail)

[[ -n "${_GNIZA4LINUX_NOTIFY_LOADED:-}" ]] && return 0
_GNIZA4LINUX_NOTIFY_LOADED=1

_log_notification() {
    local channel="$1"
    local status="$2"
    local dest="$3"
    local subject="$4"
    local log_file="${LOG_DIR:-/var/log/gniza}/notification.log"
    local timestamp; timestamp=$(date +"%Y-%m-%d %H:%M:%S")
    echo "${timestamp} | ${channel} | ${status} | ${dest} | ${subject}" >> "$log_file" 2>/dev/null
}

_log_email() {
    # Backward compatibility wrapper
    _log_notification "email" "$@"
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

_json_escape() {
    # Properly escape a string for JSON using python3 or jq
    local text="$1"
    if command -v python3 &>/dev/null; then
        python3 -c "import json,sys; print(json.dumps(sys.stdin.read()), end='')" <<< "$text"
    elif command -v jq &>/dev/null; then
        printf '%s' "$text" | jq -Rs '.'
    else
        # Fallback: escape critical chars (quotes, backslashes, newlines)
        printf '"%s"' "$(printf '%s' "$text" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | sed '$ s/\\n$//')"
    fi
}

_send_via_telegram() {
    local subject="$1"
    local body="$2"
    local token="${TELEGRAM_BOT_TOKEN:-}"
    local chat_id="${TELEGRAM_CHAT_ID:-}"

    [[ -z "$token" || -z "$chat_id" ]] && return 1

    local text="*${subject}*

${body}"
    # Truncate to Telegram's 4096 char limit
    text="${text:0:4096}"

    local escaped_text escaped_chatid
    escaped_text=$(_json_escape "$text")
    escaped_chatid=$(_json_escape "$chat_id")

    local payload="{\"chat_id\":${escaped_chatid},\"text\":${escaped_text},\"parse_mode\":\"Markdown\"}"

    local output
    output=$(curl --silent --show-error --connect-timeout 30 --max-time 60 \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "https://api.telegram.org/bot${token}/sendMessage" 2>&1)
    local rc=$?

    if (( rc != 0 )); then
        log_error "Telegram delivery failed (curl exit code: $rc): $output"
    fi
    return $rc
}

_send_via_webhook() {
    local subject="$1"
    local body="$2"
    local url="${WEBHOOK_URL:-}"
    local wtype="${WEBHOOK_TYPE:-slack}"

    [[ -z "$url" ]] && return 1

    local text="${subject}

${body}"
    local escaped_text
    escaped_text=$(_json_escape "$text")
    local payload

    case "$wtype" in
        discord)
            payload="{\"content\":${escaped_text}}"
            ;;
        *)
            payload="{\"text\":${escaped_text}}"
            ;;
    esac

    local output
    output=$(curl --silent --show-error --connect-timeout 30 --max-time 60 \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$url" 2>&1)
    local rc=$?

    if (( rc != 0 )); then
        log_error "Webhook delivery failed (curl exit code: $rc): $output"
    fi
    return $rc
}

_send_via_ntfy() {
    local subject="$1"
    local body="$2"
    local is_failure="${3:-false}"
    local url="${NTFY_URL:-}"
    local token="${NTFY_TOKEN:-}"
    local priority="${NTFY_PRIORITY:-default}"

    [[ -z "$url" ]] && return 1

    [[ "$is_failure" == "true" ]] && priority="high"

    local -a curl_args=(
        'curl' '--silent' '--show-error'
        '--connect-timeout' '30' '--max-time' '60'
        '-H' "Title: ${subject}"
        '-H' "Priority: ${priority}"
    )

    [[ -n "$token" ]] && curl_args+=('-H' "Authorization: Bearer ${token}")

    curl_args+=('-d' "$body" "$url")

    local output
    output=$("${curl_args[@]}" 2>&1)
    local rc=$?

    if (( rc != 0 )); then
        log_error "ntfy delivery failed (curl exit code: $rc): $output"
    fi
    return $rc
}

_send_via_healthcheck() {
    local is_success="${1:-true}"
    local url="${HEALTHCHECKS_URL:-}"

    [[ -z "$url" ]] && return 1

    url="${url%/}"
    [[ "$is_success" != "true" ]] && url="${url}/fail"

    local output
    output=$(curl --silent --show-error --connect-timeout 30 --max-time 60 "$url" 2>&1)
    local rc=$?

    if (( rc != 0 )); then
        log_error "Healthcheck ping failed (curl exit code: $rc): $output"
    fi
    return $rc
}

send_notification() {
    local subject="$1"
    local body="$2"
    local success="${3:-true}"

    case "${NOTIFY_ON:-$DEFAULT_NOTIFY_ON}" in
        never) return 0 ;;
        failure) [[ "$success" == "true" ]] && return 0 ;;
        always) ;;
    esac

    local hostname; hostname=$(hostname -f)
    local full_subject="[gniza] [$hostname] $subject"
    local is_failure="false"
    [[ "$success" != "true" ]] && is_failure="true"

    local any_sent=false

    # Email
    if [[ -n "${NOTIFY_EMAIL:-}" ]]; then
        log_debug "Sending email notification to $NOTIFY_EMAIL"
        if [[ -n "${SMTP_HOST:-}" ]]; then
            _send_via_smtp "$full_subject" "$body"
        else
            _send_via_legacy "$full_subject" "$body"
        fi
        local rc=$?
        if (( rc == 0 )); then
            _log_notification "email" "OK" "$NOTIFY_EMAIL" "$full_subject"
            any_sent=true
        else
            _log_notification "email" "FAIL" "$NOTIFY_EMAIL" "$full_subject"
        fi
    fi

    # Telegram
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
        log_debug "Sending Telegram notification to chat $TELEGRAM_CHAT_ID"
        _send_via_telegram "$full_subject" "$body"
        local rc=$?
        if (( rc == 0 )); then
            _log_notification "telegram" "OK" "$TELEGRAM_CHAT_ID" "$full_subject"
            any_sent=true
        else
            _log_notification "telegram" "FAIL" "$TELEGRAM_CHAT_ID" "$full_subject"
        fi
    fi

    # Webhook
    if [[ -n "${WEBHOOK_URL:-}" ]]; then
        log_debug "Sending webhook notification to $WEBHOOK_URL"
        _send_via_webhook "$full_subject" "$body"
        local rc=$?
        if (( rc == 0 )); then
            _log_notification "webhook" "OK" "$WEBHOOK_URL" "$full_subject"
            any_sent=true
        else
            _log_notification "webhook" "FAIL" "$WEBHOOK_URL" "$full_subject"
        fi
    fi

    # ntfy
    if [[ -n "${NTFY_URL:-}" ]]; then
        log_debug "Sending ntfy notification to $NTFY_URL"
        _send_via_ntfy "$full_subject" "$body" "$is_failure"
        local rc=$?
        if (( rc == 0 )); then
            _log_notification "ntfy" "OK" "$NTFY_URL" "$full_subject"
            any_sent=true
        else
            _log_notification "ntfy" "FAIL" "$NTFY_URL" "$full_subject"
        fi
    fi

    # Healthchecks.io
    if [[ -n "${HEALTHCHECKS_URL:-}" ]]; then
        log_debug "Pinging healthcheck at $HEALTHCHECKS_URL"
        _send_via_healthcheck "$success"
        local rc=$?
        if (( rc == 0 )); then
            _log_notification "healthcheck" "OK" "$HEALTHCHECKS_URL" "$full_subject"
            any_sent=true
        else
            _log_notification "healthcheck" "FAIL" "$HEALTHCHECKS_URL" "$full_subject"
        fi
    fi

    [[ "$any_sent" == "true" ]] && log_debug "Notification(s) sent" || log_debug "No notification channels configured"
    return 0
}
