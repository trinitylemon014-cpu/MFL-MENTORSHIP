# 🎓 Empower Mentorship Platform

A full-stack mentorship web application combining WhatsApp-style chat/calls and Instagram-style social feed. Built with Flask, Socket.IO, WebRTC, and SQLite.

---

## 🗂️ Project Structure

```
empower-mentorship/
├── app.py                      # Main Flask application (all routes + SocketIO events)
├── requirements.txt            # Python dependencies
├── empower.db                  # SQLite database (auto-created on first run)
├── static/
│   ├── css/
│   │   └── main.css            # Full Navy/White/Green design system
│   ├── js/
│   │   ├── main.js             # Shared utilities (emoji, alerts)
│   │   ├── chat.js             # Real-time chat via Socket.IO
│   │   ├── feed.js             # Feed likes, comments, image preview
│   │   └── webrtc.js           # WebRTC voice calling
│   └── uploads/
│       ├── profiles/           # User profile pictures
│       ├── groups/             # Group avatars
│       └── posts/              # Post images
└── templates/
    ├── base.html               # Base layout with navbar
    ├── index.html              # Landing page
    ├── student_login.html      # /student/login
    ├── mentor_login.html       # /mentor/login
    ├── mentors.html            # /mentors – mentor directory
    ├── chat.html               # /chat/<type>/<id>
    ├── group_chat.html         # /groups/<id>
    ├── groups.html             # /groups
    ├── feed.html               # /feed
    ├── profile.html            # /profile
    ├── partials/
    │   └── call_overlay.html   # Reusable call UI overlay
    └── admin/
        ├── login.html          # /admin/login
        └── dashboard.html      # /admin/dashboard
```

---

## ⚡ Quick Start

### 1. Prerequisites
- **Python 3.9+** installed
- `pip` available

### 2. Setup & Install

```bash
# Clone / extract the project folder
cd empower-mentorship

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the App

```bash
python app.py
```

The server starts at: *http://localhost:5000***

### 4. Railway deployment

Railway will automatically set the `PORT` environment variable. For WebRTC calls across different networks, add these variables in Railway:

```bash
WEBRTC_ICE_SERVERS_JSON='[{"urls":"stun:stun.l.google.com:19302"},{"urls":"stun:stun1.l.google.com:19302"}]'
WEBRTC_TURN_URL='turn:your-turn-server:3478'
WEBRTC_TURN_USERNAME='your-username'
WEBRTC_TURN_PASSWORD='your-password'
```

If you do not have a TURN server yet, the app will still use the public STUN servers by default, but calls may fail in restrictive networks.

---

## 🔐 Default Login Credentials

| Role    | Credential                         | Default             |
|---------|------------------------------------|---------------------|
| Admin   | Username + Password                | `admin` / `admin123` |
| Student | Student ID only (no password)      | `EIA20002343`       |
| Mentor  | Email + Password                   | `sarah@empower.edu` / `mentor123` |

> ⚠️ **Change the admin password** after first login via the database.

---

## 📱 Pages & URLs

| Page              | URL                          | Access         |
|-------------------|------------------------------|----------------|
| Landing           | `/`                          | Public         |
| Student Login     | `/student/login`             | Public         |
| Mentor Login      | `/mentor/login`              | Public         |
| Admin Login       | `/admin/login`               | Public         |
| Admin Dashboard   | `/admin/dashboard`           | Admin only     |
| Social Feed       | `/feed`                      | Logged in      |
| Mentor Directory  | `/mentors`                   | Logged in      |
| Chat              | `/chat/<type>/<id>`          | Logged in      |
| Groups            | `/groups`                    | Logged in      |
| Group Chat        | `/groups/<id>`               | Group member   |
| Profile           | `/profile`                   | Logged in      |

---

## 🧩 Features

### 👤 Student Accounts
- Admin creates students with ID, name, class, school, age
- Students log in with **Student ID only** (no password)
- Students can upload profile picture after first login
- Example ID format: `EIA20002343`

### 🧑‍🏫 Mentor Accounts
- Admin creates mentors with email + password
- Email format validated on creation
- Mentors log in with email + password
- Can upload profile picture, edit bio, change theme

### 🛡️ Admin Dashboard
- **Add Students** – ID, name, class, school, age
- **Add Mentors** – name, valid unique email, password
- **Assign** mentors to students
- **Moderate** posts (view + delete)
- Stats overview

### 💬 Real-time Messaging (WhatsApp-style)
- Socket.IO powered instant messaging
- Message bubbles (sent right ✅, received left)
- Emoji picker with 30 emojis
- Auto-resize textarea
- Message timestamps
- Read receipts (double tick)
- Scrollable history

### 📞 Voice Calls (WebRTC)
- One-to-one browser-based voice calls
- Call popup with Accept/Decline buttons
- Mute/unmute during call
- Call duration timer
- Oscillator-based ringtone
- STUN servers configured for NAT traversal

### 👥 Group Chats
- Mentors create named groups with optional picture
- Add multiple students to a group
- Real-time group messaging via Socket.IO
- Member list in sidebar
- Groups visible on profile page

### 📸 Social Feed (Instagram-style)
- Post text + images
- Like/unlike posts (animated heart)
- Comment on posts
- Comments load inline
- Shows poster name, avatar, role badge
- Sorted newest first

### 🎨 Chat Themes
Users can choose from their Profile page:
- ☀️ **Light** – Clean white background
- 🌙 **Dark** – Dark navy background
- 🖼️ **Picture** – Custom background image

---

## 🗄️ Database Schema

```sql
-- Students (created by admin only)
CREATE TABLE students (
  id              INTEGER PRIMARY KEY,
  student_id      TEXT UNIQUE NOT NULL,   -- e.g. EIA20002343
  full_name       TEXT NOT NULL,
  class_name      TEXT,
  school          TEXT,
  age             INTEGER,
  profile_picture TEXT DEFAULT '',
  theme           TEXT DEFAULT 'light',
  created_at      DATETIME
);

