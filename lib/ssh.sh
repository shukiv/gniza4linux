#!/usr/bin/env bash
# gniza4linux/lib/ssh.sh — SSH connectivity, remote exec, ssh_opts builder

[[ -n "${_GNIZA_SSH_LOADED:-}" ]] && return 0
_GNIZA_SSH_LOADED=1

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
    if remote_exec "echo ok" &>/dev/null; then
        log_info "SSH connection successful"
        return 0
    else
        log_error "SSH connection failed to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PORT}"
        return 1
    fi
}

ensure_remote_dir() {
    local dir; dir="$(shquote "$1")"
    remote_exec "mkdir -p '$dir'" || {
        log_error "Failed to create remote directory: $dir"
        return 1
    }
}

build_rsync_ssh_cmd() {
    if _is_password_mode; then
        echo "ssh -p $REMOTE_PORT -o StrictHostKeyChecking=yes -o ConnectTimeout=$SSH_TIMEOUT"
    else
        echo "ssh -i \"$REMOTE_KEY\" -p $REMOTE_PORT -o StrictHostKeyChecking=yes -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT"
    fi
}
