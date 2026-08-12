from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, send_from_directory
from database import *
from datetime import datetime, timedelta
import csv
import io
import os
try:
    import qrcode
except Exception:
    qrcode = None
import secrets
import socket
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin

from werkzeug.utils import secure_filename
import traceback
import base64

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

# Load local .env file if present (KEY=VALUE per line)
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    try:
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
    except Exception:
        pass

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-neon-key')
app.config.update({
    'SESSION_COOKIE_SECURE': True,
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': 'Lax',
    'PERMANENT_SESSION_LIFETIME': timedelta(minutes=30),
    'SESSION_REFRESH_EACH_REQUEST': True,
})

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
    try:
        resp = supabase.storage.from_(SUPABASE_BUCKET).upload(filename, file_stream, content_type=content_type)
        return resp.get('data') is not None
    except Exception as e:
        print('Supabase upload failed:', e)
        return False


def get_supabase_download_url(filename):
    if not supabase:
        return None
    try:
        url_data = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(filename, 3600)
        return url_data.get('signedURL')
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
            return f"{parsed.scheme}://{local_ip}:{parsed.port}"
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
        "img-src 'self' https: data:;"
    )
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'geolocation=()'
    return response


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


# ---------- Authentication ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = verify_user(username, password)
        if role:
            session.clear()
            session.permanent = True
            session['user'] = username
            session['role'] = role
            log_auth_event(username, role, 'staff_login', True, request.remote_addr)
            return redirect(url_for('dashboard'))
        else:
            log_auth_event(request.form.get('username', ''), None, 'staff_login_failed', False, request.remote_addr)
            flash('Invalid credentials', 'error')
    return render_template('login.html')


@app.route('/student_login')
def student_login_redirect():
    return redirect(url_for('student_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        ip_address = request.remote_addr
        if count_failed_auth_attempts(username, ip_address, minutes=15) >= 5:
            flash('Too many failed login attempts. Try again later.', 'error')
            log_auth_event(username, 'admin', 'admin_login_locked', False, ip_address)
            return render_template('admin_login.html')
        role = verify_user(username, password)
        if role in ('admin', 'instructor'):
            session.clear()
            session.permanent = True
            session['user'] = username
            session['role'] = role
            log_auth_event(username, role, 'admin_login', True, ip_address)
            return redirect(url_for('admin_panel' if role == 'admin' else 'dashboard'))
        log_auth_event(username, 'admin', 'admin_login_failed', False, ip_address)
        flash('Invalid admin credentials', 'error')
    return render_template('admin_login.html')

@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    # accept `next` from querystring or form so redirects survive POST
    next_url = request.values.get('next')
    if request.method == 'POST':
        student_id = request.form['student_id'].strip()
        password = request.form['password'].strip()
        student_name = verify_student(student_id, password)
        if student_name:
            session.clear()
            session.permanent = True
            session['student_id'] = student_id
            session['student_name'] = student_name
            session['role'] = 'student'
            if next_url and (next_url.startswith('/') or is_safe_url(next_url)):
                return redirect(next_url)
            return redirect(url_for('student_dashboard'))
        flash('Invalid student ID or password', 'error')
    return render_template('student_login.html', next_url=next_url)

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
    assignment_count = len([a for a in announcements if a['announcement_type'] in ('assignment', 'exercise')])
    announcement_count = len(announcements)
    return render_template('student_dashboard.html', student=student, announcements=announcements, my_attendance=my_attendance,
                           assignment_count=assignment_count, announcement_count=announcement_count)

@app.route('/student/assignments')
def student_assignments():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))
    student = get_student_info(session['student_id'])
    if not student:
        session.clear()
        return redirect(url_for('student_login'))
    announcements = get_announcements(student['class_code'])
    assignments = [a for a in announcements if a['announcement_type'] in ('assignment', 'exercise')]
    return render_template('student_assignments.html', student=student, assignments=assignments)

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
        mark_attendance(session['student_id'], course_code, date_str, time_str, latitude=lat, longitude=lon)
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
    session['student_id'] = student_id
    session['student_name'] = student_info['name']
    session['role'] = 'student'
    if next_url and (next_url.startswith('/') or is_safe_url(next_url)):
        return redirect(next_url)
    return redirect(url_for('student_dashboard'))


