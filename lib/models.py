from dataclasses import dataclass, field, fields


def _to_conf(obj) -> dict[str, str]:
    """Generic metadata-driven serialization for config dataclasses."""
    result = {}
    for f in fields(obj):
        key = f.metadata.get("conf_key")
        if key:
            val = getattr(obj, f.name)
            if val is not None and val != "":
                result[key] = str(val)
    return result


def _from_conf(cls, name, data):
    """Generic metadata-driven deserialization for config dataclasses."""
    kwargs = {"name": name} if "name" in {f.name for f in fields(cls)} else {}
    for f in fields(cls):
        key = f.metadata.get("conf_key")
        if key and key in data:
            kwargs[f.name] = data[key]
    return cls(**kwargs)


@dataclass
class Target:
    name: str = field(default="", metadata={"conf_key": "TARGET_NAME"})
    folders: str = field(default="", metadata={"conf_key": "TARGET_FOLDERS"})
    exclude: str = field(default="", metadata={"conf_key": "TARGET_EXCLUDE"})
    include: str = field(default="", metadata={"conf_key": "TARGET_INCLUDE"})
    remote: str = field(default="", metadata={"conf_key": "TARGET_REMOTE"})
    pre_hook: str = field(default="", metadata={"conf_key": "TARGET_PRE_HOOK"})
    post_hook: str = field(default="", metadata={"conf_key": "TARGET_POST_HOOK"})
    enabled: str = field(default="yes", metadata={"conf_key": "TARGET_ENABLED"})
    source_type: str = field(default="local", metadata={"conf_key": "TARGET_SOURCE_TYPE"})
    source_host: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_HOST"})
    source_port: str = field(default="22", metadata={"conf_key": "TARGET_SOURCE_PORT"})
    source_user: str = field(default="gniza", metadata={"conf_key": "TARGET_SOURCE_USER"})
    source_auth_method: str = field(default="key", metadata={"conf_key": "TARGET_SOURCE_AUTH_METHOD"})
    source_key: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_KEY"})
    source_password: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_PASSWORD"})
    source_sudo: str = field(default="yes", metadata={"conf_key": "TARGET_SOURCE_SUDO"})
    source_s3_bucket: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_S3_BUCKET"})
    source_s3_region: str = field(default="us-east-1", metadata={"conf_key": "TARGET_SOURCE_S3_REGION"})
    source_s3_endpoint: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_S3_ENDPOINT"})
    source_s3_provider: str = field(default="AWS", metadata={"conf_key": "TARGET_SOURCE_S3_PROVIDER"})
    source_s3_access_key_id: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_S3_ACCESS_KEY_ID"})
    source_s3_secret_access_key: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_S3_SECRET_ACCESS_KEY"})
    source_gdrive_sa_file: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE"})
    source_gdrive_root_folder_id: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID"})
    source_rclone_config_path: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_RCLONE_CONFIG_PATH"})
    source_rclone_remote_name: str = field(default="", metadata={"conf_key": "TARGET_SOURCE_RCLONE_REMOTE_NAME"})
    mysql_enabled: str = field(default="no", metadata={"conf_key": "TARGET_MYSQL_ENABLED"})
    mysql_mode: str = field(default="all", metadata={"conf_key": "TARGET_MYSQL_MODE"})
    mysql_databases: str = field(default="", metadata={"conf_key": "TARGET_MYSQL_DATABASES"})
    mysql_exclude: str = field(default="", metadata={"conf_key": "TARGET_MYSQL_EXCLUDE"})
    mysql_user: str = field(default="", metadata={"conf_key": "TARGET_MYSQL_USER"})
    mysql_password: str = field(default="", metadata={"conf_key": "TARGET_MYSQL_PASSWORD"})
    mysql_host: str = field(default="localhost", metadata={"conf_key": "TARGET_MYSQL_HOST"})
    mysql_port: str = field(default="3306", metadata={"conf_key": "TARGET_MYSQL_PORT"})
    mysql_extra_opts: str = field(default="--single-transaction --routines --triggers", metadata={"conf_key": "TARGET_MYSQL_EXTRA_OPTS"})
    postgresql_enabled: str = field(default="no", metadata={"conf_key": "TARGET_POSTGRESQL_ENABLED"})
    postgresql_mode: str = field(default="all", metadata={"conf_key": "TARGET_POSTGRESQL_MODE"})
    postgresql_databases: str = field(default="", metadata={"conf_key": "TARGET_POSTGRESQL_DATABASES"})
    postgresql_exclude: str = field(default="", metadata={"conf_key": "TARGET_POSTGRESQL_EXCLUDE"})
    postgresql_user: str = field(default="", metadata={"conf_key": "TARGET_POSTGRESQL_USER"})
    postgresql_password: str = field(default="", metadata={"conf_key": "TARGET_POSTGRESQL_PASSWORD"})
    postgresql_host: str = field(default="localhost", metadata={"conf_key": "TARGET_POSTGRESQL_HOST"})
    postgresql_port: str = field(default="5432", metadata={"conf_key": "TARGET_POSTGRESQL_PORT"})
    postgresql_extra_opts: str = field(default="--no-owner --no-privileges", metadata={"conf_key": "TARGET_POSTGRESQL_EXTRA_OPTS"})
    crontab_enabled: str = field(default="no", metadata={"conf_key": "TARGET_CRONTAB_ENABLED"})
    crontab_users: str = field(default="root", metadata={"conf_key": "TARGET_CRONTAB_USERS"})

    def to_conf(self) -> dict[str, str]:
        return _to_conf(self)

    @classmethod
    def from_conf(cls, name: str, data: dict[str, str]) -> "Target":
        return _from_conf(cls, name, data)


