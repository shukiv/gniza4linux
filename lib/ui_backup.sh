#!/usr/bin/env bash
# gniza4linux/lib/ui_backup.sh — Backup TUI

[[ -n "${_GNIZA4LINUX_UI_BACKUP_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_BACKUP_LOADED=1

ui_backup_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Backup" \
            "SINGLE" "Backup single target" \
            "ALL" "Backup all targets" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            SINGLE) ui_backup_wizard ;;
            ALL)    _ui_backup_all ;;
            BACK)   return 0 ;;
        esac
    done
}

ui_backup_wizard() {
    if ! has_targets; then
        ui_msgbox "No targets configured. Please add a target first."
        return 0
    fi

    local -a items=()
    local targets
    targets=$(list_targets)
    while IFS= read -r t; do
        items+=("$t" "Target: $t")
    done <<< "$targets"

    local target
    target=$(ui_menu "Select Target" "${items[@]}") || return 0

    local remote=""
    if has_remotes; then
        local -a ritems=("DEFAULT" "Use default/all remotes")
        local remotes
        remotes=$(list_remotes)
        while IFS= read -r r; do
            ritems+=("$r" "Remote: $r")
        done <<< "$remotes"

        remote=$(ui_menu "Select Remote" "${ritems[@]}") || return 0
        [[ "$remote" == "DEFAULT" ]] && remote=""
    fi

    local confirm_msg="Run backup?\n\nTarget: $target"
    [[ -n "$remote" ]] && confirm_msg+="\nRemote: $remote"
    confirm_msg+="\n"

    ui_yesno "$confirm_msg" || return 0

    _ui_run_backup "$target" "$remote"
}

_ui_backup_all() {
    if ! has_targets; then
        ui_msgbox "No targets configured."
        return 0
    fi

    ui_yesno "Backup ALL targets now?" || return 0

    local targets
    targets=$(list_targets)
    local count=0 total=0
    total=$(echo "$targets" | wc -l)

    local output=""
    while IFS= read -r t; do
        ((count++))
        local pct=$(( count * 100 / total ))
        echo "$pct"
        local result
        if result=$(gniza --cli backup --target="$t" 2>&1); then
            output+="$t: OK\n"
        else
            output+="$t: FAILED\n$result\n"
        fi
    done <<< "$targets" | ui_gauge "Backing up all targets..."

    ui_msgbox "Backup Results:\n\n$output"
}

_ui_run_backup() {
    local target="$1"
    local remote="$2"

    local -a cmd_args=(gniza --cli backup "--target=$target")
    [[ -n "$remote" ]] && cmd_args+=("--remote=$remote")

    local tmpfile
    tmpfile=$(mktemp /tmp/gniza-backup-XXXXXX.log)

    (
        echo "10"
        if "${cmd_args[@]}" > "$tmpfile" 2>&1; then
            echo "100"
        else
            echo "100"
        fi
    ) | ui_gauge "Backing up target: $target"

    if [[ -s "$tmpfile" ]]; then
        ui_textbox "$tmpfile"
    else
        ui_msgbox "Backup of '$target' completed."
    fi

    rm -f "$tmpfile"
}
