#!/usr/bin/env bash
# gniza4linux/lib/ui_common.sh — Whiptail TUI wrappers with consistent sizing

[[ -n "${_GNIZA4LINUX_UI_COMMON_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_COMMON_LOADED=1

readonly WHIPTAIL_TITLE="gniza Backup Manager"

ui_calc_size() {
    local term_h="${LINES:-24}"
    local term_w="${COLUMNS:-80}"
    local h w
    h=$(( term_h - 4 ))
    w=$(( term_w - 4 ))
    (( h > 20 )) && h=20
    (( w > 76 )) && w=76
    echo "$h" "$w"
}

_ui_backtitle() {
    echo "gniza v${GNIZA4LINUX_VERSION}"
}

ui_menu() {
    local title="$1"; shift
    local -a items=("$@")
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"
    local menu_h=$(( h - 7 ))
    (( menu_h < 3 )) && menu_h=3

    local result
    result=$(whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --menu "$title" "$h" "$w" "$menu_h" "${items[@]}" 3>&1 1>&2 2>&3) || return 1
    echo "$result"
}

ui_checklist() {
    local title="$1"; shift
    local -a items=("$@")
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"
    local list_h=$(( h - 7 ))
    (( list_h < 3 )) && list_h=3

    local result
    result=$(whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --checklist "$title" "$h" "$w" "$list_h" "${items[@]}" 3>&1 1>&2 2>&3) || return 1
    echo "$result"
}

ui_radiolist() {
    local title="$1"; shift
    local -a items=("$@")
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"
    local list_h=$(( h - 7 ))
    (( list_h < 3 )) && list_h=3

    local result
    result=$(whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --radiolist "$title" "$h" "$w" "$list_h" "${items[@]}" 3>&1 1>&2 2>&3) || return 1
    echo "$result"
}

ui_inputbox() {
    local title="$1"
    local prompt="$2"
    local default="${3:-}"
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"

    local result
    result=$(whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --inputbox "$prompt" "$h" "$w" "$default" 3>&1 1>&2 2>&3) || return 1
    echo "$result"
}

ui_yesno() {
    local prompt="$1"
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"

    whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --yesno "$prompt" "$h" "$w" 3>&1 1>&2 2>&3
}

ui_msgbox() {
    local msg="$1"
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"

    whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --msgbox "$msg" "$h" "$w" 3>&1 1>&2 2>&3
}

ui_gauge() {
    local prompt="$1"
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"

    whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --gauge "$prompt" "$h" "$w" 0 3>&1 1>&2 2>&3
}

ui_textbox() {
    local filepath="$1"
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"

    whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --textbox "$filepath" "$h" "$w" 3>&1 1>&2 2>&3
}

ui_password() {
    local prompt="$1"
    local size; size=$(ui_calc_size)
    local h w
    read -r h w <<< "$size"

    local result
    result=$(whiptail --title "$WHIPTAIL_TITLE" --backtitle "$(_ui_backtitle)" \
        --passwordbox "$prompt" "$h" "$w" 3>&1 1>&2 2>&3) || return 1
    echo "$result"
}
