import sqlite3
import json
import secrets
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

# Resolve the SQLite database relative to this file so it works from any CWD.
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'classroom.db')
SESSION_DURATION_MINUTES = 30
ALLOWED_STATUSES = {'present', 'absent', 'late', 'excused'}

# Optional Postgres (Supabase) support
USE_POSTGRES = False
PG_CONN_STR = os.environ.get('DATABASE_URL') or os.environ.get('SUPABASE_DB_URL')
if PG_CONN_STR:
    try:
        import psycopg2
        USE_POSTGRES = True
    except Exception:
        USE_POSTGRES = False


def get_conn():
    """Return a DB-connection-like object. For Postgres, return a thin wrapper
    that converts ? placeholders to %s so the rest of the code can keep using ?.
    """
    if USE_POSTGRES:
        real = psycopg2.connect(PG_CONN_STR, sslmode='require')

        class CurWrap:
            def __init__(self, cur):
                self._cur = cur

            def execute(self, sql, params=()):
                try:
                    return self._cur.execute(sql.replace('?', '%s'), params)
                except Exception:
                    return self._cur.execute(sql, params)

            def executemany(self, sql, params):
                try:
                    return self._cur.executemany(sql.replace('?', '%s'), params)
                except Exception:
                    return self._cur.executemany(sql, params)

            def fetchone(self):
                return self._cur.fetchone()

            def fetchall(self):
                return self._cur.fetchall()

            def close(self):
                return self._cur.close()

            @property
            def rowcount(self):
                return self._cur.rowcount

        class ConnWrap:
            def __init__(self, real):
                self._real = real

            def cursor(self):
                return CurWrap(self._real.cursor())

            def commit(self):
                return self._real.commit()

            def close(self):
                return self._real.close()

        return ConnWrap(real)

    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        # Create Postgres-compatible tables
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            student_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            class_code TEXT,
            email TEXT,
            status TEXT DEFAULT 'active'
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS courses (
            id SERIAL PRIMARY KEY,
            course_code TEXT UNIQUE NOT NULL,
            course_name TEXT NOT NULL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS attendance (
            id SERIAL PRIMARY KEY,
            student_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT DEFAULT 'present',
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            device_fingerprint TEXT,
            student_ip TEXT,
            fraud_flags TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS attendance_sessions (
            id SERIAL PRIMARY KEY,
            course_code TEXT NOT NULL,
            date TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            active INTEGER DEFAULT 1,
            creator_ip TEXT,
            creator_latitude DOUBLE PRECISION,
            creator_longitude DOUBLE PRECISION
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS polls (
            id SERIAL PRIMARY KEY,
            course_code TEXT NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            poll_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            answer TEXT NOT NULL,
            voted_at TEXT NOT NULL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            course_code TEXT,
            announcement_type TEXT DEFAULT 'announcement',
            attachments TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS auth_events (
            id SERIAL PRIMARY KEY,
            username TEXT,
            role TEXT,
            event_type TEXT NOT NULL,
            success INTEGER NOT NULL,
            event_time TEXT NOT NULL,
            ip_address TEXT
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS magic_tokens (
            id SERIAL PRIMARY KEY,
            student_id TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            used INTEGER DEFAULT 0
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS fraud_attempts (
            id SERIAL PRIMARY KEY,
            student_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            fraud_type TEXT NOT NULL,
            details TEXT,
            detected_at TEXT NOT NULL
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS assignments (
            id SERIAL PRIMARY KEY,
            course_code TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_at TEXT,
            max_score DOUBLE PRECISION DEFAULT 100,
            created_by TEXT,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            assignment_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            filename TEXT,
            original_filename TEXT,
            notes TEXT,
            submitted_at TEXT NOT NULL,
            score DOUBLE PRECISION,
            feedback TEXT,
            graded_by TEXT,
            graded_at TEXT,
            UNIQUE(assignment_id, student_id)
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS quizzes (
            id SERIAL PRIMARY KEY,
            course_code TEXT NOT NULL,
            title TEXT NOT NULL,
            duration_minutes INTEGER DEFAULT 10,
            max_attempts INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS quiz_questions (
            id SERIAL PRIMARY KEY,
            quiz_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            points DOUBLE PRECISION DEFAULT 1
        )''')

        c.execute('''CREATE TABLE IF NOT EXISTS quiz_attempts (
            id SERIAL PRIMARY KEY,
            quiz_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            answers TEXT,
            score DOUBLE PRECISION,
            max_score DOUBLE PRECISION,
            submitted_at TEXT NOT NULL
        )''')

        # Enforce one vote per student per poll (SQLite schema has UNIQUE too)
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_votes_poll_student ON votes (poll_id, student_id)")

        # Add missing columns safely (Postgres supports ADD COLUMN IF NOT EXISTS)
        c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS email TEXT")
        c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'")
        c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS email_verified INTEGER DEFAULT 0")
        c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS verify_code_hash TEXT")
        c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS verify_code_expiry TEXT")
        c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS verify_attempts INTEGER DEFAULT 0")
        c.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION")
        c.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION")
        c.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS device_fingerprint TEXT")
        c.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS student_ip TEXT")
        c.execute("ALTER TABLE attendance ADD COLUMN IF NOT EXISTS fraud_flags TEXT")
        c.execute("ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS creator_ip TEXT")
        c.execute("ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS creator_latitude DOUBLE PRECISION")
        c.execute("ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS creator_longitude DOUBLE PRECISION")
        c.execute("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS announcement_type TEXT DEFAULT 'announcement'")
        c.execute("ALTER TABLE announcements ADD COLUMN IF NOT EXISTS attachments TEXT")

        # Insert defaults if missing
        c.execute("SELECT 1 FROM users WHERE username='admin'")
        if not c.fetchone():
            admin_hash = generate_password_hash('admin123')
            c.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)", ('admin', admin_hash, 'admin'))

        c.execute("SELECT 1 FROM courses LIMIT 1")
        if not c.fetchone():
            c.execute("INSERT INTO courses (course_code, course_name) VALUES (%s, %s)", ('CS101', 'Introduction to Programming'))
            c.execute("INSERT INTO courses (course_code, course_name) VALUES (%s, %s)", ('MATH201', 'Calculus I'))

        c.execute("SELECT 1 FROM students WHERE student_id='S001'")
        if not c.fetchone():
            student_hash = generate_password_hash('student123')
            c.execute("INSERT INTO students (student_id, name, password_hash, class_code) VALUES (%s, %s, %s, %s)",
                      ('S001', 'Alice Wonderland', student_hash, 'CS101'))

    else:
        # SQLite path (existing behavior)
        conn_sql = conn
        c_sql = c

        c_sql.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            class_code TEXT,
            email TEXT,
            status TEXT DEFAULT 'active'
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT UNIQUE NOT NULL,
            course_name TEXT NOT NULL
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT DEFAULT 'present',
            latitude REAL,
            longitude REAL,
            FOREIGN KEY (student_id) REFERENCES students(student_id),
            FOREIGN KEY (course_code) REFERENCES courses(course_code)
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS attendance_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL,
            date TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            active INTEGER DEFAULT 1,
            creator_ip TEXT,
            creator_latitude REAL,
            creator_longitude REAL,
            FOREIGN KEY (course_code) REFERENCES courses(course_code)
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poll_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            answer TEXT NOT NULL,
            voted_at TEXT NOT NULL,
            UNIQUE(poll_id, student_id)
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            course_code TEXT,
            announcement_type TEXT DEFAULT 'announcement',
            attachments TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS auth_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            role TEXT,
            event_type TEXT NOT NULL,
            success INTEGER NOT NULL,
            event_time TEXT NOT NULL,
            ip_address TEXT
        )''')

        # Add new columns if the schema was created before updates
        c_sql.execute("PRAGMA table_info(students)")
        student_columns = [row[1] for row in c_sql.fetchall()]
        if 'email' not in student_columns:
            c_sql.execute("ALTER TABLE students ADD COLUMN email TEXT")
        if 'status' not in student_columns:
            c_sql.execute("ALTER TABLE students ADD COLUMN status TEXT DEFAULT 'active'")
        for column, ddl in (
            ('email_verified', "ALTER TABLE students ADD COLUMN email_verified INTEGER DEFAULT 0"),
            ('verify_code_hash', "ALTER TABLE students ADD COLUMN verify_code_hash TEXT"),
            ('verify_code_expiry', "ALTER TABLE students ADD COLUMN verify_code_expiry TEXT"),
            ('verify_attempts', "ALTER TABLE students ADD COLUMN verify_attempts INTEGER DEFAULT 0"),
        ):
            if column not in student_columns:
                c_sql.execute(ddl)
        c_sql.execute("PRAGMA table_info(attendance)")
        attendance_columns = [row[1] for row in c_sql.fetchall()]
        if 'latitude' not in attendance_columns:
            c_sql.execute("ALTER TABLE attendance ADD COLUMN latitude REAL")
        if 'longitude' not in attendance_columns:
            c_sql.execute("ALTER TABLE attendance ADD COLUMN longitude REAL")
        if 'device_fingerprint' not in attendance_columns:
            c_sql.execute("ALTER TABLE attendance ADD COLUMN device_fingerprint TEXT")
        if 'student_ip' not in attendance_columns:
            c_sql.execute("ALTER TABLE attendance ADD COLUMN student_ip TEXT")
        if 'fraud_flags' not in attendance_columns:
            c_sql.execute("ALTER TABLE attendance ADD COLUMN fraud_flags TEXT")
        
        c_sql.execute("PRAGMA table_info(attendance_sessions)")
        session_columns = [row[1] for row in c_sql.fetchall()]
        if 'creator_ip' not in session_columns:
            c_sql.execute("ALTER TABLE attendance_sessions ADD COLUMN creator_ip TEXT")
        if 'creator_latitude' not in session_columns:
            c_sql.execute("ALTER TABLE attendance_sessions ADD COLUMN creator_latitude REAL")
        if 'creator_longitude' not in session_columns:
            c_sql.execute("ALTER TABLE attendance_sessions ADD COLUMN creator_longitude REAL")
        c_sql.execute("PRAGMA table_info(announcements)")
        announcement_columns = [row[1] for row in c_sql.fetchall()]
        if 'announcement_type' not in announcement_columns:
            c_sql.execute("ALTER TABLE announcements ADD COLUMN announcement_type TEXT DEFAULT 'announcement'")
        if 'attachments' not in announcement_columns:
            c_sql.execute("ALTER TABLE announcements ADD COLUMN attachments TEXT")

        # Insert default admin (password: admin123)
        admin_hash = generate_password_hash('admin123')
        c_sql.execute("SELECT * FROM users WHERE username='admin'")
        if not c_sql.fetchone():
            c_sql.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                          ('admin', admin_hash, 'admin'))

        # Insert demo courses
        c_sql.execute("SELECT * FROM courses")
        if not c_sql.fetchone():
            c_sql.execute("INSERT INTO courses (course_code, course_name) VALUES (?, ?)", ('CS101', 'Introduction to Programming'))
            c_sql.execute("INSERT INTO courses (course_code, course_name) VALUES (?, ?)", ('MATH201', 'Calculus I'))

        # Insert demo student (password: student123)
        student_hash = generate_password_hash('student123')
        c_sql.execute("SELECT * FROM students WHERE student_id='S001'")
        if not c_sql.fetchone():
            c_sql.execute("INSERT INTO students (student_id, name, password_hash, class_code) VALUES (?,?,?,?)",
                          ('S001', 'Alice Wonderland', student_hash, 'CS101'))

        # Magic login tokens for passwordless login
        c_sql.execute('''CREATE TABLE IF NOT EXISTS magic_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )''')

        # Audit log of suspected attendance fraud
        c_sql.execute('''CREATE TABLE IF NOT EXISTS fraud_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            course_code TEXT NOT NULL,
            fraud_type TEXT NOT NULL,
            details TEXT,
            detected_at TEXT NOT NULL
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            due_at TEXT,
            max_score REAL DEFAULT 100,
            created_by TEXT,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            filename TEXT,
            original_filename TEXT,
            notes TEXT,
            submitted_at TEXT NOT NULL,
            score REAL,
            feedback TEXT,
            graded_by TEXT,
            graded_at TEXT,
            UNIQUE(assignment_id, student_id)
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_code TEXT NOT NULL,
            title TEXT NOT NULL,
            duration_minutes INTEGER DEFAULT 10,
            max_attempts INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS quiz_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_option TEXT NOT NULL,
            points REAL DEFAULT 1
        )''')

        c_sql.execute('''CREATE TABLE IF NOT EXISTS quiz_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quiz_id INTEGER NOT NULL,
            student_id TEXT NOT NULL,
            answers TEXT,
            score REAL,
            max_score REAL,
            submitted_at TEXT NOT NULL
        )''')

    # Announcements saved with '' course_code were invisible to students
    # (their query matches course_code IS NULL for global posts).
    c.execute("UPDATE announcements SET course_code=NULL WHERE course_code=''")

    conn.commit()
    conn.close()

# ------- Magic tokens (passwordless login) -------

def create_magic_token(student_id, minutes_valid=15):
    conn = get_conn()
    c = conn.cursor()
    token = secrets.token_urlsafe(16)
    now = datetime.now()
    expires_at = (now + timedelta(minutes=minutes_valid)).isoformat()
    c.execute("INSERT INTO magic_tokens (student_id, token, created_at, expires_at, used) VALUES (?,?,?,?,0)",
              (student_id, token, now.isoformat(), expires_at))
    conn.commit()
    conn.close()
    return token


def get_magic_token(token):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT student_id, expires_at, used FROM magic_tokens WHERE token=?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    student_id, expires_at, used = row
    if used:
        return None
    if expires_at and expires_at < now:
        return None
    return {'student_id': student_id}


def consume_magic_token(token):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE magic_tokens SET used=1 WHERE token=?", (token,))
    conn.commit()
    conn.close()

# ------- Users (Admin/Instructor) -------
def add_user(username, password, role):
    conn = get_conn()
    c = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                  (username, password_hash, role))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def verify_user(username, password):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[0], password):
        return row[1]
    return None

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, role FROM users")
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'username': r[1], 'role': r[2]} for r in rows]

def delete_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

def update_user_password(username, password):
    conn = get_conn()
    c = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        c.execute("UPDATE users SET password_hash=? WHERE username=?",
                  (password_hash, username))
        conn.commit()
        return c.rowcount > 0
    except:
        return False
    finally:
        conn.close()

# ------- Students (with password) -------
def add_student(student_id, name, password, class_code='', email='', status='active'):
    conn = get_conn()
    c = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        c.execute("INSERT INTO students (student_id, name, password_hash, class_code, email, status) VALUES (?,?,?,?,?,?)",
                  (student_id, name, password_hash, class_code, email, status))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def update_student(student_id, name, class_code='', email=''):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE students SET name=?, class_code=?, email=? WHERE student_id=?",
                  (name, class_code, email, student_id))
        conn.commit()
        return c.rowcount > 0
    except:
        return False
    finally:
        conn.close()

def update_student_password(student_id, password):
    conn = get_conn()
    c = conn.cursor()
    password_hash = generate_password_hash(password)
    try:
        c.execute("UPDATE students SET password_hash=? WHERE student_id=?",
                  (password_hash, student_id))
        conn.commit()
        return c.rowcount > 0
    except:
        return False
    finally:
        conn.close()

def verify_student(student_id, password):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name, password_hash FROM students WHERE student_id=? AND status='active'", (student_id,))
    row = c.fetchone()
    conn.close()
    if row and check_password_hash(row[1], password):
        return row[0]
    return None

def get_all_students():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT student_id, name, class_code, email, status, COALESCE(email_verified, 0) FROM students ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return [{'student_id': r[0], 'name': r[1], 'class_code': r[2], 'email': r[3], 'status': r[4], 'email_verified': bool(r[5])} for r in rows]

def approve_student(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE students SET status='active' WHERE student_id=?", (student_id,))
    conn.commit()
    conn.close()

def get_pending_student_count():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students WHERE status='pending'")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_pending_students():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT student_id, name, class_code, email FROM students WHERE status='pending' ORDER BY name")
    rows = c.fetchall()
    conn.close()
    return [{'student_id': r[0], 'name': r[1], 'class_code': r[2], 'email': r[3]} for r in rows]

def get_total_students():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_total_announcements():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM announcements")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_total_attendance_records():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM attendance")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_attendance_today_count():
    conn = get_conn()
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute("SELECT COUNT(*) FROM attendance WHERE date=?", (today,))
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_students_incomplete_profiles():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students WHERE class_code IS NULL OR class_code='' OR email IS NULL OR email=''")
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def log_auth_event(username, role, event_type, success, ip_address=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO auth_events (username, role, event_type, success, event_time, ip_address) VALUES (?, ?, ?, ?, ?, ?)",
              (username, role, event_type, 1 if success else 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ip_address))
    conn.commit()
    conn.close()

def count_failed_auth_attempts(username, ip_address, minutes=15):
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM auth_events WHERE success=0 AND event_time>=? AND (username=? OR ip_address=?)", (cutoff, username, ip_address))
    total = c.fetchone()[0] or 0
    conn.close()
    return total

def get_recent_auth_events(limit=5):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT username, role, event_type, success, event_time, ip_address FROM auth_events ORDER BY event_time DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return [{'username': r[0], 'role': r[1], 'event_type': r[2], 'success': bool(r[3]), 'event_time': r[4], 'ip_address': r[5]} for r in rows]

def get_student_emails(course_code=None):
    conn = get_conn()
    c = conn.cursor()
    if course_code:
        c.execute("SELECT email FROM students WHERE class_code=? AND email IS NOT NULL AND email!=''", (course_code,))
    else:
        c.execute("SELECT email FROM students WHERE email IS NOT NULL AND email!=''")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]

