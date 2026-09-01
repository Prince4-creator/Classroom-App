from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, send_from_directory, jsonify
from flask_wtf.csrf import CSRFProtect
from database import *
from utils import (
    validate_student_id,
    validate_email,
    validate_username,
    validate_course_code,
    validate_password,
    validate_name,
    check_rate_limit,
    clear_rate_limit,
    log_action,
    require_student_role,
)
from datetime import datetime, timedelta
import csv
import io
import json
import os
from dotenv import load_dotenv

try:
    import qrcode
except Exception:
    qrcode = None
import secrets
import hashlib
import hmac
import socket
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin
import urllib.request
import urllib.error

from werkzeug.utils import secure_filename
import traceback
import base64

# Load environment variables from .env file
load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '').strip()
SUPABASE_BUCKET = os.environ.get('SUPABASE_BUCKET', 'attachments').strip()
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print('Warning: Supabase client init failed:', e)

# Staff login lives at a non-obvious URL so students are never pointed at it.
# Override with STAFF_LOGIN_PATH in .env to use your own secret path.
STAFF_LOGIN_PATH = os.environ.get('STAFF_LOGIN_PATH', '').strip() or '/staff-portal'
if not STAFF_LOGIN_PATH.startswith('/'):
    STAFF_LOGIN_PATH = '/' + STAFF_LOGIN_PATH

app = Flask(__name__)

# Security: SECRET_KEY must be set in production
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    if os.environ.get('FLASK_ENV') == 'production':
        raise ValueError('CRITICAL: SECRET_KEY environment variable must be set in production!')
    # Development mode only
    secret_key = 'dev-insecure-key-change-in-production'
    print('WARNING: Using development secret key. Set SECRET_KEY env var for production.')

app.secret_key = secret_key
app.config.update({
    'SESSION_COOKIE_SECURE': True,
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': 'Lax',
    'PERMANENT_SESSION_LIFETIME': timedelta(minutes=30),
    'SESSION_REFRESH_EACH_REQUEST': True,
    'WTF_CSRF_ENABLED': not bool(os.environ.get('FLASK_ENV') == 'testing'),
    # Privacy browsers/proxies omit the Referer header, which made every HTTPS
    # form POST fail the SSL-strict check. The CSRF token + SameSite=Lax cookie
    # already protect against cross-site request forgery.
    'WTF_CSRF_SSL_STRICT': False,
})

# Enable CSRF protection
csrf = CSRFProtect(app)

# Initialize database (creates tables in SQLite or Postgres/Supabase)
try:
    init_db()
except Exception as _e:
    print('Warning: init_db() failed during startup:', _e)

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_UPLOAD_EXTENSIONS = {'pdf', 'doc', 'docx', 'xlsx', 'xls', 'ppt', 'pptx', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'zip'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


def upload_to_supabase(filename, file_stream, content_type='application/octet-stream'):
    if not supabase:
        return False
    bucket = supabase.storage.from_(SUPABASE_BUCKET)
    try:
        resp = bucket.upload(filename, file_stream,
                             file_options={'content-type': content_type, 'upsert': 'true'})
    except TypeError:
        try:
            resp = bucket.upload(filename, file_stream, content_type=content_type)
        except Exception as e:
            print('Supabase upload failed:', e)
            return False
    except Exception as e:
        print('Supabase upload failed:', e)
        return False
    if isinstance(resp, dict):
        return bool(resp)
    return getattr(resp, 'data', resp) is not None


def get_supabase_download_url(filename):
    if not supabase:
        return None
    try:
        url_data = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(filename, 3600)
        if isinstance(url_data, dict):
            return url_data.get('signedURL') or url_data.get('signed_url')
        return getattr(url_data, 'signed_url', None) or getattr(url_data, 'signedURL', None)
    except Exception as e:
        print('Supabase signed URL failed:', e)
        return None

def get_accessible_host_url():
    public_url = os.environ.get('PUBLIC_URL', '').strip().rstrip('/')
    if public_url:
        return public_url
    host_url = request.host_url.rstrip('/')
    parsed = urlparse(host_url)
    if parsed.hostname in ('127.0.0.1', 'localhost'):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            local_ip = s.getsockname()[0]
            s.close()
            port_part = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{local_ip}{port_part}"
        except Exception:
            return host_url
    return host_url

@app.after_request
def apply_security_headers(response):
    # Allow HTTPS images (logo hosted on external CDN) while keeping other
    # restrictions tight. If you prefer, replace `https:` with a specific
    # host like 'https://onemillioncoders.gov.gh'.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' https: data:;"
    )
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Permissions-Policy'] = 'geolocation=()'
    return response


# Debug endpoint (protected): attempt a DB connection and return status.
# Only enabled when `DEBUG_SECRET` env var is set and the request provides
# the same secret as a query parameter to avoid accidental exposure.
@app.route('/__debug/db')
def debug_db():
    secret = os.environ.get('DEBUG_SECRET', '').strip()
    provided = request.args.get('secret', '')
    if not secret or provided != secret:
        return "Not authorized", 401
    # Try to connect using the app's database settings
    try:
        if not PG_CONN_STR:
            return 'PG_CONN_STR not configured', 500
        import psycopg2
        conn = psycopg2.connect(PG_CONN_STR, sslmode='require', connect_timeout=10)
        cur = conn.cursor()
        cur.execute('SELECT version()')
        ver = cur.fetchone()
        cur.close()
        conn.close()
        return f'DB OK: {ver[0]}', 200
    except Exception as e:
        # Return a concise error message for debugging (do not reveal secrets)
        tb = traceback.format_exc()
        print('Debug DB connect error (initial):', e)
        print(tb)
        # Try IPv4-only fallback: parse the PG_CONN_STR and attempt connect to an A record
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(PG_CONN_STR)
            # parsed.netloc may include user:pass@host:port
            netloc = parsed.netloc
            if '@' in netloc:
                creds, hostport = netloc.rsplit('@', 1)
            else:
                creds = ''
                hostport = netloc
            if ':' in hostport:
                host, port = hostport.split(':', 1)
                port = int(port)
            else:
                host = hostport
                port = 5432
            username = parsed.username
            password = parsed.password
            dbname = parsed.path.lstrip('/') or parsed.hostname

            # Resolve A records (IPv4)
            addrs = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
            ipv4_candidates = [a[4][0] for a in addrs]
            if not ipv4_candidates:
                return f'ERROR: no IPv4 address found for host {host}', 502
            last_err = None
            for ip in ipv4_candidates:
                try:
                    print('Attempting IPv4 connect to', ip)
                    conn2 = psycopg2.connect(host=ip, port=port, user=username, password=password, dbname=dbname, sslmode='require', connect_timeout=10)
                    cur2 = conn2.cursor()
                    cur2.execute('SELECT version()')
                    v2 = cur2.fetchone()
                    cur2.close()
                    conn2.close()
                    return f'DB OK (IPv4): {v2[0]} (connected to {ip})', 200
                except Exception as e2:
                    last_err = e2
                    print('IPv4 attempt failed for', ip, ':', e2)
            return f'ERROR IPv4 attempts failed: {last_err}', 502
        except Exception as inner:
            print('IPv4 fallback error:', inner)
            return f'ERROR: {str(e)}; IPv4-fallback-exception: {str(inner)}', 502


def is_safe_url(target):
    if not target:
        return False
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and test_url.netloc == urlparse(request.host_url).netloc

# -------- Email helpers --------
SMTP_SERVER = os.environ.get('SMTP_SERVER', '')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME', '')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
EMAIL_FROM = os.environ.get('EMAIL_FROM', SMTP_USERNAME)
EMAIL_SEND_ERROR = None

# -------- Mistral AI --------
MISTRAL_API_KEY = os.environ.get('MISTRAL_API_KEY', '').strip()
MISTRAL_MODEL = os.environ.get('MISTRAL_MODEL', '').strip() or 'mistral-large-latest'
MISTRAL_API_URL = 'https://api.mistral.ai/v1/chat/completions'


