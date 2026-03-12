"""Multi-channel notifications for the gniza daemon."""

import json
import logging
import re
import smtplib
import socket
import ssl
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from tui.config import CONFIG_DIR, LOG_DIR, parse_conf

logger = logging.getLogger("gniza-daemon")


def _load_notification_settings():
    """Read all notification channel settings from gniza.conf."""
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    return {
        "notify_on": conf.get("NOTIFY_ON", "failure"),
        # Email
        "notify_email": conf.get("NOTIFY_EMAIL", ""),
        "smtp_host": conf.get("SMTP_HOST", ""),
        "smtp_port": conf.get("SMTP_PORT", "587"),
        "smtp_user": conf.get("SMTP_USER", ""),
        "smtp_password": conf.get("SMTP_PASSWORD", ""),
        "smtp_from": conf.get("SMTP_FROM", "") or conf.get("SMTP_USER", ""),
        "smtp_security": conf.get("SMTP_SECURITY", "tls"),
        # Telegram
        "telegram_bot_token": conf.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": conf.get("TELEGRAM_CHAT_ID", ""),
        # Webhook (Slack/Discord/generic)
        "webhook_url": conf.get("WEBHOOK_URL", ""),
        "webhook_type": conf.get("WEBHOOK_TYPE", "slack"),
        # ntfy/Gotify
        "ntfy_url": conf.get("NTFY_URL", ""),
        "ntfy_token": conf.get("NTFY_TOKEN", ""),
        "ntfy_priority": conf.get("NTFY_PRIORITY", "default"),
        # Healthchecks.io
        "healthchecks_url": conf.get("HEALTHCHECKS_URL", ""),
        # Stale alerts
        "stale_alert_hours": conf.get("STALE_ALERT_HOURS", "0"),
    }


def _log_notification(channel, status, dest, subject):
    """Append entry to notification.log (5-column format)."""
    log_file = Path(LOG_DIR) / "notification.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a") as f:
            f.write(f"{timestamp} | {channel} | {status} | {dest} | {subject}\n")
    except OSError:
        pass


