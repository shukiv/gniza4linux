#!/usr/bin/env bash
# gniza4linux/lib/constants.sh — Version, exit codes, colors, defaults
# shellcheck disable=SC2034  # constants are used by sourcing scripts

[[ -n "${_GNIZA4LINUX_CONSTANTS_LOADED:-}" ]] && return 0
_GNIZA4LINUX_CONSTANTS_LOADED=1

readonly GNIZA4LINUX_VERSION="0.2.2"
readonly GNIZA4LINUX_REPO="https://git.linux-hosting.co.il/shukivaknin/gniza4linux.git"

# Exit codes
readonly EXIT_FATAL=1
readonly EXIT_LOCKED=2
readonly EXIT_PARTIAL=5

# Colors (disabled if not a terminal)
if [[ -t 1 ]]; then
    readonly C_RED=$'\033[0;31m'
    readonly C_GREEN=$'\033[0;32m'
    readonly C_YELLOW=$'\033[0;33m'
    readonly C_BLUE=$'\033[0;34m'
    readonly C_BOLD=$'\033[1m'
    readonly C_RESET=$'\033[0m'
else
    readonly C_RED=""
    readonly C_GREEN=""
    readonly C_YELLOW=""
    readonly C_BLUE=""
    readonly C_BOLD=""
    readonly C_RESET=""
fi

# Defaults
readonly DEFAULT_BACKUP_MODE="full"
readonly DEFAULT_REMOTE_AUTH_METHOD="key"
readonly DEFAULT_REMOTE_PORT=22
readonly DEFAULT_REMOTE_USER="root"
readonly DEFAULT_REMOTE_BASE="/backups"
readonly DEFAULT_BWLIMIT=0
readonly DEFAULT_RETENTION_COUNT=30
readonly DEFAULT_LOG_LEVEL="info"
readonly DEFAULT_LOG_RETAIN=90
readonly DEFAULT_NOTIFY_ON="failure"
readonly DEFAULT_SSH_TIMEOUT=30
readonly DEFAULT_SSH_RETRIES=3
readonly DEFAULT_REMOTE_TYPE="ssh"
readonly DEFAULT_S3_REGION="us-east-1"
readonly DEFAULT_SMTP_PORT=587
readonly DEFAULT_SMTP_SECURITY="tls"
readonly DEFAULT_DISK_USAGE_THRESHOLD=95
readonly DEFAULT_RSYNC_COMPRESS="no"
readonly DEFAULT_RSYNC_CHECKSUM="no"
