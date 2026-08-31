from app import app, STAFF_LOGIN_PATH

# Use Flask test client to simulate requests without network

def run_tests():
    client = app.test_client()
    # GET should return 200 and contain login form
    r_get = client.get(STAFF_LOGIN_PATH)
    print(f'GET {STAFF_LOGIN_PATH} ->', r_get.status_code)
    if b'Admin / Instructor Login' in r_get.data:
        print('GET contains expected heading')
    else:
        print('GET missing expected heading')

    # POST with credentials will attempt DB access; we expect no exception and a flashed message on DB failure
    r_post = client.post(STAFF_LOGIN_PATH, data={'username': 'doesnotexist', 'password': 'x'})
    print(f'POST {STAFF_LOGIN_PATH} ->', r_post.status_code)
    # Search for our friendly DB error message or invalid credentials flash
    if b'unable to contact the database' in r_post.data:
        print('DB error path triggered and user-facing message shown')
    elif b'Invalid admin credentials' in r_post.data:
        print('Invalid credentials path shown')
    else:
        print('Unexpected POST response; content length', len(r_post.data))


if __name__ == '__main__':
    run_tests()
