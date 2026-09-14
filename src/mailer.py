"""Composes and sends email over Gmail SMTP.

Two kinds of email:

- **Breaking alerts**: big/unique stories (see priority.py) are emailed
  immediately, in real time, so you hear about major news within one pipeline
  run.
- **The digest**: the regular batch overview + the full list of new links.

Headlines/links/sources always come straight from the fetched RSS data -- only
the top overview paragraph is model-written (see providers.py).
"""

import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Tuple

from src.config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, MAIL_TO

_BASE_STYLE = "font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:640px;margin:auto;color:#111;"


def _truncate(text: str, limit: int = 220) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "\u2026"


def _send(html: str, text: str, subject: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [MAIL_TO], msg.as_string())


def _section_html(title: str, articles: List[Dict]) -> str:
    if not articles:
        return ""
    items = []
    for a in articles:
        snippet = _truncate(a.get("summary", ""))
        snippet_html = f"<br><span style='font-size:13px;color:#333;'>{snippet}</span>" if snippet else ""
        items.append(
            "<li style='margin-bottom:12px;'>"
            f"<a href='{a['link']}' style='font-weight:600;text-decoration:none;color:#111;'>{a['title']}</a>"
            f"<br><span style='color:#777;font-size:12px;'>{a['source']}</span>"
            f"{snippet_html}"
            "</li>"
        )
    return f"<h3 style='margin:24px 0 8px;'>{title}</h3><ul style='padding-left:18px;margin:0;'>{''.join(items)}</ul>"


def _tags_html(tags: List[str]) -> str:
    if not tags:
        return ""
    chips = "".join(
        f"<span style='display:inline-block;background:#fdecea;color:#b00020;"
        f"border-radius:10px;padding:1px 8px;font-size:11px;margin:2px 4px 2px 0;'>{t}</span>"
        for t in tags
    )
    return f"<br>{chips}"


def build_breaking_email(articles: List[Dict]) -> Tuple[str, str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    items = []
    for a in articles:
        snippet = _truncate(a.get("summary", ""))
        snippet_html = f"<br><span style='font-size:13px;color:#333;'>{snippet}</span>" if snippet else ""
        items.append(
            "<li style='margin-bottom:14px;'>"
            f"<a href='{a['link']}' style='font-weight:700;text-decoration:none;color:#b00020;'>{a['title']}</a>"
            f"<br><span style='color:#777;font-size:12px;'>{a['source']}</span>"
            f"{_tags_html(a.get('tags', []))}"
            f"{snippet_html}"
            "</li>"
        )
    html = (
        "<html><body style=\"" + _BASE_STYLE + "\">"
        "<div style='background:#b00020;color:#fff;padding:10px 16px;border-radius:6px;'>"
        f"<strong>BREAKING AI NEWS</strong> &mdash; {now}</div>"
        f"<ul style='margin-top:18px;padding-left:18px;'>{''.join(items)}</ul>"
        "<p style='color:#999;font-size:11px;margin-top:24px;'>"
        "Sent instantly because these stories were flagged as big / unique.</p>"
        "</body></html>"
    )
    text_lines = [f"BREAKING AI NEWS -- {now}", ""]
    text_lines += [f"- {a['title']} ({a['source']}) -- {a['link']}" for a in articles]
    return html, "\n".join(text_lines)


def build_email(overview: str, general: List[Dict], policy: List[Dict], tweets: List[Dict] = None, labs: List[Dict] = None) -> Tuple[str, str]:
    tweets = tweets or []
    labs = labs or []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = (
        "<html><body style=\"" + _BASE_STYLE + "\">"
        f"<h2 style='margin-bottom:4px;'>AI News Digest &mdash; {now}</h2>"
        f"<p style='color:#444;'>{overview}</p>"
        f"{_section_html('General AI News', general)}"
        f"{_section_html('AI Policy &amp; Political News', policy)}"
        f"{_section_html('AI Lab Updates', labs)}"
        f"{_section_html('AI Lab Tweets', tweets)}"
        "<p style='color:#999;font-size:11px;margin-top:32px;'>"
        "Sent automatically by your AI news digest bot.</p>"
        "</body></html>"
    )
    text_lines = [f"AI News Digest -- {now}", "", overview, ""]
    if general:
        text_lines.append("GENERAL AI NEWS")
        text_lines += [f"- {a['title']} ({a['source']}) -- {a['link']}" for a in general]
        text_lines.append("")
    if policy:
        text_lines.append("AI POLICY & POLITICAL NEWS")
        text_lines += [f"- {a['title']} ({a['source']}) -- {a['link']}" for a in policy]
        text_lines.append("")
    if labs:
        text_lines.append("AI LAB UPDATES")
        text_lines += [f"- {a['title']} ({a['source']}) -- {a['link']}" for a in labs]
        text_lines.append("")
    if tweets:
        text_lines.append("AI LAB TWEETS")
        text_lines += [f"- {a['title']} ({a['source']}) -- {a['link']}" for a in tweets]
    return html, "\n".join(text_lines)


def send_breaking_email(articles: List[Dict]) -> None:
    html, text = build_breaking_email(articles)
    top = articles[0].get("title", "AI news")
    subject = f"BREAKING AI NEWS: {top[:90]}"
    _send(html, text, subject)


def send_digest_email(overview: str, general: List[Dict], policy: List[Dict], tweets: List[Dict], count: int, labs: List[Dict] = None) -> None:
    html, text = build_email(overview, general, policy, tweets, labs)
    subject = f"AI News Digest - {count} new update{'s' if count != 1 else ''}"
    _send(html, text, subject)


def send_test_email() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = (
        "<html><body style=\"" + _BASE_STYLE + "\">"
        "<h2>Test email from AI News Digest</h2>"
        f"<p>Everything works. This was sent at {now}.</p>"
        "</body></html>"
    )
    _send(html, f"Test email from AI News Digest -- {now}", "AI News Digest -- test")