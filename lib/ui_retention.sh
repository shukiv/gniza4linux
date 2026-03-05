#!/usr/bin/env bash
# gniza4linux/lib/ui_retention.sh — Retention cleanup TUI

[[ -n "${_GNIZA4LINUX_UI_RETENTION_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_RETENTION_LOADED=1

ui_retention_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Retention" \
            "SINGLE" "Run cleanup for single target" \
            "ALL" "Run cleanup for all targets" \
            "CONFIG" "Configure retention count" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            SINGLE) _ui_retention_single ;;
            ALL)    _ui_retention_all ;;
            CONFIG) _ui_retention_config ;;
            BACK)   return 0 ;;
        esac
    done
}

_ui_retention_single() {
    if ! has_targets; then
        ui_msgbox "No targets configured."
        return 0
    fi

    local -a items=()
    local targets
    targets=$(list_targets)
    while IFS= read -r t; do
        items+=("$t" "Target: $t")
    done <<< "$targets"

    local target
    target=$(ui_menu "Select Target for Cleanup" "${items[@]}") || return 0

    ui_yesno "Run retention cleanup for target '$target'?" || return 0

    local tmpfile
    tmpfile=$(mktemp /tmp/gniza-retention-XXXXXX.log)

    (
        echo "10"
        if gniza --cli retention --target="$target" > "$tmpfile" 2>&1; then
            echo "100"
        else
            echo "100"
        fi
    ) | ui_gauge "Running retention cleanup: $target"

    if [[ -s "$tmpfile" ]]; then
        ui_textbox "$tmpfile"
    else
        ui_msgbox "Retention cleanup for '$target' completed."
    fi

    rm -f "$tmpfile"
}

_ui_retention_all() {
    if ! has_targets; then
        ui_msgbox "No targets configured."
        return 0
    fi

    ui_yesno "Run retention cleanup for ALL targets?" || return 0

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
        if result=$(gniza --cli retention --target="$t" 2>&1); then
            output+="$t: OK\n"
        else
            output+="$t: FAILED\n$result\n"
        fi
    done <<< "$targets" | ui_gauge "Running retention cleanup..."

    ui_msgbox "Retention Results:\n\n$output"
}

_ui_retention_config() {
    local current="${RETENTION_COUNT:-$DEFAULT_RETENTION_COUNT}"
    local new_count
    new_count=$(ui_inputbox "Retention Config" "Number of snapshots to keep (current: $current):" "$current") || return 0

    if [[ ! "$new_count" =~ ^[0-9]+$ ]] || (( new_count < 1 )); then
        ui_msgbox "Retention count must be a positive integer."
        return 0
    fi

    local config_file="$CONFIG_DIR/gniza.conf"
    if [[ -f "$config_file" ]] && grep -q "^RETENTION_COUNT=" "$config_file"; then
        sed -i "s/^RETENTION_COUNT=.*/RETENTION_COUNT=\"$new_count\"/" "$config_file"
    else
        echo "RETENTION_COUNT=\"$new_count\"" >> "$config_file"
    fi

    RETENTION_COUNT="$new_count"
    ui_msgbox "Retention count set to $new_count."
}
