"""Tests for lib.models — data model serialization."""
from dataclasses import fields
from lib.models import Target, Remote, Schedule, AppSettings


def test_target_to_conf():
    t = Target(name="test", folders="/var/www")
    conf = t.to_conf()
    assert conf["TARGET_NAME"] == "test"
    assert conf["TARGET_FOLDERS"] == "/var/www"


def test_target_from_conf():
    data = {"TARGET_NAME": "test", "TARGET_FOLDERS": "/var/www", "TARGET_ENABLED": "yes"}
    t = Target.from_conf("test", data)
    assert t.name == "test"
    assert t.folders == "/var/www"
    assert t.enabled == "yes"


def test_target_roundtrip():
    t = Target(name="web", folders="/var/www", source_type="ssh", source_host="10.0.0.1")
    conf = t.to_conf()
    t2 = Target.from_conf("web", conf)
    assert t2.name == "web"
    assert t2.folders == "/var/www"
    assert t2.source_type == "ssh"
    assert t2.source_host == "10.0.0.1"


def test_target_defaults():
    t = Target()
    assert t.enabled == "yes"
    assert t.source_type == "local"
    assert t.mysql_enabled == "no"


def test_remote_to_conf():
    r = Remote(name="backup", type="ssh", host="example.com")
    conf = r.to_conf()
    assert conf["REMOTE_TYPE"] == "ssh"
    assert conf["REMOTE_HOST"] == "example.com"


def test_remote_from_conf():
    data = {"REMOTE_TYPE": "ssh", "REMOTE_HOST": "example.com", "REMOTE_PORT": "22"}
    r = Remote.from_conf("backup", data)
    assert r.type == "ssh"
    assert r.host == "example.com"


def test_remote_local_type():
    r = Remote(name="local-bak", type="local", base="/mnt/backup")
    conf = r.to_conf()
    assert conf["REMOTE_TYPE"] == "local"
    assert conf["REMOTE_BASE"] == "/mnt/backup"
    assert "REMOTE_HOST" not in conf


def test_schedule_to_conf():
    s = Schedule(name="nightly", schedule="daily", time="03:00", targets="web,db")
    conf = s.to_conf()
    assert conf["SCHEDULE"] == "daily"
    assert conf["SCHEDULE_TIME"] == "03:00"
    assert conf["TARGETS"] == "web,db"


def test_schedule_from_conf():
    data = {"SCHEDULE": "weekly", "SCHEDULE_TIME": "01:00", "SCHEDULE_DAY": "sunday"}
    s = Schedule.from_conf("weekly-run", data)
    assert s.name == "weekly-run"
    assert s.schedule == "weekly"
    assert s.day == "sunday"


def test_app_settings_defaults():
    s = AppSettings()
    assert s.retention_count == "30"
    assert s.log_retain == "90"
    assert s.log_level == "info"


def test_app_settings_from_conf():
    data = {"RETENTION_COUNT": "7", "LOG_LEVEL": "debug", "WEB_PORT": "8080"}
    s = AppSettings.from_conf(data)
    assert s.retention_count == "7"
    assert s.log_level == "debug"
    assert s.web_port == "8080"


def test_app_settings_roundtrip():
    s = AppSettings(retention_count="14", log_level="warn")
    conf = s.to_conf()
    s2 = AppSettings.from_conf(conf)
    assert s2.retention_count == "14"
    assert s2.log_level == "warn"


# --- metadata-driven serialization tests ---


def test_target_conf_key_metadata():
    """Every Target field (except name) that had a conf mapping should have conf_key."""
    keyed = {f.name for f in fields(Target) if f.metadata.get("conf_key")}
    assert "folders" in keyed
    assert "source_type" in keyed
    assert "mysql_enabled" in keyed


def test_remote_conf_key_metadata():
    """Remote.name has no conf_key; all others do."""
    for f in fields(Remote):
        if f.name == "name":
            assert "conf_key" not in f.metadata
        else:
            assert "conf_key" in f.metadata, f"Remote.{f.name} missing conf_key"


def test_target_full_roundtrip():
    """Create a Target with non-default values, serialize and deserialize, verify equality."""
    t = Target(
        name="mysite",
        folders="/var/www,/etc/nginx",
        exclude="*.log",
        include="*.conf",
        remote="offsite",
        pre_hook="/usr/local/bin/pre.sh",
        post_hook="/usr/local/bin/post.sh",
        enabled="yes",
        source_type="ssh",
        source_host="10.0.0.5",
        source_port="2222",
        source_user="deployer",
        source_auth_method="password",
        source_key="/root/.ssh/id_rsa",
        source_password="secret",
        source_sudo="no",
        mysql_enabled="yes",
        mysql_mode="selected",
        mysql_databases="app_db,logs_db",
        mysql_user="backup_user",
        mysql_password="dbpass",
        mysql_host="db.local",
        mysql_port="3307",
    )
    conf = t.to_conf()
    t2 = Target.from_conf("mysite", conf)
    assert t2.name == t.name
    assert t2.folders == t.folders
    assert t2.exclude == t.exclude
    assert t2.include == t.include
    assert t2.remote == t.remote
    assert t2.source_type == t.source_type
    assert t2.source_host == t.source_host
    assert t2.source_port == t.source_port
    assert t2.source_user == t.source_user
    assert t2.source_auth_method == t.source_auth_method
    assert t2.source_sudo == t.source_sudo
    assert t2.mysql_enabled == t.mysql_enabled
    assert t2.mysql_databases == t.mysql_databases
    assert t2.mysql_host == t.mysql_host


