#!/usr/bin/env bash
# gniza4linux/lib/ui_main.sh — Main menu loop

[[ -n "${_GNIZA4LINUX_UI_MAIN_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_MAIN_LOADED=1

ui_main_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Main Menu" \
            "1" "Backup" \
            "2" "Restore" \
            "3" "Targets" \
            "4" "Remotes" \
            "5" "Snapshots" \
            "6" "Retention" \
            "7" "Schedules" \
            "8" "Logs" \
            "9" "Settings" \
            "Q" "Quit") || break

        case "$choice" in
            1)  ui_backup_menu ;;
            2)  ui_restore_menu ;;
            3)  ui_targets_menu ;;
            4)  ui_remotes_menu ;;
            5)  ui_snapshots_menu ;;
            6)  ui_retention_menu ;;
            7)  ui_schedule_menu ;;
            8)  ui_logs_menu ;;
            9)  ui_settings_menu ;;
            Q)  break ;;
        esac
    done
}
