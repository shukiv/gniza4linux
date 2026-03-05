#!/usr/bin/env bash
# gniza4linux/lib/ui_remotes.sh — Remote management TUI

[[ -n "${_GNIZA4LINUX_UI_REMOTES_LOADED:-}" ]] && return 0
_GNIZA4LINUX_UI_REMOTES_LOADED=1

ui_remotes_menu() {
    while true; do
        local -a items=()
        local remotes
        remotes=$(list_remotes)
        if [[ -n "$remotes" ]]; then
            while IFS= read -r r; do
                items+=("$r" "Remote: $r")
            done <<< "$remotes"
        fi
        items+=("ADD" "Add new remote")
        items+=("BACK" "Return to main menu")

        local choice
        choice=$(ui_menu "Remotes" "${items[@]}") || return 0

        case "$choice" in
            ADD)  ui_remote_add ;;
            BACK) return 0 ;;
            *)
                local action
                action=$(ui_menu "Remote: $choice" \
                    "EDIT" "Edit remote" \
                    "DELETE" "Delete remote" \
                    "TEST" "Test connection" \
                    "BACK" "Back") || continue
                case "$action" in
                    EDIT)   ui_remote_edit "$choice" ;;
                    DELETE) ui_remote_delete "$choice" ;;
                    TEST)   ui_remote_test "$choice" ;;
                    BACK)   continue ;;
                esac
                ;;
        esac
    done
}

ui_remote_add() {
    local name
    name=$(ui_inputbox "Add Remote" "Enter remote name (letters, digits, _ -):" "") || return 0
    [[ -z "$name" ]] && return 0

    if ! validate_target_name "$name" 2>/dev/null; then
        ui_msgbox "Invalid remote name. Must start with a letter and contain only letters, digits, underscore, or hyphen (max 32 chars)."
        return 0
    fi

    if [[ -f "$CONFIG_DIR/remotes.d/${name}.conf" ]]; then
        ui_msgbox "Remote '$name' already exists."
        return 0
    fi

    local rtype
    rtype=$(ui_radiolist "Remote Type" \
        "ssh" "SSH remote" "ON" \
        "local" "Local directory" "OFF" \
        "s3" "Amazon S3 / compatible" "OFF" \
        "gdrive" "Google Drive" "OFF") || return 0

    local conf="$CONFIG_DIR/remotes.d/${name}.conf"

    case "$rtype" in
        ssh)   _ui_remote_add_ssh "$name" "$conf" ;;
        local) _ui_remote_add_local "$name" "$conf" ;;
        s3)    _ui_remote_add_s3 "$name" "$conf" ;;
        gdrive) _ui_remote_add_gdrive "$name" "$conf" ;;
    esac
}

_ui_remote_add_ssh() {
    local name="$1" conf="$2"

    local host; host=$(ui_inputbox "SSH Remote" "Hostname or IP:" "") || return 0
    [[ -z "$host" ]] && { ui_msgbox "Host is required."; return 0; }

    local port; port=$(ui_inputbox "SSH Remote" "Port:" "$DEFAULT_REMOTE_PORT") || port="$DEFAULT_REMOTE_PORT"
    local user; user=$(ui_inputbox "SSH Remote" "Username:" "$DEFAULT_REMOTE_USER") || user="$DEFAULT_REMOTE_USER"
    local base; base=$(ui_inputbox "SSH Remote" "Base path on remote:" "$DEFAULT_REMOTE_BASE") || base="$DEFAULT_REMOTE_BASE"

    local auth_method
    auth_method=$(ui_radiolist "Authentication" \
        "key" "SSH key" "ON" \
        "password" "Password" "OFF") || auth_method="key"

    local key="" password=""
    if [[ "$auth_method" == "key" ]]; then
        key=$(ui_inputbox "SSH Remote" "Path to SSH key:" "$HOME/.ssh/id_rsa") || key=""
    else
        password=$(ui_password "Enter SSH password:") || password=""
    fi

    local bwlimit; bwlimit=$(ui_inputbox "SSH Remote" "Bandwidth limit (KB/s, 0=unlimited):" "$DEFAULT_BWLIMIT") || bwlimit="$DEFAULT_BWLIMIT"
    local retention; retention=$(ui_inputbox "SSH Remote" "Retention count:" "$DEFAULT_RETENTION_COUNT") || retention="$DEFAULT_RETENTION_COUNT"

    # Test connection before saving
    if ui_yesno "Test connection to ${user}@${host}:${port} before saving?"; then
        local test_result
        local -a ssh_cmd=(ssh -o BatchMode=yes -o ConnectTimeout=10 -p "$port")
        if [[ "$auth_method" == "key" && -n "$key" ]]; then
            ssh_cmd+=(-i "$key")
        fi
        ssh_cmd+=("${user}@${host}" "echo OK")
        if test_result=$("${ssh_cmd[@]}" 2>&1); then
            ui_msgbox "Connection successful!"
        else
            ui_msgbox "Connection failed:\n\n$test_result"
            if ! ui_yesno "Save remote anyway?"; then
                return 0
            fi
        fi
    fi

    cat > "$conf" <<EOF
REMOTE_TYPE="ssh"
REMOTE_HOST="$host"
REMOTE_PORT="$port"
REMOTE_USER="$user"
REMOTE_AUTH_METHOD="$auth_method"
REMOTE_KEY="$key"
REMOTE_PASSWORD="$password"
REMOTE_BASE="$base"
BWLIMIT="$bwlimit"
RETENTION_COUNT="$retention"
EOF
    chmod 600 "$conf"
    ui_msgbox "Remote '$name' created successfully."
}

