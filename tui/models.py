from dataclasses import dataclass, field


@dataclass
class Target:
    name: str = ""
    folders: str = ""
    exclude: str = ""
    include: str = ""
    remote: str = ""
    pre_hook: str = ""
    post_hook: str = ""
    enabled: str = "yes"
    source_type: str = "local"
    source_host: str = ""
    source_port: str = "22"
    source_user: str = "root"
    source_auth_method: str = "key"
    source_key: str = ""
    source_password: str = ""
    source_s3_bucket: str = ""
    source_s3_region: str = "us-east-1"
    source_s3_endpoint: str = ""
    source_s3_access_key_id: str = ""
    source_s3_secret_access_key: str = ""
    source_gdrive_sa_file: str = ""
    source_gdrive_root_folder_id: str = ""
    mysql_enabled: str = "no"
    mysql_mode: str = "all"
    mysql_databases: str = ""
    mysql_exclude: str = ""
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_host: str = "localhost"
    mysql_port: str = "3306"
    mysql_extra_opts: str = "--single-transaction --routines --triggers"

    def to_conf(self) -> dict[str, str]:
        data = {
            "TARGET_NAME": self.name,
            "TARGET_FOLDERS": self.folders,
            "TARGET_EXCLUDE": self.exclude,
            "TARGET_INCLUDE": self.include,
            "TARGET_REMOTE": self.remote,
            "TARGET_PRE_HOOK": self.pre_hook,
            "TARGET_POST_HOOK": self.post_hook,
            "TARGET_ENABLED": self.enabled,
            "TARGET_SOURCE_TYPE": self.source_type,
        }
        if self.source_type == "ssh":
            data.update({
                "TARGET_SOURCE_HOST": self.source_host,
                "TARGET_SOURCE_PORT": self.source_port,
                "TARGET_SOURCE_USER": self.source_user,
                "TARGET_SOURCE_AUTH_METHOD": self.source_auth_method,
                "TARGET_SOURCE_KEY": self.source_key,
                "TARGET_SOURCE_PASSWORD": self.source_password,
            })
        elif self.source_type == "s3":
            data.update({
                "TARGET_SOURCE_S3_BUCKET": self.source_s3_bucket,
                "TARGET_SOURCE_S3_REGION": self.source_s3_region,
                "TARGET_SOURCE_S3_ENDPOINT": self.source_s3_endpoint,
                "TARGET_SOURCE_S3_ACCESS_KEY_ID": self.source_s3_access_key_id,
                "TARGET_SOURCE_S3_SECRET_ACCESS_KEY": self.source_s3_secret_access_key,
            })
        elif self.source_type == "gdrive":
            data.update({
                "TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE": self.source_gdrive_sa_file,
                "TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID": self.source_gdrive_root_folder_id,
            })
        data.update({
            "TARGET_MYSQL_ENABLED": self.mysql_enabled,
            "TARGET_MYSQL_MODE": self.mysql_mode,
            "TARGET_MYSQL_DATABASES": self.mysql_databases,
            "TARGET_MYSQL_EXCLUDE": self.mysql_exclude,
            "TARGET_MYSQL_USER": self.mysql_user,
            "TARGET_MYSQL_PASSWORD": self.mysql_password,
            "TARGET_MYSQL_HOST": self.mysql_host,
            "TARGET_MYSQL_PORT": self.mysql_port,
            "TARGET_MYSQL_EXTRA_OPTS": self.mysql_extra_opts,
        })
        return data

    @classmethod
    def from_conf(cls, name: str, data: dict[str, str]) -> "Target":
        return cls(
            name=data.get("TARGET_NAME", name),
            folders=data.get("TARGET_FOLDERS", ""),
            exclude=data.get("TARGET_EXCLUDE", ""),
            include=data.get("TARGET_INCLUDE", ""),
            remote=data.get("TARGET_REMOTE", ""),
            pre_hook=data.get("TARGET_PRE_HOOK", ""),
            post_hook=data.get("TARGET_POST_HOOK", ""),
            enabled=data.get("TARGET_ENABLED", "yes"),
            source_type=data.get("TARGET_SOURCE_TYPE", "local"),
            source_host=data.get("TARGET_SOURCE_HOST", ""),
            source_port=data.get("TARGET_SOURCE_PORT", "22"),
            source_user=data.get("TARGET_SOURCE_USER", "root"),
            source_auth_method=data.get("TARGET_SOURCE_AUTH_METHOD", "key"),
            source_key=data.get("TARGET_SOURCE_KEY", ""),
            source_password=data.get("TARGET_SOURCE_PASSWORD", ""),
            source_s3_bucket=data.get("TARGET_SOURCE_S3_BUCKET", ""),
            source_s3_region=data.get("TARGET_SOURCE_S3_REGION", "us-east-1"),
            source_s3_endpoint=data.get("TARGET_SOURCE_S3_ENDPOINT", ""),
            source_s3_access_key_id=data.get("TARGET_SOURCE_S3_ACCESS_KEY_ID", ""),
            source_s3_secret_access_key=data.get("TARGET_SOURCE_S3_SECRET_ACCESS_KEY", ""),
            source_gdrive_sa_file=data.get("TARGET_SOURCE_GDRIVE_SERVICE_ACCOUNT_FILE", ""),
            source_gdrive_root_folder_id=data.get("TARGET_SOURCE_GDRIVE_ROOT_FOLDER_ID", ""),
            mysql_enabled=data.get("TARGET_MYSQL_ENABLED", "no"),
            mysql_mode=data.get("TARGET_MYSQL_MODE", "all"),
            mysql_databases=data.get("TARGET_MYSQL_DATABASES", ""),
            mysql_exclude=data.get("TARGET_MYSQL_EXCLUDE", ""),
            mysql_user=data.get("TARGET_MYSQL_USER", ""),
            mysql_password=data.get("TARGET_MYSQL_PASSWORD", ""),
            mysql_host=data.get("TARGET_MYSQL_HOST", "localhost"),
            mysql_port=data.get("TARGET_MYSQL_PORT", "3306"),
            mysql_extra_opts=data.get("TARGET_MYSQL_EXTRA_OPTS", "--single-transaction --routines --triggers"),
        )


