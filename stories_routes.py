"""
stories_routes.py – Empower Mentorship Platform

Models are imported directly from models.py.
models.py only depends on extensions.py.
No sys.modules, no lazy imports, no circular imports — ever.
"""

import os
import uuid
import requests as http_requests
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, request, jsonify, current_app, session
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Story, StoryView, Student, Mentor, MentorAssignment

stories_bp = Blueprint('stories', __name__)

GIPHY_API_KEY  = 'MuAf6Js500TU610ru5J6zJQBcPx4JfsN'
PHOTO_EXTS     = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
VIDEO_EXTS     = {'mp4', 'mov', 'webm'}
VALID_PRIVACY  = {'public', 'close_friends', 'only_me'}


# ── Pure helpers ───────────────────────────────────────────────────────────────

def _static_url(path):
    return f"/static/{path.lstrip('/')}" if path else None

def _ext(filename):
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

def _allowed(filename, allowed_set):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_set

def _save_story_file(file_obj, subfolder='stories'):
    ext   = file_obj.filename.rsplit('.', 1)[-1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    dest  = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(dest, exist_ok=True)
    file_obj.save(os.path.join(dest, fname))
    return f"uploads/{subfolder}/{fname}"

def _time_ago(dt):
    if not dt: return ''
    s = int((datetime.utcnow() - dt).total_seconds())
    if s < 60:    return 'Just now'
    if s < 3600:  return f"{s // 60}m ago"
    if s < 86400: return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"

def _parse_user_ref(user_ref):
    """
    Accepts: 'me', 'mentor/3', 'student/7', 'mentor_3', '3'
    Returns (role_str, int_id) or ('', None) on failure.
    """
    user_ref = str(user_ref).strip()
    if user_ref == 'me':
        return session.get('role', ''), session.get('user_id')
    for sep in ('/', '_'):
        if sep in user_ref:
            parts = user_ref.split(sep, 1)
            try: return parts[0], int(parts[1])
            except (ValueError, IndexError): pass
    try: return session.get('role', ''), int(user_ref)
    except ValueError: pass
    return session.get('role', ''), session.get('user_id')


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_current_identity():
    role   = session.get('role', '')
    uid    = session.get('user_id')
    name   = session.get('name', 'Unknown')
    avatar = ''
    try:
        if role == 'student':
            u = db.session.get(Student, uid)
            if u: avatar = u.profile_picture or ''
        elif role == 'mentor':
            u = db.session.get(Mentor, uid)
            if u: avatar = u.profile_picture or ''
    except Exception:
        pass
    return role, uid, name, avatar

def _user_display(role, uid):
    try:
        if role == 'student':
            u = db.session.get(Student, uid)
            return (u.full_name, u.profile_picture or '') if u else ('Unknown', '')
        if role == 'mentor':
            u = db.session.get(Mentor, uid)
            return (u.mentor_name, u.profile_picture or '') if u else ('Unknown', '')
    except Exception:
        pass
    return ('Unknown', '')

def _are_connected(role_a, id_a, role_b, id_b):
    """True if both users are the same person, or share a mentor-student assignment."""
    if role_a == role_b and id_a == id_b:
        return True
    try:
        if role_a == 'mentor' and role_b == 'student':
            return bool(MentorAssignment.query.filter_by(
                mentor_id=id_a, student_id=id_b).first())
        if role_a == 'student' and role_b == 'mentor':
            return bool(MentorAssignment.query.filter_by(
                mentor_id=id_b, student_id=id_a).first())
    except Exception:
        pass
    return False

def _record_view(story, viewer_role, viewer_id):
    """
    Persist a StoryView row for this viewer (idempotent via UNIQUE constraint).
    Skips if the viewer is the story owner.
    """
    if story.user_type == viewer_role and story.user_id == viewer_id:
        return  # owner's own view is never recorded
    try:
        sv = StoryView(
            story_id=story.id,
            viewer_type=viewer_role,
            viewer_id=viewer_id,
        )
        db.session.add(sv)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()  # already viewed — silently skip
    except Exception as e:
        current_app.logger.warning('StoryView insert failed: %s', e)
        try: db.session.rollback()
        except Exception: pass


# ── Auth decorator ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'role' not in session:
            return jsonify({'ok': False, 'error': 'Not logged in'}), 401
        return f(*args, **kwargs)
    return decorated


# ── Story creation ─────────────────────────────────────────────────────────────

def _do_create_story():
    try:
        role, uid, _, _ = _get_current_identity()
        if not role or not uid:
            return jsonify({'ok': False, 'error': 'Session expired'}), 401

        story_type = (request.form.get('story_type') or request.form.get('type', 'photo')).strip()
        caption    = (request.form.get('caption', '') or '').strip()[:150]
        bg         = (request.form.get('bg', 'gradient1') or 'gradient1').strip()
        text_body  = (request.form.get('text_body', '') or '').strip()[:200]
        privacy    = (request.form.get('privacy', 'public') or 'public').strip()
        if privacy not in VALID_PRIVACY:
            privacy = 'public'

        media_path = None
        file = request.files.get('file') or request.files.get('media')

        if story_type in ('photo', 'video'):
            if file and file.filename:
                allowed_set = PHOTO_EXTS if story_type == 'photo' else VIDEO_EXTS
                if not _allowed(file.filename, allowed_set):
                    return jsonify({'ok': False,
                                    'error': f'Invalid file type .{_ext(file.filename)}'}), 400
                media_path = _save_story_file(file)
            else:
                return jsonify({'ok': False, 'error': f'No file for {story_type} story'}), 400
        elif story_type == 'text':
            if not text_body and not caption:
                return jsonify({'ok': False, 'error': 'Text story cannot be empty'}), 400
        else:
            return jsonify({'ok': False, 'error': f'Unknown story type: {story_type}'}), 400

        story = Story(
            user_type=role, user_id=uid, story_type=story_type,
            media_path=media_path, caption=caption or None, bg=bg,
            text_body=text_body or None, privacy=privacy,
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        db.session.add(story)
        db.session.commit()
        return jsonify({'ok': True, 'story_id': story.id,
                        'media_url': _static_url(media_path),
                        'expires_at': story.expires_at.isoformat()})
    except Exception as e:
        current_app.logger.exception('_do_create_story error: %s', e)
        try: db.session.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Routes ─────────────────────────────────────────────────────────────────────

@stories_bp.route('/api/stories', methods=['GET'])
@login_required
def get_stories():
    """
    Returns one entry per user who has at least one active story.
    The current user's own stories are ALWAYS included (placed first).
    Privacy gate:
      - 'only_me'       → visible only to owner
      - 'close_friends' → visible to owner + connected users
      - 'public'        → visible to everyone
    """
    try:
        current_role, current_uid, _, _ = _get_current_identity()
        now = datetime.utcnow()

        all_stories = (
            db.session.query(Story)
            .filter(Story.expires_at > now)
            .order_by(Story.id.desc())
            .all()
        )

        # Group by (user_type, user_id) — newest slide first per user
        stories_by_user: dict[tuple, list] = {}
        for s in all_stories:
            key = (s.user_type, s.user_id)
            stories_by_user.setdefault(key, []).append(s)

        seen_ids  = set(int(x) for x in session.get('seen_story_ids', []))
        my_entry  = None
        others    = []

        for (user_type, user_id), user_stories in stories_by_user.items():
            is_mine = (user_type == current_role and user_id == current_uid)

            # ── Privacy gate ──────────────────────────────────────────────
            # We expose a user's circle only if at least one of their slides
            # is visible to the current viewer.
            if not is_mine:
                visible_slides = []
                for s in user_stories:
                    priv = s.privacy or 'public'
                    if priv == 'only_me':
                        continue  # never shown to others
                    if priv == 'close_friends':
                        if not _are_connected(current_role, current_uid, user_type, user_id):
                            continue
                    visible_slides.append(s)
                if not visible_slides:
                    continue  # nothing to show from this user
                user_stories = visible_slides

            newest = user_stories[0]
            all_seen = all(s.id in seen_ids for s in user_stories)
            total_views = 0
            if is_mine:
                total_views = StoryView.query.filter(
                    StoryView.story_id.in_([s.id for s in user_stories])
                ).count()

            name, avatar = _user_display(user_type, user_id)
            entry = {
                'story_id':    newest.id,
                'user_id':     user_id,
                'user_type':   user_type,
                'name':        'Your Story' if is_mine else name,
                'avatar':      avatar or None,
                'seen':        all_seen,
                'is_mine':     is_mine,
                'slides_count': len(user_stories),
                'total_views': total_views,
                'media_url':   _static_url(newest.media_path),
                'type':        newest.story_type,
            }

            if is_mine:
                my_entry = entry
            else:
                others.append(entry)

        # Owner's entry is always first
        result = ([my_entry] if my_entry else []) + others
        return jsonify({'ok': True, 'stories': result})

    except Exception as e:
        current_app.logger.exception('get_stories error: %s', e)
        return jsonify({'ok': False, 'error': str(e), 'stories': []}), 500


@stories_bp.route('/api/stories', methods=['POST'])
@login_required
def create_story():
    return _do_create_story()


@stories_bp.route('/api/stories/add', methods=['POST'])
@login_required
def create_story_add():
    return _do_create_story()


@stories_bp.route('/api/stories/<int:story_id>', methods=['GET'])
@login_required
def story_get(story_id):
    try:
        current_role, current_uid, _, _ = _get_current_identity()
        s = db.session.get(Story, story_id)
        if not s:
            return jsonify({'ok': False, 'error': 'Story not found'}), 404

        is_mine = (s.user_type == current_role and s.user_id == current_uid)
        # Privacy check for non-owners
        if not is_mine:
            priv = s.privacy or 'public'
            if priv == 'only_me':
                return jsonify({'ok': False, 'error': 'Forbidden'}), 403
            if priv == 'close_friends' and not _are_connected(
                    current_role, current_uid, s.user_type, s.user_id):
                return jsonify({'ok': False, 'error': 'Forbidden'}), 403

        name, avatar = _user_display(s.user_type, s.user_id)
        view_count   = StoryView.query.filter_by(story_id=s.id).count() if is_mine else None
        return jsonify({'ok': True, 'story': {
            'id':         s.id,
            'user_type':  s.user_type,
            'user_id':    s.user_id,
            'name':       name,
            'avatar':     avatar or None,
            'type':       s.story_type,
            'media_url':  _static_url(s.media_path),
            'caption':    s.caption,
            'bg':         s.bg or 'gradient1',
            'text_body':  s.text_body,
            'time':       _time_ago(s.created_at),
            'expires_at': s.expires_at.isoformat(),
            'privacy':    s.privacy or 'public',
            'is_mine':    is_mine,
            'view_count': view_count,
        }})
    except Exception as e:
        current_app.logger.exception('story_get error: %s', e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@stories_bp.route('/api/stories/<int:story_id>/seen', methods=['POST'])
@login_required
def mark_story_seen(story_id):
    """Mark a story as seen in the session AND record a StoryView DB row."""
    role, uid, _, _ = _get_current_identity()
    seen = set(int(x) for x in session.get('seen_story_ids', []))
    seen.add(story_id)
    session['seen_story_ids'] = list(seen)

    story = db.session.get(Story, story_id)
    if story:
        _record_view(story, role, uid)

    return jsonify({'ok': True})


@stories_bp.route('/api/stories/<int:story_id>/views', methods=['GET'])
@login_required
def story_views(story_id):
    """
    Returns the list of people who viewed this story slide.
    Only the story owner may call this endpoint.
    """
    try:
        role, uid, _, _ = _get_current_identity()
        story = db.session.get(Story, story_id)
        if not story:
            return jsonify({'ok': False, 'error': 'Story not found'}), 404
        if story.user_type != role or story.user_id != uid:
            return jsonify({'ok': False, 'error': 'Forbidden'}), 403

        views = (StoryView.query
                 .filter_by(story_id=story_id)
                 .order_by(StoryView.viewed_at.desc())
                 .all())
        result = []
        for v in views:
            name, avatar = _user_display(v.viewer_type, v.viewer_id)
            result.append({
                'name':        name,
                'avatar':      avatar or None,
                'viewer_type': v.viewer_type,
                'viewer_id':   v.viewer_id,
                'viewed_at':   _time_ago(v.viewed_at),
            })
        return jsonify({'ok': True, 'views': result, 'count': len(result)})
    except Exception as e:
        current_app.logger.exception('story_views error: %s', e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@stories_bp.route('/api/stories/<int:story_id>/reply', methods=['POST'])
@login_required
def story_reply(story_id):
    try:
        role, uid, replier_name, _ = _get_current_identity()
        if not role or not uid:
            return jsonify({'ok': False, 'error': 'Session expired'}), 401
        data  = request.get_json(silent=True) or {}
        reply = (data.get('reply') or data.get('text') or '').strip()
        if not reply:
            return jsonify({'ok': False, 'error': 'Reply text is required'}), 400
        story = db.session.get(Story, story_id)
        if not story:
            return jsonify({'ok': False, 'error': 'Story not found'}), 404

        import sys
        app_module = sys.modules.get('__main__') or sys.modules.get('app')
        post_to_universal_group = getattr(app_module, 'post_to_universal_group', None)

        owner_name, owner_avatar = _user_display(story.user_type, story.user_id)
        meta = {
            'story_type':         story.story_type,
            'story_media':        story.media_path or '',
            'story_bg':           story.bg or 'gradient1',
            'story_caption':      story.caption or '',
            'story_text_body':    story.text_body or '',
            'story_owner_name':   owner_name,
            'story_owner_avatar': owner_avatar,
            'reply_text':         reply,
        }
        bridge_text = (
            f"\u21a9\ufe0f {replier_name} replied to "
            f"{owner_name}'s story: \"{reply[:100]}\""
        )
        if post_to_universal_group:
            msg = post_to_universal_group(role, uid, bridge_text, 'story_reply', meta)
            if not msg:
                return jsonify({'ok': False, 'error': 'Universal group not found'}), 500
            return jsonify({'ok': True, 'message_id': msg.message_id})
        return jsonify({'ok': True})
    except Exception as e:
        current_app.logger.exception('story_reply error: %s', e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@stories_bp.route('/api/stories/<path:user_ref>/slides', methods=['GET'])
@login_required
def get_user_story_slides(user_ref):
    """
    Returns all active slides for a given user.
    Works for the owner viewing their own stories ('me' or 'role/id').
    Records StoryView rows for non-owner viewers (batch, idempotent).
    """
    try:
        current_role, current_uid, _, _ = _get_current_identity()
        user_type, user_id = _parse_user_ref(user_ref)
        if not user_type or not user_id:
            return jsonify({'ok': False, 'error': 'Could not resolve user'}), 400

        now    = datetime.utcnow()
        is_mine = (user_type == current_role and user_id == current_uid)

        slides = (
            db.session.query(Story)
            .filter(
                Story.user_type == user_type,
                Story.user_id   == user_id,
                Story.expires_at > now,
            )
            .order_by(Story.id.asc())
            .all()
        )

        # Apply privacy filtering for non-owner viewers
        if not is_mine:
            visible = []
            for s in slides:
                priv = s.privacy or 'public'
                if priv == 'only_me':
                    continue
                if priv == 'close_friends' and not _are_connected(
                        current_role, current_uid, user_type, user_id):
                    continue
                visible.append(s)
            slides = visible

        if not slides:
            name, avatar = _user_display(user_type, user_id)
            return jsonify({'ok': True, 'name': name, 'avatar': avatar or None, 'slides': []})

        # Mark all fetched slides as seen in session
        seen_ids = set(int(x) for x in session.get('seen_story_ids', []))
        for s in slides:
            seen_ids.add(s.id)
        session['seen_story_ids'] = list(seen_ids)

        # Record views in DB for non-owner viewers (idempotent)
        if not is_mine:
            for s in slides:
                _record_view(s, current_role, current_uid)

        name, avatar = _user_display(user_type, user_id)

        slide_data = []
        for s in slides:
            view_count = StoryView.query.filter_by(story_id=s.id).count() if is_mine else None
            slide_data.append({
                'story_id':   s.id,
                'type':       s.story_type,
                'media_url':  _static_url(s.media_path),
                'caption':    s.caption,
                'bg':         s.bg or 'gradient1',
                'text_body':  s.text_body,
                'time':       _time_ago(s.created_at),
                'privacy':    s.privacy or 'public',
                'is_mine':    is_mine,
                'view_count': view_count,
            })

        return jsonify({
            'ok':     True,
            'name':   name,
            'avatar': avatar or None,
            'is_mine': is_mine,
            'slides': slide_data,
        })
    except Exception as e:
        current_app.logger.exception('get_user_story_slides error: %s', e)
        return jsonify({'ok': False, 'error': str(e), 'slides': []}), 500


@stories_bp.route('/api/stories/mark-all-seen', methods=['POST'])
@login_required
def mark_all_user_stories_seen():
    data     = request.get_json(silent=True) or {}
    user_ref = data.get('user_ref')
    if not user_ref:
        return jsonify({'ok': False, 'error': 'user_ref is required'}), 400

    user_type, user_id = _parse_user_ref(user_ref)
    if not user_type or not user_id:
        return jsonify({'ok': False, 'error': 'Could not resolve user'}), 400

    now = datetime.utcnow()
    rows = (db.session.query(Story.id)
            .filter(Story.user_type == user_type,
                    Story.user_id == user_id,
                    Story.expires_at > now)
            .all())
    seen_ids = set(int(x) for x in session.get('seen_story_ids', []))
    for (sid,) in rows:
        seen_ids.add(sid)
    session['seen_story_ids'] = list(seen_ids)
    return jsonify({'ok': True})


@stories_bp.route('/api/stories/<int:story_id>/delete', methods=['POST'])
@login_required
def story_delete(story_id):
    try:
        role  = session['role']
        uid   = session['user_id']
        story = db.session.get(Story, story_id)
        if not story:
            return jsonify({'ok': False, 'error': 'Story not found'}), 404
        if story.user_type != role or story.user_id != uid:
            return jsonify({'ok': False, 'error': 'Forbidden'}), 403
        # StoryView rows cascade-delete via the relationship
        db.session.delete(story)
        db.session.commit()
        return jsonify({'ok': True})
    except Exception as e:
        current_app.logger.exception('story_delete error: %s', e)
        try: db.session.rollback()
        except Exception: pass
        return jsonify({'ok': False, 'error': str(e)}), 500


@stories_bp.route('/api/gif-search', methods=['GET'])
@login_required
def gif_search_proxy():
    if not GIPHY_API_KEY:
        return jsonify({'ok': False, 'error': 'GIF search not configured'}), 503
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'ok': False, 'error': 'No query'}), 400
    try:
        resp = http_requests.get(
            'https://api.giphy.com/v1/gifs/search',
            params={
                'api_key': GIPHY_API_KEY,
                'q':       q,
                'limit':   12,
                'rating':  'g',
                'lang':    'en',
            },
            timeout=6,
        )
        resp.raise_for_status()
        gifs = []
        for item in resp.json().get('data', []):
            url = (
                item.get('images', {}).get('fixed_height', {}).get('url') or
                item.get('images', {}).get('downsized',    {}).get('url')
            )
            if url:
                gifs.append({'url': url, 'title': item.get('title', '')})
        return jsonify({'ok': True, 'gifs': gifs})
    except http_requests.RequestException as e:
        current_app.logger.error('Giphy error: %s', e)
        return jsonify({'ok': False, 'error': 'GIF search unavailable'}), 502