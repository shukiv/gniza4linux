#!/usr/bin/env bash
# gniza4linux/lib/ui_wizard.sh — First-time setup wizard

[[ -n "${_GNIZA4LINUX_UI_WIZARD_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_WIZARD_LOADED=1

ui_first_run_wizard() {
    # Step 1: Welcome
    ui_msgbox "Welcome to gniza Backup Manager!\n\nThis wizard will help you set up your first backup:\n\n  1. Configure a backup destination (remote)\n  2. Define what to back up (target)\n  3. Optionally run your first backup\n\nPress OK to start, or Cancel to skip." \
        || return 0

    # Step 2: Create first remote
    ui_msgbox "Step 1 of 3: Configure Backup Destination\n\nChoose where your backups will be stored:\n  - SSH server\n  - Local directory (USB/NFS)\n  - Amazon S3\n  - Google Drive"

    local remote_created=false
    while ! $remote_created; do
        ui_remote_add
        if has_remotes; then
            remote_created=true
        else
            if ! ui_yesno "No remote was created.\n\nWould you like to try again?"; then
                ui_msgbox "You can configure remotes later from the main menu.\n\nSetup wizard exiting."
                return 0
            fi
        fi
    done

    # Step 3: Create first target
    ui_msgbox "Step 2 of 3: Define Backup Target\n\nChoose a name for your backup profile and select the folders you want to back up."

    local target_created=false
    while ! $target_created; do
        ui_target_add
        if has_targets; then
            target_created=true
        else
            if ! ui_yesno "No target was created.\n\nWould you like to try again?"; then
                ui_msgbox "You can configure targets later from the main menu.\n\nSetup wizard exiting."
                return 0
            fi
        fi
    done

    # Step 4: Optionally run first backup
    local target
    target=$(list_targets | head -1)
    local remote
    remote=$(list_remotes | head -1)

    if ui_yesno "Step 3 of 3: Run First Backup?\n\nTarget: $target\nRemote: $remote\n\nRun your first backup now?"; then
        _ui_run_backup "$target" "$remote"
    fi

    # Done
    ui_msgbox "Setup complete!\n\nYou can manage your backups from the main menu:\n  - Add more targets and remotes\n  - Schedule automatic backups\n  - Browse and restore snapshots"
}
