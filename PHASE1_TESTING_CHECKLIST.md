# ✅ PHASE 1 TESTING CHECKLIST - Print This!

**Print this page and check off items as you complete them**

---

## 📋 QUICK START (Do First)

### Setup (15 minutes)
- [ ] Read PHASE1_COMPLETION.md (5 min)
- [ ] Read TESTING_PHASE1.md Introduction (5 min)  
- [ ] Copy .env.example to .env: `cp .env.example .env`
- [ ] Generate SECRET_KEY: `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Paste SECRET_KEY into .env file

### Verification (10 minutes)
- [ ] Start app: `python app.py`
- [ ] Open browser: http://localhost:5000
- [ ] App loads without errors
- [ ] See login options

---

## 🔐 CSRF PROTECTION TESTING (30 minutes)

### Verify CSRF Tokens in Forms
- [ ] Navigate to Admin Login
- [ ] Open DevTools (F12) → Inspector
- [ ] Find login form HTML
- [ ] Verify line contains: `<input type="hidden" name="csrf_token"`
- [ ] Refresh page - token value changes
- [ ] Repeat for Student Login

### Test Form Submission
- [ ] Admin Login: Enter valid credentials
- [ ] Click Submit
- [ ] Should work fine (CSRF token validates)
- [ ] Student Login: Same test
- [ ] Announcement form: Create test announcement
- [ ] Should submit successfully

### Test CSRF Rejection (Optional Advanced)
```bash
# In PowerShell, test missing CSRF token:
curl -X POST http://localhost:5000/admin/login -d "username=admin&password=test"
# Expected: 400 error "CSRF token is missing"
```

---

## 🔑 AUTHENTICATION TESTING (45 minutes)

### Admin Login Flow
- [ ] Navigate to http://localhost:5000/admin/login
- [ ] Try invalid credentials: admin / wrongpassword
  - [ ] See error message
  - [ ] Stays on login page
- [ ] Try valid credentials: admin / admin123
  - [ ] Login succeeds
  - [ ] Redirected to admin dashboard
  - [ ] Session cookie set (DevTools → Application → Cookies)

### Check Security Cookie Flags
- [ ] Admin dashboard open
- [ ] DevTools → Application → Cookies
- [ ] Find "session" cookie
- [ ] Verify flags:
  - [ ] ✓ Secure (HTTPS only)
  - [ ] ✓ HttpOnly (JavaScript can't access)
  - [ ] ✓ SameSite=Lax (CSRF protection)

### Student Login Flow
- [ ] Navigate to http://localhost:5000/student/login
- [ ] Try invalid student ID: "invalid@@@"
  - [ ] Error: "Invalid student ID format"
- [ ] Try valid ID: "STU001" (or check docs for real student ID)
- [ ] Enter password: test123
- [ ] Login succeeds
- [ ] Redirected to student dashboard

### Test Session Timeout
- [ ] Log in as student
- [ ] Wait 30+ minutes (or modify SESSION_TIMEOUT if testing)
- [ ] Try to access protected page
- [ ] Should redirect to login
- [ ] Session expired message shown

---

## 📝 FORM SUBMISSION TESTING (30 minutes)

### Admin Creates Announcement
- [ ] Log in as admin
- [ ] Go to Dashboard → Announcements
- [ ] Create new announcement:
  - [ ] Title: "Test Announcement"
  - [ ] Content: "This is a test"
  - [ ] Type: "General"
- [ ] Click Submit
- [ ] Should succeed
- [ ] Announcement appears in list

### Admin Creates Course
- [ ] Go to Dashboard → Courses
- [ ] Create new course:
  - [ ] Course Code: "CS101"
  - [ ] Course Name: "Intro to CS"
  - [ ] Time: "09:00"
- [ ] Submit form
- [ ] Course appears in list

### Admin Creates Poll
- [ ] Go to Dashboard → Polls
- [ ] Create poll:
  - [ ] Question: "How is the class?"
  - [ ] Options: "Great", "Good", "OK", "Poor"
- [ ] Submit
- [ ] Poll appears with options

### Student Takes Poll (if logged in as student)
- [ ] Log in as student
- [ ] See available polls
- [ ] Vote on poll: Select "Great"
- [ ] Submit vote
- [ ] Sees "Thank you for voting"
- [ ] Can't vote twice on same poll

---

## 🛡️ SECURITY VALIDATION (20 minutes)

### Input Validation
- [ ] Admin Login - Try SQL injection: `admin' OR '1'='1`
  - [ ] Rejected with validation error
- [ ] Student ID - Try special chars: `STU001<script>`
  - [ ] Rejected or escaped
- [ ] File Upload - Try uploading .exe file
  - [ ] File rejected (if upload feature exists)

### Error Messages
- [ ] Login with wrong password
  - [ ] Error shown is generic (no info leakage)
  - [ ] Message: "Invalid credentials" (not "User doesn't exist")
- [ ] Database error (intentional)
  - [ ] Friendly error shown
  - [ ] No technical details leaked

### No Information Leakage
- [ ] Try accessing admin route while logged in as student
  - [ ] Redirected to student dashboard (or error)
  - [ ] No admin data shown
- [ ] Try accessing /admin/users
  - [ ] If not admin: redirected or error
  - [ ] If admin: works normally

---

## 📊 ENVIRONMENT CONFIGURATION (15 minutes)

### Test .env Loading
- [ ] Verify .env file exists in project root
- [ ] Verify contains: SECRET_KEY=...
- [ ] Run: `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('✓' if os.environ.get('SECRET_KEY') else '✗')"`
- [ ] Should print: ✓

