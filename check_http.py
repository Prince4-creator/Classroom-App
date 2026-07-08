import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:5000/student/forgot_password') as r:
        print('STATUS', r.status)
        data = r.read(500).decode('utf-8')
        print(data)
except Exception as e:
    print('ERROR', type(e).__name__, e)
