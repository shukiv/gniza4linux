"""HTML email template for GNIZA backup notifications."""

import html as _html


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
        <span style="font-size:28px;font-weight:bold;color:#ffffff;letter-spacing:3px;line-height:1">GNIZA</span><br>
        <span style="font-size:11px;color:#8888aa;line-height:1">Linux Backup Manager</span>
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


def build_digest_email(
    frequency="daily",
    hostname="",
    period_start="",
    period_end="",
    total=0,
    succeeded=0,
    failed=0,
    skipped=0,
    failed_sources=None,
    job_details=None,
):
    """Build an HTML digest email summarizing backup jobs for a period.

    Returns a complete HTML string with inline styles (email-client safe).
    """
    if failed_sources is None:
        failed_sources = []
    if job_details is None:
        job_details = []

    freq_label = _html.escape(frequency.capitalize())
    esc_hostname = _html.escape(hostname)
    esc_period_start = _html.escape(period_start)
    esc_period_end = _html.escape(period_end)

    # Summary stat colors
    s_color = "#27ae60" if succeeded else "#888"
    f_color = "#e74c3c" if failed else "#888"
    sk_color = "#f39c12" if skipped else "#888"

    # Stats boxes
    stats_html = f'''
        <tr><td colspan="2" style="padding:16px 0 8px 0">
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
            <tr>
              <td align="center" style="padding:12px;background:#f8f9fa;border-radius:8px">
                <span style="font-size:14px;color:#555">Total</span><br>
                <span style="font-size:28px;font-weight:bold;color:#333">{int(total)}</span>
              </td>
              <td width="8"></td>
              <td align="center" style="padding:12px;background:#f0faf0;border-radius:8px">
                <span style="font-size:14px;color:#555">OK</span><br>
                <span style="font-size:28px;font-weight:bold;color:{s_color}">{int(succeeded)}</span>
              </td>
              <td width="8"></td>
              <td align="center" style="padding:12px;background:{"#fdf0f0" if failed else "#f8f9fa"};border-radius:8px">
                <span style="font-size:14px;color:#555">Failed</span><br>
                <span style="font-size:28px;font-weight:bold;color:{f_color}">{int(failed)}</span>
              </td>
              <td width="8"></td>
              <td align="center" style="padding:12px;background:{"#fef9e7" if skipped else "#f8f9fa"};border-radius:8px">
                <span style="font-size:14px;color:#555">Skipped</span><br>
                <span style="font-size:28px;font-weight:bold;color:{sk_color}">{int(skipped)}</span>
              </td>
            </tr>
          </table>
        </td></tr>'''

    # Period and hostname info
    info_rows = ""
    if period_start and period_end:
        info_rows += _row("Period", f"{esc_period_start} &mdash; {esc_period_end}")
    if hostname:
        info_rows += _row("Hostname", esc_hostname)

    # Failed sources section
    failed_html = ""
    if failed_sources:
        items = ""
        for src in failed_sources:
            name = _html.escape(str(src.get("name", "unknown")))
            count = int(src.get("count", 1))
            suffix = "failure" if count == 1 else "failures"
            items += f'<div style="padding:2px 0;color:#666;font-size:13px">&bull; {name} ({count} {suffix})</div>'
        failed_html = f'''
        <tr><td colspan="2" style="padding:12px 0">
          <div style="background:#fdf0f0;border-left:4px solid #e74c3c;padding:12px 16px;border-radius:0 6px 6px 0">
            <strong style="color:#c0392b">Failed Sources</strong>
            {items}
          </div>
        </td></tr>'''

    # Job details table (optional)
    details_html = ""
    if job_details:
        rows = ""
        for job in job_details:
            label = _html.escape(str(job.get("label", "unknown")))
            status = str(job.get("status", "unknown"))
            started = _html.escape(str(job.get("started_at", "")))
            finished = _html.escape(str(job.get("finished_at", "")))
            if status == "success":
                st_color = "#27ae60"
                st_text = "OK"
            elif status == "failed":
                st_color = "#e74c3c"
                st_text = "FAIL"
            elif status == "skipped":
                st_color = "#f39c12"
                st_text = "SKIP"
            else:
                st_color = "#888"
                st_text = _html.escape(status.upper())
            rows += f'''<tr>
              <td style="padding:4px 8px;border-bottom:1px solid #eee;font-size:13px;color:#333">{label}</td>
              <td style="padding:4px 8px;border-bottom:1px solid #eee;font-size:13px;color:{st_color};font-weight:bold">{st_text}</td>
              <td style="padding:4px 8px;border-bottom:1px solid #eee;font-size:12px;color:#888">{started}</td>
              <td style="padding:4px 8px;border-bottom:1px solid #eee;font-size:12px;color:#888">{finished}</td>
            </tr>'''
        details_html = f'''
        <tr><td colspan="2" style="padding:12px 0">
          <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
            <tr style="background:#f8f9fa">
              <td style="padding:6px 8px;font-size:12px;font-weight:bold;color:#555">Source</td>
              <td style="padding:6px 8px;font-size:12px;font-weight:bold;color:#555">Status</td>
              <td style="padding:6px 8px;font-size:12px;font-weight:bold;color:#555">Started</td>
              <td style="padding:6px 8px;font-size:12px;font-weight:bold;color:#555">Finished</td>
            </tr>
            {rows}
          </table>
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
        <span style="font-size:28px;font-weight:bold;color:#ffffff;letter-spacing:3px;line-height:1">GNIZA</span><br>
        <span style="font-size:11px;color:#8888aa;line-height:1">Linux Backup Manager</span>
      </td>
    </tr></table>
  </td></tr>

  <!-- Digest Title -->
  <tr><td style="padding:28px 32px 0 32px;text-align:center">
    <div style="font-size:22px;font-weight:bold;color:#333">&#x1F4CA; {freq_label} Digest</div>
    <div style="font-size:14px;color:#888;margin-top:4px">{esc_period_end}</div>
  </td></tr>

  <!-- Stats + Info -->
  <tr><td style="padding:24px 32px">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
      {stats_html}
      {info_rows}
      {failed_html}
      {details_html}
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
