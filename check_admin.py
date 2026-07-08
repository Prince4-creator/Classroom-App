import urllib.request

url = 'http://127.0.0.1:5000/admin/login'
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        data = r.read()
        print('STATUS', r.getcode())
        print(data.decode('utf-8')[:800])
except Exception as e:
    print('ERROR', e)