def test_remote_full_roundtrip():
    """Create a Remote with non-default values, serialize and deserialize, verify equality."""
    r = Remote(
        name="offsite",
        type="ssh",
        host="backup.example.com",
        port="2222",
        user="backup",
        auth_method="key",
        key="/root/.ssh/backup_key",
        sudo="no",
        base="/mnt/backups",
        bwlimit="5000",
    )
    conf = r.to_conf()
    r2 = Remote.from_conf("offsite", conf)
    assert r2.name == r.name
    assert r2.type == r.type
    assert r2.host == r.host
    assert r2.port == r.port
    assert r2.user == r.user
    assert r2.auth_method == r.auth_method
    assert r2.key == r.key
    assert r2.sudo == r.sudo
    assert r2.base == r.base
    assert r2.bwlimit == r.bwlimit


def test_schedule_full_roundtrip():
    """Create a Schedule, serialize and deserialize, verify equality."""
    s = Schedule(
        name="weekly-full",
        schedule="weekly",
        time="01:00",
        day="sunday",
        targets="web,db",
        remotes="offsite",
        active="yes",
        retention_count="4",
    )
    conf = s.to_conf()
    s2 = Schedule.from_conf("weekly-full", conf)
    assert s2.name == s.name
    assert s2.schedule == s.schedule
    assert s2.time == s.time
    assert s2.day == s.day
    assert s2.targets == s.targets
    assert s2.remotes == s.remotes
    assert s2.active == s.active
    assert s2.retention_count == s.retention_count


def test_app_settings_full_roundtrip():
    """Create AppSettings with non-default values, serialize and deserialize, verify equality."""
    s = AppSettings(
        backup_mode="full",
        retention_count="7",
        log_level="debug",
        notify_email="admin@example.com",
        smtp_host="smtp.example.com",
        smtp_port="465",
        smtp_user="mailer",
        smtp_password="mailpass",
        smtp_from="backup@example.com",
        smtp_security="ssl",
        web_port="8080",
        web_host="127.0.0.1",
        stale_alert_hours="24",
        digest_enabled="yes",
        digest_frequency="weekly",
    )
    conf = s.to_conf()
    s2 = AppSettings.from_conf(conf)
    assert s2.backup_mode == s.backup_mode
    assert s2.retention_count == s.retention_count
    assert s2.log_level == s.log_level
    assert s2.notify_email == s.notify_email
    assert s2.smtp_host == s.smtp_host
    assert s2.smtp_port == s.smtp_port
    assert s2.web_port == s.web_port
    assert s2.stale_alert_hours == s.stale_alert_hours
    assert s2.digest_enabled == s.digest_enabled
    assert s2.digest_frequency == s.digest_frequency


def test_to_conf_skips_empty_values():
    """to_conf should not include keys for fields with empty string values."""
    t = Target(name="minimal", folders="/data")
    conf = t.to_conf()
    assert "TARGET_NAME" in conf
    assert "TARGET_FOLDERS" in conf
    # Fields with empty defaults should be omitted
    assert "TARGET_EXCLUDE" not in conf
    assert "TARGET_INCLUDE" not in conf
    assert "TARGET_PRE_HOOK" not in conf
    assert "TARGET_SOURCE_HOST" not in conf


def test_to_conf_includes_no_values():
    """to_conf should include 'no' values (they are meaningful for checkboxes)."""
    t = Target(name="test", folders="/data", mysql_enabled="no")
    conf = t.to_conf()
    assert conf["TARGET_MYSQL_ENABLED"] == "no"


def test_from_conf_uses_defaults_for_missing_keys():
    """from_conf should fall back to field defaults when keys are absent from data."""
    data = {"TARGET_NAME": "sparse", "TARGET_FOLDERS": "/opt"}
    t = Target.from_conf("sparse", data)
    assert t.enabled == "yes"
    assert t.source_type == "local"
    assert t.mysql_enabled == "no"
    assert t.source_port == "22"
    assert t.mysql_host == "localhost"


def test_target_name_from_conf_prefers_data():
    """Target.from_conf should prefer TARGET_NAME from data over the name parameter."""
    data = {"TARGET_NAME": "from-data", "TARGET_FOLDERS": "/x"}
    t = Target.from_conf("from-param", data)
    assert t.name == "from-data"


def test_remote_s3_roundtrip():
    """S3-type Remote round-trip."""
    r = Remote(
        name="s3-bak",
        type="s3",
        s3_provider="Minio",
        s3_bucket="backups",
        s3_region="us-west-2",
        s3_endpoint="https://minio.local:9000",
        s3_access_key_id="AKID",
        s3_secret_access_key="SKEY",
        base="/prefix",
    )
    conf = r.to_conf()
    r2 = Remote.from_conf("s3-bak", conf)
    assert r2.type == "s3"
    assert r2.s3_provider == "Minio"
    assert r2.s3_bucket == "backups"
    assert r2.s3_region == "us-west-2"
    assert r2.s3_endpoint == "https://minio.local:9000"
    assert r2.s3_access_key_id == "AKID"
    assert r2.s3_secret_access_key == "SKEY"
    assert r2.base == "/prefix"