_ui_remote_add_local() {
    local name="$1" conf="$2"

    local base; base=$(ui_inputbox "Local Remote" "Local backup directory:" "/backups") || return 0
    [[ -z "$base" ]] && { ui_msgbox "Directory is required."; return 0; }

    local retention; retention=$(ui_inputbox "Local Remote" "Retention count:" "$DEFAULT_RETENTION_COUNT") || retention="$DEFAULT_RETENTION_COUNT"

    # Test path exists
    if [[ -d "$base" ]]; then
        ui_msgbox "Directory '$base' exists and is accessible."
    else
        ui_msgbox "Directory '$base' does NOT exist yet.\nIt will be created during the first backup."
    fi

    cat > "$conf" <<EOF
REMOTE_TYPE="local"
REMOTE_BASE="$base"
RETENTION_COUNT="$retention"
EOF
    chmod 600 "$conf"
    ui_msgbox "Remote '$name' created successfully."
}

_ui_remote_add_s3() {
    local name="$1" conf="$2"

    local bucket; bucket=$(ui_inputbox "S3 Remote" "S3 Bucket name:" "") || return 0
    [[ -z "$bucket" ]] && { ui_msgbox "Bucket is required."; return 0; }

    local region; region=$(ui_inputbox "S3 Remote" "Region:" "$DEFAULT_S3_REGION") || region="$DEFAULT_S3_REGION"
    local endpoint; endpoint=$(ui_inputbox "S3 Remote" "Endpoint (leave empty for AWS):" "") || endpoint=""
    local access_key; access_key=$(ui_inputbox "S3 Remote" "Access Key ID:" "") || access_key=""
    local secret_key; secret_key=$(ui_password "Secret Access Key:") || secret_key=""
    local base; base=$(ui_inputbox "S3 Remote" "Base path in bucket:" "/backups") || base="/backups"
    local retention; retention=$(ui_inputbox "S3 Remote" "Retention count:" "$DEFAULT_RETENTION_COUNT") || retention="$DEFAULT_RETENTION_COUNT"

    # Test S3 connection before saving
    if command -v rclone &>/dev/null && ui_yesno "Test S3 connection before saving?"; then
        # Set globals temporarily for test_rclone_connection
        REMOTE_TYPE="s3" S3_BUCKET="$bucket" S3_REGION="$region" \
        S3_ENDPOINT="$endpoint" S3_ACCESS_KEY_ID="$access_key" \
        S3_SECRET_ACCESS_KEY="$secret_key" REMOTE_BASE="$base"
        local test_result
        if test_result=$(test_rclone_connection 2>&1); then
            ui_msgbox "S3 connection successful!"
        else
            ui_msgbox "S3 connection failed:\n\n$test_result"
            if ! ui_yesno "Save remote anyway?"; then
                return 0
            fi
        fi
    fi

    cat > "$conf" <<EOF
REMOTE_TYPE="s3"
S3_BUCKET="$bucket"
S3_REGION="$region"
S3_ENDPOINT="$endpoint"
S3_ACCESS_KEY_ID="$access_key"
S3_SECRET_ACCESS_KEY="$secret_key"
REMOTE_BASE="$base"
RETENTION_COUNT="$retention"
EOF
    chmod 600 "$conf"
    ui_msgbox "Remote '$name' created successfully."
}

