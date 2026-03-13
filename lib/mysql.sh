#!/usr/bin/env bash
# gniza4linux/lib/mysql.sh — MySQL database dump support

[[ -n "${_GNIZA4LINUX_MYSQL_LOADED:-}" ]] && return 0
_GNIZA4LINUX_MYSQL_LOADED=1

# System databases always excluded from dumps
_MYSQL_SYSTEM_DBS="information_schema performance_schema sys"

# Build SSH prefix for remote MySQL operations.
# Sets _MYSQL_SSH array. Returns 1 if local (no SSH needed).
_mysql_is_remote() {
    [[ "${TARGET_SOURCE_TYPE:-local}" == "ssh" ]] || return 1
    _MYSQL_SSH=(ssh -o StrictHostKeyChecking=accept-new -o "ConnectTimeout=${SSH_TIMEOUT:-30}" -p "${TARGET_SOURCE_PORT:-22}")
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        _MYSQL_SSH+=(-o BatchMode=yes)
        [[ -n "${TARGET_SOURCE_KEY:-}" ]] && _MYSQL_SSH+=(-i "$TARGET_SOURCE_KEY")
    fi
    _MYSQL_SSH+=("${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}")
    return 0
}

# Run a command locally or via SSH. For remote, wraps with sshpass if needed.
# Usage: _mysql_run_cmd "mysql -u root -e 'SHOW DATABASES'" [use_sudo]
# use_sudo: "auto" (default) = sudo when no user/password, "yes" = always, "no" = never
_mysql_run_cmd() {
    local cmd_str="$1"
    local use_sudo="${2:-auto}"
    if _mysql_is_remote; then
        # Prepend MYSQL_PWD on remote side if set
        if [[ -n "${TARGET_MYSQL_PASSWORD:-}" ]]; then
            cmd_str="MYSQL_PWD=$(printf '%q' "$TARGET_MYSQL_PASSWORD") $cmd_str"
        elif [[ "$use_sudo" == "yes" || ( "$use_sudo" == "auto" && -z "${TARGET_MYSQL_USER:-}" ) ]]; then
            # Use sudo for socket auth on remote
            cmd_str="sudo $cmd_str"
        fi
        if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
            SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_MYSQL_SSH[@]}" "$cmd_str"
        else
            "${_MYSQL_SSH[@]}" "$cmd_str"
        fi
    else
        # Local: set MYSQL_PWD if needed, then eval
        if [[ -n "${TARGET_MYSQL_PASSWORD:-}" ]]; then
            MYSQL_PWD="$TARGET_MYSQL_PASSWORD" eval "$cmd_str"
        else
            eval "$cmd_str"
        fi
    fi
}

# Run a command via SSH without the sudo/MYSQL_PWD wrapper.
# Used for binary detection where sudo is unnecessary and may be restricted.
_mysql_ssh_raw() {
    local cmd_str="$1"
    _mysql_is_remote || return 1
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
        SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_MYSQL_SSH[@]}" "$cmd_str"
    else
        "${_MYSQL_SSH[@]}" "$cmd_str"
    fi
}

# Detect the mysqldump binary (MySQL or MariaDB), locally or remotely.
_mysql_find_dump_cmd() {
    if _mysql_is_remote; then
        # SSH directly without sudo wrapper — binary detection doesn't need
        # elevated privileges, and sudo may reject shell builtins/unknown commands.
        _mysql_ssh_raw "PATH=\$PATH:/usr/bin:/usr/local/bin command -v mysqldump || PATH=\$PATH:/usr/bin:/usr/local/bin command -v mariadb-dump" 2>/dev/null || return 1
    else
        if command -v mysqldump &>/dev/null; then
            echo "mysqldump"
        elif command -v mariadb-dump &>/dev/null; then
            echo "mariadb-dump"
        else
            return 1
        fi
    fi
}