@app.route('/magic_qr')
def magic_qr():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login'))
    student_id = request.args.get('student_id')
    session_token = request.args.get('session_token')
    if not student_id:
        return "Missing student_id", 400
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
    return render_template('student_view_attendance.html', course_code=course_code, selected_date=selected_date, records=records)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------- Dashboard (role-based) ----------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    courses = get_all_courses()
    announcements = get_announcements()
    return render_template('dashboard.html', courses=courses, announcements=announcements)

# ---------- Attendance for Students ----------
@app.route('/attendance', methods=['GET', 'POST'])
def attendance():
    if request.method == 'POST':
        student_id = request.form['student_id']
        course_code = request.form['course_code']
        name = get_student_name(student_id)
        if not name:
            flash(f"Student ID {student_id} not found", 'error')
            return redirect(url_for('attendance'))
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')
        mark_attendance(student_id, course_code, date_str, time_str)
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
        student_id = request.form['student_id'].strip()
        password = request.form['password'].strip()
        token = request.form['token'].strip()
        session_info = get_attendance_session_by_token(token)
        if not session_info:
            flash('Invalid or expired attendance token.', 'error')
            return redirect(url_for('attendance_checkin', token=token))
        student_name = verify_student(student_id, password)
        if not student_name:
            flash('Invalid student ID or password.', 'error')
            return redirect(url_for('attendance_checkin', token=token))
        now = datetime.now()
        date_str = session_info['date']
        time_str = now.strftime('%H:%M:%S')
        mark_attendance(student_id, session_info['course_code'], date_str, time_str)
        flash(f"Attendance marked for {student_name} in {session_info['course_code']}", 'success')
        return redirect(url_for('attendance_checkin', token=token))

    return render_template('attendance_checkin.html', token=token, session_info=session_info)

@app.route('/attendance/session', methods=['GET', 'POST'])
def attendance_session():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login'))

    course_code = request.args.get('course', 'CS101')
    selected_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))

    if request.method == 'POST':
        course_code = request.form.get('course_code', course_code)
        selected_date = request.form.get('date', selected_date)
        token = create_attendance_session(course_code, selected_date)
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
        return redirect(url_for('login'))
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
    record_id = request.form['record_id']
    status = request.form['status']
    update_attendance_status(record_id, status)
    flash('Status updated', 'success')
    return redirect(url_for('manage_attendance', course=request.form['course_code'], date=request.form['date']))

@app.route('/export_attendance')
def export_attendance():
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
    if request.method == 'POST':
        student_id = request.form['student_id']
        course_code = request.form['course_code']
        answer = request.form['answer']
        poll_id = request.form['poll_id']
        if not get_student_name(student_id):
            flash("Invalid student ID", 'error')
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
    return render_template('poll.html', active_polls=active_polls, courses=courses)

@app.route('/poll/results')
def poll_results():
    poll_id = request.args.get('poll_id')
    if not poll_id:
        flash("No poll selected", 'error')
        return redirect(url_for('poll'))
    results = get_poll_results(poll_id)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT question FROM polls WHERE id=?", (poll_id,))
    row = c.fetchone()
    conn.close()
    question = row[0] if row else "Poll"
    return render_template('poll_results.html', results=results, question=question, poll_id=poll_id)

@app.route('/create_poll', methods=['GET', 'POST'])
def create_poll_route():
    if 'user' not in session or session['role'] not in ['admin', 'instructor']:
        return redirect(url_for('login'))
    if request.method == 'POST':
        course_code = request.form['course_code']
        question = request.form['question']
        options = [opt.strip() for opt in request.form['options'].split(',')]
        if len(options) >= 2:
            create_poll(course_code, question, options)
            flash(f"Poll created for {course_code}", 'success')
        else:
            flash("Need at least 2 options", 'error')
        return redirect(url_for('dashboard'))
    courses = get_all_courses()
    return render_template('create_poll.html', courses=courses)

