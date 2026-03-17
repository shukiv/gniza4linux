#!/usr/bin/env bash
# gniza4linux/tests/test_config.sh — Unit tests for lib/config.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source libraries in order
source "$PROJECT_DIR/lib/constants.sh"
source "$PROJECT_DIR/lib/utils.sh"
detect_mode
source "$PROJECT_DIR/lib/logging.sh"
source "$PROJECT_DIR/lib/config.sh"

PASS=0
FAIL=0

assert_eq() {
    local desc="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  PASS: $desc"
        ((PASS++)) || true
    else
        echo "  FAIL: $desc (expected='$expected', got='$actual')"
        ((FAIL++)) || true
    fi
}

assert_ok() {
    local desc="$1"; shift
    if "$@" 2>/dev/null; then
        echo "  PASS: $desc"
        ((PASS++)) || true
    else
        echo "  FAIL: $desc (expected success)"
        ((FAIL++)) || true
    fi
}

assert_fail() {
    local desc="$1"; shift
    if "$@" 2>/dev/null; then
        echo "  FAIL: $desc (expected failure)"
        ((FAIL++)) || true
    else
        echo "  PASS: $desc"
        ((PASS++)) || true
    fi
}

# ── load_config ──────────────────────────────────────────────
echo "=== load_config ==="

TMPCONF=$(mktemp)
cat > "$TMPCONF" <<'EOF'
BACKUP_MODE="incremental"
BWLIMIT=500
RETENTION_COUNT=10
LOG_LEVEL="debug"
LOG_RETAIN=30
NOTIFY_EMAIL="test@example.com"
NOTIFY_ON="always"
SSH_TIMEOUT=60
SSH_RETRIES=5
RSYNC_EXTRA_OPTS="--compress"
EOF

# Override CONFIG_DIR so load_config can find it
OLD_CONFIG_DIR="$CONFIG_DIR"
CONFIG_DIR=$(dirname "$TMPCONF")
cp "$TMPCONF" "$CONFIG_DIR/gniza.conf"

# Reset loaded flag so we can re-source
_GNIZA4LINUX_CONFIG_LOADED=""
source "$PROJECT_DIR/lib/config.sh"

load_config "$CONFIG_DIR/gniza.conf"

assert_eq "BACKUP_MODE loaded"    "incremental"     "$BACKUP_MODE"
assert_eq "BWLIMIT loaded"        "500"             "$BWLIMIT"
assert_eq "RETENTION_COUNT loaded" "10"              "$RETENTION_COUNT"
assert_eq "LOG_LEVEL loaded"      "debug"           "$LOG_LEVEL"
assert_eq "LOG_RETAIN loaded"     "30"              "$LOG_RETAIN"
assert_eq "NOTIFY_EMAIL loaded"   "test@example.com" "$NOTIFY_EMAIL"
assert_eq "NOTIFY_ON loaded"      "always"          "$NOTIFY_ON"
assert_eq "SSH_TIMEOUT loaded"    "60"              "$SSH_TIMEOUT"
assert_eq "SSH_RETRIES loaded"    "5"               "$SSH_RETRIES"
assert_eq "RSYNC_EXTRA_OPTS loaded" "--compress"    "$RSYNC_EXTRA_OPTS"

rm -f "$TMPCONF" "$CONFIG_DIR/gniza.conf"
CONFIG_DIR="$OLD_CONFIG_DIR"

# ── validate_config: valid ───────────────────────────────────
echo ""
echo "=== validate_config (valid) ==="

BACKUP_MODE="full"
BWLIMIT=0
RETENTION_COUNT=30
LOG_LEVEL="info"
LOG_RETAIN=90
NOTIFY_ON="failure"
SMTP_HOST=""
SSH_TIMEOUT=30
SSH_RETRIES=3
RSYNC_EXTRA_OPTS=""

assert_ok "valid config passes" validate_config

# ── validate_config: invalid values ──────────────────────────
echo ""
echo "=== validate_config (invalid) ==="

BACKUP_MODE="snapshot"
assert_fail "rejects bad BACKUP_MODE" validate_config
BACKUP_MODE="full"

NOTIFY_ON="sometimes"
assert_fail "rejects bad NOTIFY_ON" validate_config
NOTIFY_ON="failure"

LOG_LEVEL="verbose"
assert_fail "rejects bad LOG_LEVEL" validate_config
LOG_LEVEL="info"

SSH_TIMEOUT="abc"
assert_fail "rejects non-numeric SSH_TIMEOUT" validate_config
SSH_TIMEOUT=30

BWLIMIT="fast"
assert_fail "rejects non-numeric BWLIMIT" validate_config
BWLIMIT=0

RSYNC_EXTRA_OPTS='--delete; rm -rf /'
assert_fail "rejects unsafe RSYNC_EXTRA_OPTS" validate_config
RSYNC_EXTRA_OPTS=""

# ── _safe_source_config security ─────────────────────────────
echo ""
echo "=== _safe_source_config security ==="

INJECT_FILE=$(mktemp)
cat > "$INJECT_FILE" <<'CONF'
SAFE_VALUE="ok"
evil_lowercase="should be ignored"
$(whoami)
`id`
CONF

# Unset to test
unset SAFE_VALUE 2>/dev/null || true
unset evil_lowercase 2>/dev/null || true

_safe_source_config "$INJECT_FILE"
assert_eq "uppercase key loaded" "ok" "${SAFE_VALUE:-}"
assert_eq "lowercase key ignored" "" "${evil_lowercase:-}"

rm -f "$INJECT_FILE"

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "============================================"
echo "Results: $PASS passed, $FAIL failed"
echo "============================================"

(( FAIL > 0 )) && exit 1
exit 0
