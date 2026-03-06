#!/usr/bin/env bash
# gniza4linux/lib/mysql.sh — MySQL database dump support

[[ -n "${_GNIZA4LINUX_MYSQL_LOADED:-}" ]] && return 0
_GNIZA4LINUX_MYSQL_LOADED=1

# System databases always excluded from dumps
_MYSQL_SYSTEM_DBS="information_schema performance_schema sys"

# Detect the mysqldump binary (MySQL or MariaDB).
_mysql_find_dump_cmd() {
    if command -v mysqldump &>/dev/null; then
        echo "mysqldump"
    elif command -v mariadb-dump &>/dev/null; then
        echo "mariadb-dump"
    else
        return 1
    fi
}

# Detect the mysql client binary.
_mysql_find_client_cmd() {
    if command -v mysql &>/dev/null; then
        echo "mysql"
    elif command -v mariadb &>/dev/null; then
        echo "mariadb"
    else
        return 1
    fi
}

# Build connection arguments from TARGET_MYSQL_* globals into MYSQL_CONN_ARGS array.
# Sets MYSQL_PWD env var if password is configured.
mysql_build_conn_args() {
    MYSQL_CONN_ARGS=()
    if [[ -n "${TARGET_MYSQL_USER:-}" ]]; then
        MYSQL_CONN_ARGS+=(-u "$TARGET_MYSQL_USER")
    fi
    if [[ -n "${TARGET_MYSQL_HOST:-}" && "${TARGET_MYSQL_HOST}" != "localhost" ]]; then
        MYSQL_CONN_ARGS+=(-h "$TARGET_MYSQL_HOST")
    fi
    if [[ -n "${TARGET_MYSQL_PORT:-}" && "${TARGET_MYSQL_PORT}" != "3306" ]]; then
        MYSQL_CONN_ARGS+=(-P "$TARGET_MYSQL_PORT")
    fi
    if [[ -n "${TARGET_MYSQL_PASSWORD:-}" ]]; then
        export MYSQL_PWD="${TARGET_MYSQL_PASSWORD}"
    fi
}