-- Mentors (created by admin only)
CREATE TABLE mentors (
  id              INTEGER PRIMARY KEY,
  mentor_name     TEXT NOT NULL,
  mentor_email    TEXT UNIQUE NOT NULL,   -- validated format
  password_hash   TEXT NOT NULL,
  profile_picture TEXT DEFAULT '',
  theme           TEXT DEFAULT 'light',
  bio             TEXT DEFAULT '',
  created_at      DATETIME
);

-- Mentor–Student assignments
CREATE TABLE mentor_assignments (
  id          INTEGER PRIMARY KEY,
  mentor_id   INTEGER REFERENCES mentors(id),
  student_id  INTEGER REFERENCES students(id)
);

-- Direct messages
CREATE TABLE messages (
  message_id    INTEGER PRIMARY KEY,
  sender_type   TEXT,   -- 'student' | 'mentor'
  sender_id     INTEGER,
  receiver_type TEXT,
  receiver_id   INTEGER,
  message_text  TEXT NOT NULL,
  timestamp     DATETIME,
  is_read       BOOLEAN DEFAULT 0
);

-- Groups (mentor-created)
CREATE TABLE groups (
  group_id      INTEGER PRIMARY KEY,
  group_name    TEXT NOT NULL,
  created_by    INTEGER REFERENCES mentors(id),
  group_picture TEXT DEFAULT '',
  created_at    DATETIME
);

-- Group members
CREATE TABLE group_members (
  id        INTEGER PRIMARY KEY,
  group_id  INTEGER REFERENCES groups(group_id),
  user_type TEXT,   -- 'student' | 'mentor'
  user_id   INTEGER
);

-- Group messages
CREATE TABLE group_messages (
  message_id    INTEGER PRIMARY KEY,
  group_id      INTEGER REFERENCES groups(group_id),
  sender_type   TEXT,
  sender_id     INTEGER,
  message_text  TEXT NOT NULL,
  timestamp     DATETIME
);

-- Feed posts
CREATE TABLE posts (
  post_id   INTEGER PRIMARY KEY,
  user_type TEXT,
  user_id   INTEGER,
  content   TEXT,
  image     TEXT DEFAULT '',
  timestamp DATETIME
);

-- Post likes
CREATE TABLE post_likes (
  id        INTEGER PRIMARY KEY,
  post_id   INTEGER REFERENCES posts(post_id),
  user_type TEXT,
  user_id   INTEGER
);

-- Post comments
CREATE TABLE post_comments (
  id        INTEGER PRIMARY KEY,
  post_id   INTEGER REFERENCES posts(post_id),
  user_type TEXT,
  user_id   INTEGER,
  comment   TEXT NOT NULL,
  timestamp DATETIME
);

-- Admin
CREATE TABLE admins (
  id            INTEGER PRIMARY KEY,
  username      TEXT UNIQUE,
  password_hash TEXT
);
```

---

## 🎨 Design System

| Token         | Value       | Usage                      |
|---------------|-------------|----------------------------|
| `--navy`      | `#0a1628`   | Primary dark color         |
| `--navy-light`| `#122040`   | Navbars, sidebars          |
| `--navy-mid`  | `#1a2e52`   | Cards, headers             |
| `--green`     | `#00c853`   | Accent, CTAs, online dots  |
| `--green-dark`| `#00a844`   | Hover states               |
| `--white`     | `#ffffff`   | Backgrounds, text          |
| Font (heading)| Outfit 700+ | Page titles, card headers  |
| Font (body)   | DM Sans 400 | Body text, labels          |

---

## 🔧 Configuration

Set environment variables before running:

```bash
export SECRET_KEY="your-super-secret-key-here"
```

Or create a `.env` file:
```
SECRET_KEY=your-super-secret-key-here
```

---

## 🚀 Production Tips

1. **Use PostgreSQL** – swap `SQLALCHEMY_DATABASE_URI` in `app.py`:
   ```python
   SQLALCHEMY_DATABASE_URI = "postgresql://user:pass@localhost/empower_db"
   ```

2. **Use gunicorn + gevent** for production:
   ```bash
   pip install gunicorn gevent
   gunicorn --worker-class geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
            -w 1 app:app
   ```

3. **Set a strong SECRET_KEY** via environment variable.

4. **Configure HTTPS** – WebRTC requires HTTPS in production (not localhost).

5. **Add TURN server** for reliable WebRTC behind strict NATs:
   ```python
   RTC_CONFIG = {
     iceServers: [
       { urls: 'turn:your-turn-server:3478', username: 'user', credential: 'pass' }
     ]
   }
   ```

---

## 📋 Admin Workflow

1. Go to `/admin/login` → login with `admin` / `admin123`
2. **Add Students** → enter Student ID (e.g. `EIA20002343`), name, class, school, age
3. **Add Mentors** → enter name, valid email, password
4. **Assign** → link each mentor to their students
5. Students & mentors can now log in and use the platform

---

Built with ❤️ using Flask · Socket.IO · WebRTC · SQLite
