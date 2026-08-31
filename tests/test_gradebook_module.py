"""Tests for the assignments, quizzes, and gradebook module."""

import io
import json

import pytest

import database
from app import STAFF_LOGIN_PATH


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_NAME', str(tmp_path / 'test_classroom.db'))
    database.init_db()
    import app as app_module
    monkeypatch.setattr(app_module, 'supabase', None)
    app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app_module.app.test_client() as test_client:
        yield test_client


def login_admin(client):
    return client.post(STAFF_LOGIN_PATH, data={'username': 'admin', 'password': 'admin123'})


def login_student(client):
    return client.post('/student/login', data={'student_id': 'S001', 'password': 'student123'})


def create_quiz(course='CS101'):
    return database.create_quiz(course, 'Week 1 Quiz', 10, 1, 'admin', [
        {'question': 'Which is a language?', 'options': ['Python', 'Potato'],
         'correct_option': 'Python', 'points': 2},
        {'question': '2 + 2?', 'options': ['3', '4'],
         'correct_option': '4', 'points': 1},
    ])


# ---------- Auth guards ----------

def test_assignments_requires_staff(client):
    response = client.get('/assignments')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_gradebook_requires_staff(client):
    response = client.get('/gradebook?course=CS101')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']


def test_student_pages_require_login(client):
    for path in ('/student/assignments', '/student/quizzes', '/student/grades'):
        response = client.get(path)
        assert response.status_code == 302
        assert '/student/login' in response.headers['Location']


# ---------- Assignments ----------

def test_create_and_submit_assignment(client):
    login_admin(client)
    response = client.post('/assignments', data={
        'course_code': 'CS101', 'title': 'Homework 1',
        'description': 'Do the thing', 'due_at': '2099-01-01T23:59', 'max_score': '50',
    }, follow_redirects=True)
    assert b'Homework 1' in response.data
    assignment = database.get_assignments('CS101')[0]

    client.get('/logout')
    login_student(client)
    data = {'notes': 'my work',
            'file': (io.BytesIO(b'hello'), 'hw1.txt')}
    response = client.post(f'/student/assignment/{assignment["id"]}/submit',
                           data=data, content_type='multipart/form-data',
                           follow_redirects=True)
    assert b'Submitted' in response.data
    submission = database.get_submission(assignment['id'], 'S001')
    assert submission is not None
    assert submission['original_filename'] == 'hw1.txt'

    # Second submission is rejected
    data = {'file': (io.BytesIO(b'again'), 'hw1b.txt')}
    response = client.post(f'/student/assignment/{assignment["id"]}/submit',
                           data=data, content_type='multipart/form-data',
                           follow_redirects=True)
    assert b'already submitted' in response.data


def test_overdue_assignment_rejects_submission(client):
    assignment_id = database.create_assignment('CS101', 'Late HW', '', '2020-01-01T00:00', 100, 'admin')
    login_student(client)
    data = {'file': (io.BytesIO(b'x'), 'a.txt')}
    response = client.post(f'/student/assignment/{assignment_id}/submit',
                           data=data, content_type='multipart/form-data',
                           follow_redirects=True)
    assert b'deadline' in response.data
    assert database.get_submission(assignment_id, 'S001') is None


def test_submission_rejects_bad_file_type(client):
    assignment_id = database.create_assignment('CS101', 'HW', '', None, 100, 'admin')
    login_student(client)
    data = {'file': (io.BytesIO(b'evil'), 'virus.exe')}
    response = client.post(f'/student/assignment/{assignment_id}/submit',
                           data=data, content_type='multipart/form-data',
                           follow_redirects=True)
    assert b'valid file' in response.data
    assert database.get_submission(assignment_id, 'S001') is None


def test_grading_flow(client):
    assignment_id = database.create_assignment('CS101', 'HW', '', None, 100, 'admin')
    database.submit_assignment(assignment_id, 'S001', 'f.txt', 'hw.txt', '')
    submission = database.get_submission(assignment_id, 'S001')

    login_admin(client)
    response = client.post(f'/assignment/{assignment_id}', data={
        'action': 'grade', 'submission_id': str(submission['id']),
        'score': '87.5', 'feedback': 'Nice work',
    }, follow_redirects=True)
    assert b'87.5' in response.data
    graded = database.get_submission(assignment_id, 'S001')
    assert graded['score'] == 87.5
    assert graded['feedback'] == 'Nice work'

    # Score above max is rejected
    response = client.post(f'/assignment/{assignment_id}', data={
        'action': 'grade', 'submission_id': str(submission['id']),
        'score': '150', 'feedback': '',
    }, follow_redirects=True)
    assert database.get_submission(assignment_id, 'S001')['score'] == 87.5


