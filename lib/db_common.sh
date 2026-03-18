#!/usr/bin/env bash
# gniza4linux/lib/db_common.sh — Shared database backup helpers (MySQL + PostgreSQL)

[[ -n "${_GNIZA4LINUX_DB_COMMON_LOADED:-}" ]] && return 0
_GNIZA4LINUX_DB_COMMON_LOADED=1

# Check if target source is remote (SSH).
# Returns 0 if remote, 1 if local.
_db_is_remote() {
    [[ "${TARGET_SOURCE_TYPE:-local}" == "ssh" ]]
}

# Build SSH command array for remote database operations.
# Usage: _db_build_ssh_args <nameref_array>
# Populates the referenced array with ssh command and arguments.
_db_build_ssh_args() {
    local -n _ssh_arr=$1
    _ssh_arr=(ssh -o StrictHostKeyChecking=accept-new -o "ConnectTimeout=${SSH_TIMEOUT:-30}" -p "${TARGET_SOURCE_PORT:-22}")
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        _ssh_arr+=(-o BatchMode=yes)
        [[ -n "${TARGET_SOURCE_KEY:-}" ]] && _ssh_arr+=(-i "$TARGET_SOURCE_KEY")
    fi
    _ssh_arr+=("${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}")
}

# Run a raw SSH command (no sudo/password wrapper).
# Usage: _db_ssh_raw <ssh_array_name> <cmd_str>
_db_ssh_raw() {
    local -n _ssh_arr=$1
    local cmd_str="$2"
    _db_is_remote || return 1
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
        SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_ssh_arr[@]}" "$cmd_str"
    else
        "${_ssh_arr[@]}" "$cmd_str"
    fi
}

# Run a command locally or via SSH with password/sudo wrapping.
# Usage: _db_run_cmd <ssh_array_name> <pw_env_var> <pw_value> <cmd_str> [use_sudo]
# pw_env_var: e.g. "MYSQL_PWD" or "PGPASSWORD"
# pw_value:   the password value (from TARGET_MYSQL_PASSWORD or TARGET_POSTGRESQL_PASSWORD)
# use_sudo:   "auto" (default) = sudo when no db user/password, "yes" = always, "no" = never
# For "auto" mode, the caller must set _DB_RUN_CMD_HAS_USER=true/false before calling
# to indicate whether a database user is configured.
_db_run_cmd() {
    local -n _ssh_arr=$1
    local pw_env_var="$2"
    local pw_value="$3"
    local cmd_str="$4"
    local use_sudo="${5:-auto}"

    if _db_is_remote; then
        # Prepend password env var on remote side if set
        if [[ -n "$pw_value" ]]; then
            cmd_str="${pw_env_var}=$(printf '%q' "$pw_value") $cmd_str"
        elif [[ "$use_sudo" == "yes" || ( "$use_sudo" == "auto" && "${_DB_RUN_CMD_HAS_USER:-false}" == "false" ) ]]; then
            cmd_str="sudo $cmd_str"
        fi
        if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
            SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_ssh_arr[@]}" "$cmd_str"
        else
            "${_ssh_arr[@]}" "$cmd_str"
        fi
    else
        # Local: set password env var if needed, then eval
        # SAFETY: All interpolated values in $cmd_str must be escaped via printf '%q'
        # in the calling functions. Do not pass unescaped user input.
        if [[ -n "$pw_value" ]]; then
            eval "${pw_env_var}=$(printf '%q' "$pw_value") $cmd_str"
        else
            eval "$cmd_str"
        fi
    fi
}
