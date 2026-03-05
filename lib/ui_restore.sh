#!/usr/bin/env bash
# gniza4linux/lib/ui_restore.sh — Restore TUI

[[ -n "${_GNIZA4LINUX_UI_RESTORE_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_RESTORE_LOADED=1

ui_restore_menu() {
    while true; do
        local choice
        choice=$(ui_menu "Restore" \
            "TARGET" "Restore full target" \
            "FOLDER" "Restore single folder" \
            "BACK" "Return to main menu") || return 0

        case "$choice" in
            TARGET) ui_restore_wizard "full" ;;
            FOLDER) ui_restore_wizard "folder" ;;
            BACK)   return 0 ;;
        esac
    done
}

ui_restore_wizard() {
    local mode="$1"

    if ! has_targets; then
        ui_msgbox "No targets configured."
        return 0
    fi

    # Select target
    local -a titems=()
    local targets
    targets=$(list_targets)
    while IFS= read -r t; do
        titems+=("$t" "Target: $t")
    done <<< "$targets"

    local target
    target=$(ui_menu "Select Target to Restore" "${titems[@]}") || return 0

    # Select remote
    local remote=""
    if has_remotes; then
        local -a ritems=()
        local remotes
        remotes=$(list_remotes)
        while IFS= read -r r; do
            ritems+=("$r" "Remote: $r")
        done <<< "$remotes"

        remote=$(ui_menu "Select Remote" "${ritems[@]}") || return 0
    else
        ui_msgbox "No remotes configured."
        return 0
    fi

    # Load remote for snapshot listing
    load_remote "$remote" || { ui_msgbox "Failed to load remote '$remote'."; return 0; }

    # Select snapshot
    local snapshots
    snapshots=$(list_remote_snapshots "$target" 2>/dev/null)
    if [[ -z "$snapshots" ]]; then
        ui_msgbox "No snapshots found for target '$target' on remote '$remote'."
        return 0
    fi

    local -a sitems=()
    while IFS= read -r s; do
        sitems+=("$s" "Snapshot: $s")
    done <<< "$snapshots"

    local snapshot
    snapshot=$(ui_menu "Select Snapshot" "${sitems[@]}") || return 0

    # Restore location
    local restore_dest=""
    local restore_type
    restore_type=$(ui_radiolist "Restore Location" \
        "inplace" "Restore in-place (original location)" "ON" \
        "directory" "Restore to a different directory" "OFF") || return 0

    if [[ "$restore_type" == "directory" ]]; then
        restore_dest=$(ui_inputbox "Restore" "Enter destination directory:" "/tmp/restore") || return 0
        [[ -z "$restore_dest" ]] && { ui_msgbox "Destination is required."; return 0; }
    fi

    # Folder selection for single-folder mode
    local folder_arg=""
    if [[ "$mode" == "folder" ]]; then
        load_target "$target" || { ui_msgbox "Failed to load target."; return 0; }
        local -a fitems=()
        local folders
        folders=$(get_target_folders)
        while IFS= read -r f; do
            [[ -z "$f" ]] && continue
            fitems+=("$f" "$f")
        done <<< "$folders"

        if [[ ${#fitems[@]} -eq 0 ]]; then
            ui_msgbox "No folders defined in target '$target'."
            return 0
        fi

        folder_arg=$(ui_menu "Select Folder to Restore" "${fitems[@]}") || return 0
    fi

    # Confirm
    local confirm_msg="Restore snapshot?\n\nTarget: $target\nRemote: $remote\nSnapshot: $snapshot"
    [[ -n "$folder_arg" ]] && confirm_msg+="\nFolder: $folder_arg"
    if [[ "$restore_type" == "inplace" ]]; then
        confirm_msg+="\nLocation: In-place (original)"
    else
        confirm_msg+="\nLocation: $restore_dest"
    fi
    confirm_msg+="\n"

    ui_yesno "$confirm_msg" || return 0

    # Run restore
    local -a cmd_args=(gniza --cli restore "--target=$target" "--remote=$remote" "--snapshot=$snapshot")
    [[ -n "$restore_dest" ]] && cmd_args+=("--dest=$restore_dest")
    [[ -n "$folder_arg" ]] && cmd_args+=("--folder=$folder_arg")

    local tmpfile
    tmpfile=$(mktemp /tmp/gniza-restore-XXXXXX.log)

    (
        echo "10"
        if "${cmd_args[@]}" > "$tmpfile" 2>&1; then
            echo "100"
        else
            echo "100"
        fi
    ) | ui_gauge "Restoring target: $target"

    if [[ -s "$tmpfile" ]]; then
        ui_textbox "$tmpfile"
    else
        ui_msgbox "Restore of '$target' completed."
    fi

    rm -f "$tmpfile"
}
