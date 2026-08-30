"""Utility functions for the Classroom App"""

import re
import logging
import time
from collections import defaultdict
from functools import wraps
from flask import session, redirect, url_for, flash

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Very small in-memory rate limiter used for repeated auth attempts.
# It is intentionally lightweight and safe for local/dev use; production
# deployments should move to a shared limiter backend.
_RATE_LIMIT_STORAGE = defaultdict(list)


def check_rate_limit(key, limit=5, window_seconds=900):
    """Return True when the key is within the configured request budget."""
    now = time.time()
    window_start = now - window_seconds
    attempts = [ts for ts in _RATE_LIMIT_STORAGE.get(key, []) if ts >= window_start]
    attempts.append(now)
    _RATE_LIMIT_STORAGE[key] = attempts
    return len(attempts) <= limit


def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_student_id(student_id):
    """Validate student ID format (alphanumeric, 1-20 chars)"""
    pattern = r'^[a-zA-Z0-9_-]{1,20}$'
    return re.match(pattern, student_id) is not None


def validate_course_code(course_code):
    """Validate course code format (alphanumeric, underscores, hyphens)"""
    pattern = r'^[a-zA-Z0-9_-]{1,20}$'
    return re.match(pattern, course_code) is not None


def validate_username(username):
    """Validate username format (alphanumeric, underscores, 3-20 chars)"""
    pattern = r'^[a-zA-Z0-9_]{3,20}$'
    return re.match(pattern, username) is not None


def validate_password(password, min_length=8):
    """Validate a password has a safe minimum length."""
    return isinstance(password, str) and len(password.strip()) >= min_length


def validate_name(name, min_length=2, max_length=80):
    """Validate a human name."""
    if not isinstance(name, str):
        return False
    clean = name.strip()
    return min_length <= len(clean) <= max_length and bool(re.search(r'[A-Za-z]', clean))


def log_action(action, user, details='', success=True):
    """Log important actions for audit trail"""
    status = 'SUCCESS' if success else 'FAILED'
    logger.info(f"[{status}] User: {user}, Action: {action}, Details: {details}")


def require_role(*roles):
    """Decorator to check user role before accessing a route"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if 'user' not in session:
                flash('Please log in first.', 'error')
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('You do not have permission to access this page.', 'error')
                logger.warning(f"Unauthorized access attempt by {session.get('user')} to {func.__name__}")
                return redirect(url_for('dashboard'))
            return func(*args, **kwargs)
        return wrapper
    return decorator


def require_student_role(func):
    """Decorator to check if user is a student"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if 'student_id' not in session:
            flash('Please log in as a student first.', 'error')
            return redirect(url_for('student_login'))
        return func(*args, **kwargs)
    return wrapper


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


def generate_device_fingerprint(request):
    """
    Generate a simple device fingerprint from request headers for fraud detection.
    Returns a hash of user-agent and accepted languages.
    """
    import hashlib
    
    user_agent = request.headers.get('User-Agent', 'unknown')
    accept_language = request.headers.get('Accept-Language', 'unknown')
    
    fingerprint_string = f"{user_agent}|{accept_language}"
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()[:16]


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two geographic coordinates in kilometers.
    Uses the Haversine formula.
    """
    import math
    
    if not all([lat1, lon1, lat2, lon2]):
        return 0
    
    R = 6371  # Earth's radius in kilometers
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def check_fraud_warnings(student_id, course_code, date_str, new_lat=None, new_lon=None, new_ip=None):
    """
    Check for potential fraud indicators and return warnings.
    """
    from database import get_conn
    from datetime import datetime, timedelta
    
    warnings = []
    conn = get_conn()
    c = conn.cursor()
    
    # Check if student marked attendance recently (within 5 minutes)
    now = datetime.now()
    time_ago = (now - timedelta(minutes=5)).isoformat()
    
    c.execute("""SELECT time FROM attendance 
                 WHERE student_id=? AND course_code=? AND date=? AND time > ?""",
              (student_id, course_code, date_str, time_ago))
    recent = c.fetchone()
    if recent:
        warnings.append('Student recently marked attendance - possible duplicate attempt')
    
    # Check IP consistency
    c.execute("""SELECT creator_ip FROM attendance_sessions 
                 WHERE course_code=? AND date=? AND active=1 
                 ORDER BY created_at DESC LIMIT 1""",
              (course_code, date_str))
    session = c.fetchone()
    
    if session and session[0] and new_ip and session[0] != new_ip:
        warnings.append('Student is on a different network than the instructor')
    
    # Check location consistency
    if session:
        c.execute("""SELECT creator_latitude, creator_longitude FROM attendance_sessions 
                     WHERE course_code=? AND date=? AND active=1 
                     ORDER BY created_at DESC LIMIT 1""",
                  (course_code, date_str))
        loc = c.fetchone()
        if loc and loc[0] and loc[1] and new_lat and new_lon:
            distance = calculate_distance(loc[0], loc[1], new_lat, new_lon)
            if distance > 1.0:  # More than 1 km away
                warnings.append(f'Student is {distance:.2f} km away from instructor location')
    
    conn.close()
    return warnings


def sanitize_filename(filename, max_length=50):
    """Sanitize filename to prevent directory traversal attacks"""
    # Remove any path separators and null bytes
    filename = filename.replace('\\', '').replace('/', '').replace('\x00', '')
    
    # Keep only safe characters
    safe_filename = re.sub(r'[^a-zA-Z0-9._\-]', '', filename)
    
    # Limit length
    if len(safe_filename) > max_length:
        name, ext = safe_filename.rsplit('.', 1) if '.' in safe_filename else (safe_filename, '')
        safe_filename = name[:max_length-len(ext)-1] + '.' + ext if ext else safe_filename[:max_length]
    
    return safe_filename or 'file'


def format_error_response(error_msg, status_code=400):
    """Format error response for consistency"""
    return {
        'error': error_msg,
        'status': status_code
    }, status_code


def success_response(data, message='Success', status_code=200):
    """Format success response for consistency"""
    return {
        'success': True,
        'message': message,
        'data': data
    }, status_code
