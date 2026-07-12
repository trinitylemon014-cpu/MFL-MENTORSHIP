"""
models.py – Empower Mentorship Platform

Single source of truth for all SQLAlchemy models.
Imports db from extensions.py ONLY — no circular imports ever.

Both app.py and stories_routes.py import from here:
    from models import Student, Mentor, Story, StoryView, ...
"""

import json
from datetime import datetime
from extensions import db


class Student(db.Model):
    __tablename__      = 'students'
    id                 = db.Column(db.Integer,    primary_key=True)
    student_id         = db.Column(db.String(20), unique=True, nullable=False)
    full_name          = db.Column(db.String(100), nullable=False)
    class_name         = db.Column(db.String(50))
    school             = db.Column(db.String(100))
    last_promoted_year = db.Column(db.Integer,    nullable=True)
    profile_picture    = db.Column(db.String(200), default='')
    theme              = db.Column(db.String(20),  default='light')
    chat_bg            = db.Column(db.String(300), default='')
    last_seen          = db.Column(db.DateTime,    nullable=True)
    created_at         = db.Column(db.DateTime,    default=datetime.utcnow)


class Mentor(db.Model):
    __tablename__   = 'mentors'
    id              = db.Column(db.Integer,    primary_key=True)
    mentor_name     = db.Column(db.String(100), nullable=False)
    mentor_email    = db.Column(db.String(150), unique=True, nullable=False)
    password_hash   = db.Column(db.String(256), nullable=True)
    password_set    = db.Column(db.Boolean,     default=False)
    profile_picture = db.Column(db.String(200), default='')
    theme           = db.Column(db.String(20),  default='light')
    chat_bg         = db.Column(db.String(300), default='')
    bio             = db.Column(db.String(300), default='')
    last_seen       = db.Column(db.DateTime,    nullable=True)
    created_at      = db.Column(db.DateTime,    default=datetime.utcnow)


class MentorAssignment(db.Model):
    __tablename__ = 'mentor_assignments'
    id         = db.Column(db.Integer, primary_key=True)
    mentor_id  = db.Column(db.Integer, db.ForeignKey('mentors.id'),  nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)


class Message(db.Model):
    __tablename__ = 'messages'
    message_id    = db.Column(db.Integer, primary_key=True)
    sender_type   = db.Column(db.String(10))
    sender_id     = db.Column(db.Integer)
    receiver_type = db.Column(db.String(10))
    receiver_id   = db.Column(db.Integer)
    message_text  = db.Column(db.Text, nullable=False)
    timestamp     = db.Column(db.DateTime, default=datetime.utcnow)
    is_read       = db.Column(db.Boolean,  default=False)
    msg_type      = db.Column(db.String(20), default='text', nullable=True)
    meta_json     = db.Column(db.Text, nullable=True)

    @property
    def meta(self):
        if self.meta_json:
            try: return json.loads(self.meta_json)
            except: pass
        return {}


class Group(db.Model):
    __tablename__ = 'groups'
    group_id      = db.Column(db.Integer, primary_key=True)
    group_name    = db.Column(db.String(100), nullable=False)
    created_by    = db.Column(db.Integer, db.ForeignKey('mentors.id'), nullable=True)
    group_picture = db.Column(db.String(200), default='')
    is_universal  = db.Column(db.Boolean,     default=False)
    admins_json   = db.Column(db.Text,         default='[]')
    created_at    = db.Column(db.DateTime,    default=datetime.utcnow)


class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id        = db.Column(db.Integer, primary_key=True)
    group_id  = db.Column(db.Integer, db.ForeignKey('groups.group_id'))
    user_type = db.Column(db.String(10))
    user_id   = db.Column(db.Integer)


class GroupMessage(db.Model):
    __tablename__ = 'group_messages'
    message_id   = db.Column(db.Integer, primary_key=True)
    group_id     = db.Column(db.Integer, db.ForeignKey('groups.group_id'))
    sender_type  = db.Column(db.String(10))
    sender_id    = db.Column(db.Integer)
    message_text = db.Column(db.Text, nullable=False)
    msg_type     = db.Column(db.String(20), default='chat')
    meta_json    = db.Column(db.Text, nullable=True)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def meta(self):
        if self.meta_json:
            try: return json.loads(self.meta_json)
            except: pass
        return {}