def _validate_url(url):
    """Validate URL uses http/https scheme only (prevent file:// SSRF)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got: {parsed.scheme!r}")
    return url


def _http_post(url, data=None, headers=None, timeout=30):
    """Shared HTTP POST helper. Returns (success, response_body)."""
    if headers is None:
        headers = {}
    try:
        _validate_url(url)
        if isinstance(data, dict):
            data = json.dumps(data).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return True, resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        logger.error(f"HTTP POST to {url} failed: {e}")
        return False, str(e)


def _http_get(url, headers=None, timeout=30):
    """Shared HTTP GET helper. Returns (success, response_body)."""
    if headers is None:
        headers = {}
    try:
        _validate_url(url)
        req = urllib.request.Request(url, headers=headers, method="GET")
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return True, resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        logger.error(f"HTTP GET to {url} failed: {e}")
        return False, str(e)


def _send_email(settings, subject, body):
    """Send email via SMTP. Returns True on success."""
    host = settings["smtp_host"]
    port = int(settings["smtp_port"])
    security = settings["smtp_security"]
    sender = settings["smtp_from"]
    recipients = [r.strip() for r in settings["notify_email"].split(",") if r.strip()]

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject

    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)

        with server:
            if security == "tls":
                server.starttls()
            if settings["smtp_user"]:
                server.login(settings["smtp_user"], settings["smtp_password"])
            server.sendmail(sender, recipients, msg.as_string())

        return True
    except Exception as e:
        logger.error(f"SMTP delivery failed: {e}")
        return False


def _send_telegram(settings, subject, body):
    """Send via Telegram Bot API. Returns True on success."""
    token = settings["telegram_bot_token"]
    chat_id = settings["telegram_chat_id"]
    # Truncate to Telegram's 4096 char limit
    text = f"*{subject}*\n\n{body}"
    if len(text) > 4096:
        text = text[:4093] + "..."
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    ok, _ = _http_post(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    return ok


def _send_webhook(settings, subject, body):
    """Send via webhook (Slack/Discord/generic). Returns True on success."""
    url = settings["webhook_url"]
    wtype = settings["webhook_type"]
    text = f"{subject}\n\n{body}"

    if wtype == "discord":
        # Discord uses "content" key
        data = {"content": text}
    elif wtype == "slack":
        data = {"text": text}
    else:
        # Generic webhook
        data = {"text": text, "subject": subject, "body": body}

    ok, _ = _http_post(url, data=data)
    return ok


def _send_ntfy(settings, subject, body):
    """Send via ntfy. Returns True on success."""
    url = settings["ntfy_url"]
    headers = {"Title": subject}
    priority = settings.get("ntfy_priority", "default")
    if priority:
        headers["Priority"] = priority
    token = settings.get("ntfy_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    ok, _ = _http_post(url, data=body, headers=headers)
    return ok


def _send_healthcheck(settings, is_success):
    """Ping healthchecks.io. Returns True on success."""
    url = settings["healthchecks_url"].rstrip("/")
    if not is_success:
        url += "/fail"
    ok, _ = _http_get(url)
    return ok


def _dispatch_notification(settings, subject, body, is_success=True):
    """Send to ALL configured channels. Returns dict of {channel: success}."""
    results = {}

    # Email
    if settings["notify_email"] and settings["smtp_host"]:
        ok = _send_email(settings, subject, body)
        results["email"] = ok
        _log_notification("email", "OK" if ok else "FAIL", settings["notify_email"], subject)

    # Telegram
    if settings["telegram_bot_token"] and settings["telegram_chat_id"]:
        ok = _send_telegram(settings, subject, body)
        results["telegram"] = ok
        _log_notification("telegram", "OK" if ok else "FAIL", settings["telegram_chat_id"], subject)

    # Webhook
    if settings["webhook_url"]:
        ok = _send_webhook(settings, subject, body)
        results["webhook"] = ok
        _log_notification("webhook", "OK" if ok else "FAIL", settings["webhook_url"], subject)

    # ntfy
    if settings["ntfy_url"]:
        # Auto-set high priority on failure
        ntfy_settings = dict(settings)
        if not is_success:
            ntfy_settings["ntfy_priority"] = "high"
        ok = _send_ntfy(ntfy_settings, subject, body)
        results["ntfy"] = ok
        _log_notification("ntfy", "OK" if ok else "FAIL", settings["ntfy_url"], subject)

    # Healthchecks.io
    if settings["healthchecks_url"]:
        ok = _send_healthcheck(settings, is_success)
        results["healthcheck"] = ok
        _log_notification("healthcheck", "OK" if ok else "FAIL", settings["healthchecks_url"], subject)

    return results


# Keep the existing _parse_backup_summary unchanged
def _parse_backup_summary(log_file):
    """Extract backup summary from a job's log file."""
    try:
        text = Path(log_file).read_text(errors="replace")
    except OSError:
        return None

    summary = {}

    m = re.search(r"Total:\s+(\d+)", text)
    if m:
        summary["total"] = int(m.group(1))

    m = re.search(r"Succeeded:\s+\S*(\d+)", text)
    if m:
        summary["succeeded"] = int(m.group(1))

    m = re.search(r"Failed:\s+\S*(\d+)", text)
    if m:
        summary["failed"] = int(m.group(1))

    m = re.search(r"Duration:\s+(.+)", text)
    if m:
        summary["duration"] = m.group(1).strip()

    failed_section = re.search(r"Failed sources:\n((?:.+\n)*)", text)
    if failed_section:
        summary["failed_targets"] = failed_section.group(1).strip()

    if not summary and "Backup completed for" in text:
        m = re.search(r"Backup completed for (\S+)", text)
        name = m.group(1) if m else "unknown"
        summary = {"total": 1, "succeeded": 1, "failed": 0, "single_target": name}

    return summary if summary else None


def send_job_notification(entry):
    """Send notification for a completed job. Called from check_jobs()."""
    settings = _load_notification_settings()

    status = entry.get("status", "unknown")
    kind = entry.get("kind", "backup")

    if kind not in ("backup", "restore", "scheduled-run"):
        return

    is_success = status in ("success", "skipped")

    notify_on = settings["notify_on"]
    if notify_on == "never":
        return
    if notify_on == "failure" and is_success:
        return

    # Check if any channel is configured
    has_channel = (
        (settings["notify_email"] and settings["smtp_host"])
        or (settings["telegram_bot_token"] and settings["telegram_chat_id"])
        or settings["webhook_url"]
        or settings["ntfy_url"]
        or settings["healthchecks_url"]
    )
    if not has_channel:
        return

    hostname = socket.getfqdn()
    log_file = entry.get("log_file", "")
    summary = _parse_backup_summary(log_file) if log_file else None

    # Build subject
    if summary:
        total = summary.get("total", "?")
        succeeded = summary.get("succeeded", "?")
        failed = summary.get("failed", 0)
        if failed and failed > 0:
            if succeeded and succeeded > 0:
                status_word = "PARTIAL FAILURE"
            else:
                status_word = "FAILURE"
        else:
            status_word = "SUCCESS"
        subject = f"[gniza] [{hostname}] Backup {status_word} ({succeeded}/{total})"
    else:
        status_word = status.upper()
        subject = f"[gniza] [{hostname}] {kind.replace('-', ' ').title()} {status_word}"

    # Build body
    lines = [f"Backup Report: {status_word}", "=" * 30]
    lines.append(f"Hostname: {hostname}")
    lines.append(f"Timestamp: {datetime.utcnow().strftime('%d/%m/%Y %H:%M:%S UTC')}")
    if summary and summary.get("duration"):
        lines.append(f"Duration: {summary['duration']}")
    lines.append("")
    if summary:
        lines.append(f"Targets: {summary.get('total', '?')} total, "
                      f"{summary.get('succeeded', '?')} succeeded, "
                      f"{summary.get('failed', 0)} failed")
        if summary.get("failed_targets"):
            lines.append("")
            lines.append("Failed sources:")
            lines.append(summary["failed_targets"])
    else:
        lines.append(f"Job: {entry.get('label', 'unknown')}")
        lines.append(f"Status: {status}")
    if log_file:
        lines.append("")
        lines.append(f"Log file: {log_file}")

    body = "\n".join(lines)

    results = _dispatch_notification(settings, subject, body, is_success)
    job_id = entry.get("id")
    for channel, ok in results.items():
        if ok:
            logger.info(f"Notification sent via {channel} for job {job_id}")
        else:
            logger.warning(f"Failed to send {channel} notification for job {job_id}")