def send_email(subject, body, recipients):
    """Send email using configured SMTP. Try STARTTLS first, then fallback to SSL.
    Stores the last error in `EMAIL_SEND_ERROR` for diagnostics.
    """
    global EMAIL_SEND_ERROR
    EMAIL_SEND_ERROR = None
    if not SMTP_SERVER or not SMTP_USERNAME or not SMTP_PASSWORD:
        EMAIL_SEND_ERROR = 'SMTP is not fully configured.'
        return False
    if not recipients:
        EMAIL_SEND_ERROR = 'Recipient list is empty.'
        return False

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = ', '.join(recipients)
    msg.set_content(body)

    # Try STARTTLS on the configured port (commonly 587)
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e_starttls:
        # Keep the exception text and try SSL fallback
        EMAIL_SEND_ERROR = f"STARTTLS attempt failed: {e_starttls}"
        print('STARTTLS send failed:', e_starttls)
        # Log details for diagnostics (non-sensitive parts only)
        try:
            import traceback as _tb
            print('Email error traceback:', _tb.format_exc())
        except Exception:
            pass
        # Try SSL on port 465 if different
        try:
            ssl_port = 465 if SMTP_PORT != 465 else SMTP_PORT
            with smtplib.SMTP_SSL(SMTP_SERVER, ssl_port, timeout=30) as smtp_ssl:
                smtp_ssl.ehlo()
                smtp_ssl.login(SMTP_USERNAME, SMTP_PASSWORD)
                smtp_ssl.send_message(msg)
            return True
        except Exception as e_ssl:
            tb = traceback.format_exc()
            EMAIL_SEND_ERROR = f"STARTTLS error: {e_starttls}; SSL fallback error: {e_ssl}; traceback: {tb}"
            print('SSL fallback failed:', e_ssl)
            print(tb)
            return False


# ---------- Email verification ----------
VERIFY_CODE_TTL_MINUTES = 30
VERIFY_MAX_ATTEMPTS = 5


def generate_verification_code():
    return f"{secrets.randbelow(1000000):06d}"


def hash_verification_code(code):
    return hashlib.sha256(code.strip().encode('utf-8')).hexdigest()


def issue_verification_code(student_id, email):
    """Generate a fresh code, store only its hash, and email the code.
    Returns (sent, error_message)."""
    code = generate_verification_code()
    expiry = (datetime.now() + timedelta(minutes=VERIFY_CODE_TTL_MINUTES)).strftime('%Y-%m-%d %H:%M:%S')
    store_verification_code(student_id, hash_verification_code(code), expiry)
    subject = 'Verify your OneMillionCoders Classroom email'
    body = (
        f"Hello,\n\nYour OneMillionCoders Classroom verification code is: {code}\n\n"
        f"It expires in {VERIFY_CODE_TTL_MINUTES} minutes. "
        "If you did not request this, you can safely ignore this email."
    )
    if send_email(subject, body, [email]):
        return True, None
    return False, EMAIL_SEND_ERROR or 'email delivery failed'


# ---------- Authentication ----------
# The real staff login form is served at STAFF_LOGIN_PATH (see top of file).
# The well-known URLs below are decoys that send visitors to the student
# login page, so curious students are never shown the staff form.
if STAFF_LOGIN_PATH != '/login':
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        return redirect(url_for('login_choice'))

if STAFF_LOGIN_PATH != '/admin/login':
    @app.route('/admin/login', methods=['GET', 'POST'])
    def legacy_admin_login_redirect():
        return redirect(url_for('login_choice'))


@app.route('/student_login')
def student_login_redirect():
    return redirect(url_for('student_login'))

@app.route(STAFF_LOGIN_PATH, methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        ip_address = request.remote_addr
        try:
            if not username or not validate_username(username):
                flash('Invalid username format', 'error')
                log_auth_event(username, 'admin', 'admin_login_failed', False, ip_address)
                return render_template('admin_login.html')
            rate_key = f"admin_login:{ip_address}:{username}"
            if not check_rate_limit(rate_key, limit=5, window_seconds=900):
                flash('Too many failed login attempts. Please try again later.', 'error')
                log_auth_event(username, 'admin', 'admin_login_locked', False, ip_address)
                return render_template('admin_login.html')
            role = verify_user(username, password)
            if role in ('admin', 'instructor'):
                clear_rate_limit(rate_key)
                session.clear()
                session.permanent = True
                session['user'] = username
                session['role'] = role
                log_auth_event(username, role, 'admin_login', True, ip_address)
                return redirect(url_for('admin_panel' if role == 'admin' else 'dashboard'))
            log_auth_event(username, 'admin', 'admin_login_failed', False, ip_address)
            flash('Invalid admin credentials', 'error')
        except Exception as e:
            # Likely a DB/connectivity error (e.g. psycopg2.OperationalError). Do not expose internals.
            print('Database error during admin_login:', e)
            try:
                traceback.print_exc()
            except Exception:
                pass
            flash('Server error: unable to contact the database. Please try again later.', 'error')
            return render_template('admin_login.html')
    return render_template('admin_login.html')

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    # accept `next` from querystring or form so redirects survive POST
    next_url = request.values.get('next')
    if request.method == 'POST':
        try:
            student_id = request.form.get('student_id', '').strip()
            password = request.form.get('password', '').strip()
            
            if not student_id or not password:
                flash('Student ID and password are required.', 'error')
                return redirect(url_for('student_login', next=next_url))
            
            if not validate_student_id(student_id):
                flash('Invalid student ID format.', 'error')
                log_action('student_login_failed', student_id, 'invalid_format', False)
                return redirect(url_for('student_login', next=next_url))
            
            student_name = verify_student(student_id, password)
            if student_name:
                session.clear()
                session.permanent = True
                session['student_id'] = student_id
                session['student_name'] = student_name
                session['role'] = 'student'
                log_action('student_login', student_id, 'successful', True)
                if next_url and (next_url.startswith('/') or is_safe_url(next_url)):
                    return redirect(next_url)
                return redirect(url_for('student_dashboard'))
            
            log_action('student_login_failed', student_id, 'invalid_credentials', False)
            flash('Invalid student ID or password', 'error')
        except Exception as e:
            flash('An error occurred during login. Please try again.', 'error')
            log_action('student_login_error', 'unknown', str(e), False)
    
    return render_template('student_login.html', next_url=next_url)

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user' not in session:
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not verify_user(session['user'], current):
            flash('Current password is incorrect', 'error')
        elif len(new) < 8:
            flash('New password must be at least 8 characters', 'error')
        elif new != confirm:
            flash('New passwords do not match', 'error')
        elif update_user_password(session['user'], new):
            log_auth_event(session['user'], session.get('role', 'staff'), 'password_changed', True, request.remote_addr)
            flash('Password updated successfully', 'success')
            return redirect(url_for('admin_panel' if session.get('role') == 'admin' else 'dashboard'))
        else:
            flash('Could not update password. Please try again.', 'error')
    return render_template('change_password.html')

@app.route('/student/change_password', methods=['GET', 'POST'])
def student_change_password():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    if request.method == 'POST':
        current = request.form.get('current_password', '')
        new = request.form.get('new_password', '')
        confirm = request.form.get('confirm_password', '')
        if not verify_student(session['student_id'], current):
            flash('Current password is incorrect', 'error')
        elif len(new) < 8:
            flash('New password must be at least 8 characters', 'error')
        elif new != confirm:
            flash('New passwords do not match', 'error')
        elif update_student_password(session['student_id'], new):
            flash('Password updated successfully', 'success')
            return redirect(url_for('student_dashboard'))
        else:
            flash('Could not update password. Please try again.', 'error')
    return render_template('change_password.html')

# Forgot-password functionality removed per user request.

@app.route('/student/dashboard')
def student_dashboard():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    announcements = get_announcements(student['class_code'])
    my_attendance = get_attendance_for_student(session['student_id'])
    att_summary = get_student_attendance_summary(session['student_id'])
    assignment_count = len([a for a in announcements if a['announcement_type'] in ('assignment', 'exercise')])
    announcement_count = len(announcements)
    return render_template('student_dashboard.html', student=student, announcements=announcements, my_attendance=my_attendance,
                           att_summary=att_summary,
                           assignment_count=assignment_count, announcement_count=announcement_count)

@app.route('/student/assignments')
def student_assignments():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    assignments = get_assignments(student['class_code'])
    for a in assignments:
        a['my_submission'] = get_submission(a['id'], session['student_id'])
        a['overdue'] = assignment_is_overdue(a)
    announcements = get_announcements(student['class_code'])
    posts = [a for a in announcements if a['announcement_type'] in ('assignment', 'exercise')]
    return render_template('student_assignments.html', student=student, assignments=assignments, posts=posts)


def assignment_is_overdue(assignment):
    if not assignment.get('due_at') or not assignment.get('active'):
        return False
    try:
        return datetime.now() > datetime.fromisoformat(assignment['due_at'])
    except (ValueError, TypeError):
        return False

@app.route('/student/mark_attendance', methods=['GET', 'POST'])
def student_mark_attendance():
    if 'student_id' not in session:
        token = request.args.get('token', '').strip()
        if token:
            return redirect(url_for('student_login', next=request.path + '?token=' + token))
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))

    token = request.values.get('token', '').strip()
    session_info = None
    if token:
        session_info = get_attendance_session_by_token(token)
        if not session_info and request.method == 'GET':
            flash('Invalid or expired attendance token.', 'error')

    if request.method == 'POST':
        course_code = request.form.get('course_code')
        if token and session_info:
            course_code = session_info['course_code']
        if not course_code:
            flash('Select a course first', 'error')
            return redirect(url_for('student_mark_attendance', token=token) if token else url_for('student_mark_attendance'))
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')
        try:
            lat = float(latitude) if latitude else None
            lon = float(longitude) if longitude else None
        except (ValueError, TypeError):
            lat = None
            lon = None
        if lat is None or lon is None:
            flash('Location access is required to check in. Enable location permission in your browser and try again.', 'error')
            return redirect(url_for('student_mark_attendance', token=token) if token else url_for('student_mark_attendance'))
        
        # Collect fraud detection data
        from utils import generate_device_fingerprint, check_fraud_warnings
        device_fingerprint = generate_device_fingerprint(request)
        student_ip = request.remote_addr
        
        # Check for fraud warnings
        fraud_warnings = check_fraud_warnings(session['student_id'], course_code, date_str, lat, lon, student_ip)
        
        if fraud_warnings:
            # If there are warnings, require confirmation
            confirm = request.form.get('confirm_attendance')
            if not confirm:
                # Return the form with warnings for confirmation
                courses = get_all_courses()
                return render_template('student_mark_attendance.html', 
                                     courses=courses, student=student, session_info=session_info, 
                                     token=token, fraud_warnings=fraud_warnings,
                                     latitude=latitude, longitude=longitude, course_code=course_code)
            else:
                # Log that student confirmed despite warnings
                log_auth_event(session['student_id'], 'student', 'attendance_fraud_warning_confirmed', True, student_ip)
                try:
                    from fraud_detection import log_fraud_attempt
                    log_fraud_attempt(session['student_id'], course_code, 'warnings_confirmed',
                                      '; '.join(fraud_warnings))
                except Exception as fraud_err:
                    print('Could not record fraud attempt:', fraud_err)
        
        # Mark attendance with fraud detection data
        mark_attendance(session['student_id'], course_code, date_str, time_str, latitude=lat, longitude=lon,
                       device_fingerprint=device_fingerprint, student_ip=student_ip)
        location_info = f" from location ({lat:.4f}, {lon:.4f})" if lat and lon else " (location not captured)"
        flash(f'Attendance marked for {student["name"]} in {course_code}{location_info}', 'success')
        return redirect(url_for('student_dashboard'))
    courses = get_all_courses()
    return render_template('student_mark_attendance.html', courses=courses, student=student, session_info=session_info, token=token)


