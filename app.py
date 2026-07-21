import os, re, json, uuid, markupsafe, threading, time
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

DEFAULT_WEBRTC_ICE_SERVERS = [
    {'urls': 'stun:stun.l.google.com:19302'},
    {'urls': 'stun:stun1.l.google.com:19302'},
    {'urls': 'stun:stun2.l.google.com:19302'},
]


def _build_webrtc_ice_servers():
    servers = []
    env_servers = os.environ.get('WEBRTC_ICE_SERVERS_JSON', '').strip()
    if env_servers:
        try:
            parsed = json.loads(env_servers)
            if isinstance(parsed, list):
                servers.extend(parsed)
        except Exception as exc:
            print(f"[WebRTC] Invalid WEBRTC_ICE_SERVERS_JSON: {exc}")

    if not servers:
        servers = list(DEFAULT_WEBRTC_ICE_SERVERS)

    turn_url = os.environ.get('WEBRTC_TURN_URL', '').strip()
    if turn_url:
        turn_entry = {'urls': turn_url}
        username = os.environ.get('WEBRTC_TURN_USERNAME', '').strip()
        password = os.environ.get('WEBRTC_TURN_PASSWORD', '').strip()
        if username:
            turn_entry['username'] = username
        if password:
            turn_entry['credential'] = password
        servers.append(turn_entry)
    return servers

DATA_DIR = os.environ.get('DATA_DIR', BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()
if DATABASE_URL.startswith('postgres://'):
    # Some providers hand out the old-style scheme; SQLAlchemy needs postgresql://
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'empower-secret-2024-xK9!'),
    SQLALCHEMY_DATABASE_URI=DATABASE_URL or f"sqlite:///{os.path.join(DATA_DIR, 'empower.db')}",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    UPLOAD_FOLDER=os.path.join(DATA_DIR, 'static', 'uploads'),
    MAX_CONTENT_LENGTH=200 * 1024 * 1024,
    WEBRTC_ICE_SERVERS=_build_webrtc_ice_servers(),
)
from extensions import db
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── Models — defined once in models.py, imported here ────────────────────────
from models import (
    Student, Mentor, MentorAssignment, Message,
    Group, GroupMember, GroupMessage,
    Post, PostLike, PostComment, PostSave, CommentLike, PollVote,
    Admin, Story, StoryView, CallRecord,
)

ALLOWED_IMG   = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO = {'mp4', 'mov', 'webm', 'avi', 'mkv'}
ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'webm', 'opus'}
ALLOWED_DOCS  = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'zip', 'rar'}
ALLOWED_ALL   = ALLOWED_IMG | ALLOWED_VIDEO | ALLOWED_AUDIO | ALLOWED_DOCS

UNIVERSAL_GROUP_NAME = 'Empower Community'

def _ext(f): return f.rsplit('.', 1)[-1].lower() if '.' in f else ''
def allowed_file(f): return _ext(f) in ALLOWED_IMG

def save_file(file, subfolder):
    if file and allowed_file(file.filename):
        fname = f"{uuid.uuid4().hex}.{_ext(file.filename)}"
        dest  = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
        os.makedirs(dest, exist_ok=True); file.save(os.path.join(dest, fname))
        return f"uploads/{subfolder}/{fname}"
    return None

def save_any(file, subfolder, allowed_set):
    if file and file.filename and _ext(file.filename) in allowed_set:
        fname = f"{uuid.uuid4().hex}.{_ext(file.filename)}"
        dest  = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
        os.makedirs(dest, exist_ok=True); file.save(os.path.join(dest, fname))
        return f"uploads/{subfolder}/{fname}"
    return None

