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

# A skill as evaluation.render_skills writes it: "Contact 58th". Recognised here
# rather than passed through as structured data because the digest is one
# markdown document that becomes both the text and the HTML part, and the text
# part wants exactly these words.
_SKILL = re.compile(r"^([A-Za-z](?:[A-Za-z ]*[A-Za-z])?) (\d{1,3})(st|nd|rd|th)$")

# Bars are drawn as table cells with a background colour, not as images or CSS
# widths. Mail clients block images by default and Outlook's desktop renderer
# is the Word engine, which mishandles styled divs; a table with width and
# bgcolor attributes is the one construction that survives everywhere.
_BAR_WIDTH = 108
_BAR_HEIGHT = 7
_TRACK = "#e8e8ed"
_FILL = "#0c2c56"


def _bar(percentile: int) -> str:
    filled = max(1, round(_BAR_WIDTH * percentile / 100))
    empty = _BAR_WIDTH - filled
    cells = f'<td width="{filled}" height="{_BAR_HEIGHT}" bgcolor="{_FILL}"></td>'
    if empty:
        cells += f'<td width="{empty}" height="{_BAR_HEIGHT}" bgcolor="{_TRACK}"></td>'
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'width="{_BAR_WIDTH}" style="border-collapse:collapse;table-layout:fixed">'
        f"<tr>{cells}</tr></table>"
    )


def skill_bars(line: str) -> str | None:
    """
    A skills line redrawn as bars, or nothing if the line is something else.

    All of the line has to parse before any of it is redrawn, so an unexpected
    shape degrades to the text it already was rather than to a half-built
    table.
    """
    parts = [segment.strip() for segment in line.split("·")]
    matches = [_SKILL.match(part) for part in parts]
    if len(parts) < 2 or not all(matches):
        return None

    rows = []
    for match in matches:
        name, percentile = match.group(1), int(match.group(2))
        rows.append(
            f'<tr><td style="{_STYLE["bar_label"]}">{name}</td>'
            f'<td style="{_STYLE["bar_track"]}">{_bar(percentile)}</td>'
            f'<td style="{_STYLE["bar_rank"]}">{percentile}{match.group(3)}</td></tr>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="{_STYLE["bars"]}"><tbody>{"".join(rows)}</tbody></table>'
    )


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
    "bars": "margin:6px 0 2px;border-collapse:collapse",
    "bar_label": (
        "font-size:12px;color:#6e6e73;padding:2px 10px 2px 0;"
        "white-space:nowrap;vertical-align:middle"
    ),
    "bar_track": "padding:2px 0;vertical-align:middle;width:108px",
    "bar_rank": (
        "font-size:12px;color:#6e6e73;padding:2px 0 2px 8px;"
        "vertical-align:middle;white-space:nowrap"
    ),
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
            rest = ""
            after_bars = False
            for line in lines[1:]:
                bars = skill_bars(line)
                if bars:
                    rest += bars
                else:
                    # A table has already ended the line, so a break after one
                    # would open a gap rather than close it.
                    lead = "" if after_bars else "<br>"
                    rest += (
                        f'{lead}<span style="{_STYLE["sub"]}">'
                        f"{_inline_html(line)}</span>"
                    )
                after_bars = bool(bars)
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
