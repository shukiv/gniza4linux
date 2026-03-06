#!/usr/bin/env bash
# gniza4linux/lib/schedule.sh — Cron management for decoupled schedules
#
# Schedules are defined in $CONFIG_DIR/schedules.d/<name>.conf:
#   SCHEDULE="hourly|daily|weekly|monthly|custom"
#   SCHEDULE_TIME="HH:MM"
#   SCHEDULE_DAY=""        # dow (0-6) for weekly, dom (1-28) for monthly
#   SCHEDULE_CRON=""       # full 5-field cron expr for custom
#   REMOTES=""             # comma-separated remote names (empty = all)
#   TARGETS=""             # comma-separated target names (empty = all)
#
# Cron lines are tagged with "# gniza4linux:<name>" for clean install/remove.

[[ -n "${_GNIZA4LINUX_SCHEDULE_LOADED:-}" ]] && return 0
_GNIZA4LINUX_SCHEDULE_LOADED=1

readonly GNIZA4LINUX_CRON_TAG="# gniza4linux:"
SCHEDULES_DIR="$CONFIG_DIR/schedules.d"

# ── Discovery ─────────────────────────────────────────────────

# List schedule names (filenames without .conf) sorted alphabetically.
list_schedules() {
    if [[ ! -d "$SCHEDULES_DIR" ]]; then
        return 0
    fi
    local f
    for f in "$SCHEDULES_DIR"/*.conf; do
        [[ -f "$f" ]] || continue
        basename "$f" .conf
    done
}

# Return 0 if at least one schedule config exists.
has_schedules() {
    local schedules
    schedules=$(list_schedules)
    [[ -n "$schedules" ]]
}

# ── Loading ───────────────────────────────────────────────────

# Source a schedule config and set SCHEDULE/REMOTES/TARGETS globals.
# Usage: load_schedule <name>
load_schedule() {
    local name="$1"
    local conf="$SCHEDULES_DIR/${name}.conf"

    if [[ ! -f "$conf" ]]; then
        log_error "Schedule config not found: $conf"
        return 1
    fi

    # Reset schedule globals before sourcing
    SCHEDULE=""
    SCHEDULE_TIME=""
    SCHEDULE_DAY=""
    SCHEDULE_CRON=""
    SCHEDULE_ACTIVE="yes"
    SCHEDULE_REMOTES=""
    SCHEDULE_TARGETS=""

    _safe_source_config "$conf" || {
        log_error "Failed to parse schedule config: $conf"
        return 1
    }

    # Map REMOTES/TARGETS to SCHEDULE_* to avoid conflicts
    SCHEDULE_REMOTES="${REMOTES:-}"
    SCHEDULE_TARGETS="${TARGETS:-}"

    log_debug "Loaded schedule '$name': ${SCHEDULE} at ${SCHEDULE_TIME:-02:00}, remotes=${SCHEDULE_REMOTES:-all}, targets=${SCHEDULE_TARGETS:-all}"
}

# ── Cron Generation ───────────────────────────────────────────

# Convert schedule vars to a 5-field cron expression.
# Must be called after load_schedule() sets SCHEDULE/SCHEDULE_TIME/etc.
schedule_to_cron() {
    local name="$1"
    local schedule="${SCHEDULE:-}"
    local stime="${SCHEDULE_TIME:-02:00}"
    local sday="${SCHEDULE_DAY:-}"
    local scron="${SCHEDULE_CRON:-}"

    if [[ -z "$schedule" ]]; then
        return 1  # no schedule configured
    fi

    local hour minute
    hour="${stime%%:*}"
    minute="${stime##*:}"
    # Strip leading zeros for cron
    hour=$((10#$hour))
    minute=$((10#$minute))

    case "$schedule" in
        hourly)
            if [[ -n "$sday" && "$sday" -gt 1 ]] 2>/dev/null; then
                echo "$minute */$sday * * *"
            else
                echo "$minute * * * *"
            fi
            ;;
        daily)
            if [[ -n "$sday" ]]; then
                echo "$minute $hour * * $sday"
            else
                echo "$minute $hour * * *"
            fi
            ;;
        weekly)
            if [[ -z "$sday" ]]; then
                log_error "Schedule '$name': SCHEDULE_DAY required for weekly schedule"
                return 1
            fi
            echo "$minute $hour * * $sday"
            ;;
        monthly)
            if [[ -z "$sday" ]]; then
                log_error "Schedule '$name': SCHEDULE_DAY required for monthly schedule"
                return 1
            fi
            echo "$minute $hour $sday * *"
            ;;
        custom)
            if [[ -z "$scron" ]]; then
                log_error "Schedule '$name': SCHEDULE_CRON required for custom schedule"
                return 1
            fi
            echo "$scron"
            ;;
        *)
            log_error "Schedule '$name': unknown SCHEDULE value: $schedule"
            return 1
            ;;
    esac
}

# Resolve the installed binary path.
_gniza4linux_bin() {
    if command -v gniza &>/dev/null; then
        command -v gniza
    else
        # Fall back to the project's bin directory
        local script_dir
        script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        echo "$(dirname "$script_dir")/bin/gniza"
    fi
}