_ui_remote_add_gdrive() {
    local name="$1" conf="$2"

    local sa_file; sa_file=$(ui_inputbox "Google Drive Remote" "Service account JSON file path:" "") || return 0
    [[ -z "$sa_file" ]] && { ui_msgbox "Service account file is required."; return 0; }

    local folder_id; folder_id=$(ui_inputbox "Google Drive Remote" "Root folder ID:" "") || folder_id=""
    local base; base=$(ui_inputbox "Google Drive Remote" "Base path:" "/backups") || base="/backups"
    local retention; retention=$(ui_inputbox "Google Drive Remote" "Retention count:" "$DEFAULT_RETENTION_COUNT") || retention="$DEFAULT_RETENTION_COUNT"

    # Test GDrive connection before saving
    if command -v rclone &>/dev/null && ui_yesno "Test Google Drive connection before saving?"; then
        REMOTE_TYPE="gdrive" GDRIVE_SERVICE_ACCOUNT_FILE="$sa_file" \
        GDRIVE_ROOT_FOLDER_ID="$folder_id" REMOTE_BASE="$base"
        local test_result
        if test_result=$(test_rclone_connection 2>&1); then
            ui_msgbox "Google Drive connection successful!"
        else
            ui_msgbox "Google Drive connection failed:\n\n$test_result"
            if ! ui_yesno "Save remote anyway?"; then
                return 0
            fi
        fi
    fi

    cat > "$conf" <<EOF
REMOTE_TYPE="gdrive"
GDRIVE_SERVICE_ACCOUNT_FILE="$sa_file"
GDRIVE_ROOT_FOLDER_ID="$folder_id"
REMOTE_BASE="$base"
RETENTION_COUNT="$retention"
EOF
    chmod 600 "$conf"
    ui_msgbox "Remote '$name' created successfully."
}

ui_remote_edit() {
    local name="$1"
    local conf="$CONFIG_DIR/remotes.d/${name}.conf"

    if [[ ! -f "$conf" ]]; then
        ui_msgbox "Remote '$name' not found."
        return 0
    fi

    load_remote "$name" || { ui_msgbox "Failed to load remote '$name'."; return 0; }

    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            while true; do
                local choice
                choice=$(ui_menu "Edit Remote: $name (SSH)" \
                    "HOST" "Host: ${REMOTE_HOST}" \
                    "PORT" "Port: ${REMOTE_PORT}" \
                    "USER" "User: ${REMOTE_USER}" \
                    "AUTH" "Auth: ${REMOTE_AUTH_METHOD}" \
                    "BASE" "Base: ${REMOTE_BASE}" \
                    "BWLIMIT" "BW Limit: ${BWLIMIT} KB/s" \
                    "RETENTION" "Retention: ${RETENTION_COUNT}" \
                    "SAVE" "Save and return" \
                    "BACK" "Cancel") || return 0

                case "$choice" in
                    HOST)      local v; v=$(ui_inputbox "Edit" "Hostname:" "$REMOTE_HOST") && REMOTE_HOST="$v" ;;
                    PORT)      local v; v=$(ui_inputbox "Edit" "Port:" "$REMOTE_PORT") && REMOTE_PORT="$v" ;;
                    USER)      local v; v=$(ui_inputbox "Edit" "User:" "$REMOTE_USER") && REMOTE_USER="$v" ;;
                    AUTH)
                        local v; v=$(ui_radiolist "Auth Method" \
                            "key" "SSH key" "$([ "$REMOTE_AUTH_METHOD" = "key" ] && echo ON || echo OFF)" \
                            "password" "Password" "$([ "$REMOTE_AUTH_METHOD" = "password" ] && echo ON || echo OFF)") && REMOTE_AUTH_METHOD="$v"
                        if [[ "$REMOTE_AUTH_METHOD" == "key" ]]; then
                            local k; k=$(ui_inputbox "Edit" "SSH key path:" "$REMOTE_KEY") && REMOTE_KEY="$k"
                        else
                            local p; p=$(ui_password "Enter SSH password:") && REMOTE_PASSWORD="$p"
                        fi
                        ;;
                    BASE)      local v; v=$(ui_inputbox "Edit" "Base path:" "$REMOTE_BASE") && REMOTE_BASE="$v" ;;
                    BWLIMIT)   local v; v=$(ui_inputbox "Edit" "BW Limit (KB/s):" "$BWLIMIT") && BWLIMIT="$v" ;;
                    RETENTION) local v; v=$(ui_inputbox "Edit" "Retention count:" "$RETENTION_COUNT") && RETENTION_COUNT="$v" ;;
                    SAVE)
                        cat > "$conf" <<EOF
