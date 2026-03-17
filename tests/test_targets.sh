#!/usr/bin/env bash
# gniza4linux/tests/test_targets.sh — Unit tests for lib/targets.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source libraries in order
source "$PROJECT_DIR/lib/constants.sh"
source "$PROJECT_DIR/lib/utils.sh"
detect_mode
source "$PROJECT_DIR/lib/logging.sh"
source "$PROJECT_DIR/lib/config.sh"
source "$PROJECT_DIR/lib/targets.sh"

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

# ── Setup temp CONFIG_DIR ────────────────────────────────────
ORIG_CONFIG_DIR="$CONFIG_DIR"
CONFIG_DIR=$(mktemp -d)
mkdir -p "$CONFIG_DIR/targets.d"

cleanup() {
    rm -rf "$CONFIG_DIR"
    CONFIG_DIR="$ORIG_CONFIG_DIR"
}
trap cleanup EXIT

# ── create_target ────────────────────────────────────────────
echo "=== create_target ==="

assert_ok "create target 'webserver'" create_target "webserver" "/tmp,/var"

if [[ -f "$CONFIG_DIR/targets.d/webserver.conf" ]]; then
    echo "  PASS: config file created"
    ((PASS++)) || true
else
    echo "  FAIL: config file not created"
    ((FAIL++)) || true
fi

assert_fail "rejects invalid name '123bad'" create_target "123bad" "/tmp"
assert_fail "rejects invalid name '../evil'" create_target "../evil" "/tmp"

# ── load_target ──────────────────────────────────────────────
echo ""
echo "=== load_target ==="

assert_ok "load 'webserver'" load_target "webserver"
assert_eq "TARGET_NAME set" "webserver" "$TARGET_NAME"
assert_eq "TARGET_FOLDERS set" "/tmp,/var" "$TARGET_FOLDERS"
assert_eq "TARGET_ENABLED default" "yes" "$TARGET_ENABLED"

assert_fail "load nonexistent target" load_target "nonexistent"

# ── list_targets ─────────────────────────────────────────────
echo ""
echo "=== list_targets ==="

create_target "dbserver" "/tmp" 2>/dev/null

local_list=$(list_targets)
if echo "$local_list" | grep -q "webserver" && echo "$local_list" | grep -q "dbserver"; then
    echo "  PASS: list_targets returns both targets"
    ((PASS++)) || true
else
    echo "  FAIL: list_targets missing targets (got: $local_list)"
    ((FAIL++)) || true
fi

# ── delete_target ────────────────────────────────────────────
echo ""
echo "=== delete_target ==="

assert_ok "delete 'dbserver'" delete_target "dbserver"

if [[ ! -f "$CONFIG_DIR/targets.d/dbserver.conf" ]]; then
    echo "  PASS: config file removed"
    ((PASS++)) || true
else
    echo "  FAIL: config file still exists"
    ((FAIL++)) || true
fi

assert_fail "delete nonexistent target" delete_target "nonexistent"

# ── validate_target ──────────────────────────────────────────
echo ""
echo "=== validate_target ==="

# webserver has /tmp,/var which exist
assert_ok "valid target 'webserver'" validate_target "webserver"

# Create a target with non-existent folder
create_target "badfolders" "/nonexistent_xyz_12345" 2>/dev/null
assert_fail "rejects target with non-existent folder" validate_target "badfolders"

# Create a target with empty folders
cat > "$CONFIG_DIR/targets.d/emptyfolders.conf" <<'EOF'
TARGET_NAME="emptyfolders"
TARGET_FOLDERS=""
TARGET_ENABLED="yes"
EOF
assert_fail "rejects target with empty folders" validate_target "emptyfolders"

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "============================================"
echo "Results: $PASS passed, $FAIL failed"
echo "============================================"

(( FAIL > 0 )) && exit 1
exit 0
