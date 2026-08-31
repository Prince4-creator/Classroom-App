"""Regression tests for the security and bug fixes.

These tests run against a throwaway SQLite database (patched into
database.DB_NAME) so the development classroom.db is never modified.
"""

import pytest

import database
from app import STAFF_LOGIN_PATH
from utils import check_fraud_warnings, check_rate_limit, clear_rate_limit


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_NAME', str(tmp_path / 'test_classroom.db'))
    database.init_db()
    from app import app
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as test_client:
        yield test_client


def login_student(client, student_id='S001', password='student123'):
    return client.post('/student/login', data={'student_id': student_id, 'password': password})


def login_admin(client, username='admin', password='admin123'):
    return client.post(STAFF_LOGIN_PATH, data={'username': username, 'password': password})


# ---------- Authorization guards ----------

def test_export_attendance_requires_staff(client):
    response = client.get('/export_attendance?course=CS101&date=2026-08-30')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_update_attendance_status_requires_staff(client):
    response = client.post('/update_attendance_status',
                           data={'record_id': '1', 'status': 'present',
                                 'course_code': 'CS101', 'date': '2026-08-30'})
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_debug_routes_requires_secret(client):
    response = client.get('/debug_routes')
    assert response.status_code == 401


def test_manual_attendance_requires_login(client):
    response = client.get('/attendance')
    assert response.status_code == 302
    assert '/student/login' in response.headers['Location']


def test_poll_page_requires_login(client):
    response = client.get('/poll')
    assert response.status_code == 302
    assert '/student/login' in response.headers['Location']


# ---------- Attendance spoofing closed ----------

def test_student_cannot_mark_attendance_for_someone_else(client):
    login_student(client)
    response = client.post('/attendance',
                           data={'student_id': 'S999', 'course_code': 'CS101',
                                 'latitude': '6.6', 'longitude': '3.3'},
                           follow_redirects=True)
    assert response.status_code == 200
    # The record must be created for the logged-in student (S001 / Alice),
    # not for the spoofed ID from the form.
    assert b'Alice Wonderland' in response.data
    assert database.get_student_name('S999') is None


def test_manual_attendance_rejects_unknown_course(client):
    login_student(client)
    response = client.post('/attendance',
                           data={'student_id': 'S001', 'course_code': 'NOPE999',
                                 'latitude': '6.6', 'longitude': '3.3'},
                           follow_redirects=True)
    assert b'Invalid course selected.' in response.data


def test_attendance_requires_location(client):
    login_student(client)
    response = client.post('/attendance',
                           data={'student_id': 'S001', 'course_code': 'CS101'},
                           follow_redirects=True)
    assert b'Location access is required' in response.data
    # No attendance record may have been created.
    assert database.get_attendance_for_student('S001', 'CS101') == []


# ---------- Polls use session identity ----------

def test_vote_requires_login_and_uses_session_identity(client):
    poll_id = database.create_poll('CS101', 'Favorite language?', ['Python', 'SQL'])

    # Anonymous vote is rejected
    response = client.post('/poll', data={'poll_id': str(poll_id), 'answer': 'Python'})
    assert response.status_code == 302
    assert database.get_poll_results(poll_id) == {}

    login_student(client)
    response = client.post('/poll', data={'poll_id': str(poll_id), 'answer': 'Python'},
                           follow_redirects=True)
    assert b'Vote recorded!' in response.data
    assert database.get_poll_results(poll_id) == {'Python': 1}

    # Second vote by the same student is rejected
    response = client.post('/poll', data={'poll_id': str(poll_id), 'answer': 'SQL'},
                           follow_redirects=True)
    assert b'You already voted' in response.data
    assert database.get_poll_results(poll_id) == {'Python': 1}


def test_vote_rejects_invalid_answer(client):
    poll_id = database.create_poll('CS101', 'Pick one', ['Yes', 'No'])
    login_student(client)
    response = client.post('/poll', data={'poll_id': str(poll_id), 'answer': 'Maybe'},
                           follow_redirects=True)
    assert b'Invalid answer for this poll.' in response.data
    assert database.get_poll_results(poll_id) == {}