def test_student_cannot_submit_to_other_class_assignment(client):
    assignment_id = database.create_assignment('MATH201', 'Math HW', '', None, 100, 'admin')
    login_student(client)  # S001 is in CS101
    data = {'file': (io.BytesIO(b'x'), 'a.txt')}
    response = client.post(f'/student/assignment/{assignment_id}/submit',
                           data=data, content_type='multipart/form-data',
                           follow_redirects=True)
    assert b'not for your class' in response.data
    assert database.get_submission(assignment_id, 'S001') is None


# ---------- Quizzes ----------

def test_quiz_autograding_and_attempt_limit(client):
    quiz_id = create_quiz()
    quiz = database.get_quiz_by_id(quiz_id, include_answers=True)
    q1, q2 = quiz['questions']

    login_student(client)
    # GET renders the quiz questions
    page = client.get(f'/student/quiz/{quiz_id}/take')
    assert page.status_code == 200
    assert q1['question'].encode() in page.data

    response = client.post(f'/student/quiz/{quiz_id}/take', data={
        f'q_{q1["id"]}': 'Python',   # correct (2 pts)
        f'q_{q2["id"]}': '3',        # wrong (0 pts)
    }, follow_redirects=True)
    assert b'2 / 3' in response.data

    # Attempt limit (max_attempts=1) blocks a second try
    response = client.post(f'/student/quiz/{quiz_id}/take', data={
        f'q_{q1["id"]}': 'Python', f'q_{q2["id"]}': '4',
    }, follow_redirects=True)
    assert b'all your attempts' in response.data
    assert database.get_quiz_attempt_count(quiz_id, 'S001') == 1


def test_quiz_rejects_invalid_answers(client):
    quiz_id = create_quiz()
    quiz = database.get_quiz_by_id(quiz_id, include_answers=True)
    q1, q2 = quiz['questions']
    login_student(client)
    response = client.post(f'/student/quiz/{quiz_id}/take', data={
        f'q_{q1["id"]}': 'NOT_AN_OPTION',
        f'q_{q2["id"]}': '4',
    }, follow_redirects=True)
    assert b'1 / 3' in response.data  # only q2 counts


def test_quiz_answers_hidden_from_students_but_visible_to_staff(client):
    quiz_id = create_quiz()
    login_student(client)
    student_page = client.get(f'/student/quiz/{quiz_id}/take').data
    client.get('/logout')
    login_admin(client)
    staff_page = client.get(f'/quiz/{quiz_id}').data
    # The correct-answer checkmark appears only on the staff view
    assert '✓'.encode() in staff_page
    assert '✓'.encode() not in student_page


def test_create_quiz_validates_questions(client):
    login_admin(client)
    response = client.post('/quizzes', data={
        'course_code': 'CS101', 'title': 'Bad Quiz',
        'duration_minutes': '10', 'max_attempts': '1',
        'questions_json': json.dumps([{'question': '', 'options': ['a'], 'correct_option': 'a'}]),
    }, follow_redirects=True)
    assert b'at least one complete question' in response.data
    assert database.get_quizzes('CS101') == []


# ---------- Gradebook ----------

def test_gradebook_aggregates_grades(client):
    assignment_id = database.create_assignment('CS101', 'HW1', '', None, 100, 'admin')
    database.submit_assignment(assignment_id, 'S001', 'f.txt', 'hw.txt', '')
    submission = database.get_submission(assignment_id, 'S001')
    database.grade_submission(submission['id'], 80, '', 'admin')
    quiz_id = create_quiz()
    database.record_quiz_attempt(quiz_id, 'S001', {}, 3, 3)

    login_admin(client)
    response = client.get('/gradebook?course=CS101')
    assert response.status_code == 200
    assert b'S001' in response.data
    # 80/100 (HW) + 3/3 (quiz) = 83 earned of 103 possible
    assert b'80.6%' in response.data

    csv_response = client.get('/export_grades?course=CS101')
    assert csv_response.status_code == 200
    assert b'S001' in csv_response.data
    assert b'gradebook_CS101.csv' in csv_response.headers['Content-Disposition'].encode()


def test_student_grades_page(client):
    assignment_id = database.create_assignment('CS101', 'HW1', '', None, 100, 'admin')
    database.submit_assignment(assignment_id, 'S001', 'f.txt', 'hw.txt', '')
    submission = database.get_submission(assignment_id, 'S001')
    database.grade_submission(submission['id'], 90, 'Great job', 'admin')

    login_student(client)
    response = client.get('/student/grades')
    assert response.status_code == 200
    assert b'HW1' in response.data
    assert b'90' in response.data
    assert b'Great job' in response.data
    assert b'90.0%' in response.data