# Detect the mysql client binary, locally or remotely.
_mysql_find_client_cmd() {
    if _mysql_is_remote; then
        _mysql_ssh_raw "PATH=\$PATH:/usr/bin:/usr/local/bin command -v mysql || PATH=\$PATH:/usr/bin:/usr/local/bin command -v mariadb" 2>/dev/null || return 1
    else
        if command -v mysql &>/dev/null; then
            echo "mysql"
        elif command -v mariadb &>/dev/null; then
            echo "mariadb"
        else
            return 1
        fi
    fi
}

# Build connection arguments from TARGET_MYSQL_* globals into MYSQL_CONN_ARGS array.
# Sets MYSQL_PWD env var if password is configured (local mode only).
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

# Build connection arguments as a string for embedding in SSH commands.
# Returns a string like: -u root -h host -P port
_mysql_build_conn_str() {
    local conn_str=""
    if [[ -n "${TARGET_MYSQL_USER:-}" ]]; then
        conn_str+="-u $(printf '%q' "$TARGET_MYSQL_USER")"
    fi
    if [[ -n "${TARGET_MYSQL_HOST:-}" && "${TARGET_MYSQL_HOST}" != "localhost" ]]; then
        conn_str+=" -h $(printf '%q' "$TARGET_MYSQL_HOST")"
    fi
    if [[ -n "${TARGET_MYSQL_PORT:-}" && "${TARGET_MYSQL_PORT}" != "3306" ]]; then
        conn_str+=" -P $(printf '%q' "$TARGET_MYSQL_PORT")"
    fi
    echo "$conn_str"
}

# Get list of databases to dump.
# Outputs one database name per line.
mysql_get_databases() {
    local client_cmd
    client_cmd=$(_mysql_find_client_cmd) || {
        log_error "MySQL/MariaDB client not found"
        return 1
    }

    local all_dbs
    if _mysql_is_remote; then
        local conn_str
        conn_str=$(_mysql_build_conn_str)
        # Try without sudo first (mysql client may not be in sudoers),
        # fall back to sudo if that fails
        all_dbs=$(_mysql_run_cmd "$client_cmd $conn_str -N -e 'SHOW DATABASES'" "no" 2>&1) || {
            all_dbs=$(_mysql_run_cmd "$client_cmd $conn_str -N -e 'SHOW DATABASES'" 2>&1) || {
                log_error "Failed to list databases: $all_dbs"
                return 1
            }
        }
    else
        mysql_build_conn_args
        all_dbs=$("$client_cmd" "${MYSQL_CONN_ARGS[@]}" -N -e "SHOW DATABASES" 2>&1) || {
            log_error "Failed to list databases: $all_dbs"
            return 1
        }
    fi

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

    local is_remote=false
    local conn_str=""
    if _mysql_is_remote; then
        is_remote=true
        conn_str=$(_mysql_build_conn_str)
    else
        mysql_build_conn_args
    fi

    # Determine databases to dump
    local -a databases=()
    if [[ "${TARGET_MYSQL_MODE:-all}" == "specific" || "${TARGET_MYSQL_MODE:-all}" == "select" ]]; then
        # Use explicitly listed databases
        if [[ -z "${TARGET_MYSQL_DATABASES:-}" ]]; then
            log_error "MySQL mode=specific but TARGET_MYSQL_DATABASES is empty"
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

    # Create temp directory (always local)
    MYSQL_DUMP_DIR=$(mktemp -d "${WORK_DIR}/gniza-mysql-XXXXXX")
    mkdir -p "$MYSQL_DUMP_DIR/_mysql"

    # Parse extra opts
    local extra_opts_str=""
    if [[ -n "${TARGET_MYSQL_EXTRA_OPTS:-}" ]]; then
        extra_opts_str="${TARGET_MYSQL_EXTRA_OPTS}"
    else
        extra_opts_str="--single-transaction --routines --triggers"
    fi
    local failed=false

    for db in "${databases[@]}"; do
        # Validate database name to prevent path traversal
        if [[ ! "$db" =~ ^[a-zA-Z0-9._-]+$ ]]; then
            log_error "Invalid database name, skipping: $db"
            failed=true
            continue
        fi
        log_info "Dumping MySQL database: $db"
        local outfile="$MYSQL_DUMP_DIR/_mysql/${db}.sql.gz"
        local errfile="$MYSQL_DUMP_DIR/_mysql/${db}.err"
        if [[ "$is_remote" == "true" ]]; then
            if _mysql_run_cmd "$dump_cmd $conn_str $extra_opts_str $(printf '%q' "$db") | gzip" > "$outfile" 2>"$errfile"; then
                rm -f "$errfile"
                local size; size=$(stat -c%s "$outfile" 2>/dev/null || echo "?")
                log_debug "Dumped $db -> ${db}.sql.gz ($size bytes)"
            else
                log_error "Failed to dump database: $db"
                [[ -s "$errfile" ]] && log_error "mysqldump: $(cat "$errfile")"
                rm -f "$errfile"
                failed=true
            fi
        else
            local -a extra_opts_arr=()
            read -ra extra_opts_arr <<< "$extra_opts_str"
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
        fi
    done

    if [[ "$failed" == "true" ]]; then
        log_error "One or more MySQL dumps failed"
        return 1
    fi

    log_info "MySQL dumps completed: ${#databases[@]} database(s) in $MYSQL_DUMP_DIR/_mysql/"
    return 0
}