# ---------- Dashboard shows the student's own ID ----------

def test_student_dashboard_shows_student_id(client):
    login_student(client)
    response = client.get('/student/dashboard')
    assert response.status_code == 200
    assert b'S001' in response.data


# ---------- Global announcements visible to students ----------

def test_announcement_without_course_is_visible_to_students(client):
    database.add_announcement('Hello everyone', 'Global news', '', 'admin')
    # init_db migrates legacy '' course codes to NULL on startup
    database.init_db()
    announcements = database.get_announcements('CS101')
    assert any(a['title'] == 'Hello everyone' for a in announcements)


# ---------- Fraud warning time comparison ----------

def _skip_near_midnight():
    from datetime import datetime
    if datetime.now().hour == 0 and datetime.now().minute < 15:
        pytest.skip("Time-based check crosses the date boundary just after midnight")


def test_fraud_warnings_no_false_positive_for_old_time(client):
    _skip_near_midnight()
    from datetime import datetime, timedelta
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    old_time = (now - timedelta(minutes=10)).strftime('%H:%M:%S')
    database.mark_attendance('S001', 'CS101', date_str, old_time)
    # Same-day record from 10 minutes ago must not raise a duplicate warning.
    warnings = check_fraud_warnings('S001', 'CS101', date_str, new_ip='1.2.3.4')
    assert warnings == []


def test_fraud_warnings_flags_recent_duplicate(client):
    _skip_near_midnight()
    from datetime import datetime, timedelta
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    recent_time = (now - timedelta(minutes=1)).strftime('%H:%M:%S')
    database.mark_attendance('S001', 'CS101', date_str, recent_time)
    warnings = check_fraud_warnings('S001', 'CS101', date_str, new_ip='1.2.3.4')
    assert any('recently marked attendance' in w for w in warnings)


# ---------- Rate limit resets on success ----------

def test_clear_rate_limit_resets_budget():
    key = 'unit-test-clear'
    for _ in range(3):
        assert check_rate_limit(key, limit=3, window_seconds=60)
    assert check_rate_limit(key, limit=3, window_seconds=60) is False
    clear_rate_limit(key)
    assert check_rate_limit(key, limit=3, window_seconds=60) is True


def test_repeated_successful_admin_logins_do_not_lock_out(client):
    # Before the fix, successful logins also consumed the rate-limit budget,
    # locking legitimate users out after 5 logins within 15 minutes.
    for _ in range(6):
        response = login_admin(client)
        assert response.status_code == 302
        assert '/admin' in response.headers['Location']
        client.get('/logout')


def test_failed_admin_logins_still_lock_out(client):
    for _ in range(5):
        login_admin(client, password='wrong-password')
    response = login_admin(client, password='wrong-password')
    assert response.status_code == 200
    assert b'Too many failed login attempts' in response.data


# ---------- Admin login exposure ----------

def test_login_choice_page_has_no_staff_entry_point(client):
    response = client.get('/login_choice')
    assert response.status_code == 200
    # No staff/admin entry point is advertised to students
    assert b'Admin Login' not in response.data
    assert b'Staff login' not in response.data
    assert b'/admin/login' not in response.data


def test_well_known_staff_login_urls_are_decoys(client):
    for path in ('/login', '/admin/login'):
        response = client.get(path)
        assert response.status_code == 302
        assert '/login_choice' in response.headers['Location']


def test_staff_login_form_served_at_secret_path(client):
    response = client.get(STAFF_LOGIN_PATH)
    assert response.status_code == 200
    assert b'Admin / Instructor Login' in response.data


def test_admin_panel_warns_about_default_password(client):
    # The lockout test above exhausts the in-memory rate-limit budget
    clear_rate_limit('admin_login:127.0.0.1:admin')
    login_admin(client)
    response = client.get('/admin')
    assert response.status_code == 200
    assert b'Security risk' in response.data
    assert b'admin123' in response.data