# Build the full cron line for a schedule.
# Uses SCHEDULE_REMOTES and SCHEDULE_TARGETS if set.
build_cron_line() {
    local name="$1"
    local cron_expr
    cron_expr=$(schedule_to_cron "$name") || return 1

    local bin_path; bin_path=$(_gniza4linux_bin)
    local extra_flags=""
    if [[ -n "$SCHEDULE_REMOTES" ]]; then
        extra_flags+=" --remote=$SCHEDULE_REMOTES"
    fi
    if [[ -n "$SCHEDULE_TARGETS" ]]; then
        extra_flags+=" --target=$SCHEDULE_TARGETS"
    fi

    echo "$cron_expr PATH=\"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\" $bin_path backup${extra_flags} >>\"${LOG_DIR}/cron.log\" 2>&1"
}

# ── Crontab Management ────────────────────────────────────────

# Install cron entries for all schedules in schedules.d/.
# Strips any existing gniza4linux entries first, then appends new ones.
install_schedules() {
    if ! has_schedules; then
        log_error "No schedules configured in $SCHEDULES_DIR"
        return 1
    fi

    # Collect new cron lines
    local new_lines=""
    local count=0
    local schedules; schedules=$(list_schedules)

    while IFS= read -r sname; do
        [[ -z "$sname" ]] && continue
        load_schedule "$sname" || { log_error "Skipping schedule '$sname': failed to load"; continue; }

        if [[ -z "${SCHEDULE:-}" ]]; then
            log_debug "Schedule '$sname' has no SCHEDULE type, skipping"
            continue
        fi

        if [[ "${SCHEDULE_ACTIVE:-yes}" != "yes" ]]; then
            log_debug "Schedule '$sname' is inactive, skipping"
            continue
        fi

        local cron_line
        cron_line=$(build_cron_line "$sname") || { log_error "Skipping schedule '$sname': invalid schedule"; continue; }

        new_lines+="${GNIZA4LINUX_CRON_TAG}${sname}"$'\n'
        new_lines+="${cron_line}"$'\n'
        ((count++)) || true
    done <<< "$schedules"

    if (( count == 0 )); then
        log_warn "No valid schedules found"
        return 1
    fi

    # Get current crontab, strip old gniza4linux lines
    local current_crontab=""
    current_crontab=$(crontab -l 2>/dev/null) || true

    local filtered=""
    local skip_next=false
    while IFS= read -r line; do
        if [[ "$line" == "${GNIZA4LINUX_CRON_TAG}"* ]]; then
            skip_next=true
            continue
        fi
        if [[ "$skip_next" == "true" ]]; then
            skip_next=false
            continue
        fi
        filtered+="$line"$'\n'
    done <<< "$current_crontab"

    # Append new lines
    local final="${filtered}${new_lines}"

    # Install
    echo "$final" | crontab - || {
        log_error "Failed to install crontab"
        return 1
    }

    echo "Installed $count schedule(s):"
    echo ""

    # Show what was installed
    while IFS= read -r sname; do
        [[ -z "$sname" ]] && continue
        load_schedule "$sname" 2>/dev/null || continue
        [[ -z "${SCHEDULE:-}" ]] && continue
        local cron_line; cron_line=$(build_cron_line "$sname" 2>/dev/null) || continue
        echo "  [$sname] $cron_line"
    done <<< "$schedules"
}

# Display current gniza4linux cron entries.
show_schedules() {
    local current_crontab=""
    current_crontab=$(crontab -l 2>/dev/null) || true

    if [[ -z "$current_crontab" ]]; then
        echo "No crontab entries found."
        return 0
    fi

    local found=false
    local next_is_command=false
    local current_tag=""
    while IFS= read -r line; do
        if [[ "$line" == "${GNIZA4LINUX_CRON_TAG}"* ]]; then
            current_tag="${line#"$GNIZA4LINUX_CRON_TAG"}"
            next_is_command=true
            continue
        fi
        if [[ "$next_is_command" == "true" ]]; then
            next_is_command=false
            if [[ "$found" == "false" ]]; then
                echo "Current gniza schedules:"
                echo ""
                found=true
            fi
            echo "  [$current_tag] $line"
        fi
    done <<< "$current_crontab"

    if [[ "$found" == "false" ]]; then
        echo "No gniza schedule entries in crontab."
    fi
}

# Remove all gniza4linux cron entries.
remove_schedules() {
    local current_crontab=""
    current_crontab=$(crontab -l 2>/dev/null) || true

    if [[ -z "$current_crontab" ]]; then
        echo "No crontab entries to remove."
        return 0
    fi

    local filtered=""
    local skip_next=false
    local removed=0
    while IFS= read -r line; do
        if [[ "$line" == "${GNIZA4LINUX_CRON_TAG}"* ]]; then
            skip_next=true
            ((removed++)) || true
            continue
        fi
        if [[ "$skip_next" == "true" ]]; then
            skip_next=false
            continue
        fi
        filtered+="$line"$'\n'
    done <<< "$current_crontab"

    if (( removed == 0 )); then
        echo "No gniza schedule entries found in crontab."
        return 0
    fi

    echo "$filtered" | crontab - || {
        log_error "Failed to update crontab"
        return 1
    }

    echo "Removed $removed gniza schedule(s) from crontab."
}
