#!/usr/bin/env bash
# gniza4linux/lib/ui_schedule.sh — Schedule management TUI

[[ -n "${_GNIZA4LINUX_UI_SCHEDULE_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_SCHEDULE_LOADED=1

ui_schedule_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Schedules" \
            "LIST" "Show current schedules" \
            "ADD" "Add schedule" \
            "DELETE" "Delete schedule" \
            "INSTALL" "Install schedules to crontab" \
            "REMOVE" "Remove schedules from crontab" \
            "SHOW" "Show crontab entries" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            LIST)    _ui_schedule_list ;;
            ADD)     _ui_schedule_add ;;
            DELETE)  _ui_schedule_delete ;;
            INSTALL) _ui_schedule_install ;;
            REMOVE)  _ui_schedule_remove ;;
            SHOW)    _ui_schedule_show_cron ;;
            BACK)    return 0 ;;
        esac
    done
}

_ui_schedule_list() {
    if ! has_schedules; then
        ui_msgbox "No schedules configured."
        return 0
    fi

    local schedules
    schedules=$(list_schedules)
    local info="Configured Schedules:\n\n"

    while IFS= read -r sname; do
        [[ -z "$sname" ]] && continue
        load_schedule "$sname" 2>/dev/null || continue
        info+="[$sname]\n"
        info+="  Type: ${SCHEDULE:-not set}\n"
        info+="  Time: ${SCHEDULE_TIME:-02:00}\n"
        [[ -n "${SCHEDULE_DAY:-}" ]] && info+="  Day: $SCHEDULE_DAY\n"
        [[ -n "${SCHEDULE_REMOTES:-}" ]] && info+="  Remotes: $SCHEDULE_REMOTES\n"
        [[ -n "${SCHEDULE_TARGETS:-}" ]] && info+="  Targets: $SCHEDULE_TARGETS\n"
        info+="\n"
    done <<< "$schedules"

    ui_msgbox "$info"
}

_ui_schedule_add() {
    local name
    name=$(ui_inputbox "Add Schedule" "Schedule name:" "") || return 0
    [[ -z "$name" ]] && return 0

    if ! validate_target_name "$name" 2>/dev/null; then
        ui_msgbox "Invalid name. Must start with a letter, max 32 chars, [a-zA-Z0-9_-]."
        return 0
    fi

    local conf="$CONFIG_DIR/schedules.d/${name}.conf"
    if [[ -f "$conf" ]]; then
        ui_msgbox "Schedule '$name' already exists."
        return 0
    fi

    local stype
    stype=$(ui_radiolist "Schedule Type" \
        "hourly" "Every hour" "OFF" \
        "daily" "Once a day" "ON" \
        "weekly" "Once a week" "OFF" \
        "monthly" "Once a month" "OFF" \
        "custom" "Custom cron expression" "OFF") || return 0

    local stime="02:00"
    if [[ "$stype" != "hourly" && "$stype" != "custom" ]]; then
        stime=$(ui_inputbox "Schedule Time" "Time (HH:MM, 24h format):" "02:00") || return 0
    fi

    local sday=""
    if [[ "$stype" == "weekly" ]]; then
        sday=$(ui_inputbox "Day of Week" "Day (0=Sun, 1=Mon, ..., 6=Sat):" "0") || return 0
    elif [[ "$stype" == "monthly" ]]; then
        sday=$(ui_inputbox "Day of Month" "Day (1-28):" "1") || return 0
    fi

    local scron=""
    if [[ "$stype" == "custom" ]]; then
        scron=$(ui_inputbox "Custom Cron" "Enter 5-field cron expression:" "0 2 * * *") || return 0
    fi

    local stargets=""
    stargets=$(ui_inputbox "Targets" "Target names (comma-separated, empty=all):" "") || return 0

    local sremotes=""
    sremotes=$(ui_inputbox "Remotes" "Remote names (comma-separated, empty=all):" "") || return 0

    cat > "$conf" <<EOF
# gniza schedule: $name
SCHEDULE="$stype"
SCHEDULE_TIME="$stime"
SCHEDULE_DAY="$sday"
SCHEDULE_CRON="$scron"
TARGETS="$stargets"
REMOTES="$sremotes"
EOF
    chmod 600 "$conf"

    ui_msgbox "Schedule '$name' created.\n\nRun 'Install schedules to crontab' to activate."
}

_ui_schedule_delete() {
    if ! has_schedules; then
        ui_msgbox "No schedules configured."
        return 0
    fi

    local -a items=()
    local schedules
    schedules=$(list_schedules)
    while IFS= read -r s; do
        items+=("$s" "Schedule: $s")
    done <<< "$schedules"

    local selected
    selected=$(ui_menu "Delete Schedule" "${items[@]}") || return 0

    if ui_yesno "Delete schedule '$selected'?"; then
        rm -f "$CONFIG_DIR/schedules.d/${selected}.conf"
        ui_msgbox "Schedule '$selected' deleted."
    fi
}

_ui_schedule_install() {
    if ! has_schedules; then
        ui_msgbox "No schedules configured. Add a schedule first."
        return 0
    fi

    ui_yesno "Install all schedules to crontab?" || return 0

    local result
    if result=$(install_schedules 2>&1); then
        ui_msgbox "Schedules installed.\n\n$result"
    else
        ui_msgbox "Failed to install schedules.\n\n$result"
    fi
}

_ui_schedule_remove() {
    ui_yesno "Remove all gniza schedule entries from crontab?" || return 0

    local result
    if result=$(remove_schedules 2>&1); then
        ui_msgbox "$result"
    else
        ui_msgbox "Failed to remove schedules.\n\n$result"
    fi
}

_ui_schedule_show_cron() {
    local result
    result=$(show_schedules 2>&1)
    ui_msgbox "$result"
}
