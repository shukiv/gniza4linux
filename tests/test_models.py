"""Tests for lib.models — data model serialization."""
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