@dataclass
class Remote:
    name: str = ""
    type: str = "local"
    host: str = ""
    port: str = "22"
    user: str = "root"
    auth_method: str = "key"
    key: str = ""
    password: str = ""
    base: str = "/backups"
    bwlimit: str = "0"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    gdrive_sa_file: str = ""
    gdrive_root_folder_id: str = ""

    def to_conf(self) -> dict[str, str]:
        data: dict[str, str] = {"REMOTE_TYPE": self.type}
        if self.type == "ssh":
            data.update({
                "REMOTE_HOST": self.host,
                "REMOTE_PORT": self.port,
                "REMOTE_USER": self.user,
                "REMOTE_AUTH_METHOD": self.auth_method,
                "REMOTE_KEY": self.key,
                "REMOTE_PASSWORD": self.password,
                "REMOTE_BASE": self.base,
                "BWLIMIT": self.bwlimit,
            })
        elif self.type == "local":
            data.update({
                "REMOTE_BASE": self.base,
            })
        elif self.type == "s3":
            data.update({
                "S3_BUCKET": self.s3_bucket,
                "S3_REGION": self.s3_region,
                "S3_ENDPOINT": self.s3_endpoint,
                "S3_ACCESS_KEY_ID": self.s3_access_key_id,
                "S3_SECRET_ACCESS_KEY": self.s3_secret_access_key,
                "REMOTE_BASE": self.base,
            })
        elif self.type == "gdrive":
            data.update({
                "GDRIVE_SERVICE_ACCOUNT_FILE": self.gdrive_sa_file,
                "GDRIVE_ROOT_FOLDER_ID": self.gdrive_root_folder_id,
                "REMOTE_BASE": self.base,
            })
        return data

    @classmethod
    def from_conf(cls, name: str, data: dict[str, str]) -> "Remote":
        return cls(
            name=name,
            type=data.get("REMOTE_TYPE", "ssh"),
            host=data.get("REMOTE_HOST", ""),
            port=data.get("REMOTE_PORT", "22"),
            user=data.get("REMOTE_USER", "root"),
            auth_method=data.get("REMOTE_AUTH_METHOD", "key"),
            key=data.get("REMOTE_KEY", ""),
            password=data.get("REMOTE_PASSWORD", ""),
            base=data.get("REMOTE_BASE", "/backups"),
            bwlimit=data.get("BWLIMIT", "0"),
            s3_bucket=data.get("S3_BUCKET", ""),
            s3_region=data.get("S3_REGION", "us-east-1"),
            s3_endpoint=data.get("S3_ENDPOINT", ""),
            s3_access_key_id=data.get("S3_ACCESS_KEY_ID", ""),
            s3_secret_access_key=data.get("S3_SECRET_ACCESS_KEY", ""),
            gdrive_sa_file=data.get("GDRIVE_SERVICE_ACCOUNT_FILE", ""),
            gdrive_root_folder_id=data.get("GDRIVE_ROOT_FOLDER_ID", ""),
        )


