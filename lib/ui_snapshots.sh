#!/usr/bin/env bash
# gniza4linux/lib/ui_snapshots.sh — Snapshot browsing TUI

[[ -n "${_GNIZA4LINUX_UI_SNAPSHOTS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_SNAPSHOTS_LOADED=1

ui_snapshots_menu() {
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
    target=$(ui_menu "Select Target" "${titems[@]}") || return 0

    # Select remote
    if ! has_remotes; then
        ui_msgbox "No remotes configured."
        return 0
    fi

    local -a ritems=()
    local remotes
    remotes=$(list_remotes)
    while IFS= read -r r; do
        ritems+=("$r" "Remote: $r")
    done <<< "$remotes"

    local remote
    remote=$(ui_menu "Select Remote" "${ritems[@]}") || return 0

    load_remote "$remote" || { ui_msgbox "Failed to load remote '$remote'."; return 0; }

    # List snapshots
    while true; do
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
        sitems+=("BACK" "Return")

        local snapshot
        snapshot=$(ui_menu "Snapshots: $target @ $remote" "${sitems[@]}") || return 0

        [[ "$snapshot" == "BACK" ]] && return 0

        # Snapshot detail menu
        while true; do
            local snap_dir
            snap_dir=$(get_snapshot_dir "$target")
            local meta_info="Snapshot: $snapshot\nTarget: $target\nRemote: $remote"

            # Try to read meta.json
            local meta_content=""
            if [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
                if [[ -f "$snap_dir/$snapshot/meta.json" ]]; then
                    meta_content=$(cat "$snap_dir/$snapshot/meta.json" 2>/dev/null)
                fi
            fi
            [[ -n "$meta_content" ]] && meta_info+="\n\n$meta_content"

            local action
            action=$(ui_menu "Snapshot: $snapshot" \
                "DETAILS" "View details" \
                "DELETE" "Delete snapshot" \
                "BACK" "Back to list") || break

            case "$action" in
                DETAILS)
                    ui_msgbox "$meta_info"
                    ;;
                DELETE)
                    if ui_yesno "Delete snapshot '$snapshot'?\nThis cannot be undone."; then
                        local snap_path_del
                        snap_path_del=$(get_snapshot_dir "$target")
                        local del_ok=false
                        if _is_rclone_mode; then
                            rclone_purge "targets/${target}/snapshots/${snapshot}" 2>/dev/null && del_ok=true
                        elif [[ "${REMOTE_TYPE:-ssh}" == "local" ]]; then
                            rm -rf "$snap_path_del/$snapshot" 2>/dev/null && del_ok=true
                        else
                            remote_exec "rm -rf '$snap_path_del/$snapshot'" 2>/dev/null && del_ok=true
                        fi
                        if [[ "$del_ok" == "true" ]]; then
                            ui_msgbox "Snapshot '$snapshot' deleted."
                        else
                            ui_msgbox "Failed to delete snapshot '$snapshot'."
                        fi
                        break
                    fi
                    ;;
                BACK) break ;;
            esac
        done
    done
}
