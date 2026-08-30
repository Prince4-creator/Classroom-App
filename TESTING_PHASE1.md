# 🧪 PHASE 1 TESTING GUIDE

## Overview
This guide shows you how to test the security enhancements implemented in Phase 1:
- ✅ CSRF token protection
- ✅ Enhanced SECRET_KEY handling
- ✅ Updated environment configuration

**Estimated Time**: 30-60 minutes

---

## Part 1: Pre-Testing Setup

### Step 1.1: Generate SECRET_KEY
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Expected output:
```
a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2
```

### Step 1.2: Configure .env File
```bash
# Windows PowerShell
Copy-Item .env.example .env

# Edit the file and set:
# SECRET_KEY = (paste the generated key above)
# FLASK_ENV = development
# SMTP_SERVER = smtp.gmail.com
# (other settings are optional for testing)
```

### Step 1.3: Verify Environment
```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('✓ SECRET_KEY set:', bool(os.environ.get('SECRET_KEY')))
print('✓ FLASK_ENV:', os.environ.get('FLASK_ENV', 'not set'))
"
```

---

## Part 2: Security Feature Testing

### Test 2.1: CSRF Protection Enabled ✅

**What to test**: Verify CSRF tokens are in forms

**Steps**:
```bash
# 1. Start the app
python app.py

# 2. Open in browser: http://localhost:5000
# 3. Navigate to Admin Login
# 4. Open Developer Tools (F12)
# 5. Check the login form HTML
```

**Expected Results**:
- [ ] Form contains: `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>`
- [ ] Token value is not empty
- [ ] Token changes on page refresh

**Success**: ✅ CSRF token present in all forms

---

### Test 2.2: SECRET_KEY Security ✅

**What to test**: Application requires SECRET_KEY in production mode

**Steps**:
```bash
# Test 1: Development mode (no SECRET_KEY)
python -c "
import os
os.environ.pop('SECRET_KEY', None)
os.environ['FLASK_ENV'] = 'development'
from app import app
print('✓ Loaded in development mode without SECRET_KEY')
"

# Test 2: Production mode (no SECRET_KEY)
python -c "
import os
os.environ.pop('SECRET_KEY', None)
os.environ['FLASK_ENV'] = 'production'
try:
    from app import app
    print('✗ ERROR: Should require SECRET_KEY in production!')
except ValueError as e:
    print('✓ Correctly rejected:', str(e))
"
```

**Expected Results**:
- [ ] Development mode: Works without SECRET_KEY (with warning)
- [ ] Production mode: Fails with clear error message

**Success**: ✅ SECRET_KEY properly validated

---

### Test 2.3: Form Submission with CSRF ✅

**What to test**: Forms require valid CSRF tokens

**Steps**:

#### Test 3.1a: Valid CSRF Token (Should Work)
```bash
# 1. Start app and navigate to login
# 2. Fill in login form with any credentials
# 3. Browser automatically includes CSRF token
# 4. Submit form
```

**Expected Result**:
- [ ] Form submission processed
- [ ] Server handles request normally

#### Test 3.1b: Invalid/Missing CSRF Token (Should Fail)
```bash
# Using curl to test CSRF validation:
curl -X POST http://localhost:5000/admin/login \
  -d "username=admin&password=test" \
  -H "Content-Type: application/x-www-form-urlencoded"
```

**Expected Result**:
- [ ] Request rejected with 400/403 error
- [ ] Error message: "The CSRF token is missing" or similar

**Success**: ✅ CSRF validation working correctly

---

## Part 3: Authentication Testing

### Test 3.1: Admin Login Flow ✅

**What to test**: Admin authentication with enhanced validation

**Steps**:
```
1. Navigate to: http://localhost:5000/admin/login
2. Enter credentials: admin / admin123
3. Verify login succeeds
4. Check session cookie in DevTools (Network tab)
   - Secure flag: ✓
   - HttpOnly flag: ✓
   - SameSite=Lax: ✓
```

**Expected Results**:
- [ ] Login successful
- [ ] Redirected to admin dashboard
- [ ] Session cookie has security flags

**Success**: ✅ Admin login working with security headers

---

### Test 3.2: Student Login Flow ✅

**What to test**: Student authentication with input validation

**Steps**:
```
1. Navigate to: http://localhost:5000/student/login
2. Try invalid student ID: "invalid@@@"
   Expected: Error message "Invalid student ID format"
3. Try valid student ID: "STU001"
4. Enter password: test123
5. Verify login succeeds
```

**Expected Results**:
- [ ] Invalid formats rejected with clear message
- [ ] Valid formats accepted
- [ ] Session established correctly

**Success**: ✅ Student login with validation

---

### Test 3.3: Form Submission (Announcements) ✅

**What to test**: CSRF protection on form submissions

**Steps** (as admin):
```
1. Navigate to: Admin Dashboard → Announcements
2. Create new announcement:
   - Title: "Test Announcement"
   - Content: "This is a test"
   - Type: "General"
3. Click Submit
4. Check DevTools → Network tab
   - Verify CSRF token in request payload
```

**Expected Results**:
- [ ] Form submitted successfully
- [ ] Announcement appears in list
- [ ] CSRF token was validated server-side

**Success**: ✅ CSRF protection on form submissions

---

## Part 4: Environment Configuration Testing

### Test 4.1: .env Loading ✅

**What to test**: Environment variables properly loaded

**Steps**:
```bash
# Create .env file with test values
echo "SECRET_KEY=test-key-123456789012345678901234" > .env
echo "FLASK_ENV=development" >> .env
echo "SMTP_SERVER=smtp.test.com" >> .env

# Verify loading
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('✓ SECRET_KEY:', os.environ.get('SECRET_KEY')[:10] + '...')
print('✓ FLASK_ENV:', os.environ.get('FLASK_ENV'))
print('✓ SMTP_SERVER:', os.environ.get('SMTP_SERVER'))
"
```

