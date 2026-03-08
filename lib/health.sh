#!/usr/bin/env bash
# gniza4linux/lib/health.sh — Comprehensive health check for all destinations

[[ -n "${_GNIZA4LINUX_HEALTH_LOADED:-}" ]] && return 0
_GNIZA4LINUX_HEALTH_LOADED=1

# ── Per-destination health check ─────────────────────────────

# Run health check for a single loaded remote.
# Outputs human-readable report. Sets _HEALTH_RC to 0 (healthy) or 1 (issues).
health_check_destination() {
    local name="$1"
    _HEALTH_RC=0

    echo "━━━ Destination: $name (${REMOTE_TYPE:-ssh}) ━━━"

    # 1. Connectivity
    printf "  %-20s" "Connectivity:"
    if test_remote_connection 2>/dev/null; then
        echo "OK"
    else
        echo "FAILED"
        _HEALTH_RC=1
        echo ""
        return
    fi

    # 2. Disk/quota
    printf "  %-20s" "Disk:"
    local disk_info; disk_info=$(remote_disk_info_short 2>/dev/null) || disk_info="N/A"
    echo "$disk_info"

    # Check disk threshold
    local disk_pct; disk_pct=$(remote_disk_usage_pct 2>/dev/null) || disk_pct=0
    if [[ "$disk_pct" =~ ^[0-9]+$ ]] && (( disk_pct >= 90 )); then
        echo "  ⚠ Disk usage is ${disk_pct}% (warning threshold: 90%)"
        _HEALTH_RC=1
    fi

    # 3. Per-target stats
    local configured_targets; configured_targets=$(list_targets) || true
    local total_snapshots=0
    local total_partials=0
    local targets_with_snapshots=0

    if [[ -n "$configured_targets" ]]; then
        while IFS= read -r t; do
            [[ -z "$t" ]] && continue
            local snaps; snaps=$(list_remote_snapshots "$t" 2>/dev/null) || true
            local snap_count=0
            [[ -n "$snaps" ]] && snap_count=$(echo "$snaps" | wc -l)
            total_snapshots=$((total_snapshots + snap_count))
            (( snap_count > 0 )) && ((targets_with_snapshots++)) || true

            local partials; partials=$(count_partial_snapshots "$t" 2>/dev/null) || partials=0
            partials=$(echo "$partials" | tr -d '[:space:]')
            total_partials=$((total_partials + partials))
        done <<< "$configured_targets"
    fi

    printf "  %-20s%s (%s sources with backups)\n" "Snapshots:" "$total_snapshots" "$targets_with_snapshots"

    if (( total_partials > 0 )); then
        echo "  ⚠ Stale partials:   $total_partials"
        _HEALTH_RC=1
    else
        printf "  %-20s%s\n" "Stale partials:" "0"
    fi

    # 4. Orphaned targets
    local orphans; orphans=$(find_orphaned_targets 2>/dev/null) || true
    if [[ -n "$orphans" ]]; then
        local orphan_count; orphan_count=$(echo "$orphans" | wc -l)
        echo "  ⚠ Orphaned targets: $orphan_count"
        while IFS= read -r o; do
            [[ -z "$o" ]] && continue
            echo "      - $o"
        done <<< "$orphans"
        _HEALTH_RC=1
    else
        printf "  %-20s%s\n" "Orphaned targets:" "0"
    fi

    echo ""
}

# ── All destinations ──────────────────────────────────────────

health_check_all() {
    local remotes; remotes=$(list_remotes)
    if [[ -z "$remotes" ]]; then
        echo "No destinations configured."
        return 0
    fi

    local overall_rc=0
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        _save_remote_globals
        load_remote "$name" 2>/dev/null || {
            echo "━━━ Destination: $name ━━━"
            echo "  ERROR: Failed to load config"
            echo ""
            _restore_remote_globals
            overall_rc=1
            continue
        }
        health_check_destination "$name"
        (( _HEALTH_RC != 0 )) && overall_rc=1
        _restore_remote_globals
    done <<< "$remotes"

    return "$overall_rc"
}

# ── JSON output ───────────────────────────────────────────────