class Post(db.Model):
    __tablename__     = 'posts'
    post_id           = db.Column(db.Integer, primary_key=True)
    user_type         = db.Column(db.String(10))
    user_id           = db.Column(db.Integer)
    content           = db.Column(db.Text)
    location          = db.Column(db.String(150), default='')
    image             = db.Column(db.String(200), default='')
    images_json       = db.Column(db.Text,        default='')
    video             = db.Column(db.String(300), default='')
    audio             = db.Column(db.String(300), default='')
    audio_title       = db.Column(db.String(200), default='')
    gif_url           = db.Column(db.String(500), default='')
    poll_question     = db.Column(db.String(200), default='')
    poll_options_json = db.Column(db.Text,        default='')
    poll_expires_at   = db.Column(db.DateTime,    nullable=True)
    timestamp         = db.Column(db.DateTime,    default=datetime.utcnow)

    @property
    def images(self):
        if self.images_json:
            try: return json.loads(self.images_json)
            except: pass
        return [self.image] if self.image else []

    @property
    def poll(self):
        if not self.poll_question: return None
        try:    opts = json.loads(self.poll_options_json or '[]')
        except: opts = []
        total   = sum(o.get('votes', 0) for o in opts)
        options = [{'text': o.get('text', ''), 'votes': o.get('votes', 0),
                    'pct': round(o.get('votes', 0) / total * 100) if total else 0}
                   for o in opts]
        now = datetime.utcnow(); exp = self.poll_expires_at
        if exp and exp > now:
            h = int((exp - now).total_seconds() // 3600)
            ends = f"{h}h left" if h < 24 else f"{(exp - now).days}d left"
        else:
            ends = 'Ended'
        return {'question': self.poll_question, 'options': options,
                'total_votes': total, 'ends': ends}


class PostLike(db.Model):
    __tablename__ = 'post_likes'
    id        = db.Column(db.Integer, primary_key=True)
    post_id   = db.Column(db.Integer, db.ForeignKey('posts.post_id'))
    user_type = db.Column(db.String(10))
    user_id   = db.Column(db.Integer)


class PostComment(db.Model):
    __tablename__ = 'post_comments'
    id        = db.Column(db.Integer, primary_key=True)
    post_id   = db.Column(db.Integer, db.ForeignKey('posts.post_id'))
    user_type = db.Column(db.String(10))
    user_id   = db.Column(db.Integer)
    comment   = db.Column(db.Text, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('post_comments.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class PostSave(db.Model):
    __tablename__ = 'post_saves'
    id        = db.Column(db.Integer, primary_key=True)
    post_id   = db.Column(db.Integer, db.ForeignKey('posts.post_id'))
    user_type = db.Column(db.String(10))
    user_id   = db.Column(db.Integer)


class CommentLike(db.Model):
    __tablename__ = 'comment_likes'
    id         = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('post_comments.id'))
    user_type  = db.Column(db.String(10))
    user_id    = db.Column(db.Integer)
    __table_args__ = (
        db.UniqueConstraint('comment_id', 'user_type', 'user_id', name='uq_clike'),
    )


class PollVote(db.Model):
    __tablename__ = 'poll_votes'
    id         = db.Column(db.Integer, primary_key=True)
    post_id    = db.Column(db.Integer, db.ForeignKey('posts.post_id'))
    user_type  = db.Column(db.String(10))
    user_id    = db.Column(db.Integer)
    option_idx = db.Column(db.Integer)


class Admin(db.Model):
    __tablename__ = 'admins'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(256))


class Story(db.Model):
    """
    One row = one story slide.
    privacy: 'public' | 'close_friends' | 'only_me'
    """
    __tablename__ = 'stories'
    id         = db.Column(db.Integer,    primary_key=True)
    user_type  = db.Column(db.String(10), nullable=False)
    user_id    = db.Column(db.Integer,    nullable=False)
    story_type = db.Column(db.String(10), default='photo')
    media_path = db.Column(db.String(300), nullable=True)
    caption    = db.Column(db.String(150), nullable=True)
    bg         = db.Column(db.String(30),  default='gradient1')
    text_body  = db.Column(db.String(200), nullable=True)
    privacy    = db.Column(db.String(20),  default='public', nullable=False)
    expires_at = db.Column(db.DateTime,    nullable=False)
    created_at = db.Column(db.DateTime,    default=datetime.utcnow)

    # relationship to views (cascade delete so cleanup is automatic)
    views = db.relationship(
        'StoryView',
        backref='story',
        cascade='all, delete-orphan',
        lazy='dynamic',
    )


class StoryView(db.Model):
    """
    Tracks unique viewers of a story slide.
    The story owner's own views are never recorded here.
    """
    __tablename__ = 'story_views'
    id          = db.Column(db.Integer,   primary_key=True)
    story_id    = db.Column(db.Integer,   db.ForeignKey('stories.id', ondelete='CASCADE'),
                            nullable=False)
    viewer_type = db.Column(db.String(10), nullable=False)
    viewer_id   = db.Column(db.Integer,   nullable=False)
    viewed_at   = db.Column(db.DateTime,  default=datetime.utcnow, nullable=False)

    __table_args__ = (
        # Each user can only be counted once per slide
        db.UniqueConstraint('story_id', 'viewer_type', 'viewer_id', name='uq_story_viewer'),
    )


class CallRecord(db.Model):
    """
    Persists every call attempt so both parties see the full call history
    (ended, missed, no-answer, declined) exactly like WhatsApp / Instagram.
    """
    __tablename__  = 'call_records'
    id             = db.Column(db.Integer,    primary_key=True)
    caller_type    = db.Column(db.String(10), nullable=False)
    caller_id      = db.Column(db.Integer,    nullable=False)
    receiver_type  = db.Column(db.String(10), nullable=False)
    receiver_id    = db.Column(db.Integer,    nullable=False)
    # 'ended' | 'missed' | 'no_answer' | 'declined'
    status         = db.Column(db.String(20), nullable=False, default='ended')
    called_at      = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)
    ended_at       = db.Column(db.DateTime,   nullable=False, default=datetime.utcnow)
    duration_secs  = db.Column(db.Integer,    nullable=False, default=0)