@dataclass
class Remote:
    name: str = ""
    type: str = field(default="local", metadata={"conf_key": "REMOTE_TYPE"})
    host: str = field(default="", metadata={"conf_key": "REMOTE_HOST"})
    port: str = field(default="22", metadata={"conf_key": "REMOTE_PORT"})
    user: str = field(default="gniza", metadata={"conf_key": "REMOTE_USER"})
    auth_method: str = field(default="key", metadata={"conf_key": "REMOTE_AUTH_METHOD"})
    key: str = field(default="", metadata={"conf_key": "REMOTE_KEY"})
    password: str = field(default="", metadata={"conf_key": "REMOTE_PASSWORD"})
    sudo: str = field(default="yes", metadata={"conf_key": "REMOTE_SUDO"})
    base: str = field(default="/backups", metadata={"conf_key": "REMOTE_BASE"})
    bwlimit: str = field(default="0", metadata={"conf_key": "BWLIMIT"})
    s3_provider: str = field(default="AWS", metadata={"conf_key": "S3_PROVIDER"})
    s3_bucket: str = field(default="", metadata={"conf_key": "S3_BUCKET"})
    s3_region: str = field(default="us-east-1", metadata={"conf_key": "S3_REGION"})
    s3_endpoint: str = field(default="", metadata={"conf_key": "S3_ENDPOINT"})
    s3_access_key_id: str = field(default="", metadata={"conf_key": "S3_ACCESS_KEY_ID"})
    s3_secret_access_key: str = field(default="", metadata={"conf_key": "S3_SECRET_ACCESS_KEY"})
    gdrive_sa_file: str = field(default="", metadata={"conf_key": "GDRIVE_SERVICE_ACCOUNT_FILE"})
    gdrive_root_folder_id: str = field(default="", metadata={"conf_key": "GDRIVE_ROOT_FOLDER_ID"})
    rclone_config_path: str = field(default="", metadata={"conf_key": "RCLONE_CONFIG_PATH"})
    rclone_remote_name: str = field(default="", metadata={"conf_key": "RCLONE_REMOTE_NAME"})

    def to_conf(self) -> dict[str, str]:
        return _to_conf(self)

    @classmethod
    def from_conf(cls, name: str, data: dict[str, str]) -> "Remote":
        return _from_conf(cls, name, data)


@dataclass
class Schedule:
    name: str = ""
    schedule: str = field(default="daily", metadata={"conf_key": "SCHEDULE"})
    time: str = field(default="02:00", metadata={"conf_key": "SCHEDULE_TIME"})
    day: str = field(default="", metadata={"conf_key": "SCHEDULE_DAY"})
    cron: str = field(default="", metadata={"conf_key": "SCHEDULE_CRON"})
    targets: str = field(default="", metadata={"conf_key": "TARGETS"})
    remotes: str = field(default="", metadata={"conf_key": "REMOTES"})
    active: str = field(default="yes", metadata={"conf_key": "SCHEDULE_ACTIVE"})
    retention_count: str = field(default="", metadata={"conf_key": "RETENTION_COUNT"})

    def to_conf(self) -> dict[str, str]:
        return _to_conf(self)

    @classmethod
    def from_conf(cls, name: str, data: dict[str, str]) -> "Schedule":
        return _from_conf(cls, name, data)


