import os
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta

import psycopg2
from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash
from models.database import get_user_by_email, load_module_config, DB_CONFIG

auth_bp = Blueprint('auth', __name__)

# ── SMTP helpers (reads from .env / environment) ────────────────────────────
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT   = int(os.getenv('SMTP_PORT', 587))
SMTP_USER   = os.getenv('SMTP_USER', '')
SMTP_PASS   = os.getenv('SMTP_PASS', '')


def _send_reset_email(to_email: str, reset_link: str):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'IVMS — Password Reset Request'
    msg['From']    = f'IVMS System <{SMTP_USER}>'
    msg['To']      = to_email

    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px;">
      <h2 style="color:#1e293b;margin-bottom:4px;">&#128272; Reset Your Password</h2>
      <p style="color:#64748b;font-size:14px;">You requested a password reset for your IVMS account.<br>
         Click the button below &mdash; this link is valid for <strong>1 hour</strong>.</p>
      <a href="{reset_link}"
         style="display:inline-block;margin:24px 0;padding:12px 28px;background:#2563eb;color:#fff;
                border-radius:8px;text-decoration:none;font-weight:600;font-size:15px;">
        Reset Password
      </a>
      <p style="color:#94a3b8;font-size:12px;">If you did not request this, you can safely ignore this email.<br>
         This link will expire in 1 hour.</p>
      <hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0;">
      <p style="color:#cbd5e1;font-size:11px;">IVMS &mdash; Integrated Vehicle Management System</p>
    </div>
    """
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())


def _create_reset_token(email: str) -> str:
    token = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(hours=1)
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    # Invalidate existing unused tokens for this email
    cur.execute("UPDATE password_reset_tokens SET used=TRUE WHERE email=%s AND used=FALSE", (email,))
    cur.execute(
        "INSERT INTO password_reset_tokens (token, email, expires_at, used) VALUES (%s,%s,%s,FALSE)",
        (token, email, expires)
    )
    conn.commit(); cur.close(); conn.close()
    return token


def _get_token_email(token: str):
    """Returns email if token valid/unexpired/unused, else None."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(
        "SELECT email, expires_at, used FROM password_reset_tokens WHERE token=%s",
        (token,)
    )
    row = cur.fetchone(); cur.close(); conn.close()
    if not row:
        return None
    email, expires_at, used = row
    if used or datetime.utcnow() > expires_at:
        return None
    return email


def _consume_token(token: str):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("UPDATE password_reset_tokens SET used=TRUE WHERE token=%s", (token,))
    conn.commit(); cur.close(); conn.close()


# ── Login / Logout ──────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@auth_bp.route('/login', methods=['POST'])
def do_login():
    email    = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not email or not password:
        return render_template('login.html', error="Please enter email and password.")

    user_info = get_user_by_email(email)

    if not user_info or 'password_hash' not in user_info:
        return render_template('login.html', error="Invalid credentials.")

    if not check_password_hash(user_info['password_hash'], password):
        return render_template('login.html', error="Invalid credentials.")

    session['logged_in']      = True
    role                      = user_info.get('role', 'user')
    name                      = user_info.get('name', email)
    account_module            = user_info.get('account_module', 'Normal')
    parent_email              = user_info.get('parent_email')
    can_add_vehicle           = user_info.get('can_add_vehicle', False)
    company_name              = user_info.get('company_name')

    modules  = load_module_config()
    mod_cfg  = modules.get(account_module, modules.get('Normal', {}))

    session['user_name']        = name
    session['role']             = role
    session['email']            = email
    session['parent_email']     = parent_email
    session['account_module']   = account_module
    session['can_add_vehicle']  = can_add_vehicle
    session['company_name']     = company_name
    session['vehicle_limit']    = user_info.get('vehicle_limit') if 'vehicle_limit' in user_info else mod_cfg.get('vehicle_limit', 1)
    session['user_limit']       = user_info.get('user_limit') if 'user_limit' in user_info else mod_cfg.get('user_limit', 0)
    session['enabled_modules']  = mod_cfg.get('enabled_modules', [])

    if role == 'super_admin':
        session['vehicle_limit']   = None
        session['user_limit']      = None
        session['enabled_modules'] = [
            "dashboard", "reports", "pre_reg_report", "vehicle_add", "user_manager", "notifications", "servers",
            "dashboard_stats", "dashboard_charts", "dashboard_map", "dashboard_big_chart", "dashboard_alerts",
            "reports_trips", "reports_stops", "reports_combined", "pricing"
        ]
    elif role == 'main_admin' and account_module == 'Normal':
        account_module = 'Premium'
        mod_cfg = modules.get('Premium', mod_cfg)
        session['account_module'] = 'Premium'
        if session['vehicle_limit'] is None or session['vehicle_limit'] == 1:
            session['vehicle_limit'] = mod_cfg.get('vehicle_limit')
        if session['user_limit'] is None or session['user_limit'] == 0:
            session['user_limit'] = mod_cfg.get('user_limit')
        session['enabled_modules']  = mod_cfg.get('enabled_modules', [])
        session['can_add_vehicle']  = True

    return redirect(url_for('reports.reports_home'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


# ── Forgot Password ─────────────────────────────────────────────────────────

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')

    email = request.form.get('email', '').strip().lower()
    if not email:
        return render_template('forgot_password.html', error="Please enter your email address.")

    user = get_user_by_email(email)
    if user:
        try:
            token      = _create_reset_token(email)
            base_url   = request.host_url.rstrip('/')
            reset_link = f"{base_url}/reset-password/{token}"
            _send_reset_email(email, reset_link)
        except Exception:
            import traceback; traceback.print_exc()
            return render_template('forgot_password.html',
                                   error="Failed to send reset email. Please try again later.")

    # Always show success (prevents email enumeration)
    return render_template('forgot_password.html',
                           success="A password reset link has been sent — but only if that email is registered in our system. If you don't receive an email within a few minutes, you don't have an account with us.")


# ── Reset Password ──────────────────────────────────────────────────────────

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    email = _get_token_email(token)
    if not email:
        return render_template('forgot_password.html',
                               error="This reset link is invalid or has expired. Please request a new one.")

    if request.method == 'GET':
        return render_template('reset_password.html', token=token)

    new_pass = request.form.get('password', '').strip()
    confirm  = request.form.get('confirm_password', '').strip()

    if not new_pass or len(new_pass) < 8:
        return render_template('reset_password.html', token=token,
                               error="Password must be at least 8 characters.")
    if new_pass != confirm:
        return render_template('reset_password.html', token=token,
                               error="Passwords do not match.")

    from models.database import update_user_db
    _consume_token(token)
    update_user_db(email, {'password_hash': generate_password_hash(new_pass)})

    return render_template('login.html',
                           success="Password reset successfully! You can now log in.")