### Test Production Mode
- [ ] Create test script:
```bash
python -c "
import os
os.environ.pop('SECRET_KEY', None)  # Remove it
os.environ['FLASK_ENV'] = 'production'
try:
    from app import app
    print('✗ ERROR: Should require SECRET_KEY')
except ValueError:
    print('✓ Correctly rejects production without SECRET_KEY')
"
```
- [ ] Should print: ✓ message

### Test Development Mode
```bash
python -c "
import os
os.environ.pop('SECRET_KEY', None)
os.environ['FLASK_ENV'] = 'development'
from app import app
print('✓ Development mode works without SECRET_KEY')
"
```
- [ ] Should print: ✓ message

---

## 🧪 PERFORMANCE CHECK (10 minutes)

### Page Load Times
- [ ] Open DevTools → Network tab
- [ ] Load http://localhost:5000/admin/login
- [ ] Check response time: Should be < 500ms
- [ ] Load http://localhost:5000/student/login
- [ ] Response time: Should be < 500ms

### No Noticeable Slowdown
- [ ] CSRF tokens shouldn't slow down pages
- [ ] All pages load within normal time
- [ ] Forms submit quickly (< 1 second)

---

## 📚 DOCUMENTATION CHECK (10 minutes)

### Files Exist and Readable
- [ ] .env.example - readable, comprehensive
- [ ] TESTING_PHASE1.md - complete guide
- [ ] PHASE1_COMPLETION.md - overview
- [ ] QUICK_REFERENCE.md - has quick commands
- [ ] ACTION_ITEMS.md - lists next steps

### Files Are Helpful
- [ ] Can find setup instructions in .env.example
- [ ] Can find troubleshooting in TESTING_PHASE1.md
- [ ] Can find next steps in ACTION_ITEMS.md
- [ ] Can find commands in QUICK_REFERENCE.md

---

## ✅ FINAL VERIFICATION (5 minutes)

### All Security Features Working
- [ ] CSRF tokens in forms ✓
- [ ] Session cookies secure ✓
- [ ] Input validation working ✓
- [ ] Error handling graceful ✓

### All Core Features Working
- [ ] Login/logout ✓
- [ ] Role-based access (admin vs student) ✓
- [ ] Form submissions ✓
- [ ] Database operations ✓

### Documentation Complete
- [ ] Setup guide exists ✓
- [ ] Testing guide exists ✓
- [ ] Configuration template exists ✓
- [ ] Next steps documented ✓

---

## 🎉 COMPLETION SIGN-OFF

When you've completed all items above:

1. [ ] All checkboxes marked
2. [ ] No blocking issues found
3. [ ] App running smoothly
4. [ ] Ready for Phase 2

**Date Completed**: _______________

**Issues Found**: 
- Issue 1: _________________________________
- Issue 2: _________________________________
- Issue 3: _________________________________

**Overall Status**: 
- [ ] ✅ PASS - All tests successful, ready for Phase 2
- [ ] ⚠️  ISSUES - Found problems, fix before Phase 2
- [ ] ❌ BLOCKED - Critical issue, needs investigation

---

## 📞 IF YOU GET STUCK

### Common Issues & Fixes

**Q: App won't start**
```bash
python -c "from app import app; print('OK')"
```
If error, check:
- Flask installed? `pip install flask`
- flask-wtf installed? `pip install flask-wtf`
- .env file exists?

**Q: CSRF tokens not showing in forms**
```bash
grep -r "csrf_token" templates/ | wc -l
```
Should show 22+ lines. If not, run:
```bash
python add_csrf_tokens.py
```

**Q: Login not working**
- Check default credentials (admin/admin123)
- Verify database initialized: `python -c "from database import init_db; init_db()"`
- Check .env file exists

**Q: Tests failing**
- See TESTING_PHASE1.md "Troubleshooting" section
- Check QUICK_REFERENCE.md for commands
- Review SECURITY.md for background info

**Q: Where's the file upload feature?**
- Check app.py for `/upload` routes
- May be in Supabase configuration section
- Or look in templates for `<input type="file">`

---

## 🚀 WHEN YOU'RE DONE

1. You've completed Phase 1 testing ✅
2. Next: Start Phase 2 (see ACTION_ITEMS.md)
3. Phase 2 tasks:
   - Implement rate limiting
   - Add comprehensive validation  
   - Create unit tests
   - Set up logging

**Estimated Phase 2 Time**: 8 hours (spread over a month)

**Questions?** Check QUICK_REFERENCE.md or reach out with specific errors.

---

**Print this checklist and complete it!** ✅

Use the checkboxes above to track your progress. When all items are checked and passing, your Phase 1 testing is complete!

---

*Phase 1 Testing Checklist*  
*Last Updated: August 30, 2026*  
*Difficulty: Beginner to Intermediate*  
*Estimated Duration: 3-4 hours total*
