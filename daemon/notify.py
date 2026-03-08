"""Email notifications for the gniza daemon."""

import logging
import re
import smtplib
import socket
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from tui.config import CONFIG_DIR, LOG_DIR, parse_conf

logger = logging.getLogger("gniza-daemon")


def _load_email_settings():
    """Read SMTP/notification settings from gniza.conf."""
    conf = parse_conf(CONFIG_DIR / "gniza.conf")
    return {
        "notify_email": conf.get("NOTIFY_EMAIL", ""),
        "notify_on": conf.get("NOTIFY_ON", "failure"),
        "smtp_host": conf.get("SMTP_HOST", ""),
        "smtp_port": conf.get("SMTP_PORT", "587"),
        "smtp_user": conf.get("SMTP_USER", ""),
        "smtp_password": conf.get("SMTP_PASSWORD", ""),
        "smtp_from": conf.get("SMTP_FROM", "") or conf.get("SMTP_USER", ""),
        "smtp_security": conf.get("SMTP_SECURITY", "tls"),
    }


def _log_email(status, recipients, subject):
    """Append entry to email.log."""
    email_log = Path(LOG_DIR) / "email.log"
    try:
        email_log.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(email_log, "a") as f:
            f.write(f"{timestamp} | {status} | {recipients} | {subject}\n")
    except OSError:
        pass


def _send_smtp(settings, subject, body):
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


def _parse_backup_summary(log_file):
    """Extract backup summary from a job's log file."""
    try:
        text = Path(log_file).read_text(errors="replace")
    except OSError:
        return None

    # Look for the summary block
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

    # Extract failed sources
    failed_section = re.search(r"Failed sources:\n((?:.+\n)*)", text)
    if failed_section:
        summary["failed_targets"] = failed_section.group(1).strip()

    # Single target backup (no summary block)
    if not summary and "Backup completed for" in text:
        m = re.search(r"Backup completed for (\S+)", text)
        name = m.group(1) if m else "unknown"
        summary = {"total": 1, "succeeded": 1, "failed": 0, "single_target": name}

    return summary if summary else None


def send_job_notification(entry):
    """Send email notification for a completed job. Called from check_jobs()."""
    settings = _load_email_settings()

    if not settings["notify_email"] or not settings["smtp_host"]:
        return

    status = entry.get("status", "unknown")
    kind = entry.get("kind", "backup")

    # Only handle backup/restore jobs
    if kind not in ("backup", "restore", "scheduled-run"):
        return

    is_success = status in ("success", "skipped")

    notify_on = settings["notify_on"]
    if notify_on == "never":
        return
    if notify_on == "failure" and is_success:
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

    if _send_smtp(settings, subject, body):
        _log_email("OK", settings["notify_email"], subject)
        logger.info(f"Notification sent for job {entry.get('id')}")
    else:
        _log_email("FAIL", settings["notify_email"], subject)
        logger.warning(f"Failed to send notification for job {entry.get('id')}")


def send_test_email():
    """Send a test email. Returns (success: bool, message: str)."""
    settings = _load_email_settings()

    if not settings["notify_email"]:
        return False, "NOTIFY_EMAIL is not set. Configure it in Settings first."
    if not settings["smtp_host"]:
        return False, "SMTP_HOST is not set. Configure SMTP settings first."

    hostname = socket.getfqdn()
    subject = f"[gniza] [{hostname}] Test Email"
    body = (
        f"This is a test email from gniza on {hostname}.\n"
        f"Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"\n"
        f"If you received this message, your SMTP settings are working correctly."
    )

    if _send_smtp(settings, subject, body):
        _log_email("OK", settings["notify_email"], subject)
        return True, f"Test email sent successfully to {settings['notify_email']}"
    else:
        _log_email("FAIL", settings["notify_email"], subject)
        return False, "Failed to send test email. Check your SMTP settings."
