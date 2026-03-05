#!/usr/bin/env bash
# gniza4linux/lib/ui_targets.sh — Target management TUI

[[ -n "${_GNIZA4LINUX_UI_TARGETS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_TARGETS_LOADED=1

ui_targets_menu() {
    while true; do
        local -a items=()
        local targets
        targets=$(list_targets)
        if [[ -n "$targets" ]]; then
            while IFS= read -r t; do
                items+=("$t" "Target: $t")
            done <<< "$targets"
        fi
        items+=("ADD" "Add new target")
        items+=("BACK" "Return to main menu")

        local choice
        choice=$(ui_menu "Targets" "${items[@]}") || return 0

        case "$choice" in
            ADD)  ui_target_add ;;
            BACK) return 0 ;;
            *)
                local action
                action=$(ui_menu "Target: $choice" \
                    "EDIT" "Edit target" \
                    "DELETE" "Delete target" \
                    "BACK" "Back") || continue
                case "$action" in
                    EDIT)   ui_target_edit "$choice" ;;
                    DELETE) ui_target_delete "$choice" ;;
                    BACK)   continue ;;
                esac
                ;;
        esac
    done
}

ui_target_add() {
    local name
    name=$(ui_inputbox "Add Target" "Enter target name (letters, digits, _ -). A folder browser will open next:" "") || return 0
    [[ -z "$name" ]] && return 0

    if ! validate_target_name "$name" 2>/dev/null; then
        ui_msgbox "Invalid target name. Must start with a letter and contain only letters, digits, underscore, or hyphen (max 32 chars)."
        return 0
    fi

    if [[ -f "$CONFIG_DIR/targets.d/${name}.conf" ]]; then
        ui_msgbox "Target '$name' already exists."
        return 0
    fi

    local folders
    folders=$(ui_target_folder_picker) || return 0
    [[ -z "$folders" ]] && { ui_msgbox "No folders selected. Target not created."; return 0; }

    local exclude
    exclude=$(ui_inputbox "Add Target" "Exclude patterns (comma-separated, e.g. *.log,*.tmp):" "") || exclude=""

    local remote
    remote=$(ui_inputbox "Add Target" "Remote override (leave empty for default):" "") || remote=""

    create_target "$name" "$folders" "$exclude" "$remote"
    ui_msgbox "Target '$name' created successfully."
}

ui_target_edit() {
    local name="$1"
    load_target "$name" || { ui_msgbox "Failed to load target '$name'."; return 0; }

    while true; do
        local choice
        choice=$(ui_menu "Edit Target: $name" \
            "FOLDERS" "Folders: ${TARGET_FOLDERS}" \
            "EXCLUDE" "Exclude: ${TARGET_EXCLUDE:-none}" \
            "REMOTE" "Remote: ${TARGET_REMOTE:-default}" \
            "ENABLED" "Enabled: ${TARGET_ENABLED}" \
            "SAVE" "Save and return" \
            "BACK" "Cancel") || return 0

        case "$choice" in
            FOLDERS)
                local folders
                folders=$(ui_target_folder_picker "$TARGET_FOLDERS") || continue
                [[ -n "$folders" ]] && TARGET_FOLDERS="$folders"
                ;;
            EXCLUDE)
                local exclude
                exclude=$(ui_inputbox "Edit Exclude" "Exclude patterns (comma-separated):" "$TARGET_EXCLUDE") || continue
                TARGET_EXCLUDE="$exclude"
                ;;
            REMOTE)
                local remote
                remote=$(ui_inputbox "Edit Remote" "Remote override (leave empty for default):" "$TARGET_REMOTE") || continue
                TARGET_REMOTE="$remote"
                ;;
            ENABLED)
                if ui_yesno "Enable this target?"; then
                    TARGET_ENABLED="yes"
                else
                    TARGET_ENABLED="no"
                fi
                ;;
            SAVE)
                create_target "$name" "$TARGET_FOLDERS" "$TARGET_EXCLUDE" "$TARGET_REMOTE" \
                    "$TARGET_RETENTION" "$TARGET_PRE_HOOK" "$TARGET_POST_HOOK" "$TARGET_ENABLED"
                ui_msgbox "Target '$name' saved."
                return 0
                ;;
            BACK) return 0 ;;
        esac
    done
}

ui_target_delete() {
    local name="$1"
    if ui_yesno "Delete target '$name'? This cannot be undone."; then
        delete_target "$name"
        ui_msgbox "Target '$name' deleted."
    fi
}

ui_target_folder_picker() {
    local existing="${1:-}"
    local -a folders=()

    if [[ -n "$existing" ]]; then
        IFS=',' read -ra folders <<< "$existing"
    fi

    # If no existing folders, open file browser immediately
    if [[ ${#folders[@]} -eq 0 ]]; then
        local path
        path=$(gum file --directory --header "Select folder to back up (Esc when done)" \
            --cursor.foreground "$_GUM_ACCENT" --height 15 /) || return 1
        [[ -z "$path" ]] && return 1
        [[ "$path" != /* ]] && path="/$path"
        folders+=("$path")
    fi

    while true; do
        # Show current selection and options
        local selected_list=""
        local i
        for i in "${!folders[@]}"; do
            selected_list+="  $(( i + 1 )). ${folders[$i]}\n"
        done

        local action
        action=$(ui_menu "Selected folders:\n${selected_list}" \
            "ADD" "Add another folder" \
            "REMOVE" "Remove a folder" \
            "DONE" "Done — use these ${#folders[@]} folder(s)") || return 1

        case "$action" in
            ADD)
                local path
                path=$(gum file --directory --header "Select folder to back up" \
                    --cursor.foreground "$_GUM_ACCENT" --height 15 /) || continue
                [[ -z "$path" ]] && continue
                [[ "$path" != /* ]] && path="/$path"
                # Avoid duplicates
                local dup=false
                for f in "${folders[@]}"; do
                    [[ "$f" == "$path" ]] && dup=true
                done
                if $dup; then
                    ui_msgbox "Folder '$path' is already selected."
                else
                    folders+=("$path")
                fi
                ;;
            REMOVE)
                local -a rm_items=()
                local j=0
                for f in "${folders[@]}"; do
                    rm_items+=("$j" "$f")
                    ((j++))
                done
                local idx
                idx=$(ui_menu "Remove which folder?" "${rm_items[@]}") || continue
                unset 'folders[idx]'
                folders=("${folders[@]}")
                if [[ ${#folders[@]} -eq 0 ]]; then
                    ui_msgbox "All folders removed. Please select at least one."
                    local path
                    path=$(gum file --directory --header "Select folder to back up" \
                        --cursor.foreground "$_GUM_ACCENT" --height 15 /) || return 1
                    [[ -z "$path" ]] && return 1
                    [[ "$path" != /* ]] && path="/$path"
                    folders+=("$path")
                fi
                ;;
            DONE)
                local result
                result=$(IFS=','; echo "${folders[*]}")
                echo "$result"
                return 0
                ;;
        esac
    done
}
