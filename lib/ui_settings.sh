#!/usr/bin/env bash
# gniza4linux/lib/ui_settings.sh — Settings editor TUI

[[ -n "${_GNIZA4LINUX_UI_SETTINGS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_SETTINGS_LOADED=1

ui_settings_menu() {
    local config_file="$CONFIG_DIR/gniza.conf"

    while true; do
        local choice
        choice=$(ui_menu "Settings" \
            "LOGLEVEL" "Log level: ${LOG_LEVEL:-$DEFAULT_LOG_LEVEL}" \
            "EMAIL" "Notification email: ${NOTIFY_EMAIL:-none}" \
            "SMTP_HOST" "SMTP host: ${SMTP_HOST:-none}" \
            "SMTP_PORT" "SMTP port: ${SMTP_PORT:-$DEFAULT_SMTP_PORT}" \
            "SMTP_USER" "SMTP user: ${SMTP_USER:-none}" \
            "SMTP_PASS" "SMTP password: ****" \
            "SMTP_FROM" "SMTP from: ${SMTP_FROM:-none}" \
            "SMTP_SEC" "SMTP security: ${SMTP_SECURITY:-$DEFAULT_SMTP_SECURITY}" \
            "RETENTION" "Default retention: ${RETENTION_COUNT:-$DEFAULT_RETENTION_COUNT}" \
            "BWLIMIT" "Default BW limit: ${BWLIMIT:-$DEFAULT_BWLIMIT} KB/s" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            LOGLEVEL)
                local val
                val=$(ui_radiolist "Log Level" \
                    "debug" "Debug" "$([ "${LOG_LEVEL:-info}" = "debug" ] && echo ON || echo OFF)" \
                    "info" "Info" "$([ "${LOG_LEVEL:-info}" = "info" ] && echo ON || echo OFF)" \
                    "warn" "Warning" "$([ "${LOG_LEVEL:-info}" = "warn" ] && echo ON || echo OFF)" \
                    "error" "Error" "$([ "${LOG_LEVEL:-info}" = "error" ] && echo ON || echo OFF)") || continue
                LOG_LEVEL="$val"
                _ui_settings_save "LOG_LEVEL" "$val" "$config_file"
                ;;
            EMAIL)
                local val
                val=$(ui_inputbox "Settings" "Notification email:" "${NOTIFY_EMAIL:-}") || continue
                NOTIFY_EMAIL="$val"
                _ui_settings_save "NOTIFY_EMAIL" "$val" "$config_file"
                ;;
            SMTP_HOST)
                local val
                val=$(ui_inputbox "Settings" "SMTP host:" "${SMTP_HOST:-}") || continue
                SMTP_HOST="$val"
                _ui_settings_save "SMTP_HOST" "$val" "$config_file"
                ;;
            SMTP_PORT)
                local val
                val=$(ui_inputbox "Settings" "SMTP port:" "${SMTP_PORT:-$DEFAULT_SMTP_PORT}") || continue
                SMTP_PORT="$val"
                _ui_settings_save "SMTP_PORT" "$val" "$config_file"
                ;;
            SMTP_USER)
                local val
                val=$(ui_inputbox "Settings" "SMTP user:" "${SMTP_USER:-}") || continue
                SMTP_USER="$val"
                _ui_settings_save "SMTP_USER" "$val" "$config_file"
                ;;
            SMTP_PASS)
                local val
                val=$(ui_password "SMTP password:") || continue
                SMTP_PASSWORD="$val"
                _ui_settings_save "SMTP_PASSWORD" "$val" "$config_file"
                ;;
            SMTP_FROM)
                local val
                val=$(ui_inputbox "Settings" "SMTP from address:" "${SMTP_FROM:-}") || continue
                SMTP_FROM="$val"
                _ui_settings_save "SMTP_FROM" "$val" "$config_file"
                ;;
            SMTP_SEC)
                local val
                val=$(ui_radiolist "SMTP Security" \
                    "tls" "TLS" "$([ "${SMTP_SECURITY:-tls}" = "tls" ] && echo ON || echo OFF)" \
                    "ssl" "SSL" "$([ "${SMTP_SECURITY:-tls}" = "ssl" ] && echo ON || echo OFF)" \
                    "none" "None" "$([ "${SMTP_SECURITY:-tls}" = "none" ] && echo ON || echo OFF)") || continue
                SMTP_SECURITY="$val"
                _ui_settings_save "SMTP_SECURITY" "$val" "$config_file"
                ;;
            RETENTION)
                local val
                val=$(ui_inputbox "Settings" "Default retention count:" "${RETENTION_COUNT:-$DEFAULT_RETENTION_COUNT}") || continue
                if [[ ! "$val" =~ ^[0-9]+$ ]] || (( val < 1 )); then
                    ui_msgbox "Retention count must be a positive integer."
                    continue
                fi
                RETENTION_COUNT="$val"
                _ui_settings_save "RETENTION_COUNT" "$val" "$config_file"
                ;;
            BWLIMIT)
                local val
                val=$(ui_inputbox "Settings" "Default bandwidth limit (KB/s, 0=unlimited):" "${BWLIMIT:-$DEFAULT_BWLIMIT}") || continue
                if [[ ! "$val" =~ ^[0-9]+$ ]]; then
                    ui_msgbox "Bandwidth limit must be a non-negative integer."
                    continue
                fi
                BWLIMIT="$val"
                _ui_settings_save "BWLIMIT" "$val" "$config_file"
                ;;
            BACK) return 0 ;;
        esac
    done
}

_ui_settings_save() {
    local key="$1"
    local value="$2"
    local config_file="$3"

    # Ensure config file exists
    [[ -f "$config_file" ]] || touch "$config_file"

    if grep -q "^${key}=" "$config_file"; then
        # Use awk to avoid sed delimiter injection issues
        local tmpconf
        tmpconf=$(mktemp)
        awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k{print k "=\"" v "\""; next} {print}' "$config_file" > "$tmpconf"
        mv "$tmpconf" "$config_file"
    else
        printf '%s="%s"\n' "$key" "$value" >> "$config_file"
    fi
}
