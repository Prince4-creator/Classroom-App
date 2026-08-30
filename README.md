# Classroom Management App

A comprehensive Flask-based classroom management system for tracking attendance, managing students, creating polls, and sending announcements.

## Features

- **User Authentication**: Admin, Instructor, and Student login with brute-force protection
- **Attendance Tracking**: Mark attendance manually or via QR code token sessions
- **Polls & Voting**: Create and manage polls with real-time results
- **Announcements**: Post announcements with optional file attachments and email notifications
- **Student Registration**: Self-service student registration with admin approval
- **Magic Login**: Passwordless login tokens for students via QR codes
- **Email Integration**: SMTP-based email notifications (Gmail, Outlook, custom SMTP)
- **File Storage**: Local uploads or Supabase cloud storage
- **Security**: Password hashing, secure cookies, CSRF protection, input validation, authentication logging
- **Role-Based Access Control**: Different permissions for admins, instructors, and students
- **Database Support**: SQLite (development) or PostgreSQL/Supabase (production)

## Prerequisites

- Python 3.7+
- pip
- (Optional) PostgreSQL with Supabase for production use

## Quick Start

### Local Development

1. **Clone/Download the Repository**
   ```bash
   cd classroom_app
   ```

2. **Create Virtual Environment**
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Create `.env` File**
   ```bash
   # Copy .env.example or create .env with minimal config:
   FLASK_ENV=development
   SECRET_KEY=dev-key-change-in-production
   ```

5. **Run Application**
   ```bash
   python app.py
   ```
   Access at `http://localhost:5000`

**Default Credentials**:
- Admin: username=`admin`, password=`admin123`
- Student: ID=`S001`, password=`student123`

## Deployment

### Supabase + Vercel (Production)

Configure environment variables in Vercel dashboard:

| Variable | Value |
|----------|-------|
| `SECRET_KEY` | Strong random string (min 32 chars) |
| `DATABASE_URL` | Supabase Postgres connection string |
| `SUPABASE_URL` | `https://your-project.supabase.co` |
| `SUPABASE_KEY` | Supabase anon or service role key |
| `SUPABASE_BUCKET` | `attachments` (or your bucket name) |
| `SMTP_*` | Email configuration (optional) |

### Notes

- Local SQLite used when `DATABASE_URL` is not set
- Supabase attachments upload to Storage when configured
- Database schema auto-created via `init_db()` on startup

## Environment Configuration

Create `.env` file (use `.env.example` as template):

```env
# Flask
FLASK_ENV=production
SECRET_KEY=your-super-secret-key-here-min-32-chars

# Database (Optional - defaults to SQLite)
DATABASE_URL=postgresql://user:password@host:port/database
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_BUCKET=attachments

# Email Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com

# Public URL (for QR codes)
PUBLIC_URL=https://your-domain.com

# Debug (development only)
DEBUG_SECRET=your-debug-secret
```

### Email Setup (Gmail Example)

1. Enable 2-Factor Authentication
2. Generate App Password: https://myaccount.google.com/apppasswords
3. Use App Password in `SMTP_PASSWORD`

## Database

### SQLite (Default)
- File: `classroom.db`
- Best for: Development, small deployments
- No setup required

### PostgreSQL/Supabase (Production)
- Set `DATABASE_URL` environment variable
- Better for: Multiple users, cloud deployment
- Scalable and reliable

**Migration SQLite → PostgreSQL**:
1. Set up PostgreSQL/Supabase
2. Set `DATABASE_URL`
3. Run app (auto-creates schema)
4. Migrate existing data manually if needed

## File Uploads

- **Local**: Saved to `uploads/` directory
- **Supabase**: Cloud storage (set `SUPABASE_*` variables)

## API Routes

### Auth Routes
- `GET/POST /` - Home / Login choice
- `GET/POST /login` - Admin login
- `GET/POST /student/login` - Student login
- `GET/POST /student/register` - Register student
- `GET /logout` - Logout

### Student Routes
- `GET /student/dashboard` - Dashboard
- `GET /student/assignments` - View assignments
- `GET/POST /student/mark_attendance` - Mark attendance
- `GET /student/view_attendance` - View records
- `GET/POST /poll` - Vote on polls

### Admin Routes
- `GET /admin` - Admin dashboard
- `GET/POST /admin/students` - Manage students
- `GET/POST /admin/courses` - Manage courses
- `GET/POST /admin/announcements` - Post announcements
- `GET/POST /admin/email_test` - Test email

### Attendance Routes
- `GET/POST /attendance/session` - Create session
- `GET /attendance/general_qr` - General QR code
- `GET /manage_attendance` - Manage records
- `GET /export_attendance` - Export to CSV

## Security Features

✓ Password hashing (Werkzeug)  
✓ Session security (Secure, HttpOnly, SameSite cookies)  
✓ Brute-force protection (5 attempts → 15 min lockout)  
✓ Input validation (email, student ID, course code)  
✓ SQL injection prevention (parameterized queries)  
✓ XSS protection (Jinja2 auto-escaping)  
✓ Security headers (CSP, X-Frame-Options, etc.)  
✓ Authentication logging & audit trail  
✓ File upload validation  
✓ CSRF protection (Flask-WTF)  

## Troubleshooting

### Database Issues
```bash
# Check connection:
python -c "from database import init_db; init_db()"
```

### Email Not Sending
- Verify SMTP credentials
- Gmail: Use App Password (not regular password)
- Check firewall (port 587/465 open)
- Review logs for errors

### QR Code Issues
- Ensure `qrcode` and `Pillow` installed
- Check write permissions on `uploads/`

### Session/Login Issues
- Clear browser cookies
- Verify `SECRET_KEY` is set
- Check `FLASK_ENV`

## Performance Optimization

- Add database indexes on frequently queried columns
- Use Supabase connection pooler for PostgreSQL
- Enable gzip compression
- Cache announcements/courses
- Use CDN for static files

## Future Enhancements

- [ ] Two-Factor Authentication (2FA)
- [ ] Real-time notifications (WebSockets)
- [ ] Mobile app integration
- [ ] Advanced analytics dashboard
- [ ] Bulk import/export students
- [ ] Calendar integration
- [ ] Gradebook features
- [ ] Automated backups

## Development

### Code Style
- Follow PEP 8
- Use descriptive names
- Add docstrings

### Utilities
- `utils.py`: Validation functions, logging, decorators
- Database operations in `database.py`
- Routes in `app.py`

## License

[Specify your license here]

## Support

For issues or questions, please contact the development team.

### Useful commands

```bash
python -m py_compile app.py database.py scripts/list_students.py
python app.py
```

## Cleanup

- `.env` is ignored by `.gitignore`
- `classroom.db` is ignored for local development
- `uploads/` is ignored for local attachment storage
