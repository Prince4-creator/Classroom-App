# Quick Reference Guide

## 🚀 Getting Started (5 minutes)

```bash
# Setup
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Create .env
echo FLASK_ENV=development > .env
echo SECRET_KEY=dev-key-123 >> .env

# Run
python app.py
# Open http://localhost:5000
```

## 📋 Default Credentials (Development Only)

| Role | Username | Password |
|------|----------|----------|
| Admin | `admin` | `admin123` |
| Student | `S001` | `student123` |

## 🔑 Environment Variables

```env
# Required
FLASK_ENV=production
SECRET_KEY=<min-32-random-chars>

# Optional - Email
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com

# Optional - Database
DATABASE_URL=postgresql://...
SUPABASE_URL=https://...
SUPABASE_KEY=...

# Optional - Features
PUBLIC_URL=https://your-domain.com
DEBUG_SECRET=debug-key
```

## 📁 Project Structure

```
classroom_app/
├── app.py                 # Flask app & routes
├── database.py            # Database abstraction
├── utils.py              # Utilities & validation
├── requirements.txt      # Dependencies
├── templates/            # HTML templates
├── uploads/              # File uploads
├── classroom.db          # SQLite database
├── .env                  # Environment config
└── README.md            # Full documentation
```

## 🔧 Common Commands

```bash
# Generate SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# Test app loading
python -c "from app import app; print('OK')"

# List all routes
python app.py
# Then visit http://localhost:5000/debug_routes

# Database initialization
python -c "from database import init_db; init_db()"

# Run with Flask CLI
export FLASK_APP=app.py
flask run

# Production WSGI server
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

## 🗂️ Database Models

### Users (Admin/Instructor)
```sql
users: id, username, password_hash, role
```

### Students
```sql
students: id, student_id, name, password_hash, class_code, email, status
```

### Courses
```sql
courses: id, course_code, course_name
```

### Attendance
```sql
attendance: id, student_id, course_code, date, time, status, latitude, longitude
```

### Attendance Sessions
```sql
attendance_sessions: id, course_code, date, token, created_at, expires_at, active
```

### Polls & Votes
```sql
polls: id, course_code, question, options, created_at, active
votes: id, poll_id, student_id, answer, voted_at
```

### Announcements
```sql
announcements: id, title, content, course_code, announcement_type, attachments, created_at, created_by
```

## 🛣️ Key Routes

### Student Routes
| Route | Method | Purpose |
|-------|--------|---------|
| `/student/login` | GET/POST | Student login |
| `/student/register` | GET/POST | Student registration |
| `/student/dashboard` | GET | Dashboard |
| `/student/mark_attendance` | GET/POST | Mark attendance |

### Admin Routes
| Route | Method | Purpose |
|-------|--------|---------|
| `/admin` | GET | Admin dashboard |
| `/admin/students` | GET/POST | Manage students |
| `/admin/courses` | GET/POST | Manage courses |
| `/admin/announcements` | GET/POST | Post announcements |

## ✅ Validation Functions (from utils.py)

```python
from utils import (
    validate_email,           # Email format
    validate_student_id,      # Student ID format
    validate_course_code,     # Course code format
    validate_username,        # Username format
    sanitize_filename,        # Safe filename
    log_action,              # Audit logging
)

# Example usage
if not validate_email(email):
    flash('Invalid email', 'error')

if not validate_student_id(student_id):
    flash('Invalid student ID', 'error')
```

## 🔐 Security Checklist

Before Production:
- [ ] Change default admin password
- [ ] Set strong `SECRET_KEY`
- [ ] Configure SMTP for email
- [ ] Enable HTTPS only
- [ ] Set `FLASK_ENV=production`
- [ ] Use PostgreSQL (not SQLite)
- [ ] Add CSRF tokens to forms
- [ ] Set up monitoring/logging
- [ ] Run security audit
- [ ] Test all auth flows

## 🐛 Debugging

### Enable Debug Mode (Development Only)
```python
# In app.py, last line:
app.run(debug=True, host='0.0.0.0')
```

### View All Routes
```
http://localhost:5000/debug_routes
```

### Check Database
```python
python -c "
from database import *
print('Users:', get_all_users())
print('Students:', get_all_students())
print('Courses:', get_all_courses())
"
```

### Enable Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.debug('Your message')
```

## 📚 Important Functions

### Authentication
```python
verify_user(username, password)        # Admin/Instructor login
verify_student(student_id, password)   # Student login
add_user(username, password, role)     # Create user
add_student(student_id, name, ...)     # Create student
```

### Attendance
```python
mark_attendance(student_id, course_code, date, time)
get_attendance_by_date_and_course(date, course_code)
create_attendance_session(course_code, date)
get_attendance_session_by_token(token)
```

### Announcements
```python
add_announcement(title, content, course_code, ...)
get_announcements(course_code=None)
delete_announcement(announcement_id)
```

### Email
```python
send_email(subject, body, recipients)  # Returns True/False
```

## 🚨 Common Issues & Fixes

### "Database locked" Error
```python
# SQLite issue when multiple processes access DB
# Solution: Use PostgreSQL for production
```

### SMTP Connection Failed
```python
# Check:
# 1. SMTP_SERVER is correct
# 2. SMTP_PORT matches (587=TLS, 465=SSL)
# 3. Credentials are correct
# 4. Gmail: Use app password, not regular password
# 5. Firewall allows SMTP port
```

### Session Expires Too Quickly
```python
# Change in app.py:
'PERMANENT_SESSION_LIFETIME': timedelta(hours=1)  # Default 30 min
```

### QR Code Not Generating
```python
# Ensure PIL and qrcode installed:
pip install Pillow qrcode
# Check write permissions on uploads/ directory
```

## 📞 Support Resources

- **Setup Issues**: Read `README.md`
- **Security Questions**: Read `SECURITY.md`
- **Implementation Details**: Read `BUG_REPORT.md`
- **Next Steps**: Read `ACTION_ITEMS.md`
- **Code Examples**: Check `utils.py`

## 🎯 Performance Tips

1. **Use PostgreSQL** for production (not SQLite)
2. **Add database indexes** on frequently queried columns
3. **Cache announcements** with Redis
4. **Use Supabase** for file storage (scales better)
5. **Enable gzip** compression in web server
6. **Monitor slow queries** in logs

## 📝 Code Style

Follow PEP 8:
```python
# Good
def validate_student_id(student_id):
    """Validate student ID format."""
    pattern = r'^[a-zA-Z0-9_-]{1,20}$'
    return re.match(pattern, student_id) is not None

# Bad
def validate(s):
    return True
```

## 🔄 Workflow

### Adding a New Feature
1. Create route in `app.py`
2. Add database functions in `database.py`
3. Add validation in `utils.py`
4. Create template in `templates/`
5. Test thoroughly
6. Update documentation
7. Commit to version control

### Debugging Tips
1. Use `print()` or `logger.debug()`
2. Check browser DevTools
3. Review network requests
4. Check Flask debug toolbar
5. Look at server logs
6. Use `pdb` for breakpoints

```python
import pdb; pdb.set_trace()  # Breakpoint
```

## 📊 Monitoring

### Production Monitoring Checklist
- [ ] Error logging (Sentry/similar)
- [ ] Performance monitoring (New Relic/similar)
- [ ] Uptime monitoring (StatusPage/similar)
- [ ] Database backups (automated)
- [ ] Log aggregation (ELK/similar)
- [ ] Security scanning (OWASP/similar)

---

**Last Updated**: August 30, 2026  
**Status**: Current  
**For Full Details**: See comprehensive documentation files
