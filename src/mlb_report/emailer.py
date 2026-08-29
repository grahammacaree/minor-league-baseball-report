"""
Rendering and delivery.

The markdown-to-HTML renderer is ported from career-scanner, which uses the
same narrow subset: headings, bullets, bold, rules. The one addition here is
indented continuation lines, because a watchlist entry is a bullet with its
season context stacked underneath.
"""

from __future__ import annotations

import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .digest import Digest

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_CODE = re.compile(r"`([^`]+)`")

_STYLE = {
    "body": (
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,"
        "sans-serif;font-size:15px;line-height:1.55;color:#1d1d1f;max-width:640px;"
        "margin:0 auto;padding:8px 4px"
    ),
    "h1": "font-size:20px;font-weight:600;margin:0 0 4px",
    "h2": (
        "font-size:13px;font-weight:600;text-transform:uppercase;"
        "letter-spacing:0.06em;color:#6e6e73;margin:32px 0 12px;"
        "padding-bottom:6px;border-bottom:1px solid #e5e5ea"
    ),
    "p": "margin:0 0 14px",
    "ul": "margin:0 0 14px;padding-left:20px",
    "li": "margin:0 0 10px",
    "sub": "color:#6e6e73;font-size:13px",
    "em": "color:#6e6e73;font-style:normal",
    "code": (
        "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;"
        "background:#f5f5f7;padding:1px 5px;border-radius:4px"
    ),
}


def _inline_html(text: str) -> str:
    text = _CODE.sub(rf'<code style="{_STYLE["code"]}">\1</code>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    return re.sub(r"_(.+?)_", rf'<em style="{_STYLE["em"]}">\1</em>', text)


def markdown_to_html(text: str) -> str:
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out: list[str] = []
    bullets: list[list[str]] = []

    def flush_bullets() -> None:
        if not bullets:
            return
        items = []
        for lines in bullets:
            head = _inline_html(lines[0])
            rest = "".join(
                f'<br><span style="{_STYLE["sub"]}">{_inline_html(line)}</span>'
                for line in lines[1:]
            )
            items.append(f'<li style="{_STYLE["li"]}">{head}{rest}</li>')
        out.append(f'<ul style="{_STYLE["ul"]}">{"".join(items)}</ul>')
        bullets.clear()

    for raw_line in escaped.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            continue

        # An indented line belongs to the bullet above it: the season context
        # under a watchlist entry is part of that entry, not a new one.
        if raw_line.startswith("  ") and bullets and not stripped.startswith("- "):
            bullets[-1].append(stripped)
            continue

        if stripped.startswith("- "):
            bullets.append([stripped[2:].strip()])
            continue

        flush_bullets()
        if stripped.startswith("## "):
            out.append(f'<h2 style="{_STYLE["h2"]}">{_inline_html(stripped[3:])}</h2>')
        elif stripped.startswith("# "):
            out.append(f'<h1 style="{_STYLE["h1"]}">{_inline_html(stripped[2:])}</h1>')
        else:
            out.append(f'<p style="{_STYLE["p"]}">{_inline_html(stripped)}</p>')

    flush_bullets()
    return f'<div style="{_STYLE["body"]}">{"".join(out)}</div>'


def subject_for(digest: Digest) -> str:
    """
    A subject line that says whether the email is worth opening now.

    Roster moves lead because they are the only thing that might need acting
    on; otherwise the count of standout performances is the signal.
    """
    date_label = f"{digest.report_date:%-d %b}"
    if digest.moves:
        return f"Mariners farm {date_label}: {len(digest.moves)} roster move(s)"
    if digest.notable:
        return (
            f"Mariners farm {date_label}: {len(digest.notable)} notable performance(s)"
        )
    if digest.trends:
        return f"Mariners farm {date_label}: trends only"
    return f"Mariners farm {date_label}: quiet night"


def send(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    mail_from: str,
    recipients: list[str],
    subject: str,
    text: str,
    html: str,
) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(text, "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.sendmail(mail_from, recipients, message.as_string())