# ---------- Admin: Manage Students & Users & Courses ----------
@app.route('/admin/students', methods=['GET', 'POST'])
def admin_students():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            student_id = request.form['student_id']
            name = request.form['name']
            password = request.form['password']
            class_code = request.form.get('class_code', '')
            email = request.form.get('email', '').strip()
            if add_student(student_id, name, password, class_code, email):
                flash('Student added', 'success')
            else:
                flash('ID exists or email invalid', 'error')
        elif action == 'approve':
            approve_student(request.form['student_id'])
            flash('Student approved', 'success')
        elif action == 'delete':
            delete_student(request.form['student_id'])
            flash('Student deleted', 'success')
        return redirect(url_for('admin_students'))
    students = get_all_students()
    pending_students = get_pending_students()
    return render_template('admin_students.html', students=students, pending_students=pending_students)

@app.route('/admin/students/edit', methods=['GET', 'POST'])
def admin_edit_student():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    student_id = request.values.get('student_id')
    if request.method == 'POST':
        student_id = request.form['student_id']
        name = request.form['name']
        class_code = request.form.get('class_code', '')
        email = request.form.get('email', '').strip()
        if update_student(student_id, name, class_code, email):
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
        return redirect(url_for('login'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        if add_user(username, password, role):
            flash('User added', 'success')
        else:
            flash('Username exists', 'error')
        return redirect(url_for('admin_users'))
    users = get_all_users()
    return render_template('admin_users.html', users=users)

@app.route('/admin/courses', methods=['GET', 'POST'])
def admin_courses():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        code = request.form['code']
        name = request.form['name']
        if add_course(code, name):
            flash('Course added', 'success')
        else:
            flash('Course code exists', 'error')
        return redirect(url_for('admin_courses'))
    courses = get_all_courses()
    return render_template('admin_courses.html', courses=courses)

@app.route('/admin/announcements', methods=['GET', 'POST'])
def admin_announcements():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        course_code = request.form.get('course_code')
        announcement_type = request.form.get('announcement_type', 'announcement')
        send_to_email = request.form.get('send_email') == 'on'

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
    return render_template('admin_announcements.html', announcements=announcements, courses=courses)

@app.route('/admin/announcements/delete', methods=['POST'])
def admin_delete_announcement():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
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
        return redirect(url_for('login'))

    if request.method == 'POST':
        recipient = request.form.get('recipient', '').strip()
        subject = request.form.get('subject', 'Test email from Classroom App').strip()
        body = request.form.get('body', 'This is a test email sent from Classroom App.')

        if not recipient:
            flash('Recipient email is required.', 'error')
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
    return render_template('login_choice.html')

@app.route('/login_choice')
def login_choice():
    if 'user' in session:
        return redirect(url_for('dashboard'))
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
        if add_student(student_id, name, password, class_code, email, status='pending'):
            flash('Registration submitted. An admin must approve your account.', 'success')
            return redirect(url_for('student_login'))
        flash('Unable to register student. Student ID may already exist.', 'error')
        return redirect(url_for('student_register'))
    return render_template('student_register.html', courses=courses)


@app.route('/admin')
def admin_panel():
    if 'user' not in session or session['role'] != 'admin':
        return redirect(url_for('login'))
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
    return render_template('admin_dashboard.html', stats=stats, smtp_status=smtp_status, email_from=EMAIL_FROM, auth_events=recent_events, student_signup_url=student_signup_url)

@app.route('/admin/courses/delete', methods=['POST'])
def admin_delete_course():
    if 'user' not in session or session['role'] != 'admin': return redirect(url_for('login'))
    code = request.form['code']
    delete_course(code)
    flash('Course deleted', 'success')
    return redirect(url_for('admin_courses'))    

@app.route('/admin/users/delete', methods=['POST'])
def admin_delete_user():
    if 'user' not in session or session['role'] != 'admin': return redirect(url_for('login'))
    user_id = request.form['user_id']
    delete_user(user_id)
    flash('User deleted', 'success')
    return redirect(url_for('admin_users'))

@app.route('/debug_routes')
def debug_routes():
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