def save_any_ext(file, subfolder, ext_override=None):
    if not file: return None
    ext = ext_override or _ext(file.filename or '') or 'bin'
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest  = os.path.join(app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(dest, exist_ok=True)
    file.save(os.path.join(dest, fname))
    return f"uploads/{subfolder}/{fname}"

# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSAL GROUP HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_universal_group():
    return Group.query.filter_by(is_universal=True).first()

def ensure_universal_group():
    g = get_universal_group()
    if not g:
        g = Group(group_name=UNIVERSAL_GROUP_NAME, created_by=None,
                  group_picture='', is_universal=True)
        db.session.add(g); db.session.flush()
    for s in Student.query.all():
        if not GroupMember.query.filter_by(group_id=g.group_id, user_type='student', user_id=s.id).first():
            db.session.add(GroupMember(group_id=g.group_id, user_type='student', user_id=s.id))
    for m in Mentor.query.all():
        if not GroupMember.query.filter_by(group_id=g.group_id, user_type='mentor', user_id=m.id).first():
            db.session.add(GroupMember(group_id=g.group_id, user_type='mentor', user_id=m.id))
    db.session.commit()
    return g

def add_to_universal_group(user_type, user_id):
    g = get_universal_group()
    if not g: return
    if not GroupMember.query.filter_by(group_id=g.group_id, user_type=user_type, user_id=user_id).first():
        db.session.add(GroupMember(group_id=g.group_id, user_type=user_type, user_id=user_id))
        db.session.commit()

def post_to_universal_group(sender_type, sender_id, text, msg_type='chat', meta=None):
    g = get_universal_group()
    if not g: return None
    msg = GroupMessage(
        group_id=g.group_id, sender_type=sender_type, sender_id=sender_id,
        message_text=text, msg_type=msg_type,
        meta_json=json.dumps(meta) if meta else None,
    )
    db.session.add(msg); db.session.commit()
    name, avatar = user_info(sender_type, sender_id)
    socketio.emit('new_group_message', {
        'id': msg.message_id, 'text': text,
        'sender_type': sender_type, 'sender_id': sender_id,
        'name': name, 'avatar': avatar,
        'time': msg.timestamp.strftime('%H:%M'),
        'msg_type': msg_type, 'meta': meta or {},
    }, to=f"group_{g.group_id}")
    return msg

# ── Presence helpers ──────────────────────────────────────────────────────────
ONLINE_THRESHOLD = 45

def is_online(user):
    if not user or not getattr(user, 'last_seen', None): return False
    return (datetime.utcnow() - user.last_seen).total_seconds() < ONLINE_THRESHOLD

def last_seen_label(user):
    if not user or not getattr(user, 'last_seen', None): return 'last seen a long time ago'
    if is_online(user): return 'online'
    s = int((datetime.utcnow() - user.last_seen).total_seconds())
    if s < 60:     return 'last seen just now'
    if s < 3600:   return f"last seen {s // 60}m ago"
    if s < 86400:  return f"last seen {s // 3600}h ago"
    if s < 604800: return f"last seen {s // 86400}d ago"
    return 'last seen ' + user.last_seen.strftime('%b %d')

def touch_last_seen(role, uid):
    try:
        if role == 'student': Student.query.filter_by(id=uid).update({'last_seen': datetime.utcnow()})
        elif role == 'mentor': Mentor.query.filter_by(id=uid).update({'last_seen': datetime.utcnow()})
        db.session.commit()
    except Exception: db.session.rollback()

def get_user_by_type(utype, uid):
    if utype == 'student': return db.session.get(Student, uid)
    if utype == 'mentor':  return db.session.get(Mentor, uid)
    return None

def current_user():
    role = session.get('role'); uid = session.get('user_id')
    if role == 'student': return db.session.get(Student, uid)
    if role == 'mentor':  return db.session.get(Mentor, uid)
    if role == 'admin':   return db.session.get(Admin, uid)
    return None

def get_display(user, role):
    if user is None: return 'Unknown', ''
    if role == 'student': return user.full_name,   user.profile_picture or ''
    if role == 'mentor':  return user.mentor_name,  user.profile_picture or ''
    return 'Admin', ''

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'role' not in session: return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

def validate_email(e):
    return re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', e) is not None

def user_info(utype, uid):
    if utype == 'student':
        u = db.session.get(Student, uid)
        return (u.full_name, u.profile_picture or '') if u else ('Unknown','')
    if utype == 'mentor':
        u = db.session.get(Mentor, uid)
        return (u.mentor_name, u.profile_picture or '') if u else ('Unknown','')
    return ('Unknown','')

def _file_size_label(path):
    try:
        full = os.path.join(BASE_DIR, 'static', path)
        sz = os.path.getsize(full)
        if sz < 1024: return f"{sz} B"
        if sz < 1024*1024: return f"{sz//1024} KB"
        return f"{sz//1024//1024} MB"
    except Exception: return ''

@app.template_filter('parse_content')
def parse_content_filter(text):
    if not text: return ''
    text = str(markupsafe.escape(text))
    text = re.sub(r'#(\w+)', r'<span class="hashtag">#\1</span>', text)
    text = re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', text)
    return text.replace('\n', '<br>')

@app.template_filter('from_json')
def from_json_filter(value):
    if not value: return {}
    try: return json.loads(value)
    except: return {}

@app.before_request
def _update_presence():
    role = session.get('role'); uid = session.get('user_id')
    if role in ('student', 'mentor') and uid:
        touch_last_seen(role, uid)

# ══════════════════════════════════════════════════════════════════════════════
#  COMMENT HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _enrich_comments(post_id, role, uid):
    comments = []
    top_level = (PostComment.query
                 .filter_by(post_id=post_id, parent_id=None)
                 .order_by(PostComment.timestamp)
                 .all())
    for c in top_level:
        n, a   = user_info(c.user_type, c.user_id)
        clikes = CommentLike.query.filter_by(comment_id=c.id).count()
        cliked = bool(CommentLike.query.filter_by(comment_id=c.id, user_type=role, user_id=uid).first())
        replies = []
        for r in (PostComment.query.filter_by(parent_id=c.id).order_by(PostComment.timestamp).all()):
            rn, ra = user_info(r.user_type, r.user_id)
            rlikes = CommentLike.query.filter_by(comment_id=r.id).count()
            rliked = bool(CommentLike.query.filter_by(comment_id=r.id, user_type=role, user_id=uid).first())
            replies.append({'comment': r, 'name': rn, 'avatar': ra, 'like_count': rlikes, 'user_liked': rliked})
        comments.append({'comment': c, 'name': n, 'avatar': a, 'like_count': clikes, 'user_liked': cliked, 'replies': replies})
    return comments

# ══════════════════════════════════════════════════════════════════════════════
#  CLASS PROMOTION
# ══════════════════════════════════════════════════════════════════════════════
def _next_class(class_name):
    if not class_name: return class_name
    m = re.match(r'^(.*?)(\d+)(\D*)$', class_name.strip())
    if not m: return class_name
    prefix, num, suffix = m.group(1), int(m.group(2)), m.group(3)
    return f"{prefix}{num + 1}{suffix}"

def _run_promotion():
    current_year = datetime.utcnow().year
    students = Student.query.filter(
        db.or_(Student.last_promoted_year == None, Student.last_promoted_year < current_year)
    ).all()
    promoted = 0
    for s in students:
        s.class_name = _next_class(s.class_name); s.last_promoted_year = current_year; promoted += 1
    if promoted: db.session.commit()
    return promoted

def _start_promotion_scheduler():
    def _loop():
        while True:
            now = datetime.utcnow()
            if now.month == 1 and now.day == 1 and now.hour == 0:
                with app.app_context():
                    try:
                        n = _run_promotion()
                        if n: app.logger.info(f'[AutoPromotion] {now.year}: {n} students promoted.')
                    except Exception as e: app.logger.error(f'[AutoPromotion] Error: {e}')
            time.sleep(3600)
    t = threading.Thread(target=_loop, daemon=True, name='class-promotion'); t.start()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index(): return render_template('index.html')

@app.route('/student/login', methods=['GET','POST'])
def student_login():
    if request.method == 'POST':
        sid = request.form.get('student_id','').strip()
        student = Student.query.filter_by(student_id=sid).first()
        if not student: flash('Invalid Student ID.','error'); return render_template('student_login.html')
        session.clear(); session.update(role='student', user_id=student.id, name=student.full_name)
        return redirect(url_for('feed'))
    return render_template('student_login.html')

@app.route('/mentor/login', methods=['GET','POST'])
def mentor_login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower(); pwd = request.form.get('password','')
        if not validate_email(email): flash('Invalid email format.','error'); return render_template('mentor_login.html')
        mentor = Mentor.query.filter_by(mentor_email=email).first()
        if not mentor: flash('No account found.','error'); return render_template('mentor_login.html')
        if not mentor.password_set:
            session['setup_mentor_id'] = mentor.id
            flash(f'Welcome {mentor.mentor_name}! Please set your password.','info')
            return redirect(url_for('mentor_setup_password'))
        if not check_password_hash(mentor.password_hash, pwd): flash('Incorrect password.','error'); return render_template('mentor_login.html')
        session.clear(); session.update(role='mentor', user_id=mentor.id, name=mentor.mentor_name)
        return redirect(url_for('feed'))
    return render_template('mentor_login.html')

@app.route('/mentor/setup-password', methods=['GET','POST'])
def mentor_setup_password():
    mentor_id = session.get('setup_mentor_id')
    if not mentor_id: return redirect(url_for('mentor_login'))
    mentor = db.session.get(Mentor, mentor_id)
    if not mentor or mentor.password_set:
        session.pop('setup_mentor_id', None); return redirect(url_for('mentor_login'))
    if request.method == 'POST':
        pwd = request.form.get('password',''); pwd2 = request.form.get('password_confirm','')
        errors = []
        if len(pwd) < 8: errors.append('Minimum 8 characters.')
        if not re.search(r'[A-Z]', pwd): errors.append('Need one uppercase letter.')
        if not re.search(r'[0-9]', pwd): errors.append('Need one number.')
        if pwd != pwd2: errors.append('Passwords do not match.')
        if errors:
            for e in errors: flash(e,'error')
            return render_template('mentor_setup_password.html', mentor=mentor)
        mentor.password_hash = generate_password_hash(pwd); mentor.password_set = True
        db.session.commit(); session.pop('setup_mentor_id', None)
        session.update(role='mentor', user_id=mentor.id, name=mentor.mentor_name)
        flash(f'Welcome {mentor.mentor_name}!','success'); return redirect(url_for('feed'))
    return render_template('mentor_setup_password.html', mentor=mentor)

@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        admin = Admin.query.filter_by(username=request.form.get('username','').strip()).first()
        if admin and check_password_hash(admin.password_hash, request.form.get('password','')):
            session.clear(); session.update(role='admin', user_id=admin.id, name='Admin')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials.','error')
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    students   = Student.query.order_by(Student.created_at.desc()).all()
    mentors    = Mentor.query.order_by(Mentor.created_at.desc()).all()
    posts      = Post.query.order_by(Post.timestamp.desc()).all()
    raw_assign = MentorAssignment.query.all()
    mentor_map  = {m.id: m.mentor_name for m in mentors}
    student_map = {s.id: s.full_name   for s in students}
    assignments = [{'id': a.id, 'mentor_id': a.mentor_id, 'student_id': a.student_id,
                    'mentor_name': mentor_map.get(a.mentor_id,'Unknown'),
                    'student_name': student_map.get(a.student_id,'Unknown')} for a in raw_assign]
    return render_template('admin/dashboard.html', students=students, mentors=mentors,
                           posts=posts, assignments=assignments)

@app.route('/api/debug/assignments')
def debug_assignments():
    if session.get('role') != 'admin': return jsonify({'error':'admin only'}), 403
    rows = MentorAssignment.query.all(); out = []
    for a in rows:
        m = db.session.get(Mentor, a.mentor_id); s = db.session.get(Student, a.student_id)
        out.append({'assignment_id': a.id, 'mentor_id': a.mentor_id,
                    'mentor_name': m.mentor_name if m else 'NOT FOUND',
                    'student_id': a.student_id,
                    'student_name': s.full_name if s else 'NOT FOUND'})
    return jsonify({'total': len(out), 'assignments': out})

@app.route('/admin/add_student', methods=['POST'])
def admin_add_student():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    sid  = request.form.get('student_id','').strip()
    name = request.form.get('full_name', '').strip()
    if not sid or not name: flash('Student ID and name are required.','error'); return redirect(url_for('admin_dashboard'))
    if Student.query.filter_by(student_id=sid).first(): flash('Student ID already exists.','error'); return redirect(url_for('admin_dashboard'))
    s = Student(student_id=sid, full_name=name,
                class_name=request.form.get('class_name','').strip(),
                school=request.form.get('school','').strip())
    db.session.add(s); db.session.commit()
    add_to_universal_group('student', s.id)
    flash(f'Student "{name}" added.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add_mentor', methods=['POST'])
def admin_add_mentor():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    name  = request.form.get('mentor_name','').strip()
    email = request.form.get('mentor_email','').strip().lower()
    if not name or not email: flash('Name and email required.','error'); return redirect(url_for('admin_dashboard'))
    if not validate_email(email): flash('Invalid email.','error'); return redirect(url_for('admin_dashboard'))
    if Mentor.query.filter_by(mentor_email=email).first(): flash('Email already exists.','error'); return redirect(url_for('admin_dashboard'))
    m = Mentor(mentor_name=name, mentor_email=email, password_hash=None, password_set=False)
    db.session.add(m); db.session.commit()
    add_to_universal_group('mentor', m.id)
    flash(f'Mentor "{name}" added.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_student/<int:student_id>', methods=['POST'])
def admin_edit_student(student_id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    student  = db.get_or_404(Student, student_id)
    new_name = request.form.get('full_name','').strip()
    new_sid  = request.form.get('student_id','').strip()
    new_cls  = request.form.get('class_name','').strip()
    new_sch  = request.form.get('school','').strip()
    if not new_name: flash('Full name is required.','error'); return redirect(url_for('admin_dashboard'))
    if new_sid and new_sid != student.student_id:
        if Student.query.filter_by(student_id=new_sid).first():
            flash(f'Student ID "{new_sid}" is already taken.','error'); return redirect(url_for('admin_dashboard'))
        student.student_id = new_sid
    student.full_name = new_name; student.class_name = new_cls; student.school = new_sch
    db.session.commit(); flash(f'✅ Student "{new_name}" updated.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/edit_mentor/<int:mentor_id>', methods=['POST'])
def admin_edit_mentor(mentor_id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    mentor    = db.get_or_404(Mentor, mentor_id)
    new_name  = request.form.get('mentor_name','').strip()
    new_email = request.form.get('mentor_email','').strip().lower()
    new_bio   = request.form.get('bio','').strip()
    if not new_name: flash('Mentor name is required.','error'); return redirect(url_for('admin_dashboard'))
    if not new_email or not validate_email(new_email): flash('A valid email address is required.','error'); return redirect(url_for('admin_dashboard'))
    if new_email != mentor.mentor_email:
        if Mentor.query.filter_by(mentor_email=new_email).first():
            flash(f'Email "{new_email}" is already registered.','error'); return redirect(url_for('admin_dashboard'))
        mentor.mentor_email = new_email
    mentor.mentor_name = new_name; mentor.bio = new_bio
    db.session.commit(); flash(f'✅ Mentor "{new_name}" updated.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/promote_students', methods=['POST'])
def admin_promote_students():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    n = _run_promotion()
    flash(f'✅ {n} student{"s" if n > 1 else ""} promoted.' if n else 'All students already promoted this year.','success' if n else 'info')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/assign/bulk', methods=['POST'])
def admin_assign_bulk():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    mentor_id   = request.form.get('mentor_id', type=int)
    student_ids = request.form.getlist('student_ids')
    if not mentor_id: flash('Please select a mentor.','error'); return redirect(url_for('admin_dashboard'))
    if not student_ids: flash('Please select at least one student.','error'); return redirect(url_for('admin_dashboard'))
    mentor = db.session.get(Mentor, mentor_id)
    if not mentor: flash('Mentor not found.','error'); return redirect(url_for('admin_dashboard'))
    created = 0; skipped = 0; names = []
    for sid_str in student_ids:
        try: sid = int(sid_str)
        except: continue
        student = db.session.get(Student, sid)
        if not student: continue
        if MentorAssignment.query.filter_by(mentor_id=mentor_id, student_id=sid).first(): skipped += 1
        else:
            db.session.add(MentorAssignment(mentor_id=mentor_id, student_id=sid))
            created += 1; names.append(student.full_name)
    db.session.commit()
    if created: flash(f'✅ {created} student{"s" if created>1 else ""} assigned to "{mentor.mentor_name}": {", ".join(names)}.','success')
    if skipped: flash(f'{skipped} pair{"s were" if skipped>1 else " was"} already assigned — skipped.','info')
    if not created and not skipped: flash('No valid assignments were made.','error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/assign', methods=['POST'])
def admin_assign():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    mentor_id  = request.form.get('mentor_id',  type=int)
    student_id = request.form.get('student_id', type=int)
    if not mentor_id:  flash('Please select a mentor.','error');  return redirect(url_for('admin_dashboard'))
    if not student_id: flash('Please select a student.','error'); return redirect(url_for('admin_dashboard'))
    mentor  = db.session.get(Mentor,  mentor_id)
    student = db.session.get(Student, student_id)
    if not mentor:  flash('Mentor not found.','error');  return redirect(url_for('admin_dashboard'))
    if not student: flash('Student not found.','error'); return redirect(url_for('admin_dashboard'))
    if MentorAssignment.query.filter_by(mentor_id=mentor_id, student_id=student_id).first():
        flash(f'"{student.full_name}" is already assigned to "{mentor.mentor_name}".','info')
    else:
        db.session.add(MentorAssignment(mentor_id=mentor_id, student_id=student_id))
        db.session.commit()
        flash(f'✅ "{student.full_name}" assigned to "{mentor.mentor_name}".','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/unassign', methods=['POST'])
def admin_unassign():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    a = db.session.get(MentorAssignment, request.form.get('assignment_id', type=int))
    if a: db.session.delete(a); db.session.commit(); flash('Assignment removed.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_student/<int:student_id>', methods=['POST'])
def admin_delete_student(student_id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    student = db.get_or_404(Student, student_id); name = student.full_name
    MentorAssignment.query.filter_by(student_id=student_id).delete()
    for p in Post.query.filter_by(user_type='student', user_id=student_id).all():
        for cmt in PostComment.query.filter_by(post_id=p.post_id).all():
            CommentLike.query.filter_by(comment_id=cmt.id).delete()
        for M in [PostLike, PostComment, PostSave, PollVote]: M.query.filter_by(post_id=p.post_id).delete()
        db.session.delete(p)
    for M in [PostComment, PostLike, PostSave, PollVote]: M.query.filter_by(user_type='student', user_id=student_id).delete()
    Message.query.filter_by(sender_type='student',   sender_id=student_id).delete()
    Message.query.filter_by(receiver_type='student', receiver_id=student_id).delete()
    GroupMember.query.filter_by(user_type='student',    user_id=student_id).delete()
    GroupMessage.query.filter_by(sender_type='student', sender_id=student_id).delete()
    # Story rows cascade-delete their StoryView children automatically
    Story.query.filter_by(user_type='student', user_id=student_id).delete()
    db.session.delete(student); db.session.commit()
    flash(f'✅ Student "{name}" permanently deleted.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_mentor/<int:mentor_id>', methods=['POST'])
def admin_delete_mentor(mentor_id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    mentor = db.get_or_404(Mentor, mentor_id); name = mentor.mentor_name
    MentorAssignment.query.filter_by(mentor_id=mentor_id).delete()
    for p in Post.query.filter_by(user_type='mentor', user_id=mentor_id).all():
        for cmt in PostComment.query.filter_by(post_id=p.post_id).all():
            CommentLike.query.filter_by(comment_id=cmt.id).delete()
        for M in [PostLike, PostComment, PostSave, PollVote]: M.query.filter_by(post_id=p.post_id).delete()
        db.session.delete(p)
    for M in [PostComment, PostLike, PostSave, PollVote]: M.query.filter_by(user_type='mentor', user_id=mentor_id).delete()
    Message.query.filter_by(sender_type='mentor',   sender_id=mentor_id).delete()
    Message.query.filter_by(receiver_type='mentor', receiver_id=mentor_id).delete()
    GroupMember.query.filter_by(user_type='mentor',    user_id=mentor_id).delete()
    GroupMessage.query.filter_by(sender_type='mentor', sender_id=mentor_id).delete()
    for g in Group.query.filter_by(created_by=mentor_id, is_universal=False).all():
        GroupMember.query.filter_by(group_id=g.group_id).delete()
        GroupMessage.query.filter_by(group_id=g.group_id).delete()
        db.session.delete(g)
    # Story rows cascade-delete their StoryView children automatically
    Story.query.filter_by(user_type='mentor', user_id=mentor_id).delete()
    db.session.delete(mentor); db.session.commit()
    flash(f'✅ Mentor "{name}" permanently deleted.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_post/<int:post_id>', methods=['POST'])
def admin_delete_post(post_id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    for cmt in PostComment.query.filter_by(post_id=post_id).all():
        CommentLike.query.filter_by(comment_id=cmt.id).delete()
    for M in [PostLike, PostComment, PostSave, PollVote]: M.query.filter_by(post_id=post_id).delete()
    db.session.delete(db.get_or_404(Post, post_id))
    db.session.commit(); flash('Post deleted.','success')
    return redirect(url_for('admin_dashboard'))

@app.route('/api/online-status')
@login_required
def api_online_status():
    utype = request.args.get('type',''); uid = request.args.get('id', type=int)
    u = get_user_by_type(utype, uid)
    if not u: return jsonify({'ok':False,'error':'User not found'}), 404
    online = is_online(u)
    return jsonify({'ok':True, 'online':online, 'label': 'online' if online else last_seen_label(u)})

@app.route('/api/online-status/bulk', methods=['POST'])
@login_required
def api_online_status_bulk():
    data  = request.get_json(silent=True) or {}
    users = data.get('users', [])
    out   = {}
    for entry in users:
        utype = entry.get('type',''); uid = entry.get('id')
        if not utype or not uid: continue
        u = get_user_by_type(utype, uid)
        if not u: continue
        online = is_online(u)
        out[f"{utype}_{uid}"] = {'online': online, 'label': 'online' if online else last_seen_label(u)}
    return jsonify({'ok':True, 'statuses':out})

@app.route('/api/call-record', methods=['POST'])
@login_required
def save_call_record():
    """Persist a call record. Both caller and receiver call this independently.
    Optionally caller_type/caller_id may be supplied so the receiver can save
    a record where THEY are the receiver (not the session user as caller)."""
    role = session['role']; uid = session['user_id']
    data = request.get_json(silent=True) or {}
    caller_type   = data.get('caller_type',   role)
    caller_id_raw = data.get('caller_id',     uid)
    receiver_type = data.get('receiver_type', '')
    receiver_id   = data.get('receiver_id')
    status        = data.get('status', 'ended')
    duration_secs = int(data.get('duration_secs', 0))
    if not receiver_type or not receiver_id:
        return jsonify({'ok': False, 'error': 'receiver required'}), 400
    try:
        caller_id   = int(caller_id_raw)
        receiver_id = int(receiver_id)
    except (ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'bad id'}), 400
    # Security: session user must be one of the two parties
    is_caller   = (caller_type   == role and caller_id   == uid)
    is_receiver = (receiver_type == role and receiver_id == uid)
    if not is_caller and not is_receiver:
        return jsonify({'ok': False, 'error': 'Forbidden'}), 403
    now       = datetime.utcnow()
    called_at = now - timedelta(seconds=duration_secs) if duration_secs else now
    cr = CallRecord(
        caller_type=caller_type, caller_id=caller_id,
        receiver_type=receiver_type, receiver_id=receiver_id,
        status=status, called_at=called_at,
        ended_at=now, duration_secs=duration_secs,
    )
    db.session.add(cr); db.session.commit()
    return jsonify({'ok': True, 'id': cr.id})


@login_required
def api_universal_group_id():
    g = get_universal_group()
    if not g: return jsonify({'ok': False, 'error': 'Universal group not found'}), 404
    return jsonify({'ok': True, 'group_id': g.group_id})

@app.route('/api/messages/<int:message_id>/delete', methods=['POST'])
@login_required
def api_delete_message(message_id):
    role = session['role']; uid = session['user_id']
    msg  = db.session.get(Message, message_id)
    if not msg: return jsonify({'ok': False, 'error': 'Message not found'}), 404
    if msg.sender_type != role or msg.sender_id != uid: return jsonify({'ok': False, 'error': 'Forbidden'}), 403
    msg.message_text = '\x00deleted\x00'; msg.meta_json = None; msg.msg_type = 'deleted'
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/group-messages/<int:message_id>/delete', methods=['POST'])
@login_required
def api_delete_group_message(message_id):
    role = session['role']; uid = session['user_id']
    msg  = db.session.get(GroupMessage, message_id)
    if not msg: return jsonify({'ok': False, 'error': 'Message not found'}), 404
    if msg.sender_type != role or msg.sender_id != uid: return jsonify({'ok': False, 'error': 'Forbidden'}), 403
    msg.message_text = '\x00deleted\x00'; msg.meta_json = None; msg.msg_type = 'deleted'
    db.session.commit()
    return jsonify({'ok': True})

def _media_type_from_ext(ext):
    if ext in ALLOWED_IMG:   return 'image'
    if ext in ALLOWED_VIDEO: return 'video'
    if ext in ALLOWED_AUDIO: return 'audio'
    return 'document'

@app.route('/api/chat/upload', methods=['POST'])
@login_required
def api_chat_upload():
    file = request.files.get('file')
    if not file or not file.filename: return jsonify({'ok': False, 'error': 'No file provided'}), 400
    ext = _ext(file.filename)
    is_voice = request.form.get('is_voice') == '1'
    if is_voice:
        path = save_any_ext(file, 'chat_voice', 'webm')
        if not path: return jsonify({'ok': False, 'error': 'Upload failed'}), 500
        return jsonify({'ok': True, 'path': path, 'name': 'Voice message',
                        'media_type': 'voice', 'size_label': _file_size_label(path)})
    if ext not in ALLOWED_ALL: return jsonify({'ok': False, 'error': f'File type .{ext} not allowed'}), 400
    path = save_any(file, 'chat_attachments', ALLOWED_ALL)
    if not path: return jsonify({'ok': False, 'error': 'Upload failed'}), 500
    return jsonify({'ok': True, 'path': path, 'name': file.filename,
                    'media_type': _media_type_from_ext(ext), 'size_label': _file_size_label(path)})

@app.route('/api/group/upload', methods=['POST'])
@login_required
def api_group_upload():
    file = request.files.get('file')
    if not file or not file.filename: return jsonify({'ok': False, 'error': 'No file provided'}), 400
    is_voice = request.form.get('is_voice') == '1'
    if is_voice:
        path = save_any_ext(file, 'group_voice', 'webm')
        if not path: return jsonify({'ok': False, 'error': 'Upload failed'}), 500
        return jsonify({'ok': True, 'path': path, 'name': 'Voice message',
                        'media_type': 'voice', 'size_label': _file_size_label(path)})
    ext = _ext(file.filename)
    if ext not in ALLOWED_ALL: return jsonify({'ok': False, 'error': f'File type .{ext} not allowed'}), 400
    path = save_any(file, 'group_attachments', ALLOWED_ALL)
    if not path: return jsonify({'ok': False, 'error': 'Upload failed'}), 500
    return jsonify({'ok': True, 'path': path, 'name': file.filename,
                    'media_type': _media_type_from_ext(ext), 'size_label': _file_size_label(path)})

@app.route('/mentors')
@login_required
def mentor_directory():
    role = session['role']; uid = session['user_id']
    if role == 'mentor':
        ids = [a.student_id for a in MentorAssignment.query.filter_by(mentor_id=uid).all()]
        people = Student.query.filter(Student.id.in_(ids)).all() if ids else []
    elif role == 'student':
        ids = [a.mentor_id for a in MentorAssignment.query.filter_by(student_id=uid).all()]
        people = Mentor.query.filter(Mentor.id.in_(ids)).all() if ids else []
    else:
        people = list(Mentor.query.all()) + list(Student.query.all())
    for p in people:
        p.is_self = False; p.is_online = is_online(p); p.last_seen_label = last_seen_label(p)
    return render_template('mentors.html', people=people, role=role, current_id=uid)

@app.route('/chat/<string:peer_type>/<int:peer_id>')
@login_required
def chat(peer_type, peer_id):
    role = session['role']; uid = session['user_id']
    if peer_type == 'mentor':
        peer = db.get_or_404(Mentor,  peer_id); pname, pavatar = peer.mentor_name, peer.profile_picture or ''
    else:
        peer = db.get_or_404(Student, peer_id); pname, pavatar = peer.full_name,   peer.profile_picture or ''
    msgs = Message.query.filter(db.or_(
        db.and_(Message.sender_type==role,      Message.sender_id==uid,
                Message.receiver_type==peer_type, Message.receiver_id==peer_id),
        db.and_(Message.sender_type==peer_type,  Message.sender_id==peer_id,
                Message.receiver_type==role,      Message.receiver_id==uid)
    )).order_by(Message.timestamp).all()
    for m in msgs:
        if m.receiver_type == role and m.receiver_id == uid: m.is_read = True
    db.session.commit()
    me = current_user()
    if me is None: session.clear(); return redirect(url_for('index'))
    me_name, me_avatar = get_display(me, role)
    peer_online = is_online(peer); peer_status = 'online' if peer_online else last_seen_label(peer)

    # ── Fetch call records and merge into a unified timeline ──────────────────
    call_records = CallRecord.query.filter(db.or_(
        db.and_(CallRecord.caller_type==role,      CallRecord.caller_id==uid,
                CallRecord.receiver_type==peer_type, CallRecord.receiver_id==peer_id),
        db.and_(CallRecord.caller_type==peer_type,  CallRecord.caller_id==peer_id,
                CallRecord.receiver_type==role,      CallRecord.receiver_id==uid),
    )).order_by(CallRecord.ended_at).all()

    timeline = []
    for m in msgs:
        timeline.append({'kind': 'msg', 'ts': m.timestamp, 'obj': m})
    for cr in call_records:
        is_mine = (cr.caller_type == role and cr.caller_id == uid)
        timeline.append({'kind': 'call', 'ts': cr.ended_at, 'obj': cr, 'is_mine': is_mine})
    timeline.sort(key=lambda x: x['ts'])

    return render_template('chat.html', timeline=timeline, msgs=msgs,
                           peer_type=peer_type, peer_id=peer_id,
                           peer_name=pname, peer_avatar=pavatar,
                           me_name=me_name, me_avatar=me_avatar, role=role, uid=uid,
                           theme=me.theme or 'light', chat_bg=me.chat_bg or '',
                           peer_online=peer_online, peer_status=peer_status)

@app.route('/groups')
@login_required
def groups():
    role = session['role']; uid = session['user_id']
    member_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_type=role, user_id=uid).all()]
    regular_groups = Group.query.filter(
        Group.group_id.in_(member_ids), Group.is_universal == False
    ).all() if member_ids else []
    universal = get_universal_group()
    all_students = Student.query.order_by(Student.full_name).all() if role == 'mentor' else []
    all_mentors  = Mentor.query.order_by(Mentor.mentor_name).all()  if role == 'mentor' else []
    # Pre-serialise for JS consumption in the template
    students_json = [{'id': s.id, 'name': s.full_name, 'sub': s.student_id,
                       'avatar': s.profile_picture or ''} for s in all_students]
    mentors_json  = [{'id': m.id, 'name': m.mentor_name, 'sub': m.mentor_email,
                       'avatar': m.profile_picture or ''} for m in all_mentors]
    return render_template('groups.html',
                           groups=regular_groups, universal=universal,
                           all_students=all_students, all_mentors=all_mentors,
                           all_students_json=students_json,
                           all_mentors_json=mentors_json,
                           role=role, uid=uid)

@app.route('/groups/create', methods=['POST'])
@login_required
def create_group():
    if session['role'] != 'mentor': return redirect(url_for('groups'))
    g = Group(group_name=request.form.get('group_name','').strip(), created_by=session['user_id'],
              group_picture=save_file(request.files.get('group_picture'),'groups') or '',
              is_universal=False)
    db.session.add(g); db.session.flush()
    # Always add the creator
    db.session.add(GroupMember(group_id=g.group_id, user_type='mentor', user_id=session['user_id']))
    # Students
    for sid in request.form.getlist('student_ids'):
        try:
            sid = int(sid)
            if not GroupMember.query.filter_by(group_id=g.group_id, user_type='student', user_id=sid).first():
                db.session.add(GroupMember(group_id=g.group_id, user_type='student', user_id=sid))
        except (ValueError, TypeError):
            pass
    # Other mentors
    for mid in request.form.getlist('mentor_ids'):
        try:
            mid = int(mid)
            if mid != session['user_id'] and not GroupMember.query.filter_by(
                    group_id=g.group_id, user_type='mentor', user_id=mid).first():
                db.session.add(GroupMember(group_id=g.group_id, user_type='mentor', user_id=mid))
        except (ValueError, TypeError):
            pass
    db.session.commit(); flash('Group created!','success')
    return redirect(url_for('group_chat', group_id=g.group_id))

@app.route('/groups/<int:group_id>/add-members', methods=['POST'])
@login_required
def group_add_members(group_id):
    """Add new students and/or mentors to an existing group.
    Allowed for: the group creator, or anyone listed in the group's admins_json."""
    role = session['role']; uid = session['user_id']
    group = db.session.get(Group, group_id)
    if not group: return jsonify({'ok': False, 'error': 'Group not found'}), 404

    # Check permission
    is_creator = (role == 'mentor' and group.created_by == uid)
    admins = json.loads(group.admins_json or '[]')
    if not is_creator and (role + '_' + str(uid)) not in admins:
        return jsonify({'ok': False, 'error': 'Forbidden'}), 403

    data = request.get_json(silent=True) or {}
    student_ids = [int(x) for x in data.get('student_ids', []) if str(x).isdigit()]
    mentor_ids  = [int(x) for x in data.get('mentor_ids',  []) if str(x).isdigit()]

    added = 0
    for sid in student_ids:
        if not GroupMember.query.filter_by(group_id=group_id, user_type='student', user_id=sid).first():
            db.session.add(GroupMember(group_id=group_id, user_type='student', user_id=sid))
            added += 1
    for mid in mentor_ids:
        if not GroupMember.query.filter_by(group_id=group_id, user_type='mentor', user_id=mid).first():
            db.session.add(GroupMember(group_id=group_id, user_type='mentor', user_id=mid))
            added += 1
    db.session.commit()
    return jsonify({'ok': True, 'added': added})

@app.route('/groups/<int:group_id>/set-permissions', methods=['POST'])
@login_required
def group_set_permissions(group_id):
    """Set which members (besides creator) can add new members.
    Only the group creator may call this."""
    role = session['role']; uid = session['user_id']
    group = db.session.get(Group, group_id)
    if not group: return jsonify({'ok': False, 'error': 'Group not found'}), 404
    if not (role == 'mentor' and group.created_by == uid):
        return jsonify({'ok': False, 'error': 'Only the group creator can change permissions'}), 403
    data   = request.get_json(silent=True) or {}
    admins = data.get('admins', [])
    # Validate format: each entry must be "student_N" or "mentor_N"
    valid  = [a for a in admins if isinstance(a, str) and '_' in a]
    group.admins_json = json.dumps(valid)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/groups/<int:group_id>/members')
@login_required
def api_group_members(group_id):
    """Return current members + current admins_json for a group (JSON)."""
    role = session['role']; uid = session['user_id']
    group = db.session.get(Group, group_id)
    if not group: return jsonify({'ok': False, 'error': 'Not found'}), 404
    # Must be a member (or admin) to call this
    if not group.is_universal:
        if not GroupMember.query.filter_by(group_id=group_id, user_type=role, user_id=uid).first():
            return jsonify({'ok': False, 'error': 'Forbidden'}), 403
    members = []
    for gm in GroupMember.query.filter_by(group_id=group_id).all():
        name, avatar = user_info(gm.user_type, gm.user_id)
        members.append({'type': gm.user_type, 'id': gm.user_id,
                         'name': name, 'avatar': avatar or ''})
    admins = json.loads(group.admins_json or '[]')
    return jsonify({'ok': True, 'members': members, 'admins': admins})

@app.route('/groups/<int:group_id>')
@login_required
def group_chat(group_id):
    role = session['role']; uid = session['user_id']
    group = db.get_or_404(Group, group_id)
    if not group.is_universal:
        if not GroupMember.query.filter_by(group_id=group_id, user_type=role, user_id=uid).first():
            flash('Not a member.','error'); return redirect(url_for('groups'))
    msgs    = GroupMessage.query.filter_by(group_id=group_id).order_by(GroupMessage.timestamp).all()
    members = [{'name':n,'avatar':a,'type':m.user_type}
               for m in GroupMember.query.filter_by(group_id=group_id).all()
               for n,a in [user_info(m.user_type, m.user_id)]]
    me = current_user()
    if me is None: session.clear(); return redirect(url_for('index'))
    me_name, me_avatar = get_display(me, role)
    return render_template('group_chat.html', group=group, msgs=msgs, members=members,
                           me_name=me_name, me_avatar=me_avatar, role=role, uid=uid,
                           theme=me.theme or 'light', chat_bg=me.chat_bg or '',
                           user_info=user_info)

@app.route('/feed')
@login_required
def feed():
    role = session['role']; uid = session['user_id']
    me = current_user()
    if me is None: session.clear(); return redirect(url_for('index'))
    enriched = []
    for p in Post.query.order_by(Post.timestamp.desc()).all():
        name, avatar = user_info(p.user_type, p.user_id)
        likes    = PostLike.query.filter_by(post_id=p.post_id).count()
        liked    = bool(PostLike.query.filter_by(post_id=p.post_id, user_type=role, user_id=uid).first())
        saved    = bool(PostSave.query.filter_by(post_id=p.post_id, user_type=role, user_id=uid).first())
        comments = _enrich_comments(p.post_id, role, uid)
        enriched.append({'post':p,'name':name,'avatar':avatar,
                         'likes':likes,'liked':liked,'saved':saved,'comments':comments})
    me_name, me_avatar = get_display(me, role)
    return render_template('feed.html', posts=enriched, role=role, uid=uid,
                           me_name=me_name, me_avatar=me_avatar)

@app.route('/feed/post', methods=['POST'])
@login_required
def create_post():
    content  = request.form.get('content','').strip()
    location = request.form.get('location','').strip()
    gif_url  = request.form.get('gif_url','').strip()
    imgs = []
    for f in request.files.getlist('images'):
        p = save_any(f,'posts',ALLOWED_IMG)
        if p: imgs.append(p)
    if not imgs:
        p = save_any(request.files.get('image'),'posts',ALLOWED_IMG)
        if p: imgs.append(p)
    video = save_any(request.files.get('video'),'videos',ALLOWED_VIDEO)
    af = request.files.get('audio'); audio = save_any(af,'audio',ALLOWED_AUDIO)
    audio_title = request.form.get('audio_title','').strip() or (af.filename.rsplit('.',1)[0] if af and af.filename else '')
    pq   = request.form.get('poll_question','').strip()
    opts = [t.strip() for t in request.form.getlist('poll_options[]') if t.strip()]
    dur  = int(request.form.get('poll_duration',3))
    if not any([content,imgs,video,audio,gif_url,pq]):
        flash('Post cannot be empty.','error'); return redirect(url_for('feed'))
    db.session.add(Post(
        user_type=session['role'], user_id=session['user_id'],
        content=content, location=location,
        images_json=json.dumps(imgs) if imgs else '',
        video=video or '', audio=audio or '', audio_title=audio_title, gif_url=gif_url,
        poll_question=pq,
        poll_options_json=json.dumps([{'text':t,'votes':0} for t in opts]) if pq and len(opts)>=2 else '',
        poll_expires_at=datetime.utcnow()+timedelta(days=dur) if pq and len(opts)>=2 else None))
    db.session.commit(); return redirect(url_for('feed'))

@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def post_like(post_id):
    role=session['role']; uid=session['user_id']
    ex = PostLike.query.filter_by(post_id=post_id, user_type=role, user_id=uid).first()
    if ex: db.session.delete(ex)
    else: db.session.add(PostLike(post_id=post_id, user_type=role, user_id=uid))
    db.session.commit()
    return jsonify({'likes': PostLike.query.filter_by(post_id=post_id).count(), 'liked': not ex})

@app.route('/post/<int:post_id>/save', methods=['POST'])
@login_required
def post_save_route(post_id):
    role=session['role']; uid=session['user_id']
    ex = PostSave.query.filter_by(post_id=post_id, user_type=role, user_id=uid).first()
    if ex: db.session.delete(ex); db.session.commit(); return jsonify({'saved':False})
    db.session.add(PostSave(post_id=post_id, user_type=role, user_id=uid)); db.session.commit()
    return jsonify({'saved':True})

@app.route('/post/<int:post_id>/likes')
@login_required
def post_likes_list(post_id):
    likes = PostLike.query.filter_by(post_id=post_id).all()
    out   = []
    for lk in likes:
        name, av = user_info(lk.user_type, lk.user_id)
        out.append({'name': name, 'avatar': av or None})
    return jsonify({'ok': True, 'likes': out, 'count': len(out)})

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def post_comment(post_id):
    data      = request.get_json(silent=True) or {}
    text      = data.get('comment', '').strip()
    parent_id = data.get('parent_id', None)
    if not text: return jsonify({'error': 'empty'}), 400
    role = session['role']; uid = session['user_id']
    c = PostComment(post_id=post_id, user_type=role, user_id=uid, comment=text,
                    parent_id=int(parent_id) if parent_id else None)
    db.session.add(c); db.session.commit()
    name, avatar = user_info(role, uid)
    if not parent_id:
        try:
            post_obj = db.session.get(Post, post_id)
            if post_obj:
                post_owner_name, _ = user_info(post_obj.user_type, post_obj.user_id)
                bridge_text = f'💬 {name} commented on {post_owner_name}\'s post: "{text[:120]}"'
                post_to_universal_group(role, uid, bridge_text, msg_type='system')
        except Exception as e: app.logger.warning(f'Universal group bridge error: {e}')
    return jsonify({'id': c.id, 'name': name, 'avatar': avatar, 'comment': text,
                    'time': c.timestamp.strftime('%b %d · %H:%M'), 'parent_id': parent_id})

@app.route('/post/<int:post_id>/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def comment_like_toggle(post_id, comment_id):
    role = session['role']; uid = session['user_id']
    ex   = CommentLike.query.filter_by(comment_id=comment_id, user_type=role, user_id=uid).first()
    if ex: db.session.delete(ex); liked = False
    else: db.session.add(CommentLike(comment_id=comment_id, user_type=role, user_id=uid)); liked = True
    db.session.commit()
    count = CommentLike.query.filter_by(comment_id=comment_id).count()
    return jsonify({'ok': True, 'liked': liked, 'count': count})

@app.route('/post/<int:post_id>/comment/<int:comment_id>/likes')
@login_required
def comment_likes_list(post_id, comment_id):
    likes = CommentLike.query.filter_by(comment_id=comment_id).all()
    out   = []
    for lk in likes:
        name, av = user_info(lk.user_type, lk.user_id)
        out.append({'name': name, 'avatar': av or None})
    return jsonify({'ok': True, 'likes': out})

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def post_delete(post_id):
    role=session['role']; uid=session['user_id']
    post = db.get_or_404(Post, post_id)
    if post.user_id != uid and role != 'admin': return jsonify({'error':'forbidden'}), 403
    for cmt in PostComment.query.filter_by(post_id=post_id).all():
        CommentLike.query.filter_by(comment_id=cmt.id).delete()
    for M in [PostLike, PostComment, PostSave, PollVote]: M.query.filter_by(post_id=post_id).delete()
    db.session.delete(post); db.session.commit(); return jsonify({'deleted':True})

@app.route('/post/<int:post_id>/edit', methods=['POST'])
@login_required
def post_edit(post_id):
    post = db.get_or_404(Post, post_id)
    if post.user_id != session['user_id']: return jsonify({'error':'forbidden'}), 403
    data = request.get_json(silent=True) or {}; nc = data.get('content','').strip()
    if not nc: return jsonify({'error':'empty'}), 400
    post.content = nc; db.session.commit(); return jsonify({'content':nc})

@app.route('/post/<int:post_id>/poll/vote', methods=['POST'])
@login_required
def post_poll_vote(post_id):
    role=session['role']; uid=session['user_id']
    if PollVote.query.filter_by(post_id=post_id, user_type=role, user_id=uid).first():
        return jsonify({'error':'already voted'}), 400
    post = db.get_or_404(Post, post_id)
    idx = int((request.get_json(silent=True) or {}).get('option',0))
    try:
        opts = json.loads(post.poll_options_json or '[]')
        if 0 <= idx < len(opts):
            opts[idx]['votes'] = opts[idx].get('votes',0) + 1
            post.poll_options_json = json.dumps(opts)
            db.session.add(PollVote(post_id=post_id, user_type=role, user_id=uid, option_idx=idx))
            db.session.commit()
    except Exception: pass
    return jsonify({'voted':True, 'poll':post.poll})

@app.route('/feed/like/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id): return post_like(post_id)

@app.route('/feed/comment/<int:post_id>', methods=['POST'])
@login_required
def comment_post(post_id):
    text = request.form.get('comment','').strip()
    if not text: return jsonify({'error':'empty'}), 400
    c = PostComment(post_id=post_id, user_type=session['role'], user_id=session['user_id'], comment=text)
    db.session.add(c); db.session.commit()
    name, avatar = user_info(session['role'], session['user_id'])
    return jsonify({'name':name,'avatar':avatar,'comment':text,'time':c.timestamp.strftime('%b %d, %H:%M')})

@app.route('/profile')
@login_required
def profile():
    role = session['role']; uid = session['user_id']
    user = current_user()
    if user is None: session.clear(); return redirect(url_for('index'))
    group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_type=role, user_id=uid).all()]
    saved_ids   = [s.post_id for s in PostSave.query.filter_by(user_type=role, user_id=uid).all()]
    saved_posts = []
    if saved_ids:
        for p in Post.query.filter(Post.post_id.in_(saved_ids)).order_by(Post.timestamp.desc()).all():
            pname, pavatar = user_info(p.user_type, p.user_id)
            saved_posts.append({'post': p, 'name': pname, 'avatar': pavatar})
    return render_template('profile.html', user=user, role=role,
                           posts=Post.query.filter_by(user_type=role, user_id=uid).order_by(Post.timestamp.desc()).all(),
                           groups=Group.query.filter(Group.group_id.in_(group_ids)).all(),
                           saved_posts=saved_posts)

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    role = session['role']; user = current_user()
    if user is None: session.clear(); return redirect(url_for('index'))
    result = save_file(request.files.get('profile_picture'),'profiles')
    if result: user.profile_picture = result
    theme = request.form.get('theme')
    if theme in ('light','dark','picture'): user.theme = theme
    bg_result = save_any(request.files.get('chat_bg'),'chat_bgs',ALLOWED_IMG)
    if bg_result: user.chat_bg = bg_result
    if role == 'student':
        name = request.form.get('full_name','').strip()
        if name: user.full_name = name; session['name'] = name
    elif role == 'mentor':
        name = request.form.get('mentor_name','').strip(); bio = request.form.get('bio','').strip()
        if name: user.mentor_name = name; session['name'] = name
        if bio: user.bio = bio
    db.session.commit(); flash('Profile updated!','success')
    return redirect(url_for('profile'))

@app.route('/logout')
def logout():
    role = session.get('role'); uid = session.get('user_id')
    if role in ('student','mentor') and uid:
        try:
            old = datetime.utcnow() - timedelta(days=1)
            if role == 'student':  Student.query.filter_by(id=uid).update({'last_seen': old})
            elif role == 'mentor': Mentor.query.filter_by(id=uid).update({'last_seen': old})
            db.session.commit(); socketio.emit('user_offline', {'role': role, 'uid': uid})
        except Exception: db.session.rollback()
    session.clear(); return redirect(url_for('index'))

@app.route('/api/messages/<string:peer_type>/<int:peer_id>')
@login_required
def api_messages(peer_type, peer_id):
    role=session['role']; uid=session['user_id']
    msgs = Message.query.filter(db.or_(
        db.and_(Message.sender_type==role,      Message.sender_id==uid,
                Message.receiver_type==peer_type, Message.receiver_id==peer_id),
        db.and_(Message.sender_type==peer_type,  Message.sender_id==peer_id,
                Message.receiver_type==role,      Message.receiver_id==uid)
    )).order_by(Message.timestamp).all()
    return jsonify([{
        'id': m.message_id, 'sender_type': m.sender_type, 'sender_id': m.sender_id,
        'text': m.message_text, 'time': m.timestamp.strftime('%H:%M'),
        'is_me': m.sender_type==role and m.sender_id==uid,
        'msg_type': m.msg_type or 'text', 'meta': m.meta, 'is_read': m.is_read,
    } for m in msgs])

@app.route('/api/contacts')
@login_required
def api_contacts():
    role = session['role']; uid = session['user_id']
    try:
        if role == 'mentor':
            ids = [a.student_id for a in MentorAssignment.query.filter_by(mentor_id=uid).all()]
            peers = [('student',s) for s in (Student.query.filter(Student.id.in_(ids)).all() if ids else Student.query.all())]
        elif role == 'student':
            ids = [a.mentor_id for a in MentorAssignment.query.filter_by(student_id=uid).all()]
            peers = [('mentor',m) for m in (Mentor.query.filter(Mentor.id.in_(ids)).all() if ids else Mentor.query.all())]
        else:
            peers = [('mentor',m) for m in Mentor.query.all()] + [('student',s) for s in Student.query.all()]
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'ok':False,'error':str(e),'contacts':[]}), 500

    def _time_label(dt):
        diff = datetime.utcnow() - dt
        if diff.days == 0: return dt.strftime('%H:%M')
        if diff.days == 1: return 'Yesterday'
        if diff.days < 7:  return dt.strftime('%A')
        return dt.strftime('%d/%m/%Y')

    def _preview_text(m):
        if not m: return ''
        t = m.msg_type or 'text'
        if t == 'deleted':  return '🚫 This message was deleted'
        if t == 'image':    return '📷 Photo'
        if t == 'video':    return '🎥 Video'
        if t == 'audio':    return '🎵 Audio'
        if t == 'voice':    return '🎙 Voice message'
        if t == 'document': return f"📄 {(m.meta or {}).get('name','Document')}"
        return m.message_text[:60] if m.message_text else ''

    result = []
    for peer_type, peer in peers:
        peer_id   = peer.id
        peer_name = peer.full_name if peer_type=='student' else peer.mentor_name
        peer_av   = peer.profile_picture or ''
        online    = is_online(peer)
        last = Message.query.filter(db.or_(
            db.and_(Message.sender_type==role,      Message.sender_id==uid,
                    Message.receiver_type==peer_type, Message.receiver_id==peer_id),
            db.and_(Message.sender_type==peer_type,  Message.sender_id==peer_id,
                    Message.receiver_type==role,      Message.receiver_id==uid)
        )).order_by(Message.timestamp.desc()).first()
        unread = Message.query.filter_by(sender_type=peer_type, sender_id=peer_id,
                                         receiver_type=role, receiver_id=uid, is_read=False).count()
        result.append({
            'peer_type': peer_type, 'peer_id': peer_id, 'name': peer_name, 'avatar': peer_av,
            'online': online, 'last_seen': last_seen_label(peer),
            'last_msg': _preview_text(last),
            'last_msg_mine': (last.sender_type==role and last.sender_id==uid) if last else False,
            'last_time': _time_label(last.timestamp) if last else '',
            'unread': unread, '_sort': last.timestamp.isoformat() if last else '0000',
        })
    result.sort(key=lambda x: x['_sort'], reverse=True)
    for r in result: del r['_sort']
    return jsonify({'ok':True,'contacts':result})

# ── SocketIO ──────────────────────────────────────────────────────────────────
@socketio.on('join')
def on_join(data):
    room = data.get('room'); join_room(room)
    emit('status', {'msg': f'Joined {room}'}, to=room)
    role = session.get('role'); uid = session.get('user_id')
    if role and uid and room == f'user_{role}_{uid}':
        touch_last_seen(role, uid); socketio.emit('user_online', {'role': role, 'uid': uid})

@socketio.on('leave')
def on_leave(data): leave_room(data.get('room'))

@socketio.on('disconnect')
def on_disconnect():
    role = session.get('role'); uid = session.get('user_id')
    if role in ('student','mentor') and uid:
        touch_last_seen(role, uid); socketio.emit('user_offline', {'role': role, 'uid': uid})

@socketio.on('heartbeat')
def on_heartbeat(data=None):
    role = session.get('role'); uid = session.get('user_id')
    if role and uid:
        touch_last_seen(role, uid); emit('heartbeat_ack', {'ok': True})

@socketio.on('typing_start')
def h_typing_start(d): emit('typing_start', d, to=d.get('room'))
@socketio.on('typing_stop')
def h_typing_stop(d):  emit('typing_stop',  d, to=d.get('room'))

@socketio.on('send_message')
def handle_message(data):
    role = session.get('role'); uid = session.get('user_id')
    text      = data.get('text', '').strip()
    msg_type  = data.get('msg_type', 'text')
    meta      = data.get('meta', {}) or {}
    if msg_type == 'text' and not text: return
    if msg_type != 'text' and not meta.get('path'): return
    display_text = text if msg_type == 'text' else {
        'image': '📷 Photo', 'video': '🎥 Video',
        'audio': '🎵 Audio', 'voice': '🎙 Voice message',
        'document': f"📄 {meta.get('name','Document')}",
    }.get(msg_type, text) or meta.get('name','')
    msg = Message(sender_type=role, sender_id=uid,
                  receiver_type=data.get('peer_type'), receiver_id=data.get('peer_id'),
                  message_text=display_text, msg_type=msg_type,
                  meta_json=json.dumps(meta) if meta else None)
    db.session.add(msg); db.session.commit()
    name, avatar = user_info(role, uid)
    room = f"chat_{min(uid, data.get('peer_id',0))}_{max(uid, data.get('peer_id',0))}_{role}_{data.get('peer_type','')}"
    emit('new_message', {'id': msg.message_id, 'text': display_text,
                         'sender_type': role, 'sender_id': uid,
                         'name': name, 'avatar': avatar,
                         'time': msg.timestamp.strftime('%H:%M'),
                         'msg_type': msg_type, 'meta': meta}, to=room)

@socketio.on('send_group_message')
def handle_group_message(data):
    role     = session.get('role'); uid = session.get('user_id')
    text     = data.get('text', '').strip()
    msg_type = data.get('msg_type', 'chat')
    meta     = data.get('meta', {}) or {}
    if msg_type == 'chat' and not text: return
    if msg_type not in ('chat', 'story_reply', 'system') and not meta.get('path'): return
    display_text = text if msg_type in ('chat','story_reply','system') else {
        'image': '📷 Photo', 'video': '🎥 Video',
        'audio': '🎵 Audio', 'voice': '🎙 Voice message',
        'document': f"📄 {meta.get('name','Document')}",
    }.get(msg_type, text) or meta.get('name','')
    msg = GroupMessage(group_id=data.get('group_id'), sender_type=role, sender_id=uid,
                       message_text=display_text, msg_type=msg_type,
                       meta_json=json.dumps(meta) if meta else None)
    db.session.add(msg); db.session.commit()
    name, avatar = user_info(role, uid)
    emit('new_group_message', {'id': msg.message_id, 'text': display_text,
                               'sender_type': role, 'sender_id': uid,
                               'name': name, 'avatar': avatar,
                               'time': msg.timestamp.strftime('%H:%M'),
                               'msg_type': msg_type, 'meta': meta},
         to=f"group_{data.get('group_id')}")

@socketio.on('message_deleted')
def handle_message_deleted(data):
    room = data.get('room')
    if room: emit('message_deleted', {'message_id': data.get('message_id')}, to=room, include_self=False)

@socketio.on('group_message_deleted')
def handle_group_message_deleted(data):
    group_id = data.get('group_id')
    if group_id: emit('group_message_deleted', {'message_id': data.get('message_id')},
                      to=f"group_{group_id}", include_self=False)

@socketio.on('webrtc_offer')
def h_offer(d):    emit('webrtc_offer',   d, to=d['room'])
@socketio.on('webrtc_answer')
def h_answer(d):   emit('webrtc_answer',  d, to=d['room'])
@socketio.on('webrtc_ice')
def h_ice(d):      emit('webrtc_ice',     d, to=d['room'])
@socketio.on('call_request')
def h_call(d):     emit('incoming_call',  d, to=d['target_room'])
@socketio.on('call_accepted')
def h_accepted(d): emit('call_accepted',  d, to=d['caller_room'])
@socketio.on('call_declined')
def h_declined(d): emit('call_declined',  d, to=d['caller_room'])
@socketio.on('call_ended')
def h_ended(d):    emit('call_ended',     d, to=d['room'])

@socketio.on('call_missed_notify')
def h_call_missed(d):
    """Relay missed-call notification to the receiver's personal room."""
    target = d.get('target_room')
    if target: emit('call_missed_notify', d, to=target)

# ── Init ──────────────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()
        from sqlalchemy import text
        migrations = [
            "ALTER TABLE group_messages ADD COLUMN meta_json TEXT",
            "ALTER TABLE messages ADD COLUMN msg_type VARCHAR(20) DEFAULT 'text'",
            "ALTER TABLE messages ADD COLUMN meta_json TEXT",
            "ALTER TABLE post_comments ADD COLUMN parent_id INTEGER",
            # ── Story feature additions ────────────────────────
            "ALTER TABLE stories ADD COLUMN privacy VARCHAR(20) NOT NULL DEFAULT 'public'",
            # ── Group permission additions ─────────────────────
            "ALTER TABLE groups ADD COLUMN admins_json TEXT DEFAULT '[]'",
            # ── Call records (auto-created by db.create_all) ───
            # (no ALTER needed — new table, handled by db.create_all above)
        ]
        for sql in migrations:
            try:
                with db.engine.connect() as conn:
                    conn.execute(text(sql)); conn.commit()
            except Exception:
                pass
        if not Admin.query.filter_by(username='admin').first():
            db.session.add(Admin(username='admin', password_hash=generate_password_hash('admin123')))
            db.session.commit(); print('✅ admin / admin123')
        ensure_universal_group()
        print('✅ Universal community group ready.')
    _start_promotion_scheduler()

@app.context_processor
def inject_globals():
    return dict(current_user=current_user, hasattr=hasattr, session=session)

from stories_routes import stories_bp
app.register_blueprint(stories_bp)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
