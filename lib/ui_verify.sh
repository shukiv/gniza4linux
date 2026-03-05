#!/usr/bin/env bash
# gniza4linux/lib/ui_verify.sh — Backup verification TUI

[[ -n "${_GNIZA4LINUX_UI_VERIFY_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_VERIFY_LOADED=1

ui_verify_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Verify" \
            "SINGLE" "Verify single target" \
            "ALL" "Verify all targets" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            SINGLE) _ui_verify_single ;;
            ALL)    _ui_verify_all ;;
            BACK)   return 0 ;;
        esac
    done
}

_ui_verify_single() {
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
    target=$(ui_menu "Select Target to Verify" "${items[@]}") || return 0

    local tmpfile
    tmpfile=$(mktemp /tmp/gniza-verify-XXXXXX.log)

    (
        echo "10"
        if gniza --cli verify --target="$target" > "$tmpfile" 2>&1; then
            echo "100"
        else
            echo "100"
        fi
    ) | ui_gauge "Verifying target: $target"

    if [[ -s "$tmpfile" ]]; then
        ui_textbox "$tmpfile"
    else
        ui_msgbox "Verification of '$target' completed successfully."
    fi

    rm -f "$tmpfile"
}

_ui_verify_all() {
    if ! has_targets; then
        ui_msgbox "No targets configured."
        return 0
    fi

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
        if result=$(gniza --cli verify --target="$t" 2>&1); then
            output+="$t: OK\n"
        else
            output+="$t: FAILED\n$result\n"
        fi
    done <<< "$targets" | ui_gauge "Verifying all targets..."

    ui_msgbox "Verification Results:\n\n$output"
}
