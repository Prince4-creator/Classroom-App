#!/usr/bin/env python3
"""
send_test_email.py
Simple SMTP test script for classroom_app.
Usage:
  python send_test_email.py recipient@example.com

This script reads SMTP configuration from the environment. The main app already
loads a local `.env` file if present, so you can copy `.env.example` to `.env`
and fill in your credentials before running this script.
"""
import os
import sys
import smtplib
from email.message import EmailMessage
import traceback

# Load .env from the current project directory if it exists
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as ef:
        for raw in ef:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v and k not in os.environ:
                os.environ[k] = v

SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587') or 587)
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
EMAIL_FROM = os.environ.get('EMAIL_FROM', SMTP_USERNAME)

def send_email(recipient, subject, body):
    if not SMTP_SERVER or not SMTP_USERNAME or not SMTP_PASSWORD:
        print("SMTP not configured. Set SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD (and optionally EMAIL_FROM).")
        return False
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = recipient
    msg.set_content(body)

    # Try STARTTLS first
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
        print('Email sent using STARTTLS')
        return True
    except Exception as e_starttls:
        print('STARTTLS send failed:', e_starttls)
        # Try SSL fallback
        try:
            ssl_port = 465 if SMTP_PORT != 465 else SMTP_PORT
            with smtplib.SMTP_SSL(SMTP_SERVER, ssl_port, timeout=30) as smtp_ssl:
                smtp_ssl.ehlo()
                smtp_ssl.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp_ssl.send_message(msg)
            print('Email sent using SSL')
            return True
        except Exception as e_ssl:
            print('SSL fallback failed:', e_ssl)
            print('Traceback:')
            print(traceback.format_exc())
            return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python send_test_email.py recipient@example.com")
        sys.exit(2)
    recipient = sys.argv[1]
    subject = "Test email from classroom_app"
    body = "This is a test email sent from classroom_app.\n\nIf you received it, SMTP is configured correctly."
    ok = send_email(recipient, subject, body)
    print("Email sent." if ok else "Email failed.")

if __name__ == '__main__':
    main()