@app.route('/student/magic_login')
def student_magic_login():
    token = request.args.get('token', '').strip()
    next_url = request.args.get('next')
    if not token:
        flash('Missing magic login token', 'error')
        return redirect(url_for('student_login'))
    mt = get_magic_token(token)
    if not mt:
        flash('Invalid or expired magic login token', 'error')
        return redirect(url_for('student_login'))
    student_id = mt['student_id']
    student_info = get_student_info(student_id)
    if not student_info:
        flash('Student not found', 'error')
        return redirect(url_for('student_login'))
    consume_magic_token(token)
    session.clear()
    session.permanent = True
    session['student_id'] = student_id
    session['student_name'] = student_info['name']
    session['role'] = 'student'
    if next_url and (next_url.startswith('/') or is_safe_url(next_url)):
        return redirect(next_url)
    return redirect(url_for('student_dashboard'))


@app.route('/magic_qr')
def magic_qr():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login_choice'))
    student_id = request.args.get('student_id')
    session_token = request.args.get('session_token')
    if not student_id:
        return "Missing student_id", 400
    if qrcode is None:
        return "QR code support is not installed (pip install qrcode Pillow)", 503
    magic = create_magic_token(student_id, minutes_valid=30)
    next_path = url_for('student_mark_attendance', token=session_token) if session_token else url_for('student_dashboard')
    login_url = url_for('student_magic_login', token=magic, next=next_path, _external=True)
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(login_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return Response(buf.read(), mimetype='image/png')


@app.route('/student/view_attendance')
def student_view_attendance():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    course_code = request.args.get('course')
    if not course_code:
        courses = get_all_courses()
        return render_template('student_attendance_courses.html', courses=courses)
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    records = get_attendance_by_date_and_course(selected_date, course_code)
    att_summary = get_student_attendance_summary(session['student_id'])
    return render_template('student_view_attendance.html', course_code=course_code, selected_date=selected_date,
                           records=records, att_summary=att_summary)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_choice'))

# ---------- Dashboard (role-based) ----------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login_choice'))
    courses = get_all_courses()
    announcements = get_announcements()
    return render_template('dashboard.html', courses=courses, announcements=announcements)

# ---------- Attendance for Students ----------
@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if 'student_id' not in session and 'user' not in session:
        flash('Please log in to mark attendance.', 'error')
        return redirect(url_for('student_login', next='/attendance'))
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        course_code = request.form.get('course_code', '').strip()
        # Students can only mark attendance for themselves
        if 'student_id' in session:
            student_id = session['student_id']
        if not student_id or not validate_student_id(student_id):
            flash('Invalid student ID.', 'error')
            return redirect(url_for('attendance'))
        name = get_student_name(student_id)
        if not name:
            flash(f"Student ID {student_id} not found", 'error')
            return redirect(url_for('attendance'))
        if course_code not in {c['code'] for c in get_all_courses()}:
            flash('Invalid course selected.', 'error')
            return redirect(url_for('attendance'))
        latitude = request.form.get('latitude', '').strip()
        longitude = request.form.get('longitude', '').strip()
        try:
            lat = float(latitude) if latitude else None
            lon = float(longitude) if longitude else None
        except ValueError:
            lat = None
            lon = None
        if lat is None or lon is None:
            flash('Location access is required to check in. Enable location permission in your browser and try again.', 'error')
            return redirect(url_for('attendance'))
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')
        mark_attendance(student_id, course_code, date_str, time_str, latitude=lat, longitude=lon, student_ip=request.remote_addr)
        flash(f"Attendance marked for {name} in {course_code}", 'success')
        return redirect(url_for('attendance'))
    courses = get_all_courses()
    return render_template('attendance.html', courses=courses)

@app.route('/attendance/checkin', methods=['GET', 'POST'])
def attendance_checkin():
    token = request.values.get('token', '').strip()
    session_info = None
    if token:
        session_info = get_attendance_session_by_token(token)

    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        password = request.form.get('password', '').strip()
        token = request.form.get('token', '').strip()
        if not student_id or not password:
            flash('Student ID and password are required.', 'error')
            return redirect(url_for('attendance_checkin', token=token))
        session_info = get_attendance_session_by_token(token)
        if not session_info:
            flash('Invalid or expired attendance token.', 'error')
            return redirect(url_for('attendance_checkin', token=token))
        student_name = verify_student(student_id, password)
        if not student_name:
            flash('Invalid student ID or password.', 'error')
            return redirect(url_for('attendance_checkin', token=token))
        latitude = request.form.get('latitude', '').strip()
        longitude = request.form.get('longitude', '').strip()
        try:
            lat = float(latitude) if latitude else None
            lon = float(longitude) if longitude else None
        except ValueError:
            lat = None
            lon = None
        if lat is None or lon is None:
            flash('Location access is required to check in. Enable location permission in your browser and try again.', 'error')
            return redirect(url_for('attendance_checkin', token=token))
        now = datetime.now()
        date_str = session_info['date']
        time_str = now.strftime('%H:%M:%S')
        mark_attendance(student_id, session_info['course_code'], date_str, time_str, latitude=lat, longitude=lon, student_ip=request.remote_addr)
        flash(f"Attendance marked for {student_name} in {session_info['course_code']}", 'success')
        return redirect(url_for('attendance_checkin', token=token))

    return render_template('attendance_checkin.html', token=token, session_info=session_info)

@app.route('/attendance/session', methods=['GET', 'POST'])
def attendance_session():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login_choice'))

    course_code = request.args.get('course', 'CS101')
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    if request.method == 'POST':
        course_code = request.form.get('course_code', course_code)
        selected_date = request.form.get('date', selected_date)
        # Capture instructor's IP and location for fraud detection
        instructor_ip = request.remote_addr

        def parse_coord(value):
            try:
                return float(value) if value else None
            except (TypeError, ValueError):
                return None

        token = create_attendance_session(course_code, selected_date, 
                                        creator_ip=instructor_ip,
                                        creator_latitude=parse_coord(request.form.get('latitude')),
                                        creator_longitude=parse_coord(request.form.get('longitude')))
        flash('Attendance session token created.', 'success')
        return redirect(url_for('attendance_session', course=course_code, date=selected_date, token=token))

    session_info = get_active_attendance_session_info(course_code, selected_date)
    host_url = get_accessible_host_url()
    student_login_url = None
    if session_info and session_info.get('token'):
        login_path = url_for('student_login', next='/student/mark_attendance?token=' + session_info['token'])
        student_login_url = f"{host_url}{login_path}"
    return render_template('attendance_session.html',
                           course_code=course_code,
                           selected_date=selected_date,
                           token=session_info['token'] if session_info else None,
                           expires_at=session_info['expires_at'] if session_info else None,
                           host_url=host_url,
                           student_login_url=student_login_url)

@app.route('/attendance/general_qr', methods=['GET'])
def attendance_general_qr():
    """Generate a general QR code for all students to select course and mark attendance"""
    if qrcode is None:
        return "QR code support is not installed (pip install qrcode Pillow)", 503
    host_url = get_accessible_host_url()
    course_select_url = f"{host_url}{url_for('attendance_select_course')}"
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(course_select_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return Response(buf.read(), mimetype='image/png')

@app.route('/attendance/select_course')
def attendance_select_course():
    """Allow students to select their course before marking attendance"""
    courses = get_all_courses()
    return render_template('attendance_select_course.html', courses=courses)

# ---------- Instructor/Admin: View & Edit Attendance ----------
@app.route('/manage_attendance')
def manage_attendance():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login_choice'))
    course_code = request.args.get('course', 'CS101')
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    records = get_attendance_by_date_and_course(selected_date, course_code)
    all_dates = get_all_attendance_dates_for_course(course_code)
    courses = get_all_courses()
    stats = get_attendance_stats(course_code)
    token_info = get_active_attendance_session_info(course_code, selected_date)
    return render_template('manage_attendance.html', records=records, selected_date=selected_date,
                           all_dates=all_dates, courses=courses, course_code=course_code, stats=stats,
                           token=token_info['token'] if token_info else None,
                           expires_at=token_info['expires_at'] if token_info else None)

@app.route('/update_attendance_status', methods=['POST'])
def update_attendance_status_route():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login_choice'))
    record_id = request.form.get('record_id')
    status = request.form.get('status')
    if status not in ALLOWED_STATUSES:
        flash('Invalid attendance status', 'error')
    elif record_id:
        update_attendance_status(record_id, status)
        flash('Status updated', 'success')
    else:
        flash('Missing attendance record ID', 'error')
    return redirect(url_for('manage_attendance', course=request.form.get('course_code', 'CS101'), date=request.form.get('date', datetime.now().strftime('%Y-%m-%d'))))

@app.route('/export_attendance')
def export_attendance():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login_choice'))
    course_code = request.args.get('course')
    date = request.args.get('date')
    records = get_attendance_by_date_and_course(date, course_code)
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Student ID', 'Name', 'Time', 'Status'])
    for r in records:
        cw.writerow([r['student_id'], r['name'], r['time'], r['status']])
    output = si.getvalue()
    return Response(output, mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=attendance_{course_code}_{date}.csv'})

# ---------- Polls ----------
@app.route('/poll', methods=['GET', 'POST'])
def poll():
    if 'student_id' not in session and 'user' not in session:
        flash('Please log in to view polls.', 'error')
        return redirect(url_for('student_login', next='/poll'))
    if request.method == 'POST':
        if 'student_id' not in session:
            flash('Only students can vote in polls.', 'error')
            return redirect(url_for('poll'))
        student_id = session['student_id']
        poll_id = request.form.get('poll_id', '').strip()
        answer = request.form.get('answer', '').strip()
        target_poll = get_poll_by_id(poll_id) if poll_id else None
        if not target_poll or not target_poll['active']:
            flash('This poll is no longer active.', 'error')
            return redirect(url_for('poll'))
        if answer not in target_poll['options']:
            flash('Invalid answer for this poll.', 'error')
            return redirect(url_for('poll'))
        success = cast_vote(poll_id, student_id, answer)
        if success:
            flash("Vote recorded!", 'success')
        else:
            flash("You already voted", 'warning')
        return redirect(url_for('poll_results', poll_id=poll_id))
    courses = get_all_courses()
    active_polls = {}
    for c in courses:
        p = get_active_poll(c['code'])
        if p:
            active_polls[c['code']] = p
    return render_template('poll.html', active_polls=active_polls, courses=courses,
                           can_vote='student_id' in session)

@app.route('/poll/results')
def poll_results():
    poll_id = request.args.get('poll_id')
    if not poll_id:
        flash("No poll selected", 'error')
        return redirect(url_for('poll'))
    try:
        results = get_poll_results(poll_id)
        question = get_poll_question(poll_id) or "Poll"
    except Exception as e:
        print('poll_results DB error:', e)
        flash('Could not load poll results. Please try again later.', 'error')
        return redirect(url_for('poll'))
    return render_template('poll_results.html', results=results, question=question, poll_id=poll_id)

@app.route('/create_poll', methods=['GET', 'POST'])
def create_poll_route():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        course_code = request.form.get('course_code', '').strip()
        question = request.form.get('question', '').strip()
        options = [opt.strip() for opt in request.form.get('options', '').split(',') if opt.strip()]
        if not validate_course_code(course_code):
            flash('Invalid course code format', 'error')
        elif not question or len(question) < 5:
            flash('Poll question must be at least 5 characters', 'error')
        elif len(options) < 2:
            flash('Need at least 2 options', 'error')
        else:
            create_poll(course_code, question, options)
            flash(f"Poll created for {course_code}", 'success')
        return redirect(url_for('dashboard'))
    courses = get_all_courses()
    return render_template('create_poll.html', courses=courses)

# ---------- Assignments & Gradebook ----------

def staff_required():
    return 'user' in session and session.get('role') in ('admin', 'instructor')


def build_gradebook(course_code):
    """Aggregate graded assignments and best quiz attempts per student."""
    students = get_course_students(course_code)
    assignments = get_assignments(course_code)
    quizzes = get_quizzes(course_code)
    sub_by_assignment = {a['id']: {s['student_id']: s for s in get_submissions(a['id'])} for a in assignments}
    att_by_quiz = {}
    for q in quizzes:
        best = {}
        for att in get_quiz_attempts(q['id']):
            prev = best.get(att['student_id'])
            if prev is None or att['score'] > prev['score']:
                best[att['student_id']] = att
        att_by_quiz[q['id']] = best
    rows = []
    for st in students:
        cells = []
        earned_total = 0.0
        possible_total = 0.0
        for a in assignments:
            sub = sub_by_assignment[a['id']].get(st['student_id'])
            if sub and sub['score'] is not None:
                cells.append({'label': a['title'], 'score': sub['score'], 'max': a['max_score']})
                earned_total += float(sub['score'])
                possible_total += float(a['max_score'])
            elif sub:
                cells.append({'label': a['title'], 'score': None, 'max': a['max_score'], 'pending': True})
            else:
                cells.append({'label': a['title'], 'score': None, 'max': a['max_score'], 'missing': True})
        for q in quizzes:
            att = att_by_quiz[q['id']].get(st['student_id'])
            if att:
                cells.append({'label': q['title'], 'score': att['score'], 'max': att['max_score']})
                earned_total += float(att['score'])
                possible_total += float(att['max_score'])
            else:
                cells.append({'label': q['title'], 'score': None, 'max': None, 'missing': True})
        percent = round(earned_total / possible_total * 100, 1) if possible_total else None
        rows.append({'student_id': st['student_id'], 'name': st['name'], 'cells': cells, 'percent': percent})
    columns = [{'type': 'assignment', 'title': a['title']} for a in assignments] + \
              [{'type': 'quiz', 'title': q['title']} for q in quizzes]
    return {'rows': rows, 'columns': columns}


@app.route('/assignments', methods=['GET', 'POST'])
def assignments():
    if not staff_required():
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        course_code = request.form.get('course_code', '').strip()
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        due_at = request.form.get('due_at', '').strip() or None
        max_score_raw = request.form.get('max_score', '').strip()
        try:
            max_score = float(max_score_raw)
        except ValueError:
            max_score = None
        if course_code not in {c['code'] for c in get_all_courses()}:
            flash('Invalid course selected.', 'error')
        elif len(title) < 3:
            flash('Assignment title must be at least 3 characters.', 'error')
        elif max_score is None or max_score <= 0:
            flash('Max score must be a positive number.', 'error')
        elif due_at:
            try:
                datetime.fromisoformat(due_at)
            except ValueError:
                flash('Invalid due date format.', 'error')
                return redirect(url_for('assignments'))
            create_assignment(course_code, title, description, due_at, max_score, session['user'])
            flash(f'Assignment "{title}" created for {course_code}.', 'success')
            return redirect(url_for('assignments'))
        else:
            create_assignment(course_code, title, description, due_at, max_score, session['user'])
            flash(f'Assignment "{title}" created for {course_code}.', 'success')
            return redirect(url_for('assignments'))
    course_filter = request.args.get('course', '').strip()
    items = get_assignments(course_filter or None)
    counts = {a['id']: len(get_submissions(a['id'])) for a in items}
    return render_template('assignments.html', assignments=items, courses=get_all_courses(),
                           selected_course=course_filter, counts=counts)


@app.route('/assignment/<int:assignment_id>', methods=['GET', 'POST'])
def assignment_detail(assignment_id):
    if not staff_required():
        return redirect(url_for('login_choice'))
    assignment = get_assignment_by_id(assignment_id)
    if not assignment:
        flash('Assignment not found.', 'error')
        return redirect(url_for('assignments'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'close':
            close_assignment(assignment_id)
            flash('Assignment closed for new submissions.', 'success')
        elif action == 'grade':
            try:
                submission_id = int(request.form.get('submission_id', ''))
                score = float(request.form.get('score', ''))
            except ValueError:
                flash('Invalid grading input.', 'error')
                return redirect(url_for('assignment_detail', assignment_id=assignment_id))
            feedback = request.form.get('feedback', '').strip()
            submissions = {s['id']: s for s in get_submissions(assignment_id)}
            if submission_id not in submissions:
                flash('Submission not found for this assignment.', 'error')
            elif score < 0 or score > float(assignment['max_score']):
                flash(f"Score must be between 0 and {assignment['max_score']}.", 'error')
            else:
                grade_submission(submission_id, score, feedback, session['user'])
                flash(f"Graded {submissions[submission_id]['student_id']}: {score}/{assignment['max_score']}.", 'success')
        return redirect(url_for('assignment_detail', assignment_id=assignment_id))
    submissions = get_submissions(assignment_id)
    return render_template('assignment_detail.html', assignment=assignment, submissions=submissions)


@app.route('/student/assignment/<int:assignment_id>/submit', methods=['POST'])
def student_submit_assignment(assignment_id):
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    assignment = get_assignment_by_id(assignment_id)
    if not assignment or not assignment['active']:
        flash('Assignment not found or closed.', 'error')
        return redirect(url_for('student_assignments'))
    if assignment['course_code'] != student['class_code']:
        flash('This assignment is not for your class.', 'error')
        return redirect(url_for('student_assignments'))
    if assignment_is_overdue(assignment):
        flash('The deadline for this assignment has passed.', 'error')
        return redirect(url_for('student_assignments'))
    if get_submission(assignment_id, session['student_id']):
        flash('You already submitted this assignment.', 'warning')
        return redirect(url_for('student_assignments'))
    file = request.files.get('file')
    if not file or not file.filename or not allowed_file(file.filename):
        flash('Please choose a valid file to submit.', 'error')
        return redirect(url_for('student_assignments'))
    notes = request.form.get('notes', '').strip()[:500]
    safe_name = secure_filename(file.filename)
    stored_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secrets.token_hex(3)}_{safe_name}"
    if supabase:
        uploaded = upload_to_supabase(stored_name, file.stream, file.content_type or 'application/octet-stream')
        if not uploaded:
            flash('Upload failed. Please try again.', 'error')
            return redirect(url_for('student_assignments'))
    else:
        file.save(os.path.join(UPLOAD_FOLDER, stored_name))
    submit_assignment(assignment_id, session['student_id'], stored_name, file.filename, notes)
    flash(f'Submitted "{file.filename}" for {assignment["title"]}.', 'success')
    return redirect(url_for('student_assignments'))

# ---------- Quizzes ----------

@app.route('/quizzes', methods=['GET', 'POST'])
def quizzes():
    if not staff_required():
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        course_code = request.form.get('course_code', '').strip()
        title = request.form.get('title', '').strip()
        try:
            duration = int(request.form.get('duration_minutes', '10'))
        except ValueError:
            duration = 0
        try:
            max_attempts = int(request.form.get('max_attempts', '1'))
        except ValueError:
            max_attempts = 0
        try:
            questions = json.loads(request.form.get('questions_json', '[]'))
        except ValueError:
            questions = []
        valid_questions = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            text = str(q.get('question', '')).strip()
            options = [str(o).strip() for o in q.get('options', []) if str(o).strip()]
            correct = str(q.get('correct_option', '')).strip()
            try:
                points = float(q.get('points', 1))
            except (ValueError, TypeError):
                points = 0
            if text and len(options) >= 2 and correct in options and points > 0:
                valid_questions.append({'question': text, 'options': options, 'correct_option': correct, 'points': points})
        if course_code not in {c['code'] for c in get_all_courses()}:
            flash('Invalid course selected.', 'error')
        elif len(title) < 3:
            flash('Quiz title must be at least 3 characters.', 'error')
        elif not 1 <= duration <= 180:
            flash('Duration must be between 1 and 180 minutes.', 'error')
        elif not 1 <= max_attempts <= 5:
            flash('Attempts allowed must be between 1 and 5.', 'error')
        elif not valid_questions:
            flash('Add at least one complete question (text, 2+ options, correct answer, positive points).', 'error')
        else:
            create_quiz(course_code, title, duration, max_attempts, session['user'], valid_questions)
            flash(f'Quiz "{title}" created for {course_code} with {len(valid_questions)} question(s).', 'success')
            return redirect(url_for('quizzes'))
    course_filter = request.args.get('course', '').strip()
    items = get_quizzes(course_filter or None)
    return render_template('quizzes.html', quizzes=items, courses=get_all_courses(), selected_course=course_filter)


@app.route('/quiz/<int:quiz_id>', methods=['GET', 'POST'])
def quiz_detail(quiz_id):
    if not staff_required():
        return redirect(url_for('login_choice'))
    quiz = get_quiz_by_id(quiz_id, include_answers=True)
    if not quiz:
        flash('Quiz not found.', 'error')
        return redirect(url_for('quizzes'))
    if request.method == 'POST':
        if request.form.get('action') == 'close':
            close_quiz(quiz_id)
            flash('Quiz closed.', 'success')
        return redirect(url_for('quiz_detail', quiz_id=quiz_id))
    attempts = get_quiz_attempts(quiz_id)
    return render_template('quiz_detail.html', quiz=quiz, attempts=attempts)


@app.route('/student/quizzes')
def student_quizzes():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    items = get_quizzes(student['class_code'])
    for q in items:
        q['my_attempts'] = get_student_quiz_attempts(q['id'], session['student_id'])
        q['attempts_left'] = q['max_attempts'] - len(q['my_attempts'])
    return render_template('student_quizzes.html', student=student, quizzes=items)


@app.route('/student/quiz/<int:quiz_id>/take', methods=['GET', 'POST'])
def student_take_quiz(quiz_id):
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    quiz = get_quiz_by_id(quiz_id, include_answers=False)
    if not quiz or not quiz['active']:
        flash('Quiz not found or closed.', 'error')
        return redirect(url_for('student_quizzes'))
    if quiz['course_code'] != student['class_code']:
        flash('This quiz is not for your class.', 'error')
        return redirect(url_for('student_quizzes'))
    attempts_used = get_quiz_attempt_count(quiz_id, session['student_id'])
    if attempts_used >= quiz['max_attempts']:
        flash('You have used all your attempts for this quiz.', 'warning')
        return redirect(url_for('student_quizzes'))
    if request.method == 'POST':
        quiz_with_answers = get_quiz_by_id(quiz_id, include_answers=True)
        score = 0.0
        max_score = 0.0
        answers = {}
        for q in quiz_with_answers['questions']:
            max_score += float(q['points'])
            answer = request.form.get(f"q_{q['id']}", '').strip()
            answers[str(q['id'])] = answer
            if answer and answer in q['options'] and answer == q['correct_option']:
                score += float(q['points'])
        record_quiz_attempt(quiz_id, session['student_id'], answers, score, max_score)
        flash(f'Quiz submitted — you scored {score:g} / {max_score:g}.', 'success')
        return redirect(url_for('student_quizzes'))
    return render_template('quiz_take.html', student=student, quiz=quiz)

# ---------- AI Assistant (Mistral) ----------

ASSISTANT_SYSTEM_PROMPT = (
    "You are OneMillionCoders Classroom Assistant, a brilliant, friendly AI aide for "
    "teachers and classroom administrators. You answer any question thoroughly and "
    "accurately — teaching, lesson planning, grading, announcements, coding, general "
    "knowledge, anything. Be concise by default, detailed when asked. Use plain text "
    "with simple line breaks and '-' bullets; no markdown headers or code fences unless "
    "the user asks for code."
)

QUIZ_GEN_SYSTEM_PROMPT = (
    "You are an expert exam writer. You always reply with ONLY a raw JSON array — no "
    "explanations, no markdown, no code fences. Each element has exactly these keys: "
    "\"question\" (string), \"options\" (array of 3-4 strings), \"correct_option\" "
    "(one of the option strings, verbatim), \"points\" (number)."
)


def mistral_chat(messages, temperature=0.7, max_tokens=1500):
    """Call the Mistral chat API. Returns (reply_text, error_message)."""
    if not MISTRAL_API_KEY:
        return None, 'MISTRAL_API_KEY is not configured. Add your Mistral API key to the .env file.'
    payload = json.dumps({
        'model': MISTRAL_MODEL,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens,
    }).encode('utf-8')
    req = urllib.request.Request(
        MISTRAL_API_URL,
        data=payload,
        headers={
            'Authorization': f'Bearer {MISTRAL_API_KEY}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content'].strip(), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode('utf-8', errors='replace')[:300]
        except Exception:
            detail = ''
        print('Mistral API HTTP error:', e.code, detail)
        if e.code == 401:
            return None, 'Mistral rejected the API key. Check MISTRAL_API_KEY in your .env file.'
        if e.code == 403:
            if 'tier' in detail.lower() or '1910' in detail:
                return None, (f"Model '{MISTRAL_MODEL}' is not in your Mistral plan. "
                              "Set MISTRAL_MODEL in your .env file to one you have access to "
                              "(e.g. mistral-medium-latest or mistral-small-latest).")
            return None, 'Mistral rejected the API key. Check MISTRAL_API_KEY in your .env file.'
        if e.code == 404:
            return None, f"Model '{MISTRAL_MODEL}' is not available for this API key. Set MISTRAL_MODEL in your .env file (e.g. mistral-small-latest)."
        if e.code == 429:
            return None, 'Mistral rate limit reached. Please wait a moment and try again.'
        return None, f'Mistral API error (HTTP {e.code}). Please try again.'
    except Exception as e:
        print('Mistral API error:', e)
        return None, 'Could not reach the Mistral API. Check your internet connection and try again.'


def extract_json_questions(text):
    """Parse and validate quiz questions from a model reply. Returns list or None."""
    start, end = text.find('['), text.rfind(']')
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(parsed, list):
        return None
    cleaned = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        question = str(item.get('question', '')).strip()
        options = [str(o).strip() for o in item.get('options', []) if str(o).strip()]
        correct = str(item.get('correct_option', '')).strip()
        if not question or len(options) < 2 or correct not in options:
            continue
        try:
            points = float(item.get('points', 1))
        except (TypeError, ValueError):
            points = 1.0
        if points <= 0:
            points = 1.0
        cleaned.append({
            'question': question[:500],
            'options': [o[:200] for o in options[:4]],
            'correct_option': correct[:200],
            'points': points,
        })
    return cleaned or None


@app.route('/admin/assistant')
def admin_assistant():
    if not staff_required():
        return redirect(url_for('login_choice'))
    return render_template('admin_assistant.html',
                           mistral_configured=bool(MISTRAL_API_KEY),
                           mistral_model=MISTRAL_MODEL)


@app.route('/admin/assistant/chat', methods=['POST'])
def admin_assistant_chat():
    if not staff_required():
        return jsonify({'error': 'Not authorized'}), 403
    if not check_rate_limit(f"ai_chat:{request.remote_addr}", limit=60, window_seconds=900):
        return jsonify({'error': 'Too many AI requests. Please try again in a few minutes.'}), 429
    data = request.get_json(silent=True) or {}
    incoming = data.get('messages')
    if not isinstance(incoming, list):
        return jsonify({'error': 'No messages provided.'}), 400
    sanitized = []
    for m in incoming[-20:]:
        if not isinstance(m, dict):
            continue
        role = m.get('role')
        content = str(m.get('content', '')).strip()[:8000]
        if role in ('user', 'assistant') and content:
            sanitized.append({'role': role, 'content': content})
    if not sanitized or sanitized[-1]['role'] != 'user':
        return jsonify({'error': 'Nothing to ask yet.'}), 400
    reply, error = mistral_chat([{'role': 'system', 'content': ASSISTANT_SYSTEM_PROMPT}] + sanitized)
    if error:
        return jsonify({'error': error}), 502
    payload = {'reply': reply}
    questions = extract_json_questions(reply)
    if questions:
        payload['quiz'] = questions
    return jsonify(payload)


@app.route('/admin/assistant/generate_quiz', methods=['POST'])
def admin_generate_quiz():
    if not staff_required():
        return jsonify({'error': 'Not authorized'}), 403
    if not check_rate_limit(f"ai_quiz:{request.remote_addr}", limit=20, window_seconds=900):
        return jsonify({'error': 'Too many AI requests. Please try again in a few minutes.'}), 429
    data = request.get_json(silent=True) or {}
    topic = str(data.get('topic', '')).strip()[:200]
    course_code = str(data.get('course_code', '')).strip()[:20]
    try:
        count = min(max(int(data.get('count', 5)), 1), 10)
    except (TypeError, ValueError):
        count = 5
    if not topic:
        return jsonify({'error': 'Provide a topic first.'}), 400
    prompt = (
        f"Write {count} multiple-choice questions about: {topic}. "
        + (f"Course context: {course_code}. " if course_code else "")
        + "Vary the difficulty from easy to hard. Each question must have 4 options and exactly one correct answer."
    )
    reply, error = mistral_chat(
        [{'role': 'system', 'content': QUIZ_GEN_SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}],
        temperature=0.4,
        max_tokens=3000,
    )
    if error:
        return jsonify({'error': error}), 502
    questions = extract_json_questions(reply)
    if questions is None:
        return jsonify({'error': 'The AI returned an unexpected format. Please try again.'}), 502
    return jsonify({'questions': questions[:count]})

# ---------- Gradebook ----------

@app.route('/gradebook')
def gradebook():
    if not staff_required():
        return redirect(url_for('login_choice'))
    courses = get_all_courses()
    course_code = request.args.get('course', '').strip()
    if course_code not in {c['code'] for c in courses}:
        return render_template('gradebook.html', courses=courses, selected_course=None, book=None)
    book = build_gradebook(course_code)
    return render_template('gradebook.html', courses=courses, selected_course=course_code, book=book)


@app.route('/export_grades')
def export_grades():
    if not staff_required():
        return redirect(url_for('login_choice'))
    course_code = request.args.get('course', '').strip()
    if course_code not in {c['code'] for c in get_all_courses()}:
        flash('Invalid course selected.', 'error')
        return redirect(url_for('gradebook'))
    book = build_gradebook(course_code)
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Student ID', 'Name'] + [col['title'] for col in book['columns']] + ['Overall %'])
    for row in book['rows']:
        cell_values = []
        for cell in row['cells']:
            if cell['score'] is not None:
                cell_values.append(f"{cell['score']:g}/{cell['max']:g}")
            elif cell.get('pending'):
                cell_values.append('submitted (ungraded)')
            else:
                cell_values.append('missing')
        cw.writerow([row['student_id'], row['name']] + cell_values + [row['percent'] if row['percent'] is not None else ''])
    output = si.getvalue()
    return Response(output, mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=gradebook_{course_code}.csv'})


@app.route('/student/grades')
def student_grades():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    course_code = student['class_code']
    items = []
    earned = 0.0
    possible = 0.0
    for a in get_assignments(course_code):
        sub = get_submission(a['id'], session['student_id'])
        entry = {'kind': 'Assignment', 'title': a['title'], 'max': a['max_score'], 'score': None, 'feedback': None}
        if sub:
            entry['submitted_at'] = sub['submitted_at']
            if sub['score'] is not None:
                entry['score'] = sub['score']
                entry['feedback'] = sub['feedback']
                earned += float(sub['score'])
                possible += float(a['max_score'])
        items.append(entry)
    for q in get_quizzes(course_code):
        attempts = get_student_quiz_attempts(q['id'], session['student_id'])
        best = max(attempts, key=lambda a: a['score']) if attempts else None
        entry = {'kind': 'Quiz', 'title': q['title'], 'max': None, 'score': None, 'feedback': None}
        if best:
            entry['max'] = best['max_score']
            entry['score'] = best['score']
            entry['submitted_at'] = best['submitted_at']
            earned += float(best['score'])
            possible += float(best['max_score'])
        items.append(entry)
    percent = round(earned / possible * 100, 1) if possible else None
    return render_template('student_grades.html', student=student, items=items, percent=percent)


@app.route('/student/verify_email', methods=['GET', 'POST'])
def student_verify_email():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    info = get_student_verification(session['student_id'])
    if not info:
        session.clear()
        return redirect(url_for('student_login'))
    if request.method == 'POST':
        if info['email_verified']:
            flash('Your email is already verified.', 'success')
            return redirect(url_for('student_dashboard'))
        if not info['email']:
            flash('No email address on your account. Ask an admin to add one.', 'error')
            return redirect(url_for('student_dashboard'))
        code = request.form.get('code', '').strip()
        # Validate code is 6 digits
        if not code:
            flash('Enter the 6-digit code from your email.', 'error')
            return redirect(url_for('student_verify_email'))
        if not code.isdigit() or len(code) != 6:
            flash('Code must be exactly 6 digits.', 'error')
            return redirect(url_for('student_verify_email'))
        if info['attempts'] >= VERIFY_MAX_ATTEMPTS:
            flash('Too many incorrect attempts. Request a new code to try again.', 'error')
            return redirect(url_for('student_verify_email'))
        if not info['code_hash'] or not info['code_expiry']:
            flash('No active code yet. Request one below.', 'error')
            return redirect(url_for('student_verify_email'))
        try:
            expired = datetime.strptime(info['code_expiry'], '%Y-%m-%d %H:%M:%S') < datetime.now()
        except ValueError:
            expired = True
        if expired:
            flash('That code has expired. Request a new one below.', 'error')
            return redirect(url_for('student_verify_email'))
        if hmac.compare_digest(hash_verification_code(code), info['code_hash']):
            set_email_verified(session['student_id'], True)
            flash('Email verified — thank you!', 'success')
            return redirect(url_for('student_dashboard'))
        attempts = record_verify_attempt(session['student_id'])
        remaining = VERIFY_MAX_ATTEMPTS - attempts
        if remaining <= 0:
            flash('Too many incorrect attempts. Request a new code to try again.', 'error')
        else:
            flash(f'Incorrect code. {remaining} attempt(s) remaining.', 'error')
        return redirect(url_for('student_verify_email'))
    return render_template('student_verify_email.html', 
                         info=info, 
                         verify_code_ttl_minutes=VERIFY_CODE_TTL_MINUTES,
                         max_verify_attempts=VERIFY_MAX_ATTEMPTS)


@app.route('/student/send_verification_code', methods=['POST'])
def student_send_verification_code():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    info = get_student_verification(session['student_id'])
    if not info:
        session.clear()
        return redirect(url_for('student_login'))
    if info['email_verified']:
        flash('Your email is already verified.', 'success')
        return redirect(url_for('student_dashboard'))
    if not info['email']:
        flash('No email address on your account. Ask an admin to add one.', 'error')
        return redirect(url_for('student_dashboard'))
    if not check_rate_limit(f"verify_code:{session['student_id']}", limit=3, window_seconds=900):
        flash('Too many codes sent recently. Please try again in a few minutes.', 'error')
        return redirect(url_for('student_verify_email'))
    sent, error = issue_verification_code(session['student_id'], info['email'])
    if sent:
        flash(f'Verification code sent to {info["email"]}.', 'success')
    else:
        flash(f'Could not send the email ({error}). Ask an admin for help.', 'error')
    return redirect(url_for('student_verify_email'))


# ---------- Admin: Manage Students & Users & Courses ----------
@app.route('/admin/students', methods=['GET', 'POST'])
def admin_students():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            student_id = request.form.get('student_id', '').strip()
            name = request.form.get('name', '').strip()
            password = request.form.get('password', '')
            class_code = request.form.get('class_code', '').strip()
            email = request.form.get('email', '').strip()
            if not validate_student_id(student_id):
                flash('Invalid student ID format', 'error')
            elif not validate_name(name):
                flash('Invalid student name', 'error')
            elif not validate_password(password):
                flash('Password must be at least 8 characters', 'error')
            elif class_code and not validate_course_code(class_code):
                flash('Invalid class code format', 'error')
            elif email and not validate_email(email):
                flash('Invalid email format', 'error')
            elif add_student(student_id, name, password, class_code, email):
                if email:
                    issue_verification_code(student_id, email)
                flash('Student added', 'success')
            else:
                flash('ID exists or email invalid', 'error')
        elif action == 'approve':
            approve_student(request.form.get('student_id', ''))
            flash('Student approved', 'success')
        elif action == 'delete':
            delete_student(request.form.get('student_id', ''))
            flash('Student deleted', 'success')
        elif action == 'mark_verified':
            sid = request.form.get('student_id', '').strip()
            if sid and get_student_info(sid):
                set_email_verified(sid, True)
                flash(f'{sid} marked as verified.', 'success')
            else:
                flash('Student not found.', 'error')
        elif action == 'send_code':
            sid = request.form.get('student_id', '').strip()
            info = get_student_verification(sid) if sid else None
            if not info:
                flash('Student not found.', 'error')
            elif not info['email']:
                flash('That student has no email address yet. Add one first.', 'error')
            else:
                sent, error = issue_verification_code(sid, info['email'])
                if sent:
                    flash(f'Verification code sent to {info["email"]}.', 'success')
                else:
                    flash(f'Could not send the code email ({error}).', 'warning')
        return redirect(url_for('admin_students'))
    students = get_all_students()
    pending_students = get_pending_students()
    return render_template('admin_students.html', students=students, pending_students=pending_students)

@app.route('/admin/students/edit', methods=['GET', 'POST'])
def admin_edit_student():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    student_id = request.values.get('student_id')
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        name = request.form.get('name', '').strip()
        class_code = request.form.get('class_code', '').strip()
        email = request.form.get('email', '').strip()
        previous = get_student_info(student_id)
        if not validate_name(name):
            flash('Invalid student name', 'error')
        elif class_code and not validate_course_code(class_code):
            flash('Invalid class code format', 'error')
        elif email and not validate_email(email):
            flash('Invalid email format', 'error')
        elif update_student(student_id, name, class_code, email):
            # If email changed, reset verification status
            if previous and (previous.get('email') or '') != email:
                reset_email_verification(student_id)
            flash('Student updated', 'success')
        else:
            flash('Unable to update student', 'error')
        return redirect(url_for('admin_students'))
    student = get_student_info(student_id)
    if not student:
        flash('Student not found', 'error')
        return redirect(url_for('admin_students'))
    return render_template('admin_student_edit.html', student=student, student_id=student_id)

@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', '').strip()
        if not validate_username(username):
            flash('Invalid username format', 'error')
        elif not validate_password(password):
            flash('Password must be at least 8 characters', 'error')
        elif role not in ('admin', 'instructor'):
            flash('Invalid role selected', 'error')
        elif add_user(username, password, role):
            flash('User added', 'success')
        else:
            flash('Username exists', 'error')
        return redirect(url_for('admin_users'))
    users = get_all_users()
    return render_template('admin_users.html', users=users)

@app.route('/admin/courses', methods=['GET', 'POST'])
def admin_courses():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        name = request.form.get('name', '').strip()
        if not validate_course_code(code):
            flash('Invalid course code format', 'error')
        elif not name or len(name) < 2:
            flash('Course name must be at least 2 characters', 'error')
        elif add_course(code, name):
            flash('Course added', 'success')
        else:
            flash('Course code exists', 'error')
        return redirect(url_for('admin_courses'))
    courses = get_all_courses()
    return render_template('admin_courses.html', courses=courses)

@app.route('/admin/announcements', methods=['GET', 'POST'])
def admin_announcements():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        course_code = request.form.get('course_code') or None
        announcement_type = request.form.get('announcement_type', 'announcement').strip()
        send_to_email = request.form.get('send_email') == 'on'

        if not title or not content:
            flash('Announcement title and content are required.', 'error')
            return redirect(url_for('admin_announcements'))
        if announcement_type not in ('announcement', 'assignment', 'exercise'):
            flash('Invalid announcement type.', 'error')
            return redirect(url_for('admin_announcements'))
        if course_code and not validate_course_code(course_code):
            flash('Invalid course code format', 'error')
            return redirect(url_for('admin_announcements'))

        attachment_files = request.files.getlist('attachments')
        saved_attachments = []
        for attachment in attachment_files:
            if attachment and attachment.filename and allowed_file(attachment.filename):
                safe_name = secure_filename(attachment.filename)
                timestamped_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{safe_name}"
                if supabase:
                    uploaded = upload_to_supabase(timestamped_name, attachment.stream, attachment.content_type or 'application/octet-stream')
                    if uploaded:
                        saved_attachments.append(timestamped_name)
                else:
                    attachment_path = os.path.join(UPLOAD_FOLDER, timestamped_name)
                    attachment.save(attachment_path)
                    saved_attachments.append(timestamped_name)

        add_announcement(title, content, course_code, session['user'], announcement_type, saved_attachments)
        if send_to_email:
            recipients = get_student_emails(course_code if course_code else None)
            if not recipients:
                target = f"course {course_code}" if course_code else 'all courses'
                flash(f"Announcement posted, but no student email addresses were found for {target}.", 'warning')
            else:
                subject = f"[{announcement_type.capitalize()}] {title}"
                body = f"{content}\n\nCourse: {course_code or 'All Courses'}\nPosted by: {session['user']}"
                if saved_attachments:
                    host_url = get_accessible_host_url()
                    attachment_links = '\n'.join(
                        f"Attachment: {host_url}{url_for('download_upload', filename=filename)}" for filename in saved_attachments
                    )
                    body += f"\n\n{attachment_links}"
                if send_email(subject, body, recipients):
                    flash('Announcement posted and emails queued', 'success')
                else:
                    error_msg = EMAIL_SEND_ERROR or 'email notification failed or is not configured'
                    flash(f'Announcement posted, but {error_msg}', 'warning')
        else:
            flash('Announcement posted', 'success')
        return redirect(url_for('admin_announcements'))
    announcements = get_announcements()
    courses = get_all_courses()
    smtp_configured = bool(SMTP_SERVER and SMTP_USERNAME and SMTP_PASSWORD)
    return render_template('admin_announcements.html', announcements=announcements, courses=courses,
                           smtp_configured=smtp_configured)

@app.route('/admin/announcements/delete', methods=['POST'])
def admin_delete_announcement():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    announcement_id = request.form.get('announcement_id')
    if announcement_id:
        delete_announcement(announcement_id)
        flash('Announcement deleted', 'success')
    else:
        flash('Unable to delete announcement', 'error')
    return redirect(url_for('admin_announcements'))

@app.route('/admin/email_test', methods=['GET', 'POST'])
def admin_email_test():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))

    if request.method == 'POST':
        recipient = request.form.get('recipient', '').strip()
        subject = request.form.get('subject', 'Test email from Classroom App').strip()
        body = request.form.get('body', 'This is a test email sent from Classroom App.')

        if not recipient:
            flash('Recipient email is required.', 'error')
            return redirect(url_for('admin_email_test'))

        if not validate_email(recipient):
            flash('Recipient email format is invalid.', 'error')
            return redirect(url_for('admin_email_test'))

        if send_email(subject, body, [recipient]):
            flash(f'Test email sent to {recipient}', 'success')
        else:
            error_msg = EMAIL_SEND_ERROR or 'Unable to send the test email. Check SMTP configuration.'
            flash(f'{error_msg}', 'error')
        return redirect(url_for('admin_email_test'))

    return render_template('admin_email_test.html')

@app.route('/uploads/<path:filename>')
def download_upload(filename):
    if supabase:
        url = get_supabase_download_url(filename)
        if url:
            return redirect(url)
        flash('Attachment not found in storage.', 'error')
        return redirect(url_for('admin_announcements'))
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

# ---------- Home redirect ----------
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    if 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    return render_template('login_choice.html')

@app.route('/login_choice')
def login_choice():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    if 'student_id' in session:
        return redirect(url_for('student_dashboard'))
    return render_template('login_choice.html')

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    courses = get_all_courses()
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        name = request.form.get('name', '').strip()
        password = request.form.get('password', '').strip()
        class_code = request.form.get('class_code', '').strip()
        email = request.form.get('email', '').strip()
        if not student_id or not name or not password:
            flash('Student ID, name, and password are required.', 'error')
            return redirect(url_for('student_register'))
        if not validate_student_id(student_id):
            flash('Invalid student ID format', 'error')
            return redirect(url_for('student_register'))
        if not validate_name(name):
            flash('Invalid name format', 'error')
            return redirect(url_for('student_register'))
        if class_code and not validate_course_code(class_code):
            flash('Invalid class code format', 'error')
            return redirect(url_for('student_register'))
        if email and not validate_email(email):
            flash('Invalid email format', 'error')
            return redirect(url_for('student_register'))
        if not validate_password(password):
            flash('Password must be at least 8 characters', 'error')
            return redirect(url_for('student_register'))
        if add_student(student_id, name, password, class_code, email, status='pending'):
            if email:
                try:
                    issue_verification_code(student_id, email)
                except Exception:
                    pass
            flash('Registration submitted. An admin must approve your account.', 'success')
            return redirect(url_for('student_login'))
        flash('Unable to register student. Student ID may already exist.', 'error')
        return redirect(url_for('student_register'))
    return render_template('student_register.html', courses=courses)


@app.route('/admin')
def admin_panel():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login_choice'))
    stats = {
        'students': get_total_students(),
        'courses': len(get_all_courses()),
        'active_courses': len(get_all_courses()),
        'announcements': get_total_announcements(),
        'attendance_records': get_total_attendance_records(),
        'attendance_today': get_attendance_today_count(),
        'pending_requests': get_pending_student_count(),
    }
    recent_events = get_recent_auth_events(5)
    student_signup_url = f"{get_accessible_host_url()}{url_for('student_register')}"
    smtp_status = bool(SMTP_SERVER and SMTP_USERNAME and SMTP_PASSWORD)
    default_password_warning = bool(verify_user('admin', 'admin123'))
    return render_template('admin_dashboard.html', stats=stats, smtp_status=smtp_status, email_from=EMAIL_FROM, auth_events=recent_events, student_signup_url=student_signup_url, default_password_warning=default_password_warning)

@app.route('/admin/courses/delete', methods=['POST'])
def admin_delete_course():
    if 'user' not in session or session['role'] != 'admin': return redirect(url_for('login_choice'))
    code = request.form['code']
    delete_course(code)
    flash('Course deleted', 'success')
    return redirect(url_for('admin_courses'))    

@app.route('/admin/users/delete', methods=['POST'])
def admin_delete_user():
    if 'user' not in session or session['role'] != 'admin': return redirect(url_for('login_choice'))
    user_id = request.form['user_id']
    delete_user(user_id)
    flash('User deleted', 'success')
    return redirect(url_for('admin_users'))

@app.route('/debug_routes')
def debug_routes():
    secret = os.environ.get('DEBUG_SECRET', '').strip()
    provided = request.args.get('secret', '')
    if not secret or provided != secret:
        return "Not authorized", 401
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
        routes.append(f"{rule.rule} -> {rule.endpoint} ({methods})")
    return '<br>'.join(routes), 200

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html', path=request.path), 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0')