@dataclass
class Schedule:
    name: str = ""
    schedule: str = "daily"
    time: str = "02:00"
    day: str = ""
    cron: str = ""
    targets: str = ""
    remotes: str = ""
    active: str = "yes"
    retention_count: str = ""

    def to_conf(self) -> dict[str, str]:
        return {
            "SCHEDULE": self.schedule,
            "SCHEDULE_TIME": self.time,
            "SCHEDULE_DAY": self.day,
            "SCHEDULE_CRON": self.cron,
            "SCHEDULE_ACTIVE": self.active,
            "TARGETS": self.targets,
            "REMOTES": self.remotes,
            "RETENTION_COUNT": self.retention_count,
        }

    @classmethod
    def from_conf(cls, name: str, data: dict[str, str]) -> "Schedule":
        return cls(
            name=name,
            schedule=data.get("SCHEDULE", "daily"),
            time=data.get("SCHEDULE_TIME", "02:00"),
            day=data.get("SCHEDULE_DAY", ""),
            cron=data.get("SCHEDULE_CRON", ""),
            targets=data.get("TARGETS", ""),
            remotes=data.get("REMOTES", ""),
            active=data.get("SCHEDULE_ACTIVE", "yes"),
            retention_count=data.get("RETENTION_COUNT", ""),
        )


@dataclass
class AppSettings:
    backup_mode: str = "incremental"
    bwlimit: str = "0"
    retention_count: str = "7"
    log_level: str = "INFO"
    log_retain: str = "30"
    notify_email: str = ""
    notify_on: str = "failure"
    smtp_host: str = ""
    smtp_port: str = "587"
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_security: str = "tls"
    ssh_timeout: str = "30"
    ssh_retries: str = "3"
    rsync_extra_opts: str = ""
    rsync_compress: str = "no"
    rsync_checksum: str = "no"
    disk_usage_threshold: str = "95"
    max_concurrent_jobs: str = "1"
    web_port: str = "2323"
    web_host: str = "0.0.0.0"
    web_api_key: str = ""
    login_max_attempts: str = "5"
    login_lockout_seconds: str = "300"

    @classmethod
    def from_conf(cls, data: dict[str, str]) -> "AppSettings":
        return cls(
            backup_mode=data.get("BACKUP_MODE", "incremental"),
            bwlimit=data.get("BWLIMIT", "0"),
            retention_count=data.get("RETENTION_COUNT", "7"),
            log_level=data.get("LOG_LEVEL", "INFO"),
            log_retain=data.get("LOG_RETAIN", "90"),
            notify_email=data.get("NOTIFY_EMAIL", ""),
            notify_on=data.get("NOTIFY_ON", "failure"),
            smtp_host=data.get("SMTP_HOST", ""),
            smtp_port=data.get("SMTP_PORT", "587"),
            smtp_user=data.get("SMTP_USER", ""),
            smtp_password=data.get("SMTP_PASSWORD", ""),
            smtp_from=data.get("SMTP_FROM", ""),
            smtp_security=data.get("SMTP_SECURITY", "tls"),
            ssh_timeout=data.get("SSH_TIMEOUT", "30"),
            ssh_retries=data.get("SSH_RETRIES", "3"),
            rsync_extra_opts=data.get("RSYNC_EXTRA_OPTS", ""),
            rsync_compress=data.get("RSYNC_COMPRESS", "no"),
            rsync_checksum=data.get("RSYNC_CHECKSUM", "no"),
            disk_usage_threshold=data.get("DISK_USAGE_THRESHOLD", "95"),
            max_concurrent_jobs=data.get("MAX_CONCURRENT_JOBS", "1"),
            web_port=data.get("WEB_PORT", "2323"),
            web_host=data.get("WEB_HOST", "0.0.0.0"),
            web_api_key=data.get("WEB_API_KEY", ""),
            login_max_attempts=data.get("LOGIN_MAX_ATTEMPTS", "5"),
            login_lockout_seconds=data.get("LOGIN_LOCKOUT_SECONDS", "300"),
        )

    def to_conf(self) -> dict[str, str]:
        return {
            "BACKUP_MODE": self.backup_mode,
            "BWLIMIT": self.bwlimit,
            "RETENTION_COUNT": self.retention_count,
            "LOG_LEVEL": self.log_level,
            "LOG_RETAIN": self.log_retain,
            "NOTIFY_EMAIL": self.notify_email,
            "NOTIFY_ON": self.notify_on,
            "SMTP_HOST": self.smtp_host,
            "SMTP_PORT": self.smtp_port,
            "SMTP_USER": self.smtp_user,
            "SMTP_PASSWORD": self.smtp_password,
            "SMTP_FROM": self.smtp_from,
            "SMTP_SECURITY": self.smtp_security,
            "SSH_TIMEOUT": self.ssh_timeout,
            "SSH_RETRIES": self.ssh_retries,
            "RSYNC_EXTRA_OPTS": self.rsync_extra_opts,
            "RSYNC_COMPRESS": self.rsync_compress,
            "RSYNC_CHECKSUM": self.rsync_checksum,
            "DISK_USAGE_THRESHOLD": self.disk_usage_threshold,
            "MAX_CONCURRENT_JOBS": self.max_concurrent_jobs,
            "WEB_PORT": self.web_port,
            "WEB_HOST": self.web_host,
            "WEB_API_KEY": self.web_api_key,
            "LOGIN_MAX_ATTEMPTS": self.login_max_attempts,
            "LOGIN_LOCKOUT_SECONDS": self.login_lockout_seconds,
        }