# JSON health check for a single loaded remote.
# Uses python3 json.dumps for safe JSON generation.
health_check_destination_json() {
    local name="$1"

    # Connectivity
    local conn_ok="true"
    if ! test_remote_connection 2>/dev/null; then
        conn_ok="false"
    fi

    # Disk
    local disk_info; disk_info=$(remote_disk_info_short 2>/dev/null) || disk_info="N/A"
    local disk_pct; disk_pct=$(remote_disk_usage_pct 2>/dev/null) || disk_pct=0
    disk_pct=$(echo "$disk_pct" | tr -d '[:space:]')
    [[ ! "$disk_pct" =~ ^[0-9]+$ ]] && disk_pct=0

    # Collect per-target data as tab-separated lines: name\tsnap_count\tpartials\tlatest
    local target_lines=""
    local configured_targets; configured_targets=$(list_targets) || true

    if [[ -n "$configured_targets" ]] && [[ "$conn_ok" == "true" ]]; then
        while IFS= read -r t; do
            [[ -z "$t" ]] && continue
            local snaps; snaps=$(list_remote_snapshots "$t" 2>/dev/null) || true
            local snap_count=0
            [[ -n "$snaps" ]] && snap_count=$(echo "$snaps" | wc -l)

            local partials; partials=$(count_partial_snapshots "$t" 2>/dev/null) || partials=0
            partials=$(echo "$partials" | tr -d '[:space:]')

            local latest=""
            [[ -n "$snaps" ]] && latest=$(echo "$snaps" | head -1)

            target_lines+="${t}"$'\t'"${snap_count}"$'\t'"${partials}"$'\t'"${latest}"$'\n'
        done <<< "$configured_targets"
    fi

    # Collect orphans
    local orphan_lines=""
    if [[ "$conn_ok" == "true" ]]; then
        orphan_lines=$(find_orphaned_targets 2>/dev/null) || true
    fi

    # Use python3 for safe JSON generation
    python3 -c "
import json, sys

name = sys.argv[1]
rtype = sys.argv[2]
conn_ok = sys.argv[3] == 'true'
disk_info = sys.argv[4]
disk_pct = int(sys.argv[5])
target_data = sys.argv[6]
orphan_data = sys.argv[7]

targets = []
total_snaps = 0
total_partials = 0
for line in target_data.strip().split('\n'):
    if not line.strip():
        continue
    parts = line.split('\t')
    if len(parts) < 4:
        continue
    sc = int(parts[1])
    pc = int(parts[2])
    total_snaps += sc
    total_partials += pc
    targets.append({'name': parts[0], 'snapshots': sc, 'partials': pc, 'latest': parts[3]})

orphans = [o.strip() for o in orphan_data.strip().split('\n') if o.strip()]

status = 'healthy'
if not conn_ok:
    status = 'error'
elif disk_pct >= 90 or total_partials > 0 or orphans:
    status = 'warning'

print(json.dumps({
    'destination': name,
    'type': rtype,
    'status': status,
    'connectivity': conn_ok,
    'disk': {'info': disk_info, 'pct': disk_pct},
    'snapshots': total_snaps,
    'partials': total_partials,
    'targets': targets,
    'orphans': orphans,
}))
" "$name" "${REMOTE_TYPE:-ssh}" "$conn_ok" "$disk_info" "$disk_pct" "$target_lines" "$orphan_lines"
}

health_check_all_json() {
    local remotes; remotes=$(list_remotes)
    if [[ -z "$remotes" ]]; then
        echo "[]"
        return 0
    fi

    echo "["
    local first=true
    while IFS= read -r name; do
        [[ -z "$name" ]] && continue
        _save_remote_globals
        if load_remote "$name" 2>/dev/null; then
            [[ "$first" != "true" ]] && echo ","
            first=false
            health_check_destination_json "$name"
        else
            [[ "$first" != "true" ]] && echo ","
            first=false
            python3 -c "import json; print(json.dumps({'destination': '$name', 'type': 'unknown', 'status': 'error', 'connectivity': False, 'disk': {'info': 'N/A', 'pct': 0}, 'snapshots': 0, 'partials': 0, 'targets': [], 'orphans': []}))"
        fi
        _restore_remote_globals
    done <<< "$remotes"
    echo "]"
}
