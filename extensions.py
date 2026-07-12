# extensions.py
# ─────────────────────────────────────────────────────────────────────────────
# Single, shared SQLAlchemy instance.
#
# WHY THIS FILE EXISTS
# ────────────────────
# app.py creates the Flask app and calls db.init_app(app).
# stories_routes.py (a Blueprint) also needs db.
#
# If stories_routes.py does  `from app import db`  it triggers a circular
# import because app.py imports stories_routes.py at its bottom.
#
# The solution: define db HERE (no app attached yet), then import it in BOTH
# app.py and stories_routes.py.  app.py calls db.init_app(app) to register
# the Flask app.  Both files share the exact same object, so SQLAlchemy
# always knows which app context it belongs to — no "app not registered" error.
# ─────────────────────────────────────────────────────────────────────────────

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()