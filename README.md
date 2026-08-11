# Classroom App

A Flask-based classroom management app with attendance, polls, announcements, and student login.

## Deployment

This project supports local SQLite and production Supabase (Postgres + Storage) on Vercel.

### Local development

1. Create a local `.env` file with your settings.
2. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

3. Start the app:

```bash
python app.py
```

4. Open `http://localhost:5000`.

### Supabase + Vercel

For production on Vercel, configure the following environment variables in Vercel's dashboard:

- `SECRET_KEY` - Flask session secret
- `DATABASE_URL` or `SUPABASE_DB_URL` - Supabase Postgres connection string
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_KEY` - Supabase anon or service role key
- `SUPABASE_BUCKET` - Supabase storage bucket name (default: `attachments`)
- `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` - optional email settings

If `SUPABASE_URL` and `SUPABASE_KEY` are configured, announcement attachments upload to Supabase Storage and download via signed URLs.

### Notes

- Local uploads are stored in `uploads/` only when Supabase is not configured.
- The app now initializes its database schema on startup using `init_db()`.
- The default admin account is:
  - username: `admin`
  - password: `admin123`

### Environment file example

Create a `.env` file locally using `.env.example` as a template.

### Useful commands

```bash
python -m py_compile app.py database.py scripts/list_students.py
python app.py
```

## Cleanup

- `.env` is ignored by `.gitignore`
- `classroom.db` is ignored for local development
- `uploads/` is ignored for local attachment storage
