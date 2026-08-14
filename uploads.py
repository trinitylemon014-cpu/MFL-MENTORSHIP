"""
uploads.py – Shared Cloudinary upload helper.

Lives in its own module specifically so both app.py and stories_routes.py
can import upload_to_cloudinary() directly, with no circular import risk
and no sys.modules lookups. This is the single source of truth for how
files get uploaded to Cloudinary anywhere in the app.
"""

import os
import uuid
import cloudinary
import cloudinary.uploader

ALLOWED_IMG   = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_VIDEO = {'mp4', 'mov', 'webm', 'avi', 'mkv'}
ALLOWED_AUDIO = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'webm', 'opus'}

# ── Cloudinary configuration ────────────────────────────────────────────────
# If CLOUDINARY_URL is set (format: cloudinary://api_key:api_secret@cloud_name),
# the SDK picks it up automatically. Otherwise fall back to the three separate vars.
if os.environ.get('CLOUDINARY_URL'):
    cloudinary.config(cloudinary_url=os.environ['CLOUDINARY_URL'], secure=True)
else:
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
        api_key=os.environ.get('CLOUDINARY_API_KEY', ''),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET', ''),
        secure=True,
    )


def _ext(filename):
    return filename.rsplit('.', 1)[-1].lower() if filename and '.' in filename else ''


def _cloudinary_resource_type(ext):
    """Cloudinary buckets uploads into 'image', 'video' (covers audio too), or 'raw'."""
    if ext in ALLOWED_IMG:
        return 'image'
    if ext in ALLOWED_VIDEO or ext in ALLOWED_AUDIO:
        return 'video'
    return 'raw'


def _bytes_to_label(sz):
    try:
        sz = int(sz)
    except (TypeError, ValueError):
        return ''
    if sz < 1024:
        return f"{sz} B"
    if sz < 1024 * 1024:
        return f"{sz // 1024} KB"
    return f"{sz // 1024 // 1024} MB"


def upload_to_cloudinary(file, subfolder, ext_override=None):
    """
    Uploads a werkzeug FileStorage to Cloudinary.
    Returns (secure_url, size_label) on success, (None, None) on failure.
    Used directly by app.py (posts, profiles, chat) and stories_routes.py.
    """
    if not file or not file.filename:
        return None, None
    ext = (ext_override or _ext(file.filename) or 'bin').lower()
    resource_type = _cloudinary_resource_type(ext)
    public_id = f"{subfolder}/{uuid.uuid4().hex}"
    try:
        result = cloudinary.uploader.upload(
            file,
            public_id=public_id,
            resource_type=resource_type,
            folder='empower_mentorship',
            overwrite=True,
        )
        url = result.get('secure_url')
        size_label = _bytes_to_label(result.get('bytes', 0))
        return url, size_label
    except Exception as e:
        print(f'[Cloudinary] Upload failed ({subfolder}): {e}')
        return None, None
