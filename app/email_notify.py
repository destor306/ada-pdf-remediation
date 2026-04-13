"""
Email notifications when a job completes.
Uses SMTP (works with Gmail, SendGrid, Mailgun, etc.)

Set in .env:
  SMTP_HOST       e.g. smtp.gmail.com
  SMTP_PORT       e.g. 587
  SMTP_USER       your email
  SMTP_PASSWORD   app password (not your account password)
  NOTIFY_FROM     From address (defaults to SMTP_USER)

Gmail setup:
  1. Enable 2FA on your Google account
  2. Generate an App Password: myaccount.google.com/apppasswords
  3. Use that as SMTP_PASSWORD
"""

import os
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _cfg():
    return {
        "host":     os.environ.get("SMTP_HOST", ""),
        "port":     int(os.environ.get("SMTP_PORT", 587)),
        "user":     os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from":     os.environ.get("NOTIFY_FROM", os.environ.get("SMTP_USER", "")),
    }


def _send(to: str, subject: str, html: str):
    cfg = _cfg()
    if not cfg["host"] or not cfg["user"]:
        return  # SMTP not configured — skip silently

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["from"]
    msg["To"]      = to
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], to, msg.as_string())
    except Exception as e:
        print(f"  [email] Failed to send to {to}: {e}")


def notify_done(to: str, job_id: str, page_count: int, app_url: str):
    """Send job-complete notification in a background thread."""
    download_url = f"{app_url}/api/download/{job_id}"
    subject = "Your ADA-compliant document is ready"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:2rem">
      <h2 style="color:#2b6cb0">Your document is ready ✅</h2>
      <p>Your PDF has been successfully converted to an ADA-accessible Word document.</p>
      <p><strong>{page_count} pages</strong> processed.</p>
      <p style="margin:1.5rem 0">
        <a href="{download_url}"
           style="background:#3182ce;color:white;padding:.7rem 1.4rem;border-radius:8px;
                  text-decoration:none;font-weight:600">
          Download .docx
        </a>
      </p>
      <p style="color:#718096;font-size:.85rem">
        Next steps: open in Word → Review → Check Accessibility → export as tagged PDF
        → validate at <a href="https://pac.pdf-accessibility.org">PAC 2026</a>
      </p>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:1.5rem 0">
      <p style="color:#a0aec0;font-size:.8rem">
        This link expires in 24 hours. Job ID: {job_id[:8]}
      </p>
    </div>"""
    threading.Thread(target=_send, args=(to, subject, html), daemon=True).start()


def notify_failed(to: str, job_id: str):
    subject = "ADA remediation failed"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:2rem">
      <h2 style="color:#e53e3e">Processing failed ✗</h2>
      <p>Something went wrong converting your PDF. Job ID: <code>{job_id[:8]}</code></p>
      <p>Please try again or contact support.</p>
    </div>"""
    threading.Thread(target=_send, args=(to, subject, html), daemon=True).start()
