"""Fraud detection and prevention utilities for attendance tracking"""

import math
from database import get_conn
from datetime import datetime, timedelta


def get_fraud_warnings(student_id, course_code, date_str):
    """
    Check for potential fraud indicators for an attendance record.
    Returns a list of warnings.
    """
    warnings = []
    conn = get_conn()
    c = conn.cursor()
    
    # Get the attendance record
    c.execute("""SELECT fraud_flags, latitude, longitude, student_ip, device_fingerprint, time
                 FROM attendance 
                 WHERE student_id=? AND course_code=? AND date=?""", 
              (student_id, course_code, date_str))
    row = c.fetchone()
    
    if row:
        fraud_flags, lat, lon, ip, fingerprint, time_str = row
        
        # Parse fraud flags
        if fraud_flags:
            flags = fraud_flags.split('|')
            if "duplicate_attendance_on_same_date" in flags:
                warnings.append({
                    'level': 'warning',
                    'message': 'Student marked attendance more than once on this date',
                    'type': 'duplicate_entry'
                })
            if "ip_mismatch" in flags:
                warnings.append({
                    'level': 'warning',
                    'message': 'Student marked attendance from a different network than the instructor',
                    'type': 'ip_mismatch'
                })
        
        # Get session info for location comparison
        c.execute("""SELECT creator_latitude, creator_longitude
                     FROM attendance_sessions
                     WHERE course_code=? AND date=? AND active=1
                     ORDER BY created_at DESC LIMIT 1""",
                  (course_code, date_str))
        session_row = c.fetchone()
        
        if session_row and session_row[0] and session_row[1] and lat and lon:
            creator_lat, creator_lon = session_row[0], session_row[1]
            distance = calculate_distance(creator_lat, creator_lon, lat, lon)
            
            if distance > 1.0:  # More than 1 km away
                warnings.append({
                    'level': 'warning',
                    'message': f'Student marked attendance {distance:.2f} km away from instructor location',
                    'type': 'location_mismatch',
                    'distance_km': distance
                })
    
    conn.close()
    return warnings


def check_recent_attendance(student_id, course_code, minutes=5):
    """
    Check if the student recently marked attendance (within X minutes).
    Returns the time of the recent attendance or None.
    """
    conn = get_conn()
    c = conn.cursor()
    
    now = datetime.now()
    time_ago = (now - timedelta(minutes=minutes)).isoformat()
    
    c.execute("""SELECT time
                 FROM attendance
                 WHERE student_id=? AND course_code=? AND time > ?""",
              (student_id, course_code, time_ago))
    row = c.fetchone()
    conn.close()
    
    return row[0] if row else None


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two geographic coordinates in kilometers.
    Uses the Haversine formula.
    """
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


def generate_device_fingerprint(request):
    """
    Generate a simple device fingerprint from request headers.
    Returns a hash of user-agent and accepted languages.
    """
    import hashlib
    
    user_agent = request.headers.get('User-Agent', 'unknown')
    accept_language = request.headers.get('Accept-Language', 'unknown')
    
    fingerprint_string = f"{user_agent}|{accept_language}"
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()[:16]


def check_ip_consistency(student_id, new_ip):
    """
    Check if the student's IP is consistent with their previous login sessions.
    Returns True if consistent, False if inconsistent.
    """
    conn = get_conn()
    c = conn.cursor()
    
    # Get the most recent attendance IP for this student
    c.execute("""SELECT student_ip
                 FROM attendance
                 WHERE student_id=?
                 ORDER BY date DESC, time DESC
                 LIMIT 1""", (student_id,))
    row = c.fetchone()
    conn.close()
    
    if not row or not row[0]:
        return True  # First time or no IP recorded
    
    return row[0] == new_ip


def log_fraud_attempt(student_id, course_code, fraud_type, details=None):
    """
    Log a potential fraud attempt for admin review.
    """
    conn = get_conn()
    c = conn.cursor()
    
    try:
        # Try to insert into a fraud_attempts table if it exists
        c.execute("""INSERT INTO fraud_attempts 
                     (student_id, course_code, fraud_type, details, detected_at)
                     VALUES (?, ?, ?, ?, ?)""",
                  (student_id, course_code, fraud_type, details, datetime.now().isoformat()))
        conn.commit()
    except Exception as e:
        # Table may not exist yet
        print(f"Could not log fraud attempt: {e}")
    finally:
        conn.close()
