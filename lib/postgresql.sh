#!/usr/bin/env bash
# gniza4linux/lib/postgresql.sh — PostgreSQL database dump support

[[ -n "${_GNIZA4LINUX_POSTGRESQL_LOADED:-}" ]] && return 0
_GNIZA4LINUX_POSTGRESQL_LOADED=1

# System databases always excluded from dumps
_PGSQL_SYSTEM_DBS="template0 template1 postgres"

# Build SSH prefix for remote PostgreSQL operations.
# Sets _PGSQL_SSH array. Returns 1 if local (no SSH needed).
_pgsql_is_remote() {
    [[ "${TARGET_SOURCE_TYPE:-local}" == "ssh" ]] || return 1
    _PGSQL_SSH=(ssh -o StrictHostKeyChecking=accept-new -o "ConnectTimeout=${SSH_TIMEOUT:-30}" -p "${TARGET_SOURCE_PORT:-22}")
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "key" ]]; then
        _PGSQL_SSH+=(-o BatchMode=yes)
        [[ -n "${TARGET_SOURCE_KEY:-}" ]] && _PGSQL_SSH+=(-i "$TARGET_SOURCE_KEY")
    fi
    _PGSQL_SSH+=("${TARGET_SOURCE_USER:-gniza}@${TARGET_SOURCE_HOST}")
    return 0
}

# Run a command locally or via SSH. For remote, wraps with sshpass if needed.
# Usage: _pgsql_run_cmd "psql -U postgres -At -c 'SELECT 1'" [use_sudo]
# use_sudo: "auto" (default) = sudo when no user/password, "yes" = always, "no" = never
_pgsql_run_cmd() {
    local cmd_str="$1"
    local use_sudo="${2:-auto}"
    if _pgsql_is_remote; then
        # Prepend PGPASSWORD on remote side if set
        if [[ -n "${TARGET_POSTGRESQL_PASSWORD:-}" ]]; then
            cmd_str="PGPASSWORD=$(printf '%q' "$TARGET_POSTGRESQL_PASSWORD") $cmd_str"
        elif [[ "$use_sudo" == "yes" || ( "$use_sudo" == "auto" && -z "${TARGET_POSTGRESQL_USER:-}" ) ]]; then
            # Use sudo for peer auth on remote
            cmd_str="sudo $cmd_str"
        fi
        if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
            SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_PGSQL_SSH[@]}" "$cmd_str"
        else
            "${_PGSQL_SSH[@]}" "$cmd_str"
        fi
    else
        # Local: set PGPASSWORD if needed, then eval
        # SAFETY: All interpolated values in $cmd_str are escaped via printf '%q'
        # in the calling functions (_pgsql_build_conn_str, pgsql_dump_databases,
        # pgsql_dump_roles). Do not pass unescaped user input.
        if [[ -n "${TARGET_POSTGRESQL_PASSWORD:-}" ]]; then
            PGPASSWORD="$TARGET_POSTGRESQL_PASSWORD" eval "$cmd_str"
        else
            eval "$cmd_str"
        fi
    fi
}

# Run a command via SSH without the sudo/PGPASSWORD wrapper.
_pgsql_ssh_raw() {
    local cmd_str="$1"
    _pgsql_is_remote || return 1
    if [[ "${TARGET_SOURCE_AUTH_METHOD:-key}" == "password" && -n "${TARGET_SOURCE_PASSWORD:-}" ]]; then
        SSHPASS="$TARGET_SOURCE_PASSWORD" sshpass -e "${_PGSQL_SSH[@]}" "$cmd_str"
    else
        "${_PGSQL_SSH[@]}" "$cmd_str"
    fi
}

# Detect the pg_dump binary, locally or remotely.
_pgsql_find_dump_cmd() {
    if _pgsql_is_remote; then
        _pgsql_ssh_raw "PATH=\$PATH:/usr/bin:/usr/local/bin command -v pg_dump" 2>/dev/null || return 1
    else
        if command -v pg_dump &>/dev/null; then
            echo "pg_dump"
        else
            return 1
        fi
    fi
}

# Detect the psql client binary, locally or remotely.
_pgsql_find_client_cmd() {
    if _pgsql_is_remote; then
        _pgsql_ssh_raw "PATH=\$PATH:/usr/bin:/usr/local/bin command -v psql" 2>/dev/null || return 1
    else
        if command -v psql &>/dev/null; then
            echo "psql"
        else
            return 1
        fi
    fi
}

