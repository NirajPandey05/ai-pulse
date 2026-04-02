import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "research": "Research Breakthroughs",
    "models_releases": "LLM Models & Releases",
    "tools_products": "AI Tools & Products",
    "coding_dev": "Coding & Dev",
}

CATEGORY_ICONS = {
    "research": "🔬",
    "models_releases": "🧠",
    "tools_products": "⚡",
    "coding_dev": "💻",
}


def _score_color(score: float, is_breakthrough: bool) -> tuple[str, str]:
    """Returns (background, label)."""
    if is_breakthrough:
        return "#EF4444", f"🔥 {score:.1f}"
    if score >= 9:
        return "#10B981", f"{score:.1f}"
    if score >= 7:
        return "#3B82F6", f"{score:.1f}"
    return "#F59E0B", f"{score:.1f}"


def _render_item_html(item: dict) -> str:
    score = item.get("relevance_score", 0)
    is_bt = item.get("is_breakthrough", False)
    bg, label = _score_color(score, is_bt)
    action_items_html = "".join(
        f'<li style="margin:6px 0;color:#374151;">{a}</li>'
        for a in item.get("action_items", [])
    )
    source_tag = item.get("source", "").replace("_", " ").title()
    cat = item.get("category", "")
    cat_icon = CATEGORY_ICONS.get(cat, "")

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:10px;margin-bottom:20px;background:#ffffff;border-collapse:separate;">
  <tr>
    <td style="padding:20px;">
      <!-- Header row: badge + title -->
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;width:1%;white-space:nowrap;padding-right:12px;">
            <span style="background:{bg};color:#fff;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;letter-spacing:0.3px;">{label}</span>
          </td>
          <td style="vertical-align:middle;">
            <a href="{item['url']}" style="font-size:17px;font-weight:700;color:#111827;text-decoration:none;line-height:1.4;">{item['title']}</a>
          </td>
        </tr>
      </table>
      <!-- Source + category -->
      <p style="margin:8px 0 12px 0;color:#9ca3af;font-size:12px;">
        {cat_icon} {source_tag}
      </p>
      <!-- TL;DR -->
      <div style="background:#f8fafc;border-left:3px solid {bg};padding:10px 14px;border-radius:0 6px 6px 0;margin-bottom:14px;">
        <p style="margin:0;font-style:italic;color:#374151;font-size:14px;line-height:1.6;">{item.get('tldr','')}</p>
      </div>
      <!-- Details -->
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:4px 0;vertical-align:top;width:130px;">
            <span style="font-size:13px;font-weight:600;color:#6b7280;">What it is</span>
          </td>
          <td style="padding:4px 0;">
            <span style="font-size:13px;color:#374151;">{item.get('what_it_is','')}</span>
          </td>
        </tr>
        <tr><td colspan="2" style="height:8px;"></td></tr>
        <tr>
          <td style="padding:4px 0;vertical-align:top;width:130px;">
            <span style="font-size:13px;font-weight:600;color:#6b7280;">Why it matters</span>
          </td>
          <td style="padding:4px 0;">
            <span style="font-size:13px;color:#374151;">{item.get('why_it_matters','')}</span>
          </td>
        </tr>
        <tr><td colspan="2" style="height:8px;"></td></tr>
        <tr>
          <td style="padding:4px 0;vertical-align:top;width:130px;">
            <span style="font-size:13px;font-weight:600;color:#6b7280;">Your journey</span>
          </td>
          <td style="padding:4px 0;">
            <span style="font-size:13px;color:#374151;">{item.get('impact_on_journey','')}</span>
          </td>
        </tr>
      </table>
      <!-- Action items -->
      {f'<p style="margin:14px 0 6px 0;font-size:13px;font-weight:600;color:#6b7280;">Action items</p><ul style="margin:0;padding-left:18px;">{action_items_html}</ul>' if action_items_html else ''}
      <!-- Read more -->
      <p style="margin:14px 0 0 0;">
        <a href="{item['url']}" style="display:inline-block;background:#111827;color:#fff;padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;">Read more →</a>
      </p>
    </td>
  </tr>
</table>"""


def build_html_email(briefing: dict) -> str:
    date = briefing["date"]
    exec_summary = briefing["executive_summary"]
    items = briefing["items"]
    total_reviewed = briefing["total_items_reviewed"]
    total_included = briefing["total_items_included"]

    # Stats bar
    cat_counts = {}
    for item in items:
        c = item.get("category", "other")
        cat_counts[c] = cat_counts.get(c, 0) + 1
    stats_cells = "".join(
        f'<td style="text-align:center;padding:0 16px;border-right:1px solid #e5e7eb;">'
        f'<div style="font-size:22px;font-weight:700;color:#111827;">{count}</div>'
        f'<div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">{CATEGORY_ICONS.get(cat,"")} {CATEGORY_LABELS.get(cat,cat)}</div>'
        f'</td>'
        for cat, count in cat_counts.items() if count
    )

    # Breakthrough section
    breakthroughs = [i for i in items if i.get("is_breakthrough")]
    breakthrough_section = ""
    if breakthroughs:
        bt_html = "".join(_render_item_html(i) for i in breakthroughs)
        breakthrough_section = f"""