# Dump MySQL user grants to grants.sql in the dump directory.
# Must be called after mysql_dump_databases() sets MYSQL_DUMP_DIR.
mysql_dump_grants() {
    local client_cmd
    client_cmd=$(_mysql_find_client_cmd) || {
        log_error "MySQL/MariaDB client not found — cannot dump grants"
        return 1
    }

    local is_remote=false
    local conn_str=""
    if _mysql_is_remote; then
        is_remote=true
        conn_str=$(_mysql_build_conn_str)
    else
        mysql_build_conn_args
    fi

    local grants_file="$MYSQL_DUMP_DIR/_mysql/grants.sql"

    # System users to skip
    local -a skip_users=(
        "'root'@'localhost'"
        "'mysql.sys'@'localhost'"
        "'mysql.infoschema'@'localhost'"
        "'mysql.session'@'localhost'"
        "'debian-sys-maint'@'localhost'"
        "'mariadb.sys'@'localhost'"
    )

    # Get all users
    local users_output
    local sql_query="SELECT CONCAT(\"'\", user, \"'@'\", host, \"'\") FROM mysql.user"
    if [[ "$is_remote" == "true" ]]; then
        # Try without sudo first, fall back to sudo
        users_output=$(_mysql_run_cmd "$client_cmd $conn_str -N -e $(printf '%q' "$sql_query")" "no" 2>&1) || {
            users_output=$(_mysql_run_cmd "$client_cmd $conn_str -N -e $(printf '%q' "$sql_query")" 2>&1) || {
                log_error "Failed to list MySQL users: $users_output"
                return 1
            }
        }
    else
        users_output=$("$client_cmd" "${MYSQL_CONN_ARGS[@]}" -N -e "$sql_query" 2>&1) || {
            log_error "Failed to list MySQL users: $users_output"
            return 1
        }
    fi

    local count=0
    {
        echo "-- MySQL grants dump"
        echo "-- Generated: $(date -Iseconds)"
        echo ""

        while IFS= read -r user_host; do
            user_host="${user_host#"${user_host%%[![:space:]]*}"}"
            user_host="${user_host%"${user_host##*[![:space:]]}"}"
            [[ -z "$user_host" ]] && continue

            # Skip system users
            local skip=false
            local su
            for su in "${skip_users[@]}"; do
                if [[ "$user_host" == "$su" ]]; then
                    skip=true
                    break
                fi
            done
            [[ "$skip" == "true" ]] && continue

            # Try SHOW CREATE USER (MySQL 5.7+/MariaDB 10.2+)
            local create_user
            if [[ "$is_remote" == "true" ]]; then
                create_user=$(_mysql_run_cmd "$client_cmd $conn_str -N -e $(printf '%q' "SHOW CREATE USER $user_host")" "no" 2>/dev/null) || \
                    create_user=$(_mysql_run_cmd "$client_cmd $conn_str -N -e $(printf '%q' "SHOW CREATE USER $user_host")" 2>/dev/null) || true
            else
                create_user=$("$client_cmd" "${MYSQL_CONN_ARGS[@]}" -N -e \
                    "SHOW CREATE USER $user_host" 2>/dev/null) || true
            fi
            if [[ -n "$create_user" ]]; then
                echo "$create_user;"
            fi

            # SHOW GRANTS
            local grants
            if [[ "$is_remote" == "true" ]]; then
                grants=$(_mysql_run_cmd "$client_cmd $conn_str -N -e $(printf '%q' "SHOW GRANTS FOR $user_host")" "no" 2>/dev/null) || \
                    grants=$(_mysql_run_cmd "$client_cmd $conn_str -N -e $(printf '%q' "SHOW GRANTS FOR $user_host")" 2>/dev/null) || continue
            else
                grants=$("$client_cmd" "${MYSQL_CONN_ARGS[@]}" -N -e \
                    "SHOW GRANTS FOR $user_host" 2>/dev/null) || continue
            fi
            while IFS= read -r grant_line; do
                [[ -n "$grant_line" ]] && echo "$grant_line;"
            done <<< "$grants"
            echo ""
            ((count++)) || true
        done <<< "$users_output"
    } > "$grants_file"

    log_info "MySQL grants dumped: $count user(s) -> grants.sql"
    return 0
}

# Restore MySQL databases from a directory of .sql.gz files.
# Usage: mysql_restore_databases <dir_path>
# The directory should contain *.sql.gz files and optionally grants.sql.
mysql_restore_databases() {
    local mysql_dir="$1"

    if [[ ! -d "$mysql_dir" ]]; then
        log_error "MySQL restore dir not found: $mysql_dir"
        return 1
    fi

    local client_cmd
    client_cmd=$(_mysql_find_client_cmd) || {
        log_error "MySQL/MariaDB client not found — cannot restore databases"
        return 1
    }

    mysql_build_conn_args

    local errors=0

    # Restore database dumps
    local f
    for f in "$mysql_dir"/*.sql.gz; do
        [[ -f "$f" ]] || continue
        local db_name
        db_name=$(basename "$f" .sql.gz)

        # Skip system databases
        local skip=false
        local sdb
        for sdb in $_MYSQL_SYSTEM_DBS; do
            if [[ "$db_name" == "$sdb" ]]; then
                skip=true
                break
            fi
        done
        [[ "$skip" == "true" ]] && continue

        log_info "Restoring MySQL database: $db_name"

        # Create database if not exists
        "$client_cmd" "${MYSQL_CONN_ARGS[@]}" -e \
            "CREATE DATABASE IF NOT EXISTS \`$db_name\`" 2>/dev/null || {
            log_error "Failed to create database: $db_name"
            ((errors++)) || true
            continue
        }

        # Import dump
        if gunzip -c "$f" | "$client_cmd" "${MYSQL_CONN_ARGS[@]}" "$db_name" 2>/dev/null; then
            log_info "Restored database: $db_name"
        else
            log_error "Failed to restore database: $db_name"
            ((errors++)) || true
        fi
    done

    # Restore grants
    if [[ -f "$mysql_dir/grants.sql" ]]; then
        log_info "Restoring MySQL grants..."
        if "$client_cmd" "${MYSQL_CONN_ARGS[@]}" < "$mysql_dir/grants.sql" 2>/dev/null; then
            log_info "MySQL grants restored"
            "$client_cmd" "${MYSQL_CONN_ARGS[@]}" -e "FLUSH PRIVILEGES" 2>/dev/null || true
        else
            log_error "Failed to restore some MySQL grants (partial restore may have occurred)"
            ((errors++)) || true
        fi
    fi

    unset MYSQL_PWD 2>/dev/null || true

    if (( errors > 0 )); then
        log_error "MySQL restore completed with $errors error(s)"
        return 1
    fi

    log_info "MySQL restore completed successfully"
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
