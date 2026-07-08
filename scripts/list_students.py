import sqlite3
conn = sqlite3.connect('classroom.db')
c = conn.cursor()
c.execute("SELECT student_id, name FROM students")
rows = c.fetchall()
for r in rows:
    print(r[0], '-', r[1])
conn.close()