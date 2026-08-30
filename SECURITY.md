# Security Guidelines

## Overview

This document outlines security considerations and best practices for the Classroom Management App.

## Current Security Implementations

### 1. Authentication & Authorization
- ✓ Password hashing using Werkzeug security (PBKDF2 with SHA-256)
- ✓ Role-based access control (Admin, Instructor, Student)
- ✓ Brute-force protection (5 failed attempts → 15 min lockout)
- ✓ Session timeout (30 minutes)
- ✓ Authentication logging with IP tracking

### 2. Session Security
- ✓ Secure cookies (`SESSION_COOKIE_SECURE=True`)
- ✓ HttpOnly cookies (`SESSION_COOKIE_HTTPONLY=True`)
- ✓ SameSite protection (`SESSION_COOKIE_SAMESITE=Lax`)
- ✓ Session refresh on each request

### 3. Input Validation
- ✓ Email format validation
- ✓ Student ID format validation (alphanumeric, max 20 chars)
- ✓ Course code format validation
- ✓ Username format validation
- ✓ File upload validation (extension whitelist)

### 4. SQL Injection Prevention
- ✓ Parameterized queries throughout
- ✓ No string concatenation in SQL
- ✓ Cursor placeholder support (? for SQLite, %s for PostgreSQL)

### 5. XSS (Cross-Site Scripting) Prevention
- ✓ Jinja2 auto-escaping enabled
- ✓ User input sanitized before display
- ✓ Filename sanitization for file uploads

### 6. Security Headers
```
Content-Security-Policy: default-src 'self'; ...
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Permissions-Policy: geolocation=()
```

### 7. File Security
- ✓ File upload extension whitelist
- ✓ Filename sanitization (remove path traversal)
- ✓ Secure file storage (Supabase or local with restrictions)

### 8. Logging & Audit Trail
- ✓ Authentication events logged
- ✓ User action logging
- ✓ IP address tracking
- ✓ Failed attempt counting

## Recommended Security Enhancements

### Priority 1 (Critical)
1. **Required SECRET_KEY in Production**
   - ✓ Already implemented: raises error if missing in production
   - Ensures no default keys in production

2. **CSRF Protection**
   - Status: Flask-WTF dependency added, needs template integration
   - Action: Add `{{ csrf_token() }}` to all forms
   - Location: `templates/*.html`

3. **Database Connection Security**
   - Use SSL/TLS for PostgreSQL connections
   - Status: Partial (Supabase uses `sslmode='require'`)
   - Ensure all PG connections use SSL

4. **Password Policy**
   - Implement minimum password requirements:
     - Minimum 8 characters
     - Mix of uppercase, lowercase, numbers
   - Add password strength meter on registration

### Priority 2 (High)
5. **Two-Factor Authentication (2FA)**
   - Recommended for admin accounts
   - Use TOTP (Time-based One-Time Password) with pyotp
   - Example implementation:
     ```python
     import pyotp
     secret = pyotp.random_base32()
     totp = pyotp.TOTP(secret)
     qr_code_url = totp.provisioning_uri(user_email, 'ClassroomApp')
     ```

6. **Rate Limiting**
   - Use Flask-Limiter for API endpoints
   - Example:
     ```python
     from flask_limiter import Limiter
     limiter = Limiter(app)
     @app.route('/api/login', methods=['POST'])
     @limiter.limit("5 per minute")
     def login(): ...
     ```

7. **API Key Management**
   - Implement API keys for admin API access
   - Hash stored API keys
   - Rotate keys regularly

8. **Secrets Management**
   - Use environment variables for all secrets
   - Consider using AWS Secrets Manager or similar
   - Never commit `.env` to version control

### Priority 3 (Medium)
9. **Logging & Monitoring**
   - Implement structured logging (JSON format)
   - Log all admin actions
   - Set up alerts for suspicious activity
   - Monitor failed login attempts

10. **Data Encryption**
    - Encrypt sensitive data at rest (email addresses, phone numbers)
    - Use SQLAlchemy encryption extensions if storing more sensitive data
    - Example: `cryptography` library with Fernet

11. **Session Management**
    - Add logout from all devices feature
    - Session binding to user agent/IP address
    - Active session management dashboard

12. **Backup & Recovery**
    - Regular automated backups (daily)
    - Test backup restoration procedures
    - Secure backup storage

### Priority 4 (Nice to Have)
13. **Security Testing**
    - Unit tests for validation functions
    - Integration tests for authentication
    - Penetration testing recommendations

14. **Dependency Management**
    - Regular dependency updates
    - Use `pip-audit` to check for vulnerabilities
    - Pin versions to specific commits if needed

15. **OWASP Compliance**
    - Follow OWASP Top 10 recommendations
    - Use OWASP Zap for security scanning
    - Regular security audits

## Development Best Practices

### Before Deployment
- [ ] Change default admin credentials
- [ ] Set strong `SECRET_KEY` (min 32 random chars)
- [ ] Configure HTTPS only (use SSL certificate)
- [ ] Enable production database (PostgreSQL)
- [ ] Configure SMTP for email notifications
- [ ] Test all authentication flows
- [ ] Run security checks (OWASP Zap, pip-audit)
- [ ] Review logs for errors

### Environment Setup
```bash
# Generate strong SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# Check dependencies for vulnerabilities
pip install pip-audit
pip-audit

# Run security headers check
pip install flask-talisman
```

### Code Review Checklist
- [ ] No hardcoded secrets or credentials
- [ ] Parameterized SQL queries used
- [ ] User input validated
- [ ] Error messages don't expose system details
- [ ] File uploads are safe
- [ ] Authentication required for sensitive operations
- [ ] Proper error handling (no unhandled exceptions)

## Security Headers Configuration

The app includes the following security headers:

```python
@app.after_request
def apply_security_headers(response):
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net; "
        "img-src 'self' https: data:;"
    )
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'geolocation=()'
    return response
```

## Incident Response

If a security issue is discovered:

1. **Immediate Actions**
   - Disable affected accounts if compromised
   - Change all credentials
   - Review access logs
   - Check for unauthorized data access

2. **Investigation**
   - Determine scope of compromise
   - Identify root cause
   - Document timeline

3. **Remediation**
   - Patch vulnerability
   - Deploy fix
   - Monitor for exploitation

4. **Post-Incident**
   - Conduct security review
   - Update documentation
   - Implement preventive measures

## Reporting Security Vulnerabilities

If you discover a security vulnerability, please:
1. Do NOT post it publicly
2. Email security team with details
3. Include steps to reproduce
4. Allow time for patch before disclosure

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/2.3.x/security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [CWE/SANS Top 25](https://cwe.mitre.org/top25/)

## Compliance

Ensure compliance with:
- GDPR (if storing EU resident data)
- FERPA (if US educational institution)
- Local data protection regulations
- Institutional security policies

## Questions?

For security questions, contact: [security-contact]