# Build connection arguments from TARGET_POSTGRESQL_* globals into PGSQL_CONN_ARGS array.
# Sets PGPASSWORD env var if password is configured (local mode only).
pgsql_build_conn_args() {
    PGSQL_CONN_ARGS=()
    if [[ -n "${TARGET_POSTGRESQL_USER:-}" ]]; then
        PGSQL_CONN_ARGS+=(-U "$TARGET_POSTGRESQL_USER")
    elif _pgsql_is_remote; then
        # Remote: default to postgres user (peer auth won't work remotely)
        PGSQL_CONN_ARGS+=(-U "postgres")
    fi
    if [[ -n "${TARGET_POSTGRESQL_HOST:-}" && "${TARGET_POSTGRESQL_HOST}" != "localhost" ]]; then
        PGSQL_CONN_ARGS+=(-h "$TARGET_POSTGRESQL_HOST")
    fi
    if [[ -n "${TARGET_POSTGRESQL_PORT:-}" && "${TARGET_POSTGRESQL_PORT}" != "5432" ]]; then
        PGSQL_CONN_ARGS+=(-p "$TARGET_POSTGRESQL_PORT")
    fi
    if [[ -n "${TARGET_POSTGRESQL_PASSWORD:-}" ]]; then
        export PGPASSWORD="${TARGET_POSTGRESQL_PASSWORD}"
    fi
}

# Build connection arguments as a string for embedding in SSH commands.
# Returns a string like: -U postgres -h host -p port
_pgsql_build_conn_str() {
    local conn_str=""
    if [[ -n "${TARGET_POSTGRESQL_USER:-}" ]]; then
        conn_str+="-U $(printf '%q' "$TARGET_POSTGRESQL_USER")"
    elif _pgsql_is_remote; then
        # Remote: default to postgres user (peer auth won't work remotely)
        conn_str+="-U postgres"
    fi
    if [[ -n "${TARGET_POSTGRESQL_HOST:-}" && "${TARGET_POSTGRESQL_HOST}" != "localhost" ]]; then
        conn_str+=" -h $(printf '%q' "$TARGET_POSTGRESQL_HOST")"
    fi
    if [[ -n "${TARGET_POSTGRESQL_PORT:-}" && "${TARGET_POSTGRESQL_PORT}" != "5432" ]]; then
        conn_str+=" -p $(printf '%q' "$TARGET_POSTGRESQL_PORT")"
    fi
    echo "$conn_str"
}