REMOTE_TYPE="ssh"
REMOTE_HOST="$REMOTE_HOST"
REMOTE_PORT="$REMOTE_PORT"
REMOTE_USER="$REMOTE_USER"
REMOTE_AUTH_METHOD="$REMOTE_AUTH_METHOD"
REMOTE_KEY="$REMOTE_KEY"
REMOTE_PASSWORD="$REMOTE_PASSWORD"
REMOTE_BASE="$REMOTE_BASE"
BWLIMIT="$BWLIMIT"
RETENTION_COUNT="$RETENTION_COUNT"
EOF
                        chmod 600 "$conf"
                        ui_msgbox "Remote '$name' saved."
                        return 0
                        ;;
                    BACK) return 0 ;;
                esac
            done
            ;;
        local)
            while true; do
                local choice
                choice=$(ui_menu "Edit Remote: $name (Local)" \
                    "BASE" "Directory: ${REMOTE_BASE}" \
                    "RETENTION" "Retention: ${RETENTION_COUNT}" \
                    "SAVE" "Save and return" \
                    "BACK" "Cancel") || return 0

                case "$choice" in
                    BASE)      local v; v=$(ui_inputbox "Edit" "Directory:" "$REMOTE_BASE") && REMOTE_BASE="$v" ;;
                    RETENTION) local v; v=$(ui_inputbox "Edit" "Retention count:" "$RETENTION_COUNT") && RETENTION_COUNT="$v" ;;
                    SAVE)
                        cat > "$conf" <<EOF
REMOTE_TYPE="local"
REMOTE_BASE="$REMOTE_BASE"
RETENTION_COUNT="$RETENTION_COUNT"
EOF
                        chmod 600 "$conf"
                        ui_msgbox "Remote '$name' saved."
                        return 0
                        ;;
                    BACK) return 0 ;;
                esac
            done
            ;;
        s3)
            while true; do
                local choice
                choice=$(ui_menu "Edit Remote: $name (S3)" \
                    "BUCKET" "Bucket: ${S3_BUCKET}" \
                    "REGION" "Region: ${S3_REGION}" \
                    "ENDPOINT" "Endpoint: ${S3_ENDPOINT:-default}" \
                    "KEY" "Access Key: ${S3_ACCESS_KEY_ID:+****}" \
                    "SECRET" "Secret Key: ****" \
                    "BASE" "Base: ${REMOTE_BASE}" \
                    "RETENTION" "Retention: ${RETENTION_COUNT}" \
                    "SAVE" "Save and return" \
                    "BACK" "Cancel") || return 0

                case "$choice" in
                    BUCKET)    local v; v=$(ui_inputbox "Edit" "Bucket:" "$S3_BUCKET") && S3_BUCKET="$v" ;;
                    REGION)    local v; v=$(ui_inputbox "Edit" "Region:" "$S3_REGION") && S3_REGION="$v" ;;
                    ENDPOINT)  local v; v=$(ui_inputbox "Edit" "Endpoint:" "$S3_ENDPOINT") && S3_ENDPOINT="$v" ;;
                    KEY)       local v; v=$(ui_inputbox "Edit" "Access Key ID:" "$S3_ACCESS_KEY_ID") && S3_ACCESS_KEY_ID="$v" ;;
                    SECRET)    local v; v=$(ui_password "Secret Access Key:") && S3_SECRET_ACCESS_KEY="$v" ;;
                    BASE)      local v; v=$(ui_inputbox "Edit" "Base path:" "$REMOTE_BASE") && REMOTE_BASE="$v" ;;
                    RETENTION) local v; v=$(ui_inputbox "Edit" "Retention count:" "$RETENTION_COUNT") && RETENTION_COUNT="$v" ;;
                    SAVE)
                        cat > "$conf" <<EOF
