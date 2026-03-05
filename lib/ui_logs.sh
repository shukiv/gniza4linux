#!/usr/bin/env bash
# gniza4linux/lib/ui_logs.sh — Log viewer TUI

[[ -n "${_GNIZA4LINUX_UI_LOGS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_LOGS_LOADED=1

ui_logs_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Logs" \
            "VIEW" "View log files" \
            "STATUS" "Show backup status" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            VIEW)   _ui_logs_view ;;
            STATUS) ui_logs_status ;;
            BACK)   return 0 ;;
        esac
    done
}

_ui_logs_view() {
    local log_dir="${LOG_DIR:-/var/log/gniza}"

    if [[ ! -d "$log_dir" ]]; then
        ui_msgbox "Log directory does not exist: $log_dir"
        return 0
    fi

    local -a items=()
    local logs
    logs=$(ls -1t "$log_dir"/gniza-*.log 2>/dev/null | head -20)

    if [[ -z "$logs" ]]; then
        ui_msgbox "No log files found."
        return 0
    fi

    while IFS= read -r f; do
        local fname
        fname=$(basename "$f")
        local fsize
        fsize=$(stat -c%s "$f" 2>/dev/null || echo "0")
        items+=("$fname" "$(human_size "$fsize")")
    done <<< "$logs"
    items+=("BACK" "Return")

    local selected
    selected=$(ui_menu "Log Files (recent first)" "${items[@]}") || return 0

    [[ "$selected" == "BACK" ]] && return 0

    local filepath="$log_dir/$selected"
    if [[ -f "$filepath" ]]; then
        ui_textbox "$filepath"
    else
        ui_msgbox "Log file not found: $filepath"
    fi
}

ui_logs_status() {
    local log_dir="${LOG_DIR:-/var/log/gniza}"
    local status_msg="Backup Status Overview\n"
    status_msg+="=====================\n\n"

    # Last backup time
    local latest_log
    latest_log=$(ls -1t "$log_dir"/gniza-*.log 2>/dev/null | head -1)
    if [[ -n "$latest_log" ]]; then
        local log_date
        log_date=$(stat -c%y "$latest_log" 2>/dev/null | cut -d. -f1)
        status_msg+="Last log: $log_date\n"

        # Last result
        local last_line
        last_line=$(tail -1 "$latest_log" 2>/dev/null)
        status_msg+="Last entry: $last_line\n"
    else
        status_msg+="No backup logs found.\n"
    fi

    # Disk usage
    if [[ -d "$log_dir" ]]; then
        local du_output
        du_output=$(du -sh "$log_dir" 2>/dev/null | cut -f1)
        status_msg+="\nLog disk usage: ${du_output:-unknown}\n"
    fi

    # Log count
    local log_count
    log_count=$(ls -1 "$log_dir"/gniza-*.log 2>/dev/null | wc -l)
    status_msg+="Log files: $log_count\n"

    ui_msgbox "$status_msg"
}