# Get list of databases to dump.
# Outputs one database name per line.
pgsql_get_databases() {
    local client_cmd
    client_cmd=$(_pgsql_find_client_cmd) || {
        log_error "PostgreSQL client (psql) not found"
        return 1
    }

    local all_dbs
    local sql_query="SELECT datname FROM pg_database WHERE datistemplate = false AND datname != 'postgres'"
    if _pgsql_is_remote; then
        local conn_str
        conn_str=$(_pgsql_build_conn_str)
        # Try without sudo first (psql client may not be in sudoers),
        # fall back to sudo if that fails
        all_dbs=$(_pgsql_run_cmd "$client_cmd $conn_str -At -c $(printf '%q' "$sql_query")" "no" 2>&1) || {
            all_dbs=$(_pgsql_run_cmd "$client_cmd $conn_str -At -c $(printf '%q' "$sql_query")" 2>&1) || {
                log_error "Failed to list databases: $all_dbs"
                return 1
            }
        }
    else
        pgsql_build_conn_args
        all_dbs=$("$client_cmd" "${PGSQL_CONN_ARGS[@]}" -At -c "$sql_query" 2>&1) || {
            log_error "Failed to list databases: $all_dbs"
            return 1
        }
    fi

    # Build exclude list: system dbs + user-specified excludes
    local -a exclude_list=()
    local db
    for db in $_PGSQL_SYSTEM_DBS; do
        exclude_list+=("$db")
    done
    if [[ -n "${TARGET_POSTGRESQL_EXCLUDE:-}" ]]; then
        local -a user_excludes
        IFS=',' read -ra user_excludes <<< "$TARGET_POSTGRESQL_EXCLUDE"
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
# Sets PGSQL_DUMP_DIR global to the temp directory path containing _postgresql/ subdir.
# Returns 0 on success, 1 on failure.
pgsql_dump_databases() {
    local dump_cmd
    dump_cmd=$(_pgsql_find_dump_cmd) || {
        log_error "pg_dump not found — cannot dump PostgreSQL databases"
        return 1
    }

    local is_remote=false
    local conn_str=""
    if _pgsql_is_remote; then
        is_remote=true
        conn_str=$(_pgsql_build_conn_str)
    else
        pgsql_build_conn_args
    fi

    # Determine databases to dump
    local -a databases=()
    if [[ "${TARGET_POSTGRESQL_MODE:-all}" == "specific" || "${TARGET_POSTGRESQL_MODE:-all}" == "select" ]]; then
        # Use explicitly listed databases
        if [[ -z "${TARGET_POSTGRESQL_DATABASES:-}" ]]; then
            log_error "PostgreSQL mode=specific but TARGET_POSTGRESQL_DATABASES is empty"
            return 1
        fi
        local -a db_list
        IFS=',' read -ra db_list <<< "$TARGET_POSTGRESQL_DATABASES"
        local db
        for db in "${db_list[@]}"; do
            db="${db#"${db%%[![:space:]]*}"}"
            db="${db%"${db##*[![:space:]]}"}"
            [[ -n "$db" ]] && databases+=("$db")
        done
    else
        # mode=all: discover databases, apply excludes
        local db_output
        db_output=$(pgsql_get_databases) || {
            log_error "Failed to discover PostgreSQL databases"
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
    PGSQL_DUMP_DIR=$(mktemp -d "${WORK_DIR}/gniza-pgsql-XXXXXX")
    mkdir -p "$PGSQL_DUMP_DIR/_postgresql"

    # Parse extra opts
    local extra_opts_str=""
    if [[ -n "${TARGET_POSTGRESQL_EXTRA_OPTS:-}" ]]; then
        if [[ ! "$TARGET_POSTGRESQL_EXTRA_OPTS" =~ ^[a-zA-Z0-9\ ._=/-]+$ ]]; then
            log_error "TARGET_POSTGRESQL_EXTRA_OPTS contains invalid characters"
            return 1
        fi
        extra_opts_str="${TARGET_POSTGRESQL_EXTRA_OPTS}"
    else
        extra_opts_str="--no-owner --no-privileges"
    fi
    local failed=false

    for db in "${databases[@]}"; do
        # Validate database name to prevent path traversal
        if [[ ! "$db" =~ ^[a-zA-Z0-9._-]+$ ]]; then
            log_error "Invalid database name, skipping: $db"
            failed=true
            continue
        fi
        log_info "Dumping PostgreSQL database: $db"
        local outfile="$PGSQL_DUMP_DIR/_postgresql/${db}.sql.gz"
        local errfile="$PGSQL_DUMP_DIR/_postgresql/${db}.err"
        if [[ "$is_remote" == "true" ]]; then
            if _pgsql_run_cmd "$dump_cmd $conn_str -Fp $extra_opts_str $(printf '%q' "$db") | gzip" > "$outfile" 2>"$errfile"; then
                rm -f "$errfile"
                local size; size=$(stat -c%s "$outfile" 2>/dev/null || echo "?")
                log_debug "Dumped $db -> ${db}.sql.gz ($size bytes)"
            else
                log_error "Failed to dump database: $db"
                [[ -s "$errfile" ]] && log_error "pg_dump: $(cat "$errfile")"
                rm -f "$errfile"
                failed=true
            fi
        else
            local -a extra_opts_arr=()
            read -ra extra_opts_arr <<< "$extra_opts_str"
            if "$dump_cmd" "${PGSQL_CONN_ARGS[@]}" -Fp "${extra_opts_arr[@]}" "$db" 2>"$errfile" | gzip > "$outfile"; then
                rm -f "$errfile"
                local size; size=$(stat -c%s "$outfile" 2>/dev/null || echo "?")
                log_debug "Dumped $db -> ${db}.sql.gz ($size bytes)"
            else
                log_error "Failed to dump database: $db"
                [[ -s "$errfile" ]] && log_error "pg_dump: $(cat "$errfile")"
                rm -f "$errfile"
                failed=true
            fi
        fi
    done

    if [[ "$failed" == "true" ]]; then
        log_error "One or more PostgreSQL dumps failed"
        return 1
    fi

    log_info "PostgreSQL dumps completed: ${#databases[@]} database(s) in $PGSQL_DUMP_DIR/_postgresql/"
    return 0
}

# Dump PostgreSQL roles to roles.sql in the dump directory.
# Must be called after pgsql_dump_databases() sets PGSQL_DUMP_DIR.
pgsql_dump_roles() {
    local is_remote=false
    local conn_str=""
    if _pgsql_is_remote; then
        is_remote=true
        conn_str=$(_pgsql_build_conn_str)
    else
        pgsql_build_conn_args
    fi

    local roles_file="$PGSQL_DUMP_DIR/_postgresql/roles.sql"

    # Find pg_dumpall binary
    local dumpall_cmd
    if [[ "$is_remote" == "true" ]]; then
        dumpall_cmd=$(_pgsql_ssh_raw "PATH=\$PATH:/usr/bin:/usr/local/bin command -v pg_dumpall" 2>/dev/null) || {
            log_error "pg_dumpall not found on remote host — cannot dump roles"
            return 1
        }
    else
        if command -v pg_dumpall &>/dev/null; then
            dumpall_cmd="pg_dumpall"
        else
            log_error "pg_dumpall not found — cannot dump roles"
            return 1
        fi
    fi

    log_info "Dumping PostgreSQL roles..."
    local errfile="$PGSQL_DUMP_DIR/_postgresql/roles.err"

    if [[ "$is_remote" == "true" ]]; then
        if _pgsql_run_cmd "$dumpall_cmd $conn_str --roles-only" > "$roles_file" 2>"$errfile"; then
            rm -f "$errfile"
            log_info "PostgreSQL roles dumped -> roles.sql"
        else
            log_error "Failed to dump PostgreSQL roles"
            [[ -s "$errfile" ]] && log_error "pg_dumpall: $(cat "$errfile")"
            rm -f "$errfile"
            return 1
        fi
    else
        if "$dumpall_cmd" "${PGSQL_CONN_ARGS[@]}" --roles-only > "$roles_file" 2>"$errfile"; then
            rm -f "$errfile"
            log_info "PostgreSQL roles dumped -> roles.sql"
        else
            log_error "Failed to dump PostgreSQL roles"
            [[ -s "$errfile" ]] && log_error "pg_dumpall: $(cat "$errfile")"
            rm -f "$errfile"
            return 1
        fi
    fi

    return 0
}

# Restore PostgreSQL databases from a directory of .sql.gz files.
# Usage: pgsql_restore_databases <dir_path>
# The directory should contain *.sql.gz files and optionally roles.sql.
pgsql_restore_databases() {
    local pgsql_dir="$1"

    if [[ ! -d "$pgsql_dir" ]]; then
        log_error "PostgreSQL restore dir not found: $pgsql_dir"
        return 1
    fi

    local client_cmd
    client_cmd=$(_pgsql_find_client_cmd) || {
        log_error "PostgreSQL client (psql) not found — cannot restore databases"
        return 1
    }

    pgsql_build_conn_args

    local errors=0

    # Restore roles first (before databases, so ownership is correct)
    if [[ -f "$pgsql_dir/roles.sql" ]]; then
        log_info "Restoring PostgreSQL roles..."
        if PGOPTIONS="--client-min-messages=warning" "$client_cmd" "${PGSQL_CONN_ARGS[@]}" \
            -v ON_ERROR_STOP=off -f "$pgsql_dir/roles.sql" 2>/dev/null; then
            log_info "PostgreSQL roles restored"
        else
            log_error "Failed to restore some PostgreSQL roles (partial restore may have occurred)"
            ((errors++)) || true
        fi
    fi

    # Restore database dumps
    local f
    for f in "$pgsql_dir"/*.sql.gz; do
        [[ -f "$f" ]] || continue
        local db_name
        db_name=$(basename "$f" .sql.gz)

        # Skip system databases
        local skip=false
        local sdb
        for sdb in $_PGSQL_SYSTEM_DBS; do
            if [[ "$db_name" == "$sdb" ]]; then
                skip=true
                break
            fi
        done
        [[ "$skip" == "true" ]] && continue

        # Validate database name
        if [[ ! "$db_name" =~ ^[a-zA-Z0-9._-]+$ ]]; then
            log_error "Invalid database name in restore, skipping: $db_name"
            ((errors++)) || true
            continue
        fi

        log_info "Restoring PostgreSQL database: $db_name"

        # Create database if not exists (suppress "already exists" error)
        if command -v createdb &>/dev/null; then
            createdb "${PGSQL_CONN_ARGS[@]}" "$db_name" 2>/dev/null || true
        else
            "$client_cmd" "${PGSQL_CONN_ARGS[@]}" -c \
                "CREATE DATABASE \"$db_name\"" 2>/dev/null || true
        fi

        # Import dump
        if gunzip -c "$f" | "$client_cmd" "${PGSQL_CONN_ARGS[@]}" -d "$db_name" 2>/dev/null; then
            log_info "Restored database: $db_name"
        else
            log_error "Failed to restore database: $db_name"
            ((errors++)) || true
        fi
    done

    unset PGPASSWORD 2>/dev/null || true

    if (( errors > 0 )); then
        log_error "PostgreSQL restore completed with $errors error(s)"
        return 1
    fi

    log_info "PostgreSQL restore completed successfully"
    return 0
}

# Clean up the temporary PostgreSQL dump directory and env vars.
pgsql_cleanup_dump() {
    if [[ -n "${PGSQL_DUMP_DIR:-}" && -d "$PGSQL_DUMP_DIR" ]]; then
        rm -rf "$PGSQL_DUMP_DIR"
        log_debug "Cleaned up PostgreSQL dump dir: $PGSQL_DUMP_DIR"
        PGSQL_DUMP_DIR=""
    fi
    unset PGPASSWORD 2>/dev/null || true
}