<div style="background:#fef2f2;border:2px solid #ef4444;border-radius:12px;padding:20px 24px;margin-bottom:32px;">
  <h2 style="color:#ef4444;margin:0 0 16px 0;font-size:18px;">🔥 Breakthrough Alert</h2>
  {bt_html}
</div>"""

    # Category sections
    categories_html = ""
    for cat in ["research", "models_releases", "tools_products", "coding_dev"]:
        cat_items = [i for i in items if i.get("category") == cat and not i.get("is_breakthrough")]
        if not cat_items:
            continue
        icon = CATEGORY_ICONS.get(cat, "")
        label = CATEGORY_LABELS.get(cat, cat)
        items_html = "".join(_render_item_html(i) for i in cat_items)
        categories_html += f"""
<h2 style="color:#111827;font-size:18px;margin:32px 0 16px 0;padding-bottom:10px;border-bottom:2px solid #f3f4f6;">
  {icon} {label}
</h2>
{items_html}"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AI Pulse — {date}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="680" cellpadding="0" cellspacing="0" style="max-width:680px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#1e1b4b 0%,#312e81 50%,#1d4ed8 100%);border-radius:12px 12px 0 0;padding:32px 36px;">
              <p style="margin:0 0 6px 0;color:#a5b4fc;font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;">Daily AI Briefing</p>
              <h1 style="margin:0 0 4px 0;color:#ffffff;font-size:28px;font-weight:800;">🤖 AI Pulse</h1>
              <p style="margin:0;color:#c7d2fe;font-size:15px;">{date} &nbsp;·&nbsp; {total_included} items curated from {total_reviewed} reviewed</p>
            </td>
          </tr>

          <!-- Executive Summary -->
          <tr>
            <td style="background:#1e40af;padding:20px 36px;">
              <p style="margin:0 0 6px 0;color:#93c5fd;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;">Today's Big Picture</p>
              <p style="margin:0;color:#eff6ff;font-size:15px;line-height:1.7;">{exec_summary}</p>
            </td>
          </tr>

          <!-- Stats bar -->
          <tr>
            <td style="background:#ffffff;padding:16px 36px;border-bottom:1px solid #f3f4f6;">
              <table cellpadding="0" cellspacing="0">
                <tr>
                  {stats_cells}
                  <td style="text-align:center;padding:0 16px;">
                    <div style="font-size:22px;font-weight:700;color:#111827;">{total_reviewed}</div>
                    <div style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">📥 Total Reviewed</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="background:#ffffff;border-radius:0 0 12px 12px;padding:28px 36px;">
              {breakthrough_section}
              {categories_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 0;text-align:center;">
              <p style="margin:0;color:#9ca3af;font-size:12px;">
                AI Pulse &nbsp;·&nbsp; {date} &nbsp;·&nbsp; Powered by Gemini 2.5 Pro
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_email(briefing: dict, dry_run: bool = False) -> None:
    if not config.ENABLE_EMAIL or dry_run:
        logger.info("Email delivery skipped (ENABLE_EMAIL=False or --dry-run)")
        return

    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_tls = os.environ.get("SMTP_TLS", "ssl").lower()

    # Support comma-separated list of recipients
    recipient_raw = os.environ.get("RECIPIENT_EMAIL", "")
    recipients = [r.strip() for r in recipient_raw.split(",") if r.strip()]

    if not all([smtp_user, smtp_password, recipients]):
        logger.error("Missing email credentials (SMTP_USER, SMTP_PASSWORD, RECIPIENT_EMAIL)")
        return

    date = briefing["date"]
    item_count = briefing["total_items_included"]
    has_breakthrough = any(i.get("is_breakthrough") for i in briefing["items"])
    bt_suffix = " | 🔥 BREAKTHROUGH" if has_breakthrough else ""
    subject = f"🤖 AI Pulse — {date} | {item_count} items{bt_suffix}"

    html_body = build_html_email(briefing)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if smtp_tls == "starttls":
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, recipients, msg.as_string())
        else:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, recipients, msg.as_string())
        logger.info(f"Email sent to {recipients} via {smtp_host}:{smtp_port} — subject: {subject}")
    except Exception as e:
        logger.error(f"Email send failed: {e}", exc_info=True)
