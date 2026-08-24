import psycopg2, traceback
url = 'postgresql://postgres:Princeboame123@db.puqdlbvzcnvmqrfvorsw.supabase.co:5432/postgres'
print('Testing connection to:', url)
try:
    conn = psycopg2.connect(url, sslmode='require', connect_timeout=10)
    cur = conn.cursor()
    cur.execute('SELECT 1')
    print('OK: SELECT 1 ->', cur.fetchone())
    cur.close()
    conn.close()
except Exception as e:
    print('ERROR:', e)
    traceback.print_exc()