@dataclass
class AppSettings:
    backup_mode: str = field(default="incremental", metadata={"conf_key": "BACKUP_MODE"})
    bwlimit: str = field(default="0", metadata={"conf_key": "BWLIMIT"})
    retention_count: str = field(default="30", metadata={"conf_key": "RETENTION_COUNT"})
    log_level: str = field(default="info", metadata={"conf_key": "LOG_LEVEL"})
    log_retain: str = field(default="90", metadata={"conf_key": "LOG_RETAIN"})
    notify_email: str = field(default="", metadata={"conf_key": "NOTIFY_EMAIL"})
    notify_on: str = field(default="failure", metadata={"conf_key": "NOTIFY_ON"})
    smtp_host: str = field(default="", metadata={"conf_key": "SMTP_HOST"})
    smtp_port: str = field(default="587", metadata={"conf_key": "SMTP_PORT"})
    smtp_user: str = field(default="", metadata={"conf_key": "SMTP_USER"})
    smtp_password: str = field(default="", metadata={"conf_key": "SMTP_PASSWORD"})
    smtp_from: str = field(default="", metadata={"conf_key": "SMTP_FROM"})
    smtp_security: str = field(default="tls", metadata={"conf_key": "SMTP_SECURITY"})
    telegram_bot_token: str = field(default="", metadata={"conf_key": "TELEGRAM_BOT_TOKEN"})
    telegram_chat_id: str = field(default="", metadata={"conf_key": "TELEGRAM_CHAT_ID"})
    webhook_url: str = field(default="", metadata={"conf_key": "WEBHOOK_URL"})
    webhook_type: str = field(default="slack", metadata={"conf_key": "WEBHOOK_TYPE"})
    ntfy_url: str = field(default="", metadata={"conf_key": "NTFY_URL"})
    ntfy_token: str = field(default="", metadata={"conf_key": "NTFY_TOKEN"})
    ntfy_priority: str = field(default="default", metadata={"conf_key": "NTFY_PRIORITY"})
    healthchecks_url: str = field(default="", metadata={"conf_key": "HEALTHCHECKS_URL"})
    stale_alert_hours: str = field(default="0", metadata={"conf_key": "STALE_ALERT_HOURS"})
    digest_enabled: str = field(default="no", metadata={"conf_key": "DIGEST_ENABLED"})
    digest_frequency: str = field(default="daily", metadata={"conf_key": "DIGEST_FREQUENCY"})
    digest_time: str = field(default="08:00", metadata={"conf_key": "DIGEST_TIME"})
    digest_day: str = field(default="1", metadata={"conf_key": "DIGEST_DAY"})
    ssh_timeout: str = field(default="30", metadata={"conf_key": "SSH_TIMEOUT"})
    ssh_retries: str = field(default="3", metadata={"conf_key": "SSH_RETRIES"})
    rsync_extra_opts: str = field(default="", metadata={"conf_key": "RSYNC_EXTRA_OPTS"})
    rsync_compress: str = field(default="no", metadata={"conf_key": "RSYNC_COMPRESS"})
    rsync_checksum: str = field(default="no", metadata={"conf_key": "RSYNC_CHECKSUM"})
    disk_usage_threshold: str = field(default="95", metadata={"conf_key": "DISK_USAGE_THRESHOLD"})
    max_concurrent_jobs: str = field(default="1", metadata={"conf_key": "MAX_CONCURRENT_JOBS"})
    work_dir: str = field(default="", metadata={"conf_key": "WORK_DIR"})
    web_port: str = field(default="2323", metadata={"conf_key": "WEB_PORT"})
    web_host: str = field(default="0.0.0.0", metadata={"conf_key": "WEB_HOST"})
    web_api_key: str = field(default="", metadata={"conf_key": "WEB_API_KEY"})
    login_max_attempts: str = field(default="5", metadata={"conf_key": "LOGIN_MAX_ATTEMPTS"})
    login_lockout_seconds: str = field(default="300", metadata={"conf_key": "LOGIN_LOCKOUT_SECONDS"})

    @classmethod
    def from_conf(cls, data: dict[str, str]) -> "AppSettings":
        return _from_conf(cls, None, data)

    def to_conf(self) -> dict[str, str]:
        return _to_conf(self)
