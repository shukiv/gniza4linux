#!/usr/bin/env bash
# gniza4linux/lib/ui_common.sh — Gum TUI wrappers

[[ -n "${_GNIZA4LINUX_UI_COMMON_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_COMMON_LOADED=1

# Theme
readonly _GUM_ACCENT="212"
readonly _GUM_CURSOR="▸ "

# ── Internal: tag-description mapping ─────────────────────────
# gum returns the selected display text, not a separate tag.
# To handle duplicate descriptions, we append a zero-width space
# marker per item (U+200B repeated i times) to guarantee uniqueness,
# then strip the markers from the result to find the index.
#
# Alternatively we use a simpler approach: display "tag  description"
# and split on the double-space to extract the tag.
# Tags in gniza are always short identifiers without spaces.

_gum_fmt_items() {
    local -n _tags=$1 _descs=$2
    local i
    for i in "${!_tags[@]}"; do
        printf '%s\n' "${_tags[$i]}  ${_descs[$i]}"
    done
}

_gum_extract_tag() {
    local line="$1"
    echo "${line%%  *}"
}

# ── Menu (tag/description pairs) ─────────────────────────────
# Usage: ui_menu "Title" "TAG1" "Desc 1" "TAG2" "Desc 2" ...
# Returns the selected TAG.
ui_menu() {
    local title="$1"; shift
    local -a tags=() descs=()
    while [[ $# -ge 2 ]]; do
        tags+=("$1")
        descs+=("$2")
        shift 2
    done

    local result
    result=$(_gum_fmt_items tags descs | gum choose \
        --header "$title" \
        --header.foreground "$_GUM_ACCENT" \
        --cursor.foreground "$_GUM_ACCENT" \
        --cursor "$_GUM_CURSOR") || return 1

    _gum_extract_tag "$result"
}

# ── Checklist (tag/description/status triplets, multi-select) ─
# Usage: ui_checklist "Title" "TAG1" "Desc 1" "ON" "TAG2" "Desc 2" "OFF" ...
# Returns space-separated quoted tags: "TAG1" "TAG2"
ui_checklist() {
    local title="$1"; shift
    local -a tags=() descs=() selected=()
    while [[ $# -ge 3 ]]; do
        tags+=("$1")
        descs+=("$2")
        [[ "$3" == "ON" ]] && selected+=("${1}  ${2}")
        shift 3
    done

    local -a sel_args=()
    local s
    for s in "${selected[@]}"; do
        sel_args+=(--selected "$s")
    done

    local result
    result=$(_gum_fmt_items tags descs | gum choose --no-limit \
        --header "$title" \
        --header.foreground "$_GUM_ACCENT" \
        --cursor.foreground "$_GUM_ACCENT" \
        --cursor "$_GUM_CURSOR" \
        "${sel_args[@]}") || return 1

    local output=""
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        local tag
        tag=$(_gum_extract_tag "$line")
        [[ -n "$output" ]] && output+=" "
        output+="\"$tag\""
    done <<< "$result"
    echo "$output"
}

# ── Radiolist (tag/description/status triplets, single select) ─
# Usage: ui_radiolist "Title" "TAG1" "Desc 1" "ON" "TAG2" "Desc 2" "OFF" ...
# Returns the selected TAG.
ui_radiolist() {
    local title="$1"; shift
    local -a tags=() descs=()
    local preselected=""
    while [[ $# -ge 3 ]]; do
        tags+=("$1")
        descs+=("$2")
        [[ "$3" == "ON" ]] && preselected="${1}  ${2}"
        shift 3
    done

    local -a sel_args=()
    [[ -n "$preselected" ]] && sel_args=(--selected "$preselected")

    local result
    result=$(_gum_fmt_items tags descs | gum choose \
        --header "$title" \
        --header.foreground "$_GUM_ACCENT" \
        --cursor.foreground "$_GUM_ACCENT" \
        --cursor "$_GUM_CURSOR" \
        "${sel_args[@]}") || return 1

    _gum_extract_tag "$result"
}

# ── Input box ─────────────────────────────────────────────────
ui_inputbox() {
    local title="$1"
    local prompt="$2"
    local default="${3:-}"

    gum input \
        --header "$prompt" \
        --header.foreground "$_GUM_ACCENT" \
        --value "$default" \
        --width 60 || return 1
}

# ── Yes/No confirmation ──────────────────────────────────────
ui_yesno() {
    local prompt="$1"
    gum confirm "$(printf '%b' "$prompt")" \
        --affirmative "Yes" \
        --negative "No"
}

# ── Message box ───────────────────────────────────────────────
ui_msgbox() {
    local msg="$1"
    echo ""
    printf '%b' "$msg" | gum style \
        --border rounded \
        --border-foreground "$_GUM_ACCENT" \
        --padding "1 2" \
        --margin "0 2"
    echo ""
    read -rsp "  Press any key to continue..." -n1 < /dev/tty
    echo ""
}

# ── Progress gauge (reads percentage lines from stdin) ────────
ui_gauge() {
    local prompt="$1"
    while IFS= read -r pct; do
        [[ "$pct" =~ ^[0-9]+$ ]] || continue
        local filled=$(( pct / 5 ))
        local empty=$(( 20 - filled ))
        local bar=""
        local i
        for ((i=0; i<filled; i++)); do bar+="█"; done
        for ((i=0; i<empty; i++)); do bar+="░"; done
        printf "\r  %s [%s] %s%%" "$prompt" "$bar" "$pct"
    done
    printf "\033[2K\r  %s [████████████████████] done\n" "$prompt"
}

# ── Text file viewer ─────────────────────────────────────────
ui_textbox() {
    local filepath="$1"
    gum pager < "$filepath"
}

# ── Password input ────────────────────────────────────────────
ui_password() {
    local prompt="$1"
    gum input \
        --password \
        --header "$prompt" \
        --header.foreground "$_GUM_ACCENT" \
        --width 60 || return 1
}
