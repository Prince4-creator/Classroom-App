from database import get_all_students

for student in get_all_students():
    print(student['student_id'], '-', student['name'])