def send_test_notification(channel=None):
    """Send a test notification. Returns (success: bool, message: str).

    If channel is None, sends to all configured channels.
    If channel is specified, sends only to that channel.
    """
    settings = _load_notification_settings()
    hostname = socket.getfqdn()
    subject = f"[gniza] [{hostname}] Test Notification"
    body = (
        f"This is a test notification from gniza on {hostname}.\n"
        f"Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\n"
        f"If you received this message, your notification settings are working correctly."
    )

    if channel:
        # Test specific channel
        if channel == "email":
            if not settings["notify_email"] or not settings["smtp_host"]:
                return False, "Email not configured. Set NOTIFY_EMAIL and SMTP_HOST first."
            ok = _send_email(settings, subject, body)
            _log_notification("email", "OK" if ok else "FAIL", settings["notify_email"], subject)
            return (True, f"Test email sent to {settings['notify_email']}") if ok else (False, "Failed to send test email. Check SMTP settings.")

        elif channel == "telegram":
            if not settings["telegram_bot_token"] or not settings["telegram_chat_id"]:
                return False, "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first."
            ok = _send_telegram(settings, subject, body)
            _log_notification("telegram", "OK" if ok else "FAIL", settings["telegram_chat_id"], subject)
            return (True, "Test Telegram message sent.") if ok else (False, "Failed to send Telegram message. Check bot token and chat ID.")

        elif channel == "webhook":
            if not settings["webhook_url"]:
                return False, "Webhook not configured. Set WEBHOOK_URL first."
            ok = _send_webhook(settings, subject, body)
            _log_notification("webhook", "OK" if ok else "FAIL", settings["webhook_url"], subject)
            return (True, "Test webhook sent.") if ok else (False, "Failed to send webhook. Check URL.")

        elif channel == "ntfy":
            if not settings["ntfy_url"]:
                return False, "ntfy not configured. Set NTFY_URL first."
            ok = _send_ntfy(settings, subject, body)
            _log_notification("ntfy", "OK" if ok else "FAIL", settings["ntfy_url"], subject)
            return (True, "Test ntfy notification sent.") if ok else (False, "Failed to send ntfy notification. Check URL.")

        elif channel == "healthcheck":
            if not settings["healthchecks_url"]:
                return False, "Healthchecks.io not configured. Set HEALTHCHECKS_URL first."
            ok = _send_healthcheck(settings, True)
            _log_notification("healthcheck", "OK" if ok else "FAIL", settings["healthchecks_url"], subject)
            return (True, "Test healthcheck ping sent.") if ok else (False, "Failed to ping healthchecks.io. Check URL.")

        else:
            return False, f"Unknown channel: {channel}"

    # Test all configured channels
    results = _dispatch_notification(settings, subject, body, is_success=True)
    if not results:
        return False, "No notification channels configured."

    ok_channels = [ch for ch, ok in results.items() if ok]
    fail_channels = [ch for ch, ok in results.items() if not ok]

    if fail_channels and not ok_channels:
        return False, f"All channels failed: {', '.join(fail_channels)}"
    elif fail_channels:
        return True, f"Sent via {', '.join(ok_channels)}. Failed: {', '.join(fail_channels)}"
    else:
        return True, f"Test notification sent via {', '.join(ok_channels)}"


def send_stale_alert(stale_sources):
    """Send alert about stale backup sources."""
    settings = _load_notification_settings()
    hostname = socket.getfqdn()

    subject = f"[gniza] [{hostname}] Stale Backup Alert"
    lines = [
        f"Stale Backup Alert",
        "=" * 30,
        f"Hostname: {hostname}",
        f"Timestamp: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        "",
        f"The following {len(stale_sources)} source(s) have not had a successful backup recently:",
        "",
    ]
    for src in stale_sources:
        name = src.get("name", "unknown")
        last = src.get("last_success", "never")
        hours = src.get("hours_ago", "?")
        lines.append(f"  - {name}: last success {last} ({hours}h ago)")

    body = "\n".join(lines)
    _dispatch_notification(settings, subject, body, is_success=False)


# Backward compatibility alias
def send_test_email():
    """Send a test email. Returns (success: bool, message: str)."""
    return send_test_notification("email")
