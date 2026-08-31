import pytest

from app import app, STAFF_LOGIN_PATH
from utils import check_rate_limit, validate_email, validate_student_id


@pytest.fixture
def client():
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        yield client


def test_validation_helpers():
    assert validate_email('student@example.com') is True
    assert validate_email('bad-email') is False
    assert validate_student_id('STU001') is True
    assert validate_student_id('bad id') is False


def test_rate_limit_helper_blocks_after_limit():
    key = 'phase2-test-key'
    assert check_rate_limit(key, 2, 60) is True
    assert check_rate_limit(key, 2, 60) is True
    assert check_rate_limit(key, 2, 60) is False


def test_admin_login_rejects_invalid_username(client):
    response = client.post(STAFF_LOGIN_PATH, data={'username': 'ab', 'password': 'secret123'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Invalid username format' in response.data


def test_student_register_rejects_invalid_student_id(client):
    response = client.post(
        '/student/register',
        data={
            'student_id': 'bad id',
            'name': 'Test User',
            'password': 'secret123',
            'class_code': 'CS101',
            'email': 'student@example.com',
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b'Invalid student ID format' in response.data