REMOTE_TYPE="s3"
S3_BUCKET="$S3_BUCKET"
S3_REGION="$S3_REGION"
S3_ENDPOINT="$S3_ENDPOINT"
S3_ACCESS_KEY_ID="$S3_ACCESS_KEY_ID"
S3_SECRET_ACCESS_KEY="$S3_SECRET_ACCESS_KEY"
REMOTE_BASE="$REMOTE_BASE"
RETENTION_COUNT="$RETENTION_COUNT"
EOF
                        chmod 600 "$conf"
                        ui_msgbox "Remote '$name' saved."
                        return 0
                        ;;
                    BACK) return 0 ;;
                esac
            done
            ;;
        gdrive)
            while true; do
                local choice
                choice=$(ui_menu "Edit Remote: $name (GDrive)" \
                    "SA" "Service Account: ${GDRIVE_SERVICE_ACCOUNT_FILE}" \
                    "FOLDER" "Folder ID: ${GDRIVE_ROOT_FOLDER_ID:-none}" \
                    "BASE" "Base: ${REMOTE_BASE}" \
                    "RETENTION" "Retention: ${RETENTION_COUNT}" \
                    "SAVE" "Save and return" \
                    "BACK" "Cancel") || return 0

                case "$choice" in
                    SA)        local v; v=$(ui_inputbox "Edit" "Service account file:" "$GDRIVE_SERVICE_ACCOUNT_FILE") && GDRIVE_SERVICE_ACCOUNT_FILE="$v" ;;
                    FOLDER)    local v; v=$(ui_inputbox "Edit" "Root folder ID:" "$GDRIVE_ROOT_FOLDER_ID") && GDRIVE_ROOT_FOLDER_ID="$v" ;;
                    BASE)      local v; v=$(ui_inputbox "Edit" "Base path:" "$REMOTE_BASE") && REMOTE_BASE="$v" ;;
                    RETENTION) local v; v=$(ui_inputbox "Edit" "Retention count:" "$RETENTION_COUNT") && RETENTION_COUNT="$v" ;;
                    SAVE)
                        cat > "$conf" <<EOF
REMOTE_TYPE="gdrive"
GDRIVE_SERVICE_ACCOUNT_FILE="$GDRIVE_SERVICE_ACCOUNT_FILE"
GDRIVE_ROOT_FOLDER_ID="$GDRIVE_ROOT_FOLDER_ID"
REMOTE_BASE="$REMOTE_BASE"
RETENTION_COUNT="$RETENTION_COUNT"
EOF
                        chmod 600 "$conf"
                        ui_msgbox "Remote '$name' saved."
                        return 0
                        ;;
                    BACK) return 0 ;;
                esac
            done
            ;;
    esac
}

ui_remote_delete() {
    local name="$1"
    local conf="$CONFIG_DIR/remotes.d/${name}.conf"

    if [[ ! -f "$conf" ]]; then
        ui_msgbox "Remote '$name' not found."
        return 0
    fi

    if ui_yesno "Delete remote '$name'? This cannot be undone."; then
        rm -f "$conf"
        log_info "Deleted remote config: $conf"
        ui_msgbox "Remote '$name' deleted."
    fi
}

ui_remote_test() {
    local name="$1"
    load_remote "$name" || { ui_msgbox "Failed to load remote '$name'."; return 0; }

    local result
    case "${REMOTE_TYPE:-ssh}" in
        ssh)
            result=$(ssh -o BatchMode=yes -o ConnectTimeout=10 \
                -p "$REMOTE_PORT" -i "$REMOTE_KEY" \
                "${REMOTE_USER}@${REMOTE_HOST}" "echo OK" 2>&1) \
                && ui_msgbox "Connection to '$name' successful.\n\nResponse: $result" \
                || ui_msgbox "Connection to '$name' failed.\n\nError: $result"
            ;;
        local)
            if [[ -d "$REMOTE_BASE" ]]; then
                ui_msgbox "Local directory '$REMOTE_BASE' exists and is accessible."
            else
                ui_msgbox "Local directory '$REMOTE_BASE' does NOT exist."
            fi
            ;;
        s3|gdrive)
            if command -v rclone &>/dev/null; then
                # Use the proper rclone transport layer (temp config file, not CLI args)
                load_remote "$name" || { ui_msgbox "Failed to load remote."; break; }
                if result=$(test_rclone_connection 2>&1); then
                    ui_msgbox "${REMOTE_TYPE} connection to '$name' successful."
                else
                    ui_msgbox "${REMOTE_TYPE} connection to '$name' failed.\n\nError: $result"
                fi
            else
                ui_msgbox "rclone is not installed. Cannot test ${REMOTE_TYPE} connection."
            fi
            ;;
        *)
            ui_msgbox "Unknown remote type: ${REMOTE_TYPE}"
            ;;
    esac
}