# Get list of databases to dump.
# Outputs one database name per line.
mysql_get_databases() {
    local client_cmd
    client_cmd=$(_mysql_find_client_cmd) || {
        log_error "MySQL/MariaDB client not found"
        return 1
    }

    mysql_build_conn_args

    local all_dbs
    all_dbs=$("$client_cmd" "${MYSQL_CONN_ARGS[@]}" -N -e "SHOW DATABASES" 2>&1) || {
        log_error "Failed to list databases: $all_dbs"
        return 1
    }

    # Build exclude list: system dbs + user-specified excludes
    local -a exclude_list=()
    local db
    for db in $_MYSQL_SYSTEM_DBS; do
        exclude_list+=("$db")
    done
    if [[ -n "${TARGET_MYSQL_EXCLUDE:-}" ]]; then
        local -a user_excludes
        IFS=',' read -ra user_excludes <<< "$TARGET_MYSQL_EXCLUDE"
        local ex
        for ex in "${user_excludes[@]}"; do
            ex="${ex#"${ex%%[![:space:]]*}"}"
            ex="${ex%"${ex##*[![:space:]]}"}"
            [[ -n "$ex" ]] && exclude_list+=("$ex")
        done
    fi

    while IFS= read -r db; do
        db="${db#"${db%%[![:space:]]*}"}"
        db="${db%"${db##*[![:space:]]}"}"
        [[ -z "$db" ]] && continue

        # Skip system/excluded databases
        local skip=false
        local ex
        for ex in "${exclude_list[@]}"; do
            if [[ "$db" == "$ex" ]]; then
                skip=true
                break
            fi
        done
        [[ "$skip" == "true" ]] && continue

        echo "$db"
    done <<< "$all_dbs"
}

# Dump all configured databases to a temp directory.
# Sets MYSQL_DUMP_DIR global to the temp directory path containing _mysql/ subdir.
# Returns 0 on success, 1 on failure.
mysql_dump_databases() {
    local dump_cmd
    dump_cmd=$(_mysql_find_dump_cmd) || {
        log_error "mysqldump/mariadb-dump not found — cannot dump MySQL databases"
        return 1
    }

    mysql_build_conn_args

    # Determine databases to dump
    local -a databases=()
    if [[ "${TARGET_MYSQL_MODE:-all}" == "select" ]]; then
        # Use explicitly listed databases
        if [[ -z "${TARGET_MYSQL_DATABASES:-}" ]]; then
            log_error "MySQL mode=select but TARGET_MYSQL_DATABASES is empty"
            return 1
        fi
        local -a db_list
        IFS=',' read -ra db_list <<< "$TARGET_MYSQL_DATABASES"
        local db
        for db in "${db_list[@]}"; do
            db="${db#"${db%%[![:space:]]*}"}"
            db="${db%"${db##*[![:space:]]}"}"
            [[ -n "$db" ]] && databases+=("$db")
        done
    else
        # mode=all: discover databases, apply excludes
        local db_output
        db_output=$(mysql_get_databases) || {
            log_error "Failed to discover MySQL databases"
            return 1
        }
        while IFS= read -r db; do
            [[ -n "$db" ]] && databases+=("$db")
        done <<< "$db_output"
    fi

    if [[ ${#databases[@]} -eq 0 ]]; then
        log_warn "No databases to dump"
        return 0
    fi

    # Create temp directory
    MYSQL_DUMP_DIR=$(mktemp -d "${WORK_DIR}/gniza-mysql-XXXXXX")
    mkdir -p "$MYSQL_DUMP_DIR/_mysql"

    # Parse extra opts into array
    local -a extra_opts_arr=()
    if [[ -n "${TARGET_MYSQL_EXTRA_OPTS:-}" ]]; then
        read -ra extra_opts_arr <<< "${TARGET_MYSQL_EXTRA_OPTS}"
    else
        extra_opts_arr=(--single-transaction --routines --triggers)
    fi
    local failed=false

    for db in "${databases[@]}"; do
        # Validate database name to prevent path traversal
        if [[ ! "$db" =~ ^[a-zA-Z0-9_-]+$ ]]; then
            log_error "Invalid database name, skipping: $db"
            failed=true
            continue
        fi
        log_info "Dumping MySQL database: $db"
        local outfile="$MYSQL_DUMP_DIR/_mysql/${db}.sql.gz"
        local errfile="$MYSQL_DUMP_DIR/_mysql/${db}.err"
        if "$dump_cmd" "${MYSQL_CONN_ARGS[@]}" "${extra_opts_arr[@]}" "$db" 2>"$errfile" | gzip > "$outfile"; then
            rm -f "$errfile"
            local size; size=$(stat -c%s "$outfile" 2>/dev/null || echo "?")
            log_debug "Dumped $db -> ${db}.sql.gz ($size bytes)"
        else
            log_error "Failed to dump database: $db"
            [[ -s "$errfile" ]] && log_error "mysqldump: $(cat "$errfile")"
            rm -f "$errfile"
            failed=true
        fi
    done

    if [[ "$failed" == "true" ]]; then
        log_error "One or more MySQL dumps failed"
        return 1
    fi

    log_info "MySQL dumps completed: ${#databases[@]} database(s) in $MYSQL_DUMP_DIR/_mysql/"
    return 0
}

# Clean up the temporary MySQL dump directory and env vars.
mysql_cleanup_dump() {
    if [[ -n "${MYSQL_DUMP_DIR:-}" && -d "$MYSQL_DUMP_DIR" ]]; then
        rm -rf "$MYSQL_DUMP_DIR"
        log_debug "Cleaned up MySQL dump dir: $MYSQL_DUMP_DIR"
        MYSQL_DUMP_DIR=""
    fi
    unset MYSQL_PWD 2>/dev/null || true
}
