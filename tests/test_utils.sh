#!/usr/bin/env bash
# gniza4linux/tests/test_utils.sh — Unit tests for lib/utils.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Source libraries in order
source "$PROJECT_DIR/lib/constants.sh"
source "$PROJECT_DIR/lib/utils.sh"
detect_mode
source "$PROJECT_DIR/lib/logging.sh"

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

# ── validate_target_name ─────────────────────────────────────
echo "=== validate_target_name ==="

assert_ok   "accepts 'mysite'"        validate_target_name "mysite"
assert_ok   "accepts 'web-server'"    validate_target_name "web-server"
assert_ok   "accepts 'db_backup1'"    validate_target_name "db_backup1"
assert_ok   "accepts single char 'a'" validate_target_name "a"

assert_fail "rejects empty string"    validate_target_name ""
assert_fail "rejects '123bad'"        validate_target_name "123bad"
assert_fail "rejects '../evil'"       validate_target_name "../evil"
assert_fail "rejects 'a]b'"           validate_target_name "a]b"
assert_fail "rejects name >32 chars"  validate_target_name "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
assert_fail "rejects name with space" validate_target_name "a b"

# ── validate_path ────────────────────────────────────────────
echo ""
echo "=== validate_path ==="

assert_ok   "accepts /tmp"              validate_path "/tmp"
assert_fail "rejects relative path"     validate_path "relative/path"
assert_fail "rejects path with .."      validate_path "/tmp/../etc"
assert_fail "rejects non-existent path" validate_path "/nonexistent_path_xyz_12345"

# ── validate_timestamp ───────────────────────────────────────
echo ""
echo "=== validate_timestamp ==="

assert_ok   "accepts 2026-01-15T020000" validate_timestamp "2026-01-15T020000"
assert_ok   "accepts 2025-12-31T235959" validate_timestamp "2025-12-31T235959"
assert_fail "rejects empty"             validate_timestamp ""
assert_fail "rejects bad format"        validate_timestamp "2026-01-15 02:00:00"
assert_fail "rejects partial"           validate_timestamp "2026-01-15T02"

# ── human_size ───────────────────────────────────────────────
echo ""
echo "=== human_size ==="

assert_eq "0 bytes"   "0 B"     "$(human_size 0)"
assert_eq "500 bytes" "500 B"   "$(human_size 500)"
assert_eq "1 KB"      "1.0 KB"  "$(human_size 1024)"
assert_eq "1 MB"      "1.0 MB"  "$(human_size 1048576)"
assert_eq "1 GB"      "1.0 GB"  "$(human_size 1073741824)"
assert_eq "1.5 GB"    "1.5 GB"  "$(human_size 1610612736)"

# ── human_duration ───────────────────────────────────────────
echo ""
echo "=== human_duration ==="

assert_eq "0 seconds" "0s"           "$(human_duration 0)"
assert_eq "45 seconds" "45s"         "$(human_duration 45)"
assert_eq "2 minutes"  "2m 0s"      "$(human_duration 120)"
assert_eq "1h 5m 3s"  "1h 5m 3s"   "$(human_duration 3903)"

# ── _safe_source_config ──────────────────────────────────────
echo ""
echo "=== _safe_source_config ==="

source "$PROJECT_DIR/lib/config.sh"

TMPFILE=$(mktemp)
cat > "$TMPFILE" <<'EOF'
TEST_KEY1="hello"
TEST_KEY2='world'
TEST_KEY3=noquotes
# This is a comment
  # Indented comment

TEST_KEY4="has spaces"
EOF

_safe_source_config "$TMPFILE"
assert_eq "double-quoted value" "hello"      "$TEST_KEY1"
assert_eq "single-quoted value" "world"      "$TEST_KEY2"
assert_eq "unquoted value"      "noquotes"   "$TEST_KEY3"
assert_eq "value with spaces"   "has spaces" "$TEST_KEY4"

# Test that code injection is not executed
INJECTION_FILE=$(mktemp)
cat > "$INJECTION_FILE" <<'EOF'
SAFE_VAR="safe"
$(touch /tmp/gniza_test_injection)
`touch /tmp/gniza_test_injection2`
EOF

_safe_source_config "$INJECTION_FILE"
assert_eq "safe var loaded" "safe" "$SAFE_VAR"

if [[ ! -f /tmp/gniza_test_injection ]] && [[ ! -f /tmp/gniza_test_injection2 ]]; then
    echo "  PASS: code injection blocked"
    ((PASS++)) || true
else
    echo "  FAIL: code injection was executed"
    ((FAIL++)) || true
    rm -f /tmp/gniza_test_injection /tmp/gniza_test_injection2
fi

rm -f "$TMPFILE" "$INJECTION_FILE"

# ── Summary ──────────────────────────────────────────────────
echo ""
echo "============================================"
echo "Results: $PASS passed, $FAIL failed"
echo "============================================"

(( FAIL > 0 )) && exit 1
exit 0