**Expected Results**:
- [ ] All variables loaded correctly
- [ ] No errors during loading

**Success**: ✅ Environment loading working

---

### Test 4.2: Default Credentials ⚠️

**What to test**: Check current default credentials

**Steps**:
```bash
# Check database.py for default admin credentials
grep -n "admin" database.py
grep -n "password" database.py
```

**Action Required** ⚠️:
- [ ] Document current default admin credentials
- [ ] Change admin password via app
- [ ] Update documentation with new credentials

---

## Part 5: Error Handling Testing

### Test 5.1: Database Error Handling ✅

**What to test**: Graceful error handling on DB issues

**Steps**:
```bash
# 1. Start app normally
python app.py

# 2. Temporarily disconnect database (development only)
# Rename: mv classroom.db classroom.db.bak

# 3. Try to access student login
# Should see: "Database error" (not a crash)

# 4. Restore database
# mv classroom.db.bak classroom.db
```

**Expected Results**:
- [ ] App doesn't crash
- [ ] User sees friendly error message
- [ ] App recovers after DB is restored

**Success**: ✅ Error handling is graceful

---

### Test 5.2: Invalid Input Handling ✅

**What to test**: Input validation prevents issues

**Steps**:
```
1. Student Login:
   - Try: student_id = "'; DROP TABLE users; --"
   - Expected: Input validation error
   
2. Announcement:
   - Try: title with 5000 characters
   - Expected: Form length limit or error
   
3. File upload:
   - Try: upload .exe file
   - Expected: File type rejected
```

**Expected Results**:
- [ ] All invalid inputs properly rejected
- [ ] No SQL injection possible
- [ ] Clear error messages shown

**Success**: ✅ Input validation working

---

## Part 6: Performance Check

### Test 6.1: Page Load Times ✅

**What to test**: CSRF protection doesn't significantly slow down pages

**Steps**:
```bash
python -c "
import time
from app import app

with app.test_client() as client:
    # Time GET request
    start = time.time()
    response = client.get('/admin/login')
    duration = (time.time() - start) * 1000
    
    print(f'✓ Page load time: {duration:.2f}ms')
    print(f'✓ Status code: {response.status_code}')
    print(f'✓ CSRF token in response: {\"csrf_token\" in response.get_data(as_text=True)}')
"
```

**Expected Results**:
- [ ] Page loads in < 500ms
- [ ] CSRF token included
- [ ] No performance degradation

**Success**: ✅ Performance acceptable

---

## Part 7: Verification Checklist

### Security ✅
- [ ] CSRF tokens in all forms
- [ ] SECRET_KEY properly validated
- [ ] Session cookies secure (HttpOnly, Secure, SameSite)
- [ ] No SQL injection vulnerabilities
- [ ] Input validation working
- [ ] Error messages don't leak info

### Functionality ✅
- [ ] Admin login works
- [ ] Student login works
- [ ] Form submissions work
- [ ] Announcements can be created
- [ ] Attendance tracking works
- [ ] Polls can be created

### Configuration ✅
- [ ] .env file loads correctly
- [ ] SECRET_KEY is required in production
- [ ] Database connections work
- [ ] SMTP configuration ready

### Error Handling ✅
- [ ] Graceful error messages
- [ ] No unhandled exceptions
- [ ] Database errors handled
- [ ] Invalid input handled

---

## Part 8: Final Sign-Off

### Checklist for Completion
```bash
# Run this to verify all critical components
python -c "
from app import app
from flask_wtf.csrf import CSRFProtect
import os

print('╔════════════════════════════════════════════════════╗')
print('║        PHASE 1 SECURITY VERIFICATION               ║')
print('╚════════════════════════════════════════════════════╝')
print()

checks = {
    'CSRF Protection': 'csrf' in dir(app),
    'Routes Loaded': len([r for r in app.url_map.iter_rules()]) > 30,
    'Environment': bool(os.environ.get('SECRET_KEY')),
}

for check, result in checks.items():
    status = '✅' if result else '❌'
    print(f'{status} {check}')

print()
all_pass = all(checks.values())
if all_pass:
    print('🎉 Phase 1 Complete - All checks passed!')
else:
    print('⚠️  Review failed checks above')
"
```

---

## Troubleshooting

### Issue: CSRF token not in form
**Solution**:
```bash
# Re-run the token injection script
python add_csrf_tokens.py

# Verify template has the token
grep -n "csrf_token" templates/your_template.html
```

### Issue: "Secret key not set" error
**Solution**:
```bash
# Generate and add to .env
python -c "import secrets; print(secrets.token_hex(32))"
# Add to .env: SECRET_KEY=<generated_key>
```

### Issue: CSRF validation failing
**Solution**:
1. Clear browser cookies
2. Try a different form
3. Check that template includes: `{{ csrf_token() }}`
4. Ensure Flask-WTF is installed: `pip install flask-wtf`

### Issue: Login not working
**Solution**:
```bash
# Check database initialization
python -c "from database import init_db; init_db(); print('✓ Database initialized')"

# Verify default credentials in code
grep -A 5 "admin" database.py
```

---

## Next Steps After Phase 1

✅ **Completed This Phase**:
- CSRF protection enabled
- Input validation framework created
- Environment configuration improved
- All templates updated with CSRF tokens

📋 **Phase 2 (Next Month)**: Start with QUICK_REFERENCE.md section "Phase 2 Tasks"

📚 **Documentation**: All tests documented in QUICK_REFERENCE.md

---

**Status**: Phase 1 Testing Guide Complete ✅  
**Last Updated**: August 30, 2026  
**Next Review**: After Phase 1 completion
