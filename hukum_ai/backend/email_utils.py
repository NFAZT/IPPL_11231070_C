import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD")

APP_FRONTEND_URL = os.getenv("APP_FRONTEND_URL", "http://localhost:3000")


def send_password_reset_email(to_email: str, token: str) -> None:
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError(
        )

    reset_url = f"{APP_FRONTEND_URL}/reset-password?token={token}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset Password - HAI Hukum AI"
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    text_body = f"""Halo,

Kami menerima permintaan reset password...

Berikut TOKEN reset password Anda:
{token}

Cara pakai di aplikasi:
1. Buka menu "Lupa Password" lalu pilih "Sudah punya token? Reset password".
2. Masukkan token di atas.
3. Masukkan password baru.

Jika Anda tidak merasa meminta reset password, abaikan saja email ini.
"""

    msg.attach(MIMEText(text_body, "plain", "utf-8"))

    print(f"[SMTP] HOST={SMTP_HOST}:{SMTP_PORT}, USER={SMTP_USER!r}, PASS_LEN={len(SMTP_PASS)}")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [to_email], msg.as_string())
        print(f"[EMAIL] Reset password terkirim ke {to_email}")
    except Exception as e:
        print(f"[EMAIL] Gagal kirim email reset ke {to_email}: {e}")
        raise