def get_student_info(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT student_id, name, class_code, email, COALESCE(email_verified, 0) FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    conn.close()
    return {'student_id': row[0], 'name': row[1], 'class_code': row[2], 'email': row[3], 'email_verified': bool(row[4])} if row else None

def get_student_verification(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT email, COALESCE(email_verified, 0), verify_code_hash, verify_code_expiry, COALESCE(verify_attempts, 0) FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {'email': row[0], 'email_verified': bool(row[1]), 'code_hash': row[2], 'code_expiry': row[3], 'attempts': row[4]}

def store_verification_code(student_id, code_hash, expiry):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE students SET verify_code_hash=?, verify_code_expiry=?, verify_attempts=0 WHERE student_id=?",
              (code_hash, expiry, student_id))
    conn.commit()
    conn.close()

def record_verify_attempt(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE students SET verify_attempts=COALESCE(verify_attempts,0)+1 WHERE student_id=?", (student_id,))
    conn.commit()
    c.execute("SELECT COALESCE(verify_attempts,0) FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def set_email_verified(student_id, verified):
    conn = get_conn()
    c = conn.cursor()
    if verified:
        c.execute("UPDATE students SET email_verified=1, verify_code_hash=NULL, verify_code_expiry=NULL, verify_attempts=0 WHERE student_id=?",
                  (student_id,))
    else:
        c.execute("UPDATE students SET email_verified=0 WHERE student_id=?", (student_id,))
    conn.commit()
    conn.close()

def update_student_email(student_id, email):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE students SET email=?, email_verified=0, verify_code_hash=NULL, verify_code_expiry=NULL, verify_attempts=0 WHERE student_id=?",
              (email, student_id))
    conn.commit()
    conn.close()

def get_student_name(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT name FROM students WHERE student_id=?", (student_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def delete_student(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM students WHERE student_id=?", (student_id,))
    conn.commit()
    conn.close()

# ------- Courses -------
def get_all_courses():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT course_code, course_name FROM courses ORDER BY course_code")
    rows = c.fetchall()
    conn.close()
    return [{'code': r[0], 'name': r[1]} for r in rows]

def add_course(code, name):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO courses (course_code, course_name) VALUES (?, ?)", (code, name))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def delete_course(code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM courses WHERE course_code=?", (code,))
    conn.commit()
    conn.close()

# ------- Attendance -------
def mark_attendance(student_id, course_code, date_str, time_str, status='present', latitude=None, longitude=None, device_fingerprint=None, student_ip=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id FROM attendance WHERE student_id=? AND course_code=? AND date=?", 
              (student_id, course_code, date_str))
    exists = c.fetchone()
    
    # Detect fraud flags
    fraud_flags = []
    
    # Check for duplicate attendance within 5 minutes
    if exists:
        fraud_flags.append("duplicate_attendance_on_same_date")
    
    # Check if IP differs from session creator
    c.execute("SELECT creator_ip FROM attendance_sessions WHERE course_code=? AND date=? AND active=1", 
              (course_code, date_str))
    session_row = c.fetchone()
    if session_row and session_row[0] and student_ip and session_row[0] != student_ip:
        fraud_flags.append("ip_mismatch")
    
    fraud_string = "|".join(fraud_flags) if fraud_flags else None
    
    if exists:
        c.execute("UPDATE attendance SET time=?, status=?, latitude=?, longitude=?, device_fingerprint=?, student_ip=?, fraud_flags=? WHERE student_id=? AND course_code=? AND date=?", 
                  (time_str, status, latitude, longitude, device_fingerprint, student_ip, fraud_string, student_id, course_code, date_str))
    else:
        c.execute("INSERT INTO attendance (student_id, course_code, date, time, status, latitude, longitude, device_fingerprint, student_ip, fraud_flags) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (student_id, course_code, date_str, time_str, status, latitude, longitude, device_fingerprint, student_ip, fraud_string))
    conn.commit()
    conn.close()
    
    return fraud_flags

def get_attendance_by_date_and_course(date, course_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT a.id, a.student_id, s.name, a.course_code, co.course_name, a.time, a.status, a.latitude, a.longitude
                 FROM attendance a
                 JOIN students s ON a.student_id = s.student_id
                 LEFT JOIN courses co ON a.course_code = co.course_code
                 WHERE a.date=? AND a.course_code=? ORDER BY s.name''', (date, course_code))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'student_id': r[1], 'name': r[2], 'course_code': r[3], 'course_name': r[4], 'time': r[5], 'status': r[6], 'latitude': r[7], 'longitude': r[8]} for r in rows]

def get_attendance_for_student(student_id, course_code=None):
    conn = get_conn()
    c = conn.cursor()
    if course_code:
        c.execute("SELECT date, time, status FROM attendance WHERE student_id=? AND course_code=? ORDER BY date DESC", (student_id, course_code))
    else:
        c.execute("SELECT course_code, date, time, status FROM attendance WHERE student_id=? ORDER BY date DESC", (student_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_attendance_dates_for_course(course_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT DISTINCT date FROM attendance WHERE course_code=? ORDER BY date DESC", (course_code,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def update_attendance_status(record_id, status):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE attendance SET status=? WHERE id=?", (status, record_id))
    conn.commit()
    conn.close()

def get_attendance_stats(course_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM students WHERE class_code=?", (course_code,))
    total_students = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(DISTINCT date) FROM attendance WHERE course_code=?", (course_code,))
    days = c.fetchone()[0] or 0
    c.execute("SELECT status, COUNT(*) FROM attendance WHERE course_code=? GROUP BY status", (course_code,))
    status_counts = {row[0]: row[1] for row in c.fetchall()}
    conn.close()
    return {'total_students': total_students, 'days': days,
            'present': status_counts.get('present', 0),
            'late': status_counts.get('late', 0),
            'absent': status_counts.get('absent', 0),
            'excused': status_counts.get('excused', 0)}

def _attendance_rate(counts):
    counted = counts['present'] + counts['late'] + counts['absent']
    if counted == 0:
        return None
    return round((counts['present'] + counts['late']) / counted * 100)

def get_student_attendance_summary(student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT course_code, status, COUNT(*) FROM attendance WHERE student_id=? GROUP BY course_code, status",
              (student_id,))
    rows = c.fetchall()
    conn.close()
    courses = {}
    for course_code, status, count in rows:
        if status not in ALLOWED_STATUSES:
            continue
        entry = courses.setdefault(course_code, {'present': 0, 'late': 0, 'absent': 0, 'excused': 0})
        entry[status] += count
    overall = {'present': 0, 'late': 0, 'absent': 0, 'excused': 0}
    for entry in courses.values():
        entry['rate'] = _attendance_rate(entry)
        for key in overall:
            overall[key] += entry[key]
    overall['rate'] = _attendance_rate(overall)
    return {'overall': overall, 'courses': courses}

def create_attendance_session(course_code, date_str, creator_ip=None, creator_latitude=None, creator_longitude=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE attendance_sessions SET active=0 WHERE course_code=? AND date=? AND active=1",
              (course_code, date_str))
    token = secrets.token_urlsafe(8)
    now = datetime.now()
    expires_at = (now + timedelta(minutes=SESSION_DURATION_MINUTES)).isoformat()
    c.execute("INSERT INTO attendance_sessions (course_code, date, token, created_at, expires_at, active, creator_ip, creator_latitude, creator_longitude) VALUES (?,?,?,?,?,1,?,?,?)",
              (course_code, date_str, token, now.isoformat(), expires_at, creator_ip, creator_latitude, creator_longitude))
    conn.commit()
    conn.close()
    return token

def get_attendance_session_by_token(token):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT course_code, date, expires_at, creator_ip, creator_latitude, creator_longitude FROM attendance_sessions WHERE token=? AND active=1", (token,))
    row = c.fetchone()
    if row:
        expires_at = row[2]
        if expires_at and expires_at < now:
            c.execute("UPDATE attendance_sessions SET active=0 WHERE token=?", (token,))
            conn.commit()
            conn.close()
            return None
    conn.close()
    if row:
        return {
            'course_code': row[0], 
            'date': row[1],
            'creator_ip': row[3],
            'creator_latitude': row[4],
            'creator_longitude': row[5]
        }
    return None

def get_active_attendance_session(course_code, date_str):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT token, expires_at FROM attendance_sessions WHERE course_code=? AND date=? AND active=1 ORDER BY created_at DESC LIMIT 1",
              (course_code, date_str))
    row = c.fetchone()
    if row:
        expires_at = row[1]
        if expires_at and expires_at < now:
            c.execute("UPDATE attendance_sessions SET active=0 WHERE course_code=? AND date=? AND active=1",
                      (course_code, date_str))
            conn.commit()
            conn.close()
            return None
    conn.close()
    return row[0] if row else None

def get_active_attendance_session_info(course_code, date_str):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("SELECT token, expires_at FROM attendance_sessions WHERE course_code=? AND date=? AND active=1 ORDER BY created_at DESC LIMIT 1",
              (course_code, date_str))
    row = c.fetchone()
    if row:
        expires_at = row[1]
        if expires_at and expires_at < now:
            c.execute("UPDATE attendance_sessions SET active=0 WHERE course_code=? AND date=? AND active=1",
                      (course_code, date_str))
            conn.commit()
            conn.close()
            return None
    conn.close()
    return {'token': row[0], 'expires_at': row[1]} if row else None


# ------- Announcements -------
def add_announcement(title, content, course_code, created_by, announcement_type='announcement', attachments=None):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    attachments_json = json.dumps(attachments or [])
    c.execute("INSERT INTO announcements (title, content, course_code, announcement_type, attachments, created_at, created_by) VALUES (?,?,?,?,?,?,?)",
              (title, content, course_code, announcement_type, attachments_json, now, created_by))
    conn.commit()
    conn.close()

def get_announcements(course_code=None):
    conn = get_conn()
    c = conn.cursor()
    if course_code:
        c.execute("SELECT id, title, content, course_code, announcement_type, attachments, created_at, created_by FROM announcements WHERE course_code=? OR course_code IS NULL ORDER BY created_at DESC", (course_code,))
    else:
        c.execute("SELECT id, title, content, course_code, announcement_type, attachments, created_at, created_by FROM announcements ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [
        {
            'id': r[0],
            'title': r[1],
            'content': r[2],
            'course_code': r[3],
            'announcement_type': r[4],
            'attachments': json.loads(r[5]) if r[5] else [],
            'created_at': r[6],
            'author': r[7]
        } for r in rows]

def delete_announcement(announcement_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM announcements WHERE id=?", (announcement_id,))
    conn.commit()
    conn.close()

# ------- Polls -------
def create_poll(course_code, question, options_list):
    conn = get_conn()
    c = conn.cursor()
    options_json = json.dumps(options_list)
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("INSERT INTO polls (course_code, question, options, created_at, active) VALUES (%s, %s, %s, %s, 1) RETURNING id",
                  (course_code, question, options_json, now))
        poll_id = c.fetchone()[0]
    else:
        c.execute("INSERT INTO polls (course_code, question, options, created_at, active) VALUES (?,?,?,?,1)",
                  (course_code, question, options_json, now))
        conn.commit()
        try:
            poll_id = c.lastrowid
        except Exception:
            poll_id = None
    conn.commit()
    conn.close()
    return poll_id

def get_active_poll(course_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, question, options FROM polls WHERE course_code=? AND active=1 ORDER BY created_at DESC LIMIT 1", (course_code,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'question': row[1], 'options': json.loads(row[2])}
    return None

def get_poll_by_id(poll_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, course_code, question, options, active FROM polls WHERE id=?", (poll_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id': row[0], 'course_code': row[1], 'question': row[2],
                'options': json.loads(row[3]), 'active': bool(row[4])}
    return None

def get_poll_question(poll_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT question FROM polls WHERE id=?", (poll_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def cast_vote(poll_id, student_id, answer):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    try:
        c.execute("INSERT INTO votes (poll_id, student_id, answer, voted_at) VALUES (?,?,?,?)",
                  (poll_id, student_id, answer, now))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def get_poll_results(poll_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT answer, COUNT(*) FROM votes WHERE poll_id=? GROUP BY answer", (poll_id,))
    rows = c.fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}

def close_poll(poll_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE polls SET active=0 WHERE id=?", (poll_id,))
    conn.commit()
    conn.close()

# ------- Assignments & submissions -------

def create_assignment(course_code, title, description, due_at, max_score, created_by):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("INSERT INTO assignments (course_code, title, description, due_at, max_score, created_by, created_at, active) "
                  "VALUES (%s, %s, %s, %s, %s, %s, %s, 1) RETURNING id",
                  (course_code, title, description, due_at, max_score, created_by, now))
        assignment_id = c.fetchone()[0]
    else:
        c.execute("INSERT INTO assignments (course_code, title, description, due_at, max_score, created_by, created_at, active) "
                  "VALUES (?,?,?,?,?,?,?,1)",
                  (course_code, title, description, due_at, max_score, created_by, now))
        assignment_id = c.lastrowid
    conn.commit()
    conn.close()
    return assignment_id

def get_assignments(course_code=None):
    conn = get_conn()
    c = conn.cursor()
    if course_code:
        c.execute("SELECT id, course_code, title, description, due_at, max_score, created_by, created_at, active "
                  "FROM assignments WHERE course_code=? ORDER BY created_at DESC", (course_code,))
    else:
        c.execute("SELECT id, course_code, title, description, due_at, max_score, created_by, created_at, active "
                  "FROM assignments ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [
        {'id': r[0], 'course_code': r[1], 'title': r[2], 'description': r[3],
         'due_at': r[4], 'max_score': r[5], 'created_by': r[6], 'created_at': r[7],
         'active': bool(r[8])} for r in rows]

def get_assignment_by_id(assignment_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, course_code, title, description, due_at, max_score, created_by, created_at, active "
              "FROM assignments WHERE id=?", (assignment_id,))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {'id': r[0], 'course_code': r[1], 'title': r[2], 'description': r[3],
            'due_at': r[4], 'max_score': r[5], 'created_by': r[6], 'created_at': r[7],
            'active': bool(r[8])}

def close_assignment(assignment_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE assignments SET active=0 WHERE id=?", (assignment_id,))
    conn.commit()
    conn.close()

def submit_assignment(assignment_id, student_id, filename, original_filename, notes):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    try:
        c.execute("INSERT INTO submissions (assignment_id, student_id, filename, original_filename, notes, submitted_at) "
                  "VALUES (?,?,?,?,?,?)",
                  (assignment_id, student_id, filename, original_filename, notes, now))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def get_submissions(assignment_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT s.id, s.student_id, st.name, s.filename, s.original_filename, s.notes,
                        s.submitted_at, s.score, s.feedback, s.graded_by, s.graded_at
                 FROM submissions s LEFT JOIN students st ON st.student_id = s.student_id
                 WHERE s.assignment_id=? ORDER BY s.submitted_at""", (assignment_id,))
    rows = c.fetchall()
    conn.close()
    return [
        {'id': r[0], 'student_id': r[1], 'name': r[2] or r[1], 'filename': r[3],
         'original_filename': r[4], 'notes': r[5], 'submitted_at': r[6], 'score': r[7],
         'feedback': r[8], 'graded_by': r[9], 'graded_at': r[10]} for r in rows]

def get_submission(assignment_id, student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, assignment_id, student_id, filename, original_filename, notes, submitted_at, "
              "score, feedback, graded_by, graded_at FROM submissions WHERE assignment_id=? AND student_id=?",
              (assignment_id, student_id))
    r = c.fetchone()
    conn.close()
    if not r:
        return None
    return {'id': r[0], 'assignment_id': r[1], 'student_id': r[2], 'filename': r[3],
            'original_filename': r[4], 'notes': r[5], 'submitted_at': r[6], 'score': r[7],
            'feedback': r[8], 'graded_by': r[9], 'graded_at': r[10]}

def grade_submission(submission_id, score, feedback, graded_by):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE submissions SET score=?, feedback=?, graded_by=?, graded_at=? WHERE id=?",
              (score, feedback, graded_by, datetime.now().isoformat(), submission_id))
    conn.commit()
    changed = c.rowcount if hasattr(c, 'rowcount') else 0
    conn.close()
    return changed > 0

# ------- Quizzes -------

def create_quiz(course_code, title, duration_minutes, max_attempts, created_by, questions):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("INSERT INTO quizzes (course_code, title, duration_minutes, max_attempts, created_by, created_at, active) "
                  "VALUES (%s, %s, %s, %s, %s, %s, 1) RETURNING id",
                  (course_code, title, duration_minutes, max_attempts, created_by, now))
        quiz_id = c.fetchone()[0]
    else:
        c.execute("INSERT INTO quizzes (course_code, title, duration_minutes, max_attempts, created_by, created_at, active) "
                  "VALUES (?,?,?,?,?,?,1)",
                  (course_code, title, duration_minutes, max_attempts, created_by, now))
        quiz_id = c.lastrowid
    for q in questions:
        c.execute("INSERT INTO quiz_questions (quiz_id, question, options, correct_option, points) VALUES (?,?,?,?,?)",
                  (quiz_id, q['question'], json.dumps(q['options']), q['correct_option'], q.get('points', 1)))
    conn.commit()
    conn.close()
    return quiz_id

def get_quizzes(course_code=None):
    conn = get_conn()
    c = conn.cursor()
    if course_code:
        c.execute("""SELECT q.id, q.course_code, q.title, q.duration_minutes, q.max_attempts,
                            q.created_at, q.active, COUNT(qq.id)
                     FROM quizzes q LEFT JOIN quiz_questions qq ON qq.quiz_id = q.id
                     WHERE q.course_code=? GROUP BY q.id ORDER BY q.created_at DESC""", (course_code,))
    else:
        c.execute("""SELECT q.id, q.course_code, q.title, q.duration_minutes, q.max_attempts,
                            q.created_at, q.active, COUNT(qq.id)
                     FROM quizzes q LEFT JOIN quiz_questions qq ON qq.quiz_id = q.id
                     GROUP BY q.id ORDER BY q.created_at DESC""")
    rows = c.fetchall()
    conn.close()
    return [
        {'id': r[0], 'course_code': r[1], 'title': r[2], 'duration_minutes': r[3],
         'max_attempts': r[4], 'created_at': r[5], 'active': bool(r[6]), 'question_count': r[7]}
        for r in rows]

def get_quiz_by_id(quiz_id, include_answers=False):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, course_code, title, duration_minutes, max_attempts, created_at, active FROM quizzes WHERE id=?",
              (quiz_id,))
    r = c.fetchone()
    if not r:
        conn.close()
        return None
    quiz = {'id': r[0], 'course_code': r[1], 'title': r[2], 'duration_minutes': r[3],
            'max_attempts': r[4], 'created_at': r[5], 'active': bool(r[6]), 'questions': []}
    c.execute("SELECT id, question, options, correct_option, points FROM quiz_questions WHERE quiz_id=? ORDER BY id",
              (quiz_id,))
    for q in c.fetchall():
        item = {'id': q[0], 'question': q[1], 'options': json.loads(q[2]), 'points': q[4]}
        if include_answers:
            item['correct_option'] = q[3]
        quiz['questions'].append(item)
    conn.close()
    return quiz

def close_quiz(quiz_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE quizzes SET active=0 WHERE id=?", (quiz_id,))
    conn.commit()
    conn.close()

def get_quiz_attempt_count(quiz_id, student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM quiz_attempts WHERE quiz_id=? AND student_id=?", (quiz_id, student_id))
    count = c.fetchone()[0]
    conn.close()
    return count

def record_quiz_attempt(quiz_id, student_id, answers, score, max_score):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()
    if USE_POSTGRES:
        c.execute("INSERT INTO quiz_attempts (quiz_id, student_id, answers, score, max_score, submitted_at) "
                  "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                  (quiz_id, student_id, json.dumps(answers), score, max_score, now))
        attempt_id = c.fetchone()[0]
    else:
        c.execute("INSERT INTO quiz_attempts (quiz_id, student_id, answers, score, max_score, submitted_at) "
                  "VALUES (?,?,?,?,?,?)",
                  (quiz_id, student_id, json.dumps(answers), score, max_score, now))
        attempt_id = c.lastrowid
    conn.commit()
    conn.close()
    return attempt_id

def get_quiz_attempts(quiz_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT qa.id, qa.student_id, st.name, qa.score, qa.max_score, qa.submitted_at
                 FROM quiz_attempts qa LEFT JOIN students st ON st.student_id = qa.student_id
                 WHERE qa.quiz_id=? ORDER BY qa.submitted_at""", (quiz_id,))
    rows = c.fetchall()
    conn.close()
    return [
        {'id': r[0], 'student_id': r[1], 'name': r[2] or r[1], 'score': r[3],
         'max_score': r[4], 'submitted_at': r[5]} for r in rows]

def get_student_quiz_attempts(quiz_id, student_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, score, max_score, submitted_at FROM quiz_attempts WHERE quiz_id=? AND student_id=? "
              "ORDER BY submitted_at DESC", (quiz_id, student_id))
    rows = c.fetchall()
    conn.close()
    return [{'id': r[0], 'score': r[1], 'max_score': r[2], 'submitted_at': r[3]} for r in rows]

# ------- Gradebook helpers -------

def get_course_students(course_code):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT student_id, name FROM students WHERE class_code=? ORDER BY name", (course_code,))
    rows = c.fetchall()
    conn.close()
    return [{'student_id': r[0], 'name': r[1]} for r in rows]