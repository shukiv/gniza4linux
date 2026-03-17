#!/usr/bin/env bash
# gniza4linux/lib/ssh.sh — SSH connectivity, remote exec, ssh_opts builder

[[ -n "${_GNIZA_SSH_LOADED:-}" ]] && return 0
_GNIZA_SSH_LOADED=1

declare -g REMOTE_RESTRICTED_SHELL=false

_is_password_mode() {
    [[ "${REMOTE_AUTH_METHOD:-key}" == "password" ]]
}

build_ssh_opts() {
    local opts=()
    opts+=(-n)
    if _is_password_mode; then
        opts+=(-o "StrictHostKeyChecking=yes")
    else
        opts+=(-i "$REMOTE_KEY")
        opts+=(-o "StrictHostKeyChecking=yes")
        opts+=(-o "BatchMode=yes")
    fi
    opts+=(-o "ControlMaster=auto")
    opts+=(-o "ControlPath=/tmp/gniza-ssh-%r@%h:%p")
    opts+=(-o "ControlPersist=60")
    opts+=(-p "$REMOTE_PORT")
    opts+=(-o "ConnectTimeout=$SSH_TIMEOUT")
    opts+=(-o "ServerAliveInterval=60")
    opts+=(-o "ServerAliveCountMax=3")
    echo "${opts[*]}"
}

remote_exec() {
    local cmd="$1"
    local ssh_opts; ssh_opts=$(build_ssh_opts)
    if _is_password_mode; then
        log_debug "CMD: sshpass -e ssh $ssh_opts ${REMOTE_USER}@${REMOTE_HOST} '<cmd>'"
        export SSHPASS="$REMOTE_PASSWORD"
        # shellcheck disable=SC2086
        sshpass -e ssh $ssh_opts "${REMOTE_USER}@${REMOTE_HOST}" "$cmd"
    else
        log_debug "CMD: ssh $ssh_opts ${REMOTE_USER}@${REMOTE_HOST} '$cmd'"
        # shellcheck disable=SC2086
        ssh $ssh_opts "${REMOTE_USER}@${REMOTE_HOST}" "$cmd"
    fi
}

test_ssh_connection() {
    log_info "Testing SSH connection to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}..."
    REMOTE_RESTRICTED_SHELL=false
    if remote_exec "echo ok" &>/dev/null; then
        log_info "SSH connection successful"
        return 0
    elif remote_exec "ls ." &>/dev/null; then
        log_info "SSH connection successful (restricted shell detected)"
        REMOTE_RESTRICTED_SHELL=true
        return 0
    else
        log_error "SSH connection failed to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
        return 1
    fi
}

ensure_remote_dir() {
    local dir; dir="$(shquote "$1")"
    if ! remote_exec "mkdir -p '$dir'" 2>/dev/null; then
        log_warn "mkdir -p failed for remote dir '$dir' — relying on rsync --mkpath"
    fi
}

# Probe whether REMOTE_BASE works as-is on the remote.
# If an absolute path like /backups fails (read-only root), automatically
# convert to a relative path (./backups) so users don't have to care.
normalize_remote_base() {
    [[ "${REMOTE_TYPE:-ssh}" != "ssh" ]] && return 0
    local base="${REMOTE_BASE:-/backups}"

    # Try creating the base directory with the configured path
    if remote_exec "mkdir -p '$(shquote "$base")'" 2>/dev/null; then
        return 0
    fi

    # Absolute path failed — try relative (strip leading /)
    if [[ "$base" == /* ]]; then
        local rel=".${base}"
        if remote_exec "mkdir -p '$(shquote "$rel")'" 2>/dev/null; then
            log_info "Remote root is read-only — using relative path: $rel (instead of $base)"
            REMOTE_BASE="$rel"
            return 0
        fi
    fi

    log_warn "Could not create remote base '$base' — rsync will attempt to create it"
    return 0
}

build_rsync_ssh_cmd() {
    if _is_password_mode; then
        echo "ssh -p $REMOTE_PORT -o StrictHostKeyChecking=yes -o ConnectTimeout=$SSH_TIMEOUT"
    else
        echo "ssh -i \"$REMOTE_KEY\" -p $REMOTE_PORT -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT"
    fi
}
