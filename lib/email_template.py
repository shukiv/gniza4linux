"""HTML email template for GNIZA backup notifications."""
import base64
from pathlib import Path

_LOGO_B64 = None


def _get_logo_b64():
    """Load and cache the logo PNG as base64."""
    global _LOGO_B64
    if _LOGO_B64 is None:
        # Look in data/ directory (shipped with the package)
        root = Path(__file__).resolve().parent.parent
        for candidate in [
            root / "data" / "gniza-logo.png",
            root / "gniza-logo.png",
        ]:
            if candidate.is_file():
                _LOGO_B64 = base64.b64encode(candidate.read_bytes()).decode()
                break
        else:
            _LOGO_B64 = ""
    return _LOGO_B64


def build_html_email(
    status_word="SUCCESS",
    hostname="",
    timestamp="",
    duration="",
    sources="",
    destinations="",
    total="",
    succeeded="",
    failed="",
    failed_targets="",
    log_file="",
    job_label="",
):
    """Build a professional HTML email for backup notifications.

    Returns a complete HTML string with inline styles (email-client safe).
    """
    # Status colors
    if "FAILURE" in status_word.upper():
        if "PARTIAL" in status_word.upper():
            badge_bg = "#f39c12"
            badge_icon = "⚠"
        else:
            badge_bg = "#e74c3c"
            badge_icon = "✗"
    elif "SKIPPED" in status_word.upper():
        badge_bg = "#95a5a6"
        badge_icon = "⏭"
    else:
        badge_bg = "#27ae60"
        badge_icon = "✓"

    # Build info rows
    info_rows = ""
    if hostname:
        info_rows += _row("Hostname", hostname)
    if timestamp:
        info_rows += _row("Timestamp", timestamp)
    if duration:
        info_rows += _row("Duration", duration)
    if sources:
        info_rows += _row("Sources", sources)
    if destinations:
        info_rows += _row("Destinations", destinations)
    if job_label and not sources:
        info_rows += _row("Job", job_label)

    # Build summary section
    summary_html = ""
    if total:
        s_color = "#27ae60" if succeeded else "#888"
        f_color = "#e74c3c" if failed and str(failed) != "0" else "#888"
        summary_html = f'''
        <tr><td colspan="2" style="padding:16px 0 8px 0">
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
            <tr>
              <td align="center" style="padding:12px;background:#f8f9fa;border-radius:8px">
                <span style="font-size:14px;color:#555">Total</span><br>
                <span style="font-size:28px;font-weight:bold;color:#333">{total}</span>
              </td>
              <td width="12"></td>
              <td align="center" style="padding:12px;background:#f0faf0;border-radius:8px">
                <span style="font-size:14px;color:#555">Succeeded</span><br>
                <span style="font-size:28px;font-weight:bold;color:{s_color}">{succeeded}</span>
              </td>
              <td width="12"></td>
              <td align="center" style="padding:12px;background:{"#fdf0f0" if failed and str(failed) != "0" else "#f8f9fa"};border-radius:8px">
                <span style="font-size:14px;color:#555">Failed</span><br>
                <span style="font-size:28px;font-weight:bold;color:{f_color}">{failed}</span>
              </td>
            </tr>
          </table>
        </td></tr>'''

    # Failed targets section
    failed_html = ""
    if failed_targets:
        lines = failed_targets.strip().replace("\n", "<br>")
        failed_html = f'''
        <tr><td colspan="2" style="padding:12px 0">
          <div style="background:#fdf0f0;border-left:4px solid #e74c3c;padding:12px 16px;border-radius:0 6px 6px 0">
            <strong style="color:#c0392b">Failed Sources</strong><br>
            <span style="color:#666;font-size:13px">{lines}</span>
          </div>
        </td></tr>'''

    # Log file
    log_html = ""
    if log_file:
        log_html = f'''
        <tr><td colspan="2" style="padding:8px 0">
          <span style="color:#888;font-size:12px">Log: {log_file}</span>
        </td></tr>'''

    return f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:20px 0">
<tr><td align="center">
<table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08)">

  <!-- Header -->
  <tr><td style="background:#1a1a2e;padding:28px 0;text-align:center">
    <table cellpadding="0" cellspacing="0" style="margin:0 auto"><tr>
      <td style="vertical-align:middle;padding-right:12px">
        <img src="https://git.linux-hosting.co.il/shukivaknin/gniza4linux/raw/branch/main/data/gniza-logo.png" width="48" height="48" alt="" style="display:block">
      </td>
      <td style="vertical-align:middle;text-align:left">
        <span style="font-size:28px;font-weight:bold;color:#ffffff;letter-spacing:3px">GNIZA</span><br>
        <span style="font-size:11px;color:#8888aa">Linux Backup Manager</span>
      </td>
    </tr></table>
  </td></tr>

  <!-- Status Badge -->
  <tr><td style="padding:28px 32px 0 32px;text-align:center">
    <div style="display:inline-block;background:{badge_bg};color:#fff;padding:10px 28px;border-radius:24px;font-size:16px;font-weight:bold;letter-spacing:1px">
      {badge_icon} &nbsp; {status_word.upper()}
    </div>
  </td></tr>

  <!-- Info Table -->
  <tr><td style="padding:24px 32px">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
      {info_rows}
      {summary_html}
      {failed_html}
      {log_html}
    </table>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f8f9fa;padding:16px 32px;text-align:center;border-top:1px solid #eee">
    <span style="font-size:12px;color:#999">GNIZA Backup Manager</span>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''


def _row(label, value):
    """Build a single key-value row for the info table."""
    return f'''<tr>
      <td style="padding:6px 12px 6px 0;color:#888;font-size:14px;white-space:nowrap;vertical-align:top">{label}</td>
      <td style="padding:6px 0;color:#333;font-size:14px">{value}</td>
    </tr>'''
