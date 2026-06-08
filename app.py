import base64
import hashlib
import os
import re
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import Flask, Response, abort, g, jsonify, make_response, redirect, render_template, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from filedrop_config import (
    AVATAR_COLORS,
    BLOCKED_FILENAME_CHARS,
    CSRF_TOKEN_BYTES,
    DATABASE_FILENAME,
    DEFAULT_PARALLEL_UPLOADS,
    DEFAULT_STORAGE_LIMIT_BYTES,
    DEFAULT_UPLOAD_DIRECTORY,
    EMAIL_MAX_LENGTH,
    FORM_CONSTRAINTS,
    INSTANCE_PATH_ENV,
    IMAGE_PREVIEW_EXTENSIONS,
    MAX_UPLOAD_SIZE_BYTES,
    MAX_PARALLEL_UPLOADS,
    MIN_PARALLEL_UPLOADS,
    PASSWORD_HASH_METHOD,
    PASSWORD_MIN_LENGTH,
    PRIVATE_KEY_FILENAME,
    PUBLIC_KEY_FILENAME,
    RSA_KEY_SIZE,
    RSA_PUBLIC_EXPONENT,
    SECURE_COOKIES_ENV,
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME_HOURS,
    SESSION_TOKEN_BYTES,
    TEMPORARY_PASSWORD_BYTES,
    UPLOAD_PATH_ENV,
    USERNAME_CHARACTERS,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    VIDEO_PREVIEW_EXTENSIONS,
    env_flag,
    env_value,
)

INSTANCE_PATH = env_value(INSTANCE_PATH_ENV)
app = Flask(__name__, instance_relative_config=True, instance_path=INSTANCE_PATH)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_SIZE_BYTES,
    SESSION_COOKIE_NAME=SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE=env_flag(SECURE_COOKIES_ENV),
    SESSION_LIFETIME_HOURS=SESSION_LIFETIME_HOURS,
)

Path(app.instance_path).mkdir(parents=True, exist_ok=True)
DATABASE = Path(app.instance_path) / DATABASE_FILENAME
PRIVATE_KEY_PATH = Path(app.instance_path) / PRIVATE_KEY_FILENAME
PUBLIC_KEY_PATH = Path(app.instance_path) / PUBLIC_KEY_FILENAME
UPLOAD_ROOT = Path(env_value(UPLOAD_PATH_ENV, Path(app.root_path) / DEFAULT_UPLOAD_DIRECTORY)).resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
STATIC_ASSET_VERSION = str(
    max(
        (path.stat().st_mtime_ns for path in Path(app.static_folder).rglob("*") if path.is_file()),
        default=0,
    )
)
TRASH_DIRECTORY_NAME = ".filedrop_trash"
DEFAULT_RECENT_DAYS = 7
DEFAULT_TRASH_RETENTION_DAYS = 30
DEFAULT_TRASH_LIMIT_BYTES = 15 * 1024 ** 3

def utc_now():
    return datetime.now(timezone.utc)


def iso_time(value):
    return value.astimezone(timezone.utc).isoformat()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def setup_required():
    return get_db().execute("SELECT 1 FROM users LIMIT 1").fetchone() is None


def api_response_requested():
    return request.path.startswith("/api/")


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.context_processor
def inject_form_constraints():
    return {"form_constraints": FORM_CONSTRAINTS, "static_asset_version": STATIC_ASSET_VERSION}


def init_db():
    db = get_db()
    db.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied')),
            must_change_password INTEGER NOT NULL DEFAULT 0,
            is_initial_admin INTEGER NOT NULL DEFAULT 0,
            storage_limit_bytes INTEGER NOT NULL DEFAULT {DEFAULT_STORAGE_LIMIT_BYTES},
            avatar_color TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            csrf_token TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS item_orders (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            folder_path TEXT NOT NULL,
            item_path TEXT NOT NULL,
            position INTEGER NOT NULL,
            PRIMARY KEY (user_id, folder_path, item_path)
        );
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            theme TEXT NOT NULL DEFAULT 'system' CHECK (theme IN ('system', 'light', 'dark')),
            conflict_mode TEXT NOT NULL DEFAULT 'add' CHECK (conflict_mode IN ('add', 'replace')),
            parallel_uploads INTEGER NOT NULL DEFAULT {DEFAULT_PARALLEL_UPLOADS}
                CHECK (parallel_uploads BETWEEN {MIN_PARALLEL_UPLOADS} AND {MAX_PARALLEL_UPLOADS}),
            confirm_single_delete INTEGER NOT NULL DEFAULT 0,
            confirm_bulk_delete INTEGER NOT NULL DEFAULT 0,
            full_view INTEGER NOT NULL DEFAULT 0,
            sort_by TEXT NOT NULL DEFAULT 'manual'
                CHECK (sort_by IN ('manual', 'name', 'modified', 'size', 'extension')),
            sort_direction TEXT NOT NULL DEFAULT 'asc' CHECK (sort_direction IN ('asc', 'desc'))
        );
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, path)
        );
        CREATE TABLE IF NOT EXISTS folder_usage (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            folder_path TEXT NOT NULL,
            use_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TEXT NOT NULL,
            PRIMARY KEY (user_id, folder_path)
        );
        CREATE TABLE IF NOT EXISTS sidebar_folders (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            folder_path TEXT NOT NULL,
            position INTEGER NOT NULL,
            hidden INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, folder_path)
        );
        CREATE TABLE IF NOT EXISTS trash_items (
            trash_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            original_path TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('file', 'folder')),
            size INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS upload_receipts (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            upload_id TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, upload_id)
        );
        CREATE TABLE IF NOT EXISTS share_links (
            token TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            root_path TEXT NOT NULL,
            access_mode TEXT NOT NULL CHECK (access_mode IN ('view', 'edit', 'restricted_edit')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS share_editors (
            share_token TEXT NOT NULL REFERENCES share_links(token) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (share_token, user_id)
        );
        CREATE TABLE IF NOT EXISTS notification_states (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            notification_key TEXT NOT NULL,
            read_at TEXT,
            dismissed_at TEXT,
            PRIMARY KEY (user_id, notification_key)
        );
        CREATE TABLE IF NOT EXISTS file_records (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            path_folded TEXT NOT NULL,
            name TEXT NOT NULL,
            name_folded TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('file', 'folder')),
            size INTEGER,
            modified_at REAL,
            UNIQUE(user_id, path)
        );
        CREATE INDEX IF NOT EXISTS file_records_exact_path_idx ON file_records(user_id, path_folded);
        CREATE INDEX IF NOT EXISTS file_records_exact_name_idx ON file_records(user_id, name_folded);
        CREATE INDEX IF NOT EXISTS file_records_parent_rank_idx ON file_records(user_id, path);
        CREATE TABLE IF NOT EXISTS file_prefixes (
            prefix TEXT NOT NULL,
            file_id INTEGER NOT NULL REFERENCES file_records(file_id) ON DELETE CASCADE,
            PRIMARY KEY (prefix, file_id)
        );
        CREATE INDEX IF NOT EXISTS file_prefixes_file_idx ON file_prefixes(file_id);
        CREATE TABLE IF NOT EXISTS file_terms (
            term TEXT NOT NULL,
            file_id INTEGER NOT NULL REFERENCES file_records(file_id) ON DELETE CASCADE,
            PRIMARY KEY (term, file_id)
        );
        CREATE INDEX IF NOT EXISTS file_terms_file_idx ON file_terms(file_id);
        CREATE TABLE IF NOT EXISTS app_migrations (
            name TEXT PRIMARY KEY
        );
        """
    )
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "is_initial_admin" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_initial_admin INTEGER NOT NULL DEFAULT 0")
    if "storage_limit_bytes" not in user_columns:
        db.execute(f"ALTER TABLE users ADD COLUMN storage_limit_bytes INTEGER NOT NULL DEFAULT {DEFAULT_STORAGE_LIMIT_BYTES}")
    preference_columns = {row["name"] for row in db.execute("PRAGMA table_info(user_preferences)")}
    if "sort_by" not in preference_columns:
        db.execute("ALTER TABLE user_preferences ADD COLUMN sort_by TEXT NOT NULL DEFAULT 'manual'")
    if "sort_direction" not in preference_columns:
        db.execute("ALTER TABLE user_preferences ADD COLUMN sort_direction TEXT NOT NULL DEFAULT 'asc'")
    if "recent_days" not in preference_columns:
        db.execute(f"ALTER TABLE user_preferences ADD COLUMN recent_days INTEGER NOT NULL DEFAULT {DEFAULT_RECENT_DAYS}")
    if "trash_retention_days" not in preference_columns:
        db.execute(f"ALTER TABLE user_preferences ADD COLUMN trash_retention_days INTEGER NOT NULL DEFAULT {DEFAULT_TRASH_RETENTION_DAYS}")
    if "trash_limit_bytes" not in preference_columns:
        db.execute(f"ALTER TABLE user_preferences ADD COLUMN trash_limit_bytes INTEGER NOT NULL DEFAULT {DEFAULT_TRASH_LIMIT_BYTES}")
    parallel_upload_migration = "interactive_parallel_uploads_4"
    if not db.execute("SELECT 1 FROM app_migrations WHERE name = ?", (parallel_upload_migration,)).fetchone():
        db.execute(
            "UPDATE user_preferences SET parallel_uploads = ? WHERE parallel_uploads = 3 OR parallel_uploads > ?",
            (DEFAULT_PARALLEL_UPLOADS, MAX_PARALLEL_UPLOADS),
        )
        db.execute("INSERT INTO app_migrations (name) VALUES (?)", (parallel_upload_migration,))
    file_delete_confirmation_migration = "file_delete_confirmations_default_off"
    if not db.execute("SELECT 1 FROM app_migrations WHERE name = ?", (file_delete_confirmation_migration,)).fetchone():
        db.execute("UPDATE user_preferences SET confirm_single_delete = 0, confirm_bulk_delete = 0")
        db.execute("INSERT INTO app_migrations (name) VALUES (?)", (file_delete_confirmation_migration,))
    if not db.execute("SELECT 1 FROM users WHERE is_initial_admin = 1").fetchone():
        first_admin = db.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        if first_admin:
            db.execute("UPDATE users SET is_initial_admin = 1 WHERE id = ?", (first_admin["id"],))
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_time(utc_now()),))
    db.execute("DELETE FROM upload_receipts WHERE created_at <= ?", (iso_time(utc_now() - timedelta(hours=24)),))
    cleanup_trash_for_all_users()
    db.commit()


def aesthetic_color(username):
    digest = hashlib.sha256(username.casefold().encode("utf-8")).digest()
    return AVATAR_COLORS[digest[0] % len(AVATAR_COLORS)]


def load_or_create_keys():
    if PRIVATE_KEY_PATH.exists() and PUBLIC_KEY_PATH.exists():
        private_key = serialization.load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())
        return private_key, public_key

    private_key = rsa.generate_private_key(public_exponent=RSA_PUBLIC_EXPONENT, key_size=RSA_KEY_SIZE)
    public_key = private_key.public_key()
    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    PUBLIC_KEY_PATH.write_bytes(
        public_key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    try:
        PRIVATE_KEY_PATH.chmod(0o600)
        PUBLIC_KEY_PATH.chmod(0o644)
    except OSError:
        pass
    return private_key, public_key


PRIVATE_KEY, PUBLIC_KEY = load_or_create_keys()


def encoded_signature(session_id):
    signature = PRIVATE_KEY.sign(
        session_id.encode("ascii"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def signed_session_cookie(session_id):
    return f"{session_id}.{encoded_signature(session_id)}"


def verified_session_id(cookie):
    if not cookie or "." not in cookie:
        return None
    session_id, encoded = cookie.split(".", 1)
    try:
        signature = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        PUBLIC_KEY.verify(
            signature,
            session_id.encode("ascii"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except (ValueError, TypeError):
        return None
    except Exception:
        return None
    return session_id


def set_session_cookie(response, session_id):
    response.set_cookie(
        app.config["SESSION_COOKIE_NAME"],
        signed_session_cookie(session_id),
        httponly=True,
        secure=app.config["SESSION_COOKIE_SECURE"],
        samesite="Strict",
        max_age=app.config["SESSION_LIFETIME_HOURS"] * 60 * 60,
    )


def clear_session_cookie(response):
    response.delete_cookie(app.config["SESSION_COOKIE_NAME"], httponly=True, samesite="Strict")


def create_session(user_id):
    session_id = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
    now = utc_now()
    get_db().execute(
        "INSERT INTO sessions (id, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, csrf_token, iso_time(now + timedelta(hours=app.config["SESSION_LIFETIME_HOURS"])), iso_time(now)),
    )
    get_db().commit()
    return session_id


@app.before_request
def load_user_and_check_csrf():
    g.user = None
    g.session = None
    if setup_required() and request.endpoint not in {"setup", "setup_post", "static", "health"}:
        if api_response_requested():
            abort(503, description="Filedrop setup is required before using the API.")
        return redirect(url_for("setup"))
    session_id = verified_session_id(request.cookies.get(app.config["SESSION_COOKIE_NAME"]))
    if session_id:
        row = get_db().execute(
            """SELECT sessions.*, users.username, users.email, users.role, users.status,
                      users.must_change_password, users.avatar_color, users.storage_limit_bytes
               FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.id = ? AND sessions.expires_at > ?""",
            (session_id, iso_time(utc_now())),
        ).fetchone()
        if row and row["status"] == "approved":
            g.session = row
            g.user = row

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.endpoint not in {"login_post", "register_post", "setup_post"}:
        if not g.session:
            abort(401, description="Sign in is required.")
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not token or not secrets.compare_digest(token, g.session["csrf_token"]):
            abort(403, description="The security token is missing or invalid. Refresh the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            if request.path.startswith("/api/"):
                abort(401, description="Sign in is required.")
            return redirect(url_for("login"))
        if g.user["must_change_password"] and request.endpoint not in {"change_password", "logout"}:
            if request.path.startswith("/api/"):
                abort(403, description="Change your password before using Filedrop.")
            return redirect(url_for("change_password"))
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def prevent_api_html_redirects(response):
    if request.path.startswith("/api/") and 300 <= response.status_code < 400:
        location = response.headers.get("Location", "")
        message = "Sign in is required." if "login" in location else "This API request could not be completed."
        if "change-password" in location:
            message = "Change your password before using Filedrop."
        replacement = jsonify({"message": message, "redirect": location})
        replacement.status_code = 401 if "login" in location else 403
        replacement.headers["Cache-Control"] = "no-store"
        return replacement
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403, description="Administrator access is required.")
        return view(*args, **kwargs)
    return wrapped


def account_validation_error(username, email, password):
    username = username.strip()
    email = email.strip()
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH or any(char not in USERNAME_CHARACTERS for char in username):
        return f"Username must be {USERNAME_MIN_LENGTH}-{USERNAME_MAX_LENGTH} characters and use only letters, numbers, periods, underscores, or hyphens."
    if len(email) > EMAIL_MAX_LENGTH or "@" not in email or email.startswith("@") or email.endswith("@"):
        return "Enter a valid email address."
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    return None


def validate_account_input(username, email, password):
    username = username.strip()
    email = email.strip()
    error = account_validation_error(username, email, password)
    if error:
        abort(400, description=error)
    return username, email


def validate_name(name, label="Names"):
    if not name or not name.strip():
        abort(400, description=f"{label} must include at least one visible character.")
    if name in {".", ".."} or any(char in name for char in BLOCKED_FILENAME_CHARS):
        abort(400, description=f"{label} cannot include path separators.")


def validate_relative_path(relative_path, label="Paths"):
    if not isinstance(relative_path, str):
        abort(400, description=f"{label} must be text.")
    parts = [part for part in relative_path.split("/") if part]
    for part in parts:
        validate_name(part, "Path segments")
    return parts


def parse_upload_file(upload):
    if not upload or not upload.filename:
        abort(400, description="No file was selected.")
    filename = upload.filename.replace("\\", "/").rsplit("/", 1)[-1]
    validate_name(filename, "Filenames")
    return filename


def upload_size(upload):
    stream = upload.stream
    try:
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(position)
        return size
    except (AttributeError, OSError):
        return upload.content_length or 0


def accessible_root():
    home = (UPLOAD_ROOT / g.user["username"]).resolve()
    home.mkdir(exist_ok=True)
    return home


def user_accessible_root(user):
    home = (UPLOAD_ROOT / user["username"]).resolve()
    home.mkdir(exist_ok=True)
    return home


def directory_size(path):
    total = 0
    if not path.exists():
        return total
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def visible_user_items(folder):
    return [item for item in folder.iterdir() if item.name != TRASH_DIRECTORY_NAME]


def storage_usage_for_user(user):
    return directory_size(user_accessible_root(user))


def user_id_value(user):
    return user["user_id"] if "user_id" in user.keys() else user["id"]


def user_preferences_for_user(user):
    db = get_db()
    user_id = user_id_value(user)
    db.execute("INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)", (user_id,))
    row = db.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)).fetchone()
    return {
        "theme": row["theme"],
        "conflictMode": row["conflict_mode"],
        "parallelUploads": row["parallel_uploads"],
        "confirmSingleDelete": bool(row["confirm_single_delete"]),
        "confirmBulkDelete": bool(row["confirm_bulk_delete"]),
        "fullView": bool(row["full_view"]),
        "sortBy": row["sort_by"],
        "sortDirection": row["sort_direction"],
        "recentDays": row["recent_days"],
        "trashRetentionDays": row["trash_retention_days"],
        "trashLimitBytes": row["trash_limit_bytes"],
    }


def trash_root_for_user(user):
    root = user_accessible_root(user) / TRASH_DIRECTORY_NAME
    root.mkdir(exist_ok=True)
    return root


def trash_usage_for_user(user):
    row = get_db().execute(
        "SELECT COALESCE(SUM(size), 0) AS size FROM trash_items WHERE user_id = ?",
        (user_id_value(user),),
    ).fetchone()
    return int(row["size"] or 0)


def remove_trash_row(user, row):
    stored = user_accessible_root(user) / row["stored_path"]
    if stored.exists():
        shutil.rmtree(stored) if stored.is_dir() else stored.unlink()
    get_db().execute("DELETE FROM trash_items WHERE trash_id = ? AND user_id = ?", (row["trash_id"], user_id_value(user)))


def cleanup_trash_for_user(user, retention_days=None, limit_bytes=None):
    preferences = user_preferences_for_user(user)
    retention = max(1, int(retention_days or preferences["trashRetentionDays"]))
    limit = max(0, int(limit_bytes if limit_bytes is not None else preferences["trashLimitBytes"]))
    cutoff = iso_time(utc_now() - timedelta(days=retention))
    db = get_db()
    expired = db.execute(
        "SELECT * FROM trash_items WHERE user_id = ? AND deleted_at <= ? ORDER BY deleted_at ASC",
        (user_id_value(user), cutoff),
    ).fetchall()
    for row in expired:
        remove_trash_row(user, row)
    while trash_usage_for_user(user) > limit:
        row = db.execute(
            "SELECT * FROM trash_items WHERE user_id = ? ORDER BY deleted_at ASC LIMIT 1",
            (user_id_value(user),),
        ).fetchone()
        if not row:
            break
        remove_trash_row(user, row)


def cleanup_trash_for_all_users():
    for user in get_db().execute("SELECT * FROM users"):
        cleanup_trash_for_user(user)


def favorite_paths(user=None):
    user = user or g.user
    return {
        row["path"]
        for row in get_db().execute("SELECT path FROM favorites WHERE user_id = ?", (user_id_value(user),))
    }


def with_favorites(items, favorites=None):
    favorites = favorites if favorites is not None else favorite_paths()
    return [{**item, "favorite": item["path"] in favorites} for item in items]


def record_folder_use(path):
    if not g.user or path is None:
        return
    get_db().execute(
        """INSERT INTO folder_usage (user_id, folder_path, use_count, last_used_at)
           VALUES (?, ?, 1, ?)
           ON CONFLICT(user_id, folder_path)
           DO UPDATE SET use_count = use_count + 1, last_used_at = excluded.last_used_at""",
        (g.user["user_id"], path, iso_time(utc_now())),
    )


def storage_payload_for_user(user):
    used = storage_usage_for_user(user)
    limit = int(user["storage_limit_bytes"] or DEFAULT_STORAGE_LIMIT_BYTES)
    return {
        "usedBytes": used,
        "limitBytes": limit,
        "percent": min(100, round((used / limit) * 100, 1)) if limit > 0 else 100,
    }


def format_bytes(value):
    units = ("bytes", "KB", "MB", "GB", "TB")
    amount = float(value)
    unit_index = 0
    while amount >= 1024 and unit_index < len(units) - 1:
        amount /= 1024
        unit_index += 1
    return f"{amount:.1f} {units[unit_index]}" if unit_index else f"{int(amount)} {units[unit_index]}"


def enforce_storage_limit(user, incoming_size, destination=None):
    limit = int(user["storage_limit_bytes"] or DEFAULT_STORAGE_LIMIT_BYTES)
    existing_size = 0
    if destination and destination.exists() and destination.is_file():
        try:
            existing_size = destination.stat().st_size
        except OSError:
            existing_size = 0
    projected = storage_usage_for_user(user) + max(0, incoming_size - existing_size)
    if projected > limit:
        abort(
            413,
            description=f"Storage limit exceeded. This account can use {format_bytes(limit)}.",
        )


def admin_user_rows():
    rows = get_db().execute("SELECT * FROM users ORDER BY status != 'pending', username COLLATE NOCASE").fetchall()
    users = []
    for row in rows:
        used = storage_usage_for_user(row)
        limit = row["storage_limit_bytes"] or DEFAULT_STORAGE_LIMIT_BYTES
        users.append({
            **dict(row),
            "storage_used_bytes": used,
            "storage_limit_gb": round(limit / (1024 ** 3), 2),
            "storage_used_label": format_bytes(used),
            "storage_limit_label": format_bytes(limit),
        })
    return users


def resolve_upload_path(relative_path=""):
    root = accessible_root()
    parts = validate_relative_path(relative_path or "")
    path = (root / Path(*parts)).resolve() if parts else root
    if path != root and root not in path.parents:
        abort(400, description="Path is outside your upload folder.")
    return path


def item_payload(path, root=None):
    root = root or accessible_root()
    relative_path = path.relative_to(root).as_posix()
    payload = {"name": path.name, "path": "" if relative_path == "." else relative_path, "type": "folder" if path.is_dir() else "file"}
    try:
        metadata = path.stat()
        payload["modifiedAt"] = metadata.st_mtime
        if path.is_file():
            payload["size"] = metadata.st_size
    except OSError:
        payload["modifiedAt"] = None
        if path.is_file():
            payload["size"] = None
    if path.is_file():
        extension = path.suffix.lstrip(".").lower()
        payload["extension"] = extension or None
        if extension in IMAGE_PREVIEW_EXTENSIONS:
            payload["preview"] = "image"
        elif extension in VIDEO_PREVIEW_EXTENSIONS:
            payload["preview"] = "video"
    return payload


SEARCH_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
SEARCH_CONTENT_EXTENSIONS = {"csv", "json", "log", "md", "py", "rtf", "text", "txt", "xml", "yaml", "yml"}
SEARCH_CONTENT_MAX_BYTES = 512 * 1024


def search_tokens(value):
    return {token.casefold() for token in SEARCH_TOKEN_RE.findall(value or "") if token}


def prefixes_for(value):
    folded = (value or "").casefold()
    parts = {folded, Path(folded).name}
    prefixes = set()
    for index in range(1, min(len(folded), 160) + 1):
        prefixes.add(folded[:index])
    for part in parts:
        for token in re.split(r"[/\s._!()\[\]{}-]+", part):
            token = token.strip()
            if not token:
                continue
            for index in range(1, min(len(token), 80) + 1):
                prefixes.add(token[:index])
    return prefixes


def index_content_terms(path):
    if not path.is_file() or path.suffix.lstrip(".").casefold() not in SEARCH_CONTENT_EXTENSIONS:
        return set()
    try:
        if path.stat().st_size > SEARCH_CONTENT_MAX_BYTES:
            return set()
        return search_tokens(path.read_text(errors="ignore"))
    except OSError:
        return set()


def upsert_search_record(user, path, root=None):
    root = root or user_accessible_root(user)
    if not path.exists():
        return
    payload = item_payload(path, root=root)
    terms = search_tokens(payload["name"]) | search_tokens(payload["path"]) | index_content_terms(path)
    prefixes = prefixes_for(payload["name"]) | prefixes_for(payload["path"])
    db = get_db()
    user_id = user_id_value(user)
    existing = db.execute("SELECT file_id FROM file_records WHERE user_id = ? AND path = ?", (user_id, payload["path"])).fetchone()
    if existing:
        file_id = existing["file_id"]
        db.execute(
            """UPDATE file_records
               SET path_folded = ?, name = ?, name_folded = ?, type = ?, size = ?, modified_at = ?
               WHERE file_id = ?""",
            (payload["path"].casefold(), payload["name"], payload["name"].casefold(), payload["type"], payload.get("size"), payload.get("modifiedAt"), file_id),
        )
    else:
        cursor = db.execute(
            """INSERT INTO file_records
               (user_id, path, path_folded, name, name_folded, type, size, modified_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, payload["path"], payload["path"].casefold(), payload["name"], payload["name"].casefold(), payload["type"], payload.get("size"), payload.get("modifiedAt")),
        )
        file_id = cursor.lastrowid
    db.execute("DELETE FROM file_prefixes WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM file_terms WHERE file_id = ?", (file_id,))
    db.executemany("INSERT OR IGNORE INTO file_prefixes (prefix, file_id) VALUES (?, ?)", ((prefix, file_id) for prefix in prefixes))
    db.executemany("INSERT OR IGNORE INTO file_terms (term, file_id) VALUES (?, ?)", ((term, file_id) for term in terms))


def delete_search_records(user, relative_path):
    user_id = user_id_value(user)
    path = (relative_path or "").strip("/")
    db = get_db()
    rows = db.execute(
        "SELECT file_id FROM file_records WHERE user_id = ? AND (path = ? OR path LIKE ?)",
        (user_id, path, f"{path}/%"),
    ).fetchall()
    file_ids = [row["file_id"] for row in rows]
    if not file_ids:
        return
    placeholders = ",".join("?" for _ in file_ids)
    db.execute(f"DELETE FROM file_prefixes WHERE file_id IN ({placeholders})", file_ids)
    db.execute(f"DELETE FROM file_terms WHERE file_id IN ({placeholders})", file_ids)
    db.execute(f"DELETE FROM file_records WHERE file_id IN ({placeholders})", file_ids)


def index_path_tree(user, path, root=None):
    root = root or user_accessible_root(user)
    if not path.exists():
        return
    upsert_search_record(user, path, root=root)
    if path.is_dir():
        for child in path.rglob("*"):
            upsert_search_record(user, child, root=root)


def ensure_search_index(user):
    user_id = user_id_value(user)
    if get_db().execute("SELECT 1 FROM file_records WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
        return
    index_path_tree(user, user_accessible_root(user))
    get_db().commit()


def ordered_items(folder, root=None, user_id=None):
    root = root or accessible_root()
    folder_path = "" if folder == root else folder.relative_to(root).as_posix()
    positions = {}
    if user_id:
        positions = {
            row["item_path"]: row["position"]
            for row in get_db().execute(
                "SELECT item_path, position FROM item_orders WHERE user_id = ? AND folder_path = ?",
                (user_id, folder_path),
            )
        }
    paths = visible_user_items(folder) if g.user and root == user_accessible_root(g.user) else list(folder.iterdir())
    items = [item_payload(path, root=root) for path in paths]
    return sorted(items, key=lambda item: (positions.get(item["path"], len(positions)), item["name"].casefold()))


def available_filename(folder, filename):
    path = folder / filename
    if not path.exists():
        return filename
    stem, suffix, counter = path.stem, path.suffix, 1
    while (folder / f"{stem}_{counter}{suffix}").exists():
        counter += 1
    return f"{stem}_{counter}{suffix}"


def available_item_path(folder, item_path):
    destination = folder / item_path.name
    if not destination.exists():
        return destination
    stem, suffix, counter = item_path.stem, item_path.suffix, 1
    while (folder / f"{stem}_{counter}{suffix}").exists():
        counter += 1
    return folder / f"{stem}_{counter}{suffix}"


def prepare_item_moves(item_paths, destination_folder, replace_existing=False, root=None, resolver=None):
    root = root or accessible_root()
    resolver = resolver or resolve_upload_path
    moves = []
    for relative_path in item_paths:
        if not isinstance(relative_path, str):
            abort(400, description="Item paths must be text.")
        item_path = resolver(relative_path)
        if item_path == root or not item_path.exists():
            abort(404, description="File or folder was not found.")
        if item_path == destination_folder or (item_path.is_dir() and item_path in destination_folder.parents):
            abort(400, description="A folder cannot be moved into itself.")
        destination = destination_folder / item_path.name
        if destination.exists() and destination != item_path and not replace_existing:
            destination = available_item_path(destination_folder, item_path)
        moves.append((item_path, destination))

    source_paths = [item_path for item_path, _destination in moves]
    if any(parent != child and parent in child.parents for parent in source_paths for child in source_paths):
        abort(400, description="Move a folder or its contents, not both at the same time.")
    return moves


def execute_item_moves(moves, replace_existing=False):
    moved = 0
    for item_path, destination in moves:
        if item_path == destination:
            continue
        if replace_existing and destination.exists():
            shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
        item_path.rename(destination)
        moved += 1
    return moved


def move_item_to_trash(user, item_path):
    user_root = user_accessible_root(user)
    relative_path = item_path.relative_to(user_root).as_posix()
    size = directory_size(item_path) if item_path.is_dir() else item_path.stat().st_size
    item_type = "folder" if item_path.is_dir() else "file"
    db = get_db()
    now = iso_time(utc_now())
    cursor = db.execute(
        """INSERT INTO trash_items (user_id, original_path, stored_path, name, type, size, deleted_at)
           VALUES (?, ?, '', ?, ?, ?, ?)""",
        (user_id_value(user), relative_path, item_path.name, item_type, size, now),
    )
    stored = trash_root_for_user(user) / f"{cursor.lastrowid}_{item_path.name}"
    stored_path = stored.relative_to(user_root).as_posix()
    item_path.rename(stored)
    db.execute("UPDATE trash_items SET stored_path = ? WHERE trash_id = ?", (stored_path, cursor.lastrowid))
    delete_search_records(user, relative_path)
    db.execute("DELETE FROM favorites WHERE user_id = ? AND (path = ? OR path LIKE ?)", (user_id_value(user), relative_path, f"{relative_path}/%"))
    cleanup_trash_for_user(user)
    return relative_path


def get_share(token):
    row = get_db().execute(
        """SELECT share_links.*, users.username, users.role
           FROM share_links JOIN users ON users.id = share_links.owner_id
           WHERE share_links.token = ?""",
        (token,),
    ).fetchone()
    if not row:
        abort(404, description="Share link was not found.")
    return row


def share_editors_payload(token):
    return [
        {"id": row["id"], "username": row["username"]}
        for row in get_db().execute(
            """SELECT users.id, users.username
               FROM share_editors JOIN users ON users.id = share_editors.user_id
               WHERE share_editors.share_token = ?
               ORDER BY users.username COLLATE NOCASE""",
            (token,),
        )
    ]


def share_payload(share):
    return {
        "token": share["token"],
        "url": url_for("share_browse_root", token=share["token"], _external=True),
        "accessMode": share["access_mode"],
        "editors": share_editors_payload(share["token"]),
    }


def find_owned_share_for_path(relative_path):
    return get_db().execute(
        "SELECT * FROM share_links WHERE owner_id = ? AND root_path = ? ORDER BY created_at DESC LIMIT 1",
        (g.user["user_id"], relative_path),
    ).fetchone()


def approved_users_for_names(usernames):
    db = get_db()
    users = []
    for username in dict.fromkeys(usernames):
        user = db.execute(
            "SELECT id, username FROM users WHERE username = ? COLLATE NOCASE AND status = 'approved'",
            (username,),
        ).fetchone()
        if not user:
            abort(404, description=f"Approved user {username} was not found.")
        users.append(user)
    return users


def normalize_access_mode(value):
    if value not in {"view", "edit", "restricted_edit"}:
        abort(400, description="Choose a valid share access option.")
    return value


def notification_state_map(keys):
    if not keys:
        return {}
    placeholders = ",".join("?" for _key in keys)
    return {
        row["notification_key"]: row
        for row in get_db().execute(
            f"SELECT * FROM notification_states WHERE user_id = ? AND notification_key IN ({placeholders})",
            (g.user["user_id"], *keys),
        )
    }


def current_notifications():
    notifications = []
    if g.user["role"] == "admin":
        pending = get_db().execute("SELECT COUNT(*) AS count, COALESCE(MAX(id), 0) AS max_id FROM users WHERE status = 'pending'").fetchone()
        pending_count = pending["count"]
        if pending_count:
            notifications.append({
                "key": f"pending-users:{pending_count}:{pending['max_id']}",
                "type": "admin_pending_users",
                "title": f"{pending_count} account request{'' if pending_count == 1 else 's'} waiting",
                "message": "Review pending user approvals.",
                "url": url_for("admin"),
                "count": pending_count,
            })

    for row in get_db().execute(
        """SELECT share_links.token, share_links.root_path, share_links.created_at, users.username AS owner_username
           FROM share_editors
           JOIN share_links ON share_links.token = share_editors.share_token
           JOIN users ON users.id = share_links.owner_id
           WHERE share_editors.user_id = ?
           ORDER BY share_links.created_at DESC""",
        (g.user["user_id"],),
    ):
        folder_name = Path(row["root_path"]).name if row["root_path"] else row["owner_username"]
        notifications.append({
            "key": f"share:{row['token']}",
            "type": "shared_folder",
            "title": f"{row['owner_username']} shared {folder_name} with you",
            "message": "Open the shared folder.",
            "url": url_for("share_browse_root", token=row["token"]),
            "count": 1,
        })

    states = notification_state_map([notification["key"] for notification in notifications])
    visible = []
    for notification in notifications:
        state = states.get(notification["key"])
        if state and state["dismissed_at"]:
            continue
        notification["read"] = bool(state and state["read_at"])
        visible.append(notification)
    return visible


def share_root(share):
    owner_root = user_accessible_root(share)
    parts = validate_relative_path(share["root_path"])
    root = (owner_root / Path(*parts)).resolve() if parts else owner_root
    if root != owner_root and owner_root not in root.parents:
        abort(400, description="Shared folder is outside the owner's upload folder.")
    if not root.exists() or not root.is_dir():
        abort(404, description="Shared folder was not found.")
    return root


def resolve_share_path(share, relative_path=""):
    root = share_root(share)
    parts = validate_relative_path(relative_path or "")
    path = (root / Path(*parts)).resolve() if parts else root
    if path != root and root not in path.parents:
        abort(400, description="Path is outside the shared folder.")
    return path, root


def can_edit_share(share):
    if not g.user:
        return False
    if g.user["user_id"] == share["owner_id"]:
        return True
    if share["access_mode"] == "edit":
        return True
    if share["access_mode"] != "restricted_edit":
        return False
    return get_db().execute(
        "SELECT 1 FROM share_editors WHERE share_token = ? AND user_id = ?",
        (share["token"], g.user["user_id"]),
    ).fetchone() is not None


def share_edit_required(share):
    if not g.user:
        abort(401, description="Create an account or sign in to edit this shared folder.")
    if not can_edit_share(share):
        abort(403, description="You do not have edit access to this shared folder.")


def share_item_payload(path, root):
    return item_payload(path, root=root)


def share_parent_path(folder, root):
    parent_path = folder.parent.relative_to(root).as_posix() if folder != root else ""
    return "" if parent_path == "." else parent_path


def render_browser(relative_path=""):
    folder = resolve_upload_path(relative_path)
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    root = accessible_root()
    current_path = "" if folder == root else folder.relative_to(root).as_posix()
    response = make_response(
        render_template(
            "index.html",
            current_path=current_path,
            csrf_token=g.session["csrf_token"],
            preferences=user_preferences(),
            user=g.user,
            share=None,
            root_label=g.user["username"],
            storage=storage_payload_for_user(g.user),
        )
    )
    response.headers["Cache-Control"] = "private, max-age=30" if request.headers.get("X-Filedrop-Prefetch") == "1" else "private, no-cache"
    return response


def render_share_browser(token, relative_path=""):
    share = get_share(token)
    folder, root = resolve_share_path(share, relative_path)
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    current_path = "" if folder == root else folder.relative_to(root).as_posix()
    preferences = user_preferences() if g.user else {
        "theme": "system",
        "conflictMode": "add",
        "parallelUploads": DEFAULT_PARALLEL_UPLOADS,
        "confirmSingleDelete": False,
        "confirmBulkDelete": False,
        "fullView": False,
        "sortBy": "manual",
        "sortDirection": "asc",
    }
    response = make_response(
        render_template(
            "index.html",
            current_path=current_path,
            csrf_token=g.session["csrf_token"] if g.session else "",
            preferences=preferences,
            user=g.user,
            share={
                "token": token,
                "url": url_for("share_browse_root", token=token, _external=True),
                "canEdit": can_edit_share(share),
                "requiresAccountToEdit": share["access_mode"] in {"edit", "restricted_edit"} and not g.user,
                "accessMode": share["access_mode"],
            },
            root_label=share["username"],
            storage=None,
        )
    )
    response.headers["Cache-Control"] = "private, no-cache"
    return response


def user_preferences():
    preferences = user_preferences_for_user(g.user)
    get_db().commit()
    return preferences


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"message": error.description}), error.code
    return render_template("message.html", title=f"Error {error.code}", message=error.description), error.code


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception("Unhandled application error")
    if request.path.startswith("/api/"):
        return jsonify({"message": "The server hit an unexpected error.", "error": error.__class__.__name__}), 500
    return render_template("message.html", title="Error 500", message="The server hit an unexpected error."), 500


@app.get("/setup")
def setup():
    if not setup_required():
        return redirect(url_for("login"))
    return render_template("setup.html")


@app.post("/setup")
def setup_post():
    if not setup_required():
        return redirect(url_for("login"))

    password = request.form.get("password", "")
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    error = account_validation_error(username, email, password)
    if not error and password != request.form.get("confirm_password", ""):
        error = "Passwords do not match."
    if error:
        return render_template("setup.html", error=error), 400

    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            db.rollback()
            return redirect(url_for("login"))
        cursor = db.execute(
            """INSERT INTO users
               (username, email, password_hash, role, status, is_initial_admin, avatar_color, created_at)
               VALUES (?, ?, ?, 'admin', 'approved', 1, ?, ?)""",
            (username, email, generate_password_hash(password, method=PASSWORD_HASH_METHOD), aesthetic_color(username), iso_time(utc_now())),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return render_template("setup.html", error="That username or email address is already in use."), 409

    session_id = create_session(cursor.lastrowid)
    response = redirect(url_for("index"))
    set_session_cookie(response, session_id)
    return response


@app.get("/login")
def login():
    if g.user:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.post("/login")
def login_post():
    identifier = request.form.get("identifier", "").strip()
    user = get_db().execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE", (identifier, identifier)
    ).fetchone()
    if not user or not check_password_hash(user["password_hash"], request.form.get("password", "")):
        return render_template("login.html", error="Incorrect username, email, or password."), 401
    if user["status"] != "approved":
        message = "Your account request is waiting for administrator approval." if user["status"] == "pending" else "Your account request was denied."
        return render_template("login.html", error=message), 403
    session_id = create_session(user["id"])
    response = redirect(url_for("change_password") if user["must_change_password"] else url_for("index"))
    set_session_cookie(response, session_id)
    return response


@app.get("/register")
def register():
    return render_template("register.html")


@app.post("/register")
def register_post():
    password = request.form.get("password", "")
    username, email = validate_account_input(request.form.get("username", ""), request.form.get("email", ""), password)
    try:
        get_db().execute(
            """INSERT INTO users (username, email, password_hash, avatar_color, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (username, email, generate_password_hash(password, method=PASSWORD_HASH_METHOD), aesthetic_color(username), iso_time(utc_now())),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return render_template("register.html", error="That username or email address is already in use."), 409
    return render_template("message.html", title="Request submitted", message="Your account request was sent to an administrator for approval.", link_url=url_for("login"), link_text="Back to sign in")


@app.post("/logout")
@login_required
def logout():
    get_db().execute("DELETE FROM sessions WHERE id = ?", (g.session["id"],))
    get_db().commit()
    response = redirect(url_for("login"))
    clear_session_cookie(response)
    return response


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("change_password.html", csrf_token=g.session["csrf_token"], forced=bool(g.user["must_change_password"]))
    password = request.form.get("password", "")
    if len(password) < PASSWORD_MIN_LENGTH:
        return render_template("change_password.html", csrf_token=g.session["csrf_token"], forced=bool(g.user["must_change_password"]), error=f"Password must be at least {PASSWORD_MIN_LENGTH} characters."), 400
    if password != request.form.get("confirm_password", ""):
        return render_template("change_password.html", csrf_token=g.session["csrf_token"], forced=bool(g.user["must_change_password"]), error="Passwords do not match."), 400
    get_db().execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?", (generate_password_hash(password, method=PASSWORD_HASH_METHOD), g.user["user_id"]))
    get_db().execute("DELETE FROM sessions WHERE user_id = ? AND id != ?", (g.user["user_id"], g.session["id"]))
    get_db().commit()
    return redirect(url_for("index"))


@app.get("/admin")
@admin_required
def admin():
    return render_template("admin.html", users=admin_user_rows(), csrf_token=g.session["csrf_token"])


@app.post("/admin/users/<int:user_id>/storage-limit")
@admin_required
def update_user_storage_limit(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404, description="User was not found.")
    try:
        limit_gb = float(request.form.get("storage_limit_gb", ""))
    except ValueError:
        abort(400, description="Storage limit must be a number.")
    if limit_gb <= 0 or limit_gb > 1024 * 1024:
        abort(400, description="Storage limit must be greater than 0 GB.")
    limit_bytes = int(limit_gb * 1024 * 1024 * 1024)
    get_db().execute("UPDATE users SET storage_limit_bytes = ? WHERE id = ?", (limit_bytes, user_id))
    get_db().commit()
    return redirect(url_for("admin"))


@app.post("/admin/users/<int:user_id>/approve")
@admin_required
def approve_user(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404, description="User was not found.")
    get_db().execute("UPDATE users SET status = 'approved' WHERE id = ?", (user_id,))
    get_db().commit()
    (UPLOAD_ROOT / user["username"]).mkdir(exist_ok=True)
    return redirect(url_for("admin"))


@app.post("/admin/users/<int:user_id>/deny")
@admin_required
def deny_user(user_id):
    get_db().execute("UPDATE users SET status = 'denied' WHERE id = ? AND role != 'admin'", (user_id,))
    get_db().execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    get_db().commit()
    return redirect(url_for("admin"))


@app.post("/admin/users/<int:user_id>/reset-password")
@admin_required
def reset_user_password(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404, description="User was not found.")
    temporary_password = secrets.token_urlsafe(TEMPORARY_PASSWORD_BYTES)
    get_db().execute("UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?", (generate_password_hash(temporary_password, method=PASSWORD_HASH_METHOD), user_id))
    get_db().execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    get_db().commit()
    return render_template("admin.html", users=admin_user_rows(), csrf_token=g.session["csrf_token"], temporary_password=temporary_password, reset_username=user["username"])


@app.post("/admin/users/<int:user_id>/promote")
@admin_required
def promote_user(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404, description="User was not found.")
    if user["status"] != "approved":
        abort(409, description="Only approved users can become administrators.")
    get_db().execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))
    get_db().commit()
    return redirect(url_for("admin"))


@app.post("/admin/users/<int:user_id>/demote")
@admin_required
def demote_user(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        abort(404, description="User was not found.")
    if user["is_initial_admin"]:
        abort(409, description="The initial administrator cannot be demoted.")
    get_db().execute("UPDATE users SET role = 'user' WHERE id = ?", (user_id,))
    get_db().commit()
    return redirect(url_for("admin"))


@app.get("/")
@login_required
def index():
    return render_browser()


@app.get("/browse/")
@login_required
def browse_root():
    return render_browser()


@app.get("/browse/<path:relative_path>")
@login_required
def browse(relative_path):
    return render_browser(relative_path)


@app.get("/s/<token>")
def share_browse_root(token):
    return render_share_browser(token)


@app.get("/s/<token>/browse/")
def share_browse_slash(token):
    return render_share_browser(token)


@app.get("/s/<token>/browse/<path:relative_path>")
def share_browse(token, relative_path):
    return render_share_browser(token, relative_path)


@app.get("/api/health")
def health():
    get_db().execute("SELECT 1").fetchone()
    if not UPLOAD_ROOT.exists() or not UPLOAD_ROOT.is_dir() or not os.access(UPLOAD_ROOT, os.W_OK):
        return jsonify({"status": "error", "message": "Upload directory is unavailable."}), 503
    return jsonify({"status": "ok", "checkedAt": iso_time(utc_now())})


@app.get("/api/storage")
@login_required
def storage_usage():
    return jsonify(storage_payload_for_user(g.user))


@app.patch("/api/preferences")
@login_required
def update_preferences():
    data = request.get_json(silent=True) or {}
    if set(data) - {"theme", "conflictMode", "parallelUploads", "confirmSingleDelete", "confirmBulkDelete", "fullView", "sortBy", "sortDirection", "recentDays", "trashRetentionDays", "trashLimitBytes"}:
        abort(400, description="Unknown preference.")
    preferences = user_preferences()
    preferences.update(data)
    if preferences["theme"] not in {"system", "light", "dark"}:
        abort(400, description="Choose a valid appearance.")
    if preferences["conflictMode"] not in {"add", "replace"}:
        abort(400, description="Choose a valid file conflict option.")
    if (
        not isinstance(preferences["parallelUploads"], int)
        or isinstance(preferences["parallelUploads"], bool)
        or not MIN_PARALLEL_UPLOADS <= preferences["parallelUploads"] <= MAX_PARALLEL_UPLOADS
    ):
        abort(400, description=f"Uploads at once must be between {MIN_PARALLEL_UPLOADS} and {MAX_PARALLEL_UPLOADS}.")
    for name in {"confirmSingleDelete", "confirmBulkDelete", "fullView"}:
        if not isinstance(preferences[name], bool):
            abort(400, description=f"{name} must be true or false.")
    if preferences["sortBy"] not in {"manual", "name", "modified", "size", "extension"}:
        abort(400, description="Choose a valid file sort option.")
    if preferences["sortDirection"] not in {"asc", "desc"}:
        abort(400, description="Choose a valid sort direction.")
    for name in {"recentDays", "trashRetentionDays"}:
        if not isinstance(preferences[name], int) or isinstance(preferences[name], bool) or not 1 <= preferences[name] <= 365:
            abort(400, description=f"{name} must be between 1 and 365 days.")
    if not isinstance(preferences["trashLimitBytes"], int) or isinstance(preferences["trashLimitBytes"], bool) or preferences["trashLimitBytes"] < 0:
        abort(400, description="Trash storage limit must be zero or higher.")
    get_db().execute(
        """UPDATE user_preferences
           SET theme = ?, conflict_mode = ?, parallel_uploads = ?,
               confirm_single_delete = ?, confirm_bulk_delete = ?, full_view = ?,
               sort_by = ?, sort_direction = ?, recent_days = ?,
               trash_retention_days = ?, trash_limit_bytes = ?
           WHERE user_id = ?""",
        (
            preferences["theme"],
            preferences["conflictMode"],
            preferences["parallelUploads"],
            preferences["confirmSingleDelete"],
            preferences["confirmBulkDelete"],
            preferences["fullView"],
            preferences["sortBy"],
            preferences["sortDirection"],
            preferences["recentDays"],
            preferences["trashRetentionDays"],
            preferences["trashLimitBytes"],
            g.user["user_id"],
        ),
    )
    cleanup_trash_for_user(g.user, preferences["trashRetentionDays"], preferences["trashLimitBytes"])
    get_db().commit()
    return jsonify(preferences)


@app.get("/api/notifications")
@login_required
def notifications():
    items = current_notifications()
    unread_count = sum(item["count"] for item in items if not item["read"])
    return jsonify({"notifications": items, "unreadCount": unread_count})


@app.post("/api/notifications/read")
@login_required
def read_notifications():
    data = request.get_json(silent=True) or {}
    keys = data.get("keys", [])
    if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
        abort(400, description="Notification keys must be a list of text values.")
    now = iso_time(utc_now())
    get_db().executemany(
        """INSERT INTO notification_states (user_id, notification_key, read_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id, notification_key) DO UPDATE SET read_at = excluded.read_at""",
        ((g.user["user_id"], key, now) for key in keys),
    )
    get_db().commit()
    return jsonify({"read": len(keys)})


@app.delete("/api/notifications/<path:notification_key>")
@login_required
def dismiss_notification(notification_key):
    now = iso_time(utc_now())
    get_db().execute(
        """INSERT INTO notification_states (user_id, notification_key, read_at, dismissed_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, notification_key)
           DO UPDATE SET read_at = excluded.read_at, dismissed_at = excluded.dismissed_at""",
        (g.user["user_id"], notification_key, now, now),
    )
    get_db().commit()
    return Response(status=204)


@app.post("/api/shares")
@login_required
def create_share():
    data = request.get_json(silent=True) or {}
    folder = resolve_upload_path(data.get("path", ""))
    root = accessible_root()
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    access_mode = normalize_access_mode(data.get("accessMode", "view"))
    editor_names = data.get("editors", [])
    if not isinstance(editor_names, list):
        abort(400, description="Editors must be a list of usernames.")
    editor_names = [name.strip() for name in editor_names if isinstance(name, str) and name.strip()]
    if access_mode != "restricted_edit":
        editor_names = []
    db = get_db()
    editors = approved_users_for_names(editor_names)
    shared_path = "" if folder == root else folder.relative_to(root).as_posix()
    existing = find_owned_share_for_path(shared_path)
    if existing:
        db.execute("UPDATE share_links SET access_mode = ? WHERE token = ?", (access_mode, existing["token"]))
        db.execute("DELETE FROM share_editors WHERE share_token = ?", (existing["token"],))
        db.executemany(
            "INSERT INTO share_editors (share_token, user_id) VALUES (?, ?)",
            ((existing["token"], editor["id"]) for editor in editors),
        )
        db.commit()
        return jsonify(share_payload(get_share(existing["token"])))

    token = secrets.token_urlsafe(6)
    while db.execute("SELECT 1 FROM share_links WHERE token = ?", (token,)).fetchone():
        token = secrets.token_urlsafe(6)
    db.execute(
        "INSERT INTO share_links (token, owner_id, root_path, access_mode, created_at) VALUES (?, ?, ?, ?, ?)",
        (token, g.user["user_id"], shared_path, access_mode, iso_time(utc_now())),
    )
    db.executemany(
        "INSERT INTO share_editors (share_token, user_id) VALUES (?, ?)",
        ((token, editor["id"]) for editor in editors),
    )
    db.commit()
    return jsonify(share_payload(get_share(token))), 201


@app.get("/api/shares/current")
@login_required
def current_share():
    folder = resolve_upload_path(request.args.get("path", ""))
    root = accessible_root()
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    shared_path = "" if folder == root else folder.relative_to(root).as_posix()
    share = find_owned_share_for_path(shared_path)
    return jsonify({"share": share_payload(share) if share else None})


@app.patch("/api/shares/<token>")
@login_required
def update_share(token):
    share = get_share(token)
    if share["owner_id"] != g.user["user_id"]:
        abort(403, description="Only the owner can change this share link.")
    data = request.get_json(silent=True) or {}
    access_mode = normalize_access_mode(data.get("accessMode", share["access_mode"]))
    editor_names = data.get("editors", [])
    if not isinstance(editor_names, list):
        abort(400, description="Editors must be a list of usernames.")
    editor_names = [name.strip() for name in editor_names if isinstance(name, str) and name.strip()]
    if access_mode != "restricted_edit":
        editor_names = []
    editors = approved_users_for_names(editor_names)
    db = get_db()
    db.execute("UPDATE share_links SET access_mode = ? WHERE token = ?", (access_mode, token))
    db.execute("DELETE FROM share_editors WHERE share_token = ?", (token,))
    db.executemany(
        "INSERT INTO share_editors (share_token, user_id) VALUES (?, ?)",
        ((token, editor["id"]) for editor in editors),
    )
    db.commit()
    return jsonify(share_payload(get_share(token)))


@app.delete("/api/shares/<token>")
@login_required
def delete_share(token):
    share = get_share(token)
    if share["owner_id"] != g.user["user_id"]:
        abort(403, description="Only the owner can remove this share link.")
    get_db().execute("DELETE FROM share_links WHERE token = ?", (token,))
    get_db().commit()
    return Response(status=204)


@app.get("/api/users/search")
@login_required
def search_users():
    query = request.args.get("q", "").strip()
    if len(query) < 1:
        return jsonify({"users": []})
    users = [
        {"id": row["id"], "username": row["username"]}
        for row in get_db().execute(
            """SELECT id, username FROM users
               WHERE status = 'approved' AND username LIKE ? COLLATE NOCASE
               ORDER BY username COLLATE NOCASE
               LIMIT 8""",
            (f"{query}%",),
        )
    ]
    return jsonify({"users": users})


@app.get("/api/items")
@login_required
def items():
    folder = resolve_upload_path(request.args.get("path", ""))
    root = accessible_root()
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    parent_path = folder.parent.relative_to(root).as_posix() if folder != root else ""
    current = "" if folder == root else folder.relative_to(root).as_posix()
    record_folder_use(current)
    get_db().commit()
    return jsonify({"items": with_favorites(ordered_items(folder)), "parent": "" if parent_path == "." else parent_path, "path": current})


def item_from_record(row):
    path = resolve_upload_path(row["path"])
    if not path.exists() or path.name == TRASH_DIRECTORY_NAME:
        return None
    return item_payload(path)


@app.get("/api/items/recent")
@login_required
def recent_items():
    days = request.args.get("days", user_preferences()["recentDays"])
    try:
        days = max(1, min(365, int(days)))
    except (TypeError, ValueError):
        abort(400, description="Recent time period must be a number of days.")
    cutoff = (utc_now() - timedelta(days=days)).timestamp()
    ensure_search_index(g.user)
    rows = get_db().execute(
        """SELECT * FROM file_records
           WHERE user_id = ? AND path != '' AND modified_at >= ? AND path NOT LIKE ?
           ORDER BY modified_at DESC
           LIMIT 200""",
        (g.user["user_id"], cutoff, f"{TRASH_DIRECTORY_NAME}/%"),
    ).fetchall()
    items = [item for row in rows if (item := item_from_record(row))]
    return jsonify({"items": with_favorites(items), "path": "__recents__", "parent": ""})


@app.get("/api/items/favorites")
@login_required
def favorite_items():
    items = []
    for row in get_db().execute("SELECT path FROM favorites WHERE user_id = ? ORDER BY created_at DESC", (g.user["user_id"],)):
        path = resolve_upload_path(row["path"])
        if path.exists():
            items.append(item_payload(path))
    return jsonify({"items": with_favorites(items, {item["path"] for item in items}), "path": "__favorites__", "parent": ""})


@app.patch("/api/items/favorite")
@login_required
def toggle_favorite():
    data = request.get_json(silent=True) or {}
    item_path = resolve_upload_path(data.get("path", ""))
    if item_path == accessible_root() or not item_path.exists():
        abort(404, description="File or folder was not found.")
    relative_path = item_path.relative_to(accessible_root()).as_posix()
    favorite = data.get("favorite")
    db = get_db()
    if favorite is False:
        db.execute("DELETE FROM favorites WHERE user_id = ? AND path = ?", (g.user["user_id"], relative_path))
        is_favorite = False
    else:
        db.execute(
            "INSERT OR IGNORE INTO favorites (user_id, path, created_at) VALUES (?, ?, ?)",
            (g.user["user_id"], relative_path, iso_time(utc_now())),
        )
        is_favorite = True
    db.commit()
    return jsonify({"path": relative_path, "favorite": is_favorite})


@app.get("/api/sidebar")
@login_required
def sidebar():
    root = accessible_root()
    favorite = favorite_paths()
    shared = [
        {
            **item_payload(root / row["root_path"] if row["root_path"] else root),
            "token": row["token"],
            "url": url_for("share_browse_root", token=row["token"]),
        }
        for row in get_db().execute(
            "SELECT token, root_path FROM share_links WHERE owner_id = ? ORDER BY created_at DESC",
            (g.user["user_id"],),
        )
        if (root / row["root_path"] if row["root_path"] else root).exists()
    ]
    top_folders = [item_payload(path) for path in visible_user_items(root) if path.is_dir()]
    sidebar_rows = {
        row["folder_path"]: row
        for row in get_db().execute("SELECT * FROM sidebar_folders WHERE user_id = ?", (g.user["user_id"],))
    }

    def folder_rank(item):
        row = sidebar_rows.get(item["path"])
        usage = get_db().execute(
            "SELECT use_count, last_used_at FROM folder_usage WHERE user_id = ? AND folder_path = ?",
            (g.user["user_id"], item["path"]),
        ).fetchone()
        hidden = row["hidden"] if row else 0
        manual = row["position"] if row and not hidden else 10_000
        use_count = usage["use_count"] if usage else 0
        last_used = usage["last_used_at"] if usage else ""
        return (hidden, manual, -use_count, last_used, item["name"].casefold())

    visible_folders = [
        item for item in sorted(top_folders, key=folder_rank)
        if not (sidebar_rows.get(item["path"]) and sidebar_rows[item["path"]]["hidden"])
    ]
    return jsonify({
        "shared": with_favorites(shared, favorite),
        "folders": with_favorites(visible_folders[:8], favorite),
    })


@app.put("/api/sidebar/folders")
@login_required
def update_sidebar_folders():
    data = request.get_json(silent=True) or {}
    paths = data.get("paths", [])
    hidden = data.get("hidden", [])
    if not isinstance(paths, list) or not isinstance(hidden, list):
        abort(400, description="Sidebar folders must be lists.")
    root = accessible_root()
    db = get_db()
    for index, path in enumerate(paths):
        folder = resolve_upload_path(path)
        if folder == root or not folder.exists() or not folder.is_dir():
            abort(404, description="Folder was not found.")
        db.execute(
            """INSERT INTO sidebar_folders (user_id, folder_path, position, hidden)
               VALUES (?, ?, ?, 0)
               ON CONFLICT(user_id, folder_path)
               DO UPDATE SET position = excluded.position, hidden = 0""",
            (g.user["user_id"], path, index),
        )
    for path in hidden:
        folder = resolve_upload_path(path)
        if folder == root or not folder.exists() or not folder.is_dir():
            continue
        db.execute(
            """INSERT INTO sidebar_folders (user_id, folder_path, position, hidden)
               VALUES (?, ?, 10000, 1)
               ON CONFLICT(user_id, folder_path)
               DO UPDATE SET hidden = 1""",
            (g.user["user_id"], path),
        )
    db.commit()
    return sidebar()


@app.get("/api/search")
@login_required
def search_files():
    query = request.args.get("q", "").strip()
    current_path = "/".join(validate_relative_path(request.args.get("path", ""), "Search path"))
    if len(query) < 1:
        return jsonify({"results": []})
    ensure_search_index(g.user)
    folded = query.casefold()
    terms = list(search_tokens(query))
    user_id = g.user["user_id"]
    db = get_db()
    rows_by_id = {}

    def add_rows(rows):
        for row in rows:
            if row["path"]:
                rows_by_id[row["file_id"]] = row

    add_rows(db.execute(
        """SELECT * FROM file_records
           WHERE user_id = ? AND (path_folded = ? OR name_folded = ?)
           LIMIT 40""",
        (user_id, folded, folded),
    ))
    add_rows(db.execute(
        """SELECT file_records.*
           FROM file_prefixes JOIN file_records ON file_records.file_id = file_prefixes.file_id
           WHERE file_records.user_id = ? AND file_prefixes.prefix = ?
           LIMIT 80""",
        (user_id, folded),
    ))
    if terms:
        placeholders = ",".join("?" for _ in terms)
        add_rows(db.execute(
            f"""SELECT file_records.*, COUNT(file_terms.term) AS matched_terms
                FROM file_terms JOIN file_records ON file_records.file_id = file_terms.file_id
                WHERE file_records.user_id = ? AND file_terms.term IN ({placeholders})
                GROUP BY file_records.file_id
                ORDER BY matched_terms DESC
                LIMIT 80""",
            (user_id, *terms),
        ))

    def rank(row):
        parent = Path(row["path"]).parent.as_posix()
        parent = "" if parent == "." else parent
        in_current = parent == current_path
        under_current = bool(current_path) and row["path"].startswith(f"{current_path}/")
        exact_name = row["name_folded"] == folded
        prefix_name = row["name_folded"].startswith(folded)
        return (0 if in_current else 1 if under_current else 2, 0 if exact_name else 1 if prefix_name else 2, row["name_folded"])

    results = sorted(rows_by_id.values(), key=rank)[:30]
    return jsonify({
        "results": [
            {
                "fileId": row["file_id"],
                "name": row["name"],
                "path": row["path"],
                "parent": "" if Path(row["path"]).parent.as_posix() == "." else Path(row["path"]).parent.as_posix(),
                "type": row["type"],
                "size": row["size"],
            }
            for row in results
        ]
    })


@app.get("/api/shares/<token>/items")
def shared_items(token):
    share = get_share(token)
    folder, root = resolve_share_path(share, request.args.get("path", ""))
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    user_id = g.user["user_id"] if g.user else None
    return jsonify({
        "items": ordered_items(folder, root=root, user_id=user_id),
        "parent": share_parent_path(folder, root),
        "path": "" if folder == root else folder.relative_to(root).as_posix(),
    })


@app.post("/api/folders")
@login_required
def create_folder():
    data = request.get_json(silent=True) or {}
    folder, name = resolve_upload_path(data.get("path", "")), data.get("name", "")
    validate_name(name, "Folder names")
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    new_folder = folder / name
    if new_folder.exists():
        abort(409, description="A file or folder with that name already exists.")
    new_folder.mkdir()
    upsert_search_record(g.user, new_folder)
    get_db().commit()
    return jsonify(item_payload(new_folder)), 201


@app.post("/api/shares/<token>/folders")
def create_shared_folder(token):
    share = get_share(token)
    share_edit_required(share)
    data = request.get_json(silent=True) or {}
    folder, root = resolve_share_path(share, data.get("path", ""))
    name = data.get("name", "")
    validate_name(name, "Folder names")
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    new_folder = folder / name
    if new_folder.exists():
        abort(409, description="A file or folder with that name already exists.")
    new_folder.mkdir()
    owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
    upsert_search_record(owner, new_folder, root=user_accessible_root(owner))
    get_db().commit()
    return jsonify(share_item_payload(new_folder, root)), 201


@app.post("/api/folders/tree")
@login_required
def create_folder_tree():
    data = request.get_json(silent=True) or {}
    root = resolve_upload_path(data.get("path", ""))
    directories = data.get("directories", [])
    if not root.exists() or not root.is_dir():
        abort(404, description="Folder was not found.")
    if not isinstance(directories, list):
        abort(400, description="Directories must be a list of paths.")
    if not all(isinstance(path, str) for path in directories):
        abort(400, description="Directory paths must be text.")

    tree = []
    for relative_path in sorted(set(directories), key=lambda path: (path.count("/"), path)):
        parts = validate_relative_path(relative_path, "Directory paths")
        if not parts:
            continue
        directory = resolve_upload_path("/".join([data.get("path", "").strip("/"), *parts]))
        for ancestor in [directory, *directory.parents]:
            if ancestor.exists() and not ancestor.is_dir():
                abort(409, description=f"A file already exists in the path for {relative_path}.")
            if ancestor == root:
                break
        tree.append(directory)

    created = 0
    for directory in tree:
        if directory.exists():
            continue
        directory.mkdir(parents=True)
        upsert_search_record(g.user, directory)
        created += 1
    get_db().commit()
    return jsonify({"created": created}), 201


@app.post("/api/shares/<token>/folders/tree")
def create_shared_folder_tree(token):
    share = get_share(token)
    share_edit_required(share)
    data = request.get_json(silent=True) or {}
    root_folder, share_root_path = resolve_share_path(share, data.get("path", ""))
    directories = data.get("directories", [])
    if not root_folder.exists() or not root_folder.is_dir():
        abort(404, description="Folder was not found.")
    if not isinstance(directories, list):
        abort(400, description="Directories must be a list of paths.")
    if not all(isinstance(path, str) for path in directories):
        abort(400, description="Directory paths must be text.")

    tree = []
    for relative_path in sorted(set(directories), key=lambda path: (path.count("/"), path)):
        parts = validate_relative_path(relative_path, "Directory paths")
        if not parts:
            continue
        base = data.get("path", "").strip("/")
        directory, _root = resolve_share_path(share, "/".join([base, *parts]))
        for ancestor in [directory, *directory.parents]:
            if ancestor.exists() and not ancestor.is_dir():
                abort(409, description=f"A file already exists in the path for {relative_path}.")
            if ancestor == root_folder:
                break
            if ancestor == share_root_path:
                break
        tree.append(directory)

    created = 0
    for directory in tree:
        if directory.exists():
            continue
        directory.mkdir(parents=True)
        owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
        upsert_search_record(owner, directory, root=user_accessible_root(owner))
        created += 1
    get_db().commit()
    return jsonify({"created": created}), 201


@app.post("/api/folders/from-selection")
@login_required
def create_folder_from_selection():
    data = request.get_json(silent=True) or {}
    folder, name = resolve_upload_path(data.get("path", "")), data.get("name", "")
    item_paths = data.get("paths", [])
    validate_name(name, "Folder names")
    if not isinstance(item_paths, list) or not item_paths:
        abort(400, description="Select at least one file or folder.")
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    new_folder = folder / name
    if new_folder.exists():
        abort(409, description="A file or folder with that name already exists.")
    replace_existing = data.get("replace") is True
    moves = prepare_item_moves(item_paths, new_folder, replace_existing=replace_existing)
    new_folder.mkdir()
    moved = execute_item_moves(moves, replace_existing=replace_existing)
    index_path_tree(g.user, new_folder)
    get_db().commit()
    return jsonify({"folder": item_payload(new_folder), "moved": moved}), 201


@app.post("/api/shares/<token>/folders/from-selection")
def create_shared_folder_from_selection(token):
    share = get_share(token)
    share_edit_required(share)
    data = request.get_json(silent=True) or {}
    folder, root = resolve_share_path(share, data.get("path", ""))
    name = data.get("name", "")
    item_paths = data.get("paths", [])
    validate_name(name, "Folder names")
    if not isinstance(item_paths, list) or not item_paths:
        abort(400, description="Select at least one file or folder.")
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    new_folder = folder / name
    if new_folder.exists():
        abort(409, description="A file or folder with that name already exists.")
    replace_existing = data.get("replace") is True
    resolver = lambda path: resolve_share_path(share, path)[0]
    moves = prepare_item_moves(item_paths, new_folder, replace_existing=replace_existing, root=root, resolver=resolver)
    new_folder.mkdir()
    moved = execute_item_moves(moves, replace_existing=replace_existing)
    owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
    index_path_tree(owner, new_folder, root=user_accessible_root(owner))
    get_db().commit()
    return jsonify({"folder": share_item_payload(new_folder, root), "moved": moved}), 201


@app.patch("/api/items")
@login_required
def rename_item():
    data = request.get_json(silent=True) or {}
    item_path, new_name = resolve_upload_path(data.get("path", "")), data.get("name", "")
    validate_name(new_name)
    if item_path == accessible_root() or not item_path.exists():
        abort(404, description="File or folder was not found.")
    destination = item_path.with_name(new_name)
    if destination.exists():
        abort(409, description="A file or folder with that name already exists.")
    old_relative = item_path.relative_to(accessible_root()).as_posix()
    item_path.rename(destination)
    delete_search_records(g.user, old_relative)
    index_path_tree(g.user, destination)
    get_db().commit()
    return jsonify(item_payload(destination))


@app.patch("/api/shares/<token>/items")
def rename_shared_item(token):
    share = get_share(token)
    share_edit_required(share)
    data = request.get_json(silent=True) or {}
    item_path, root = resolve_share_path(share, data.get("path", ""))
    new_name = data.get("name", "")
    validate_name(new_name)
    if item_path == root or not item_path.exists():
        abort(404, description="File or folder was not found.")
    destination = item_path.with_name(new_name)
    if destination.exists():
        abort(409, description="A file or folder with that name already exists.")
    owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
    old_relative = item_path.relative_to(user_accessible_root(owner)).as_posix()
    item_path.rename(destination)
    delete_search_records(owner, old_relative)
    index_path_tree(owner, destination, root=user_accessible_root(owner))
    get_db().commit()
    return jsonify(share_item_payload(destination, root))


@app.post("/api/items/move")
@login_required
def move_items():
    data = request.get_json(silent=True) or {}
    destination_folder = resolve_upload_path(data.get("destination", ""))
    item_paths = data.get("paths", [])
    if not isinstance(item_paths, list) or not item_paths:
        abort(400, description="Select at least one file or folder to move.")
    if not destination_folder.exists() or not destination_folder.is_dir():
        abort(404, description="Destination folder was not found.")

    replace_existing = data.get("replace") is True
    moves = prepare_item_moves(item_paths, destination_folder, replace_existing=replace_existing)
    old_paths = [path.relative_to(accessible_root()).as_posix() for path, _destination in moves]
    moved = execute_item_moves(moves, replace_existing=replace_existing)
    for old_path in old_paths:
        delete_search_records(g.user, old_path)
    for _source, destination in moves:
        index_path_tree(g.user, destination)
    get_db().commit()
    return jsonify({"moved": moved})


@app.post("/api/shares/<token>/items/move")
def move_shared_items(token):
    share = get_share(token)
    share_edit_required(share)
    data = request.get_json(silent=True) or {}
    destination_folder, root = resolve_share_path(share, data.get("destination", ""))
    item_paths = data.get("paths", [])
    if not isinstance(item_paths, list) or not item_paths:
        abort(400, description="Select at least one file or folder to move.")
    if not destination_folder.exists() or not destination_folder.is_dir():
        abort(404, description="Destination folder was not found.")

    replace_existing = data.get("replace") is True
    resolver = lambda path: resolve_share_path(share, path)[0]
    moves = prepare_item_moves(item_paths, destination_folder, replace_existing=replace_existing, root=root, resolver=resolver)
    owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
    owner_root = user_accessible_root(owner)
    old_paths = [path.relative_to(owner_root).as_posix() for path, _destination in moves]
    moved = execute_item_moves(moves, replace_existing=replace_existing)
    for old_path in old_paths:
        delete_search_records(owner, old_path)
    for _source, destination in moves:
        index_path_tree(owner, destination, root=owner_root)
    get_db().commit()
    return jsonify({"moved": moved})


@app.put("/api/items/order")
@login_required
def reorder_items():
    data = request.get_json(silent=True) or {}
    folder = resolve_upload_path(data.get("path", ""))
    item_paths = data.get("paths", [])
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    if not isinstance(item_paths, list) or not all(isinstance(path, str) for path in item_paths):
        abort(400, description="Item paths must be a list of text paths.")
    actual_paths = {item_payload(path)["path"] for path in folder.iterdir()}
    if len(item_paths) != len(set(item_paths)) or set(item_paths) != actual_paths:
        abort(400, description="The item order must include every item in the folder exactly once.")
    root = accessible_root()
    folder_path = "" if folder == root else folder.relative_to(root).as_posix()
    db = get_db()
    db.execute("DELETE FROM item_orders WHERE user_id = ? AND folder_path = ?", (g.user["user_id"], folder_path))
    db.executemany(
        "INSERT INTO item_orders (user_id, folder_path, item_path, position) VALUES (?, ?, ?, ?)",
        ((g.user["user_id"], folder_path, item_path, position) for position, item_path in enumerate(item_paths)),
    )
    db.commit()
    return jsonify({"ordered": len(item_paths)})


@app.put("/api/shares/<token>/items/order")
def reorder_shared_items(token):
    share = get_share(token)
    share_edit_required(share)
    data = request.get_json(silent=True) or {}
    folder, root = resolve_share_path(share, data.get("path", ""))
    item_paths = data.get("paths", [])
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    if not isinstance(item_paths, list) or not all(isinstance(path, str) for path in item_paths):
        abort(400, description="Item paths must be a list of text paths.")
    actual_paths = {share_item_payload(path, root)["path"] for path in folder.iterdir()}
    if len(item_paths) != len(set(item_paths)) or set(item_paths) != actual_paths:
        abort(400, description="The item order must include every item in the folder exactly once.")
    folder_path = "" if folder == root else folder.relative_to(root).as_posix()
    db = get_db()
    db.execute("DELETE FROM item_orders WHERE user_id = ? AND folder_path = ?", (g.user["user_id"], folder_path))
    db.executemany(
        "INSERT INTO item_orders (user_id, folder_path, item_path, position) VALUES (?, ?, ?, ?)",
        ((g.user["user_id"], folder_path, item_path, position) for position, item_path in enumerate(item_paths)),
    )
    db.commit()
    return jsonify({"ordered": len(item_paths)})


@app.get("/api/trash")
@login_required
def trash_items():
    cleanup_trash_for_user(g.user)
    get_db().commit()
    rows = get_db().execute(
        "SELECT * FROM trash_items WHERE user_id = ? ORDER BY deleted_at DESC LIMIT 300",
        (g.user["user_id"],),
    ).fetchall()
    return jsonify({
        "items": [
            {
                "trashId": row["trash_id"],
                "name": row["name"],
                "path": row["original_path"],
                "type": row["type"],
                "size": row["size"],
                "deletedAt": row["deleted_at"],
                "modifiedAt": datetime.fromisoformat(row["deleted_at"]).timestamp(),
            }
            for row in rows
        ],
        "usageBytes": trash_usage_for_user(g.user),
        "path": "__trash__",
        "parent": "",
    })


@app.delete("/api/trash")
@login_required
def empty_trash():
    rows = get_db().execute("SELECT * FROM trash_items WHERE user_id = ?", (g.user["user_id"],)).fetchall()
    for row in rows:
        remove_trash_row(g.user, row)
    get_db().commit()
    return jsonify({"deleted": len(rows)})


@app.delete("/api/items")
@login_required
def delete_item():
    item_path = resolve_upload_path(request.args.get("path", ""))
    if item_path == accessible_root() or not item_path.exists():
        abort(404, description="File or folder was not found.")
    move_item_to_trash(g.user, item_path)
    get_db().commit()
    return Response(status=204)


@app.delete("/api/shares/<token>/items")
def delete_shared_item(token):
    share = get_share(token)
    share_edit_required(share)
    item_path, root = resolve_share_path(share, request.args.get("path", ""))
    if item_path == root or not item_path.exists():
        abort(404, description="File or folder was not found.")
    owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
    move_item_to_trash(owner, item_path)
    get_db().commit()
    return Response(status=204)


@app.post("/api/files")
@login_required
def upload_file():
    upload_id = request.headers.get("X-Upload-ID", "").strip()
    if upload_id and (len(upload_id) > 100 or not upload_id.replace("-", "").isalnum()):
        abort(400, description="Upload ID is invalid.")
    if upload_id:
        db = get_db()
        receipt = db.execute(
            "SELECT path FROM upload_receipts WHERE user_id = ? AND upload_id = ?",
            (g.user["user_id"], upload_id),
        ).fetchone()
        if receipt:
            path = accessible_root() / receipt["path"]
            return jsonify({"filename": path.name, "path": receipt["path"], "item": item_payload(path)}), 200
    upload = request.files.get("file")
    filename = parse_upload_file(upload)
    incoming_size = upload_size(upload)
    folder = resolve_upload_path(request.form.get("path", ""))
    if folder.exists() and not folder.is_dir():
        abort(409, description="A file already exists in the upload path.")
    folder.mkdir(parents=True, exist_ok=True)
    replace_existing = request.form.get("replace", "").lower() in {"1", "true", "yes"}
    saved_filename = filename if replace_existing else available_filename(folder, filename)
    destination = folder / saved_filename
    if replace_existing and destination.exists() and destination.is_dir():
        abort(409, description="A folder with that name already exists.")
    enforce_storage_limit(g.user, incoming_size, destination if replace_existing else None)
    upload.save(destination)
    saved_path = (folder / saved_filename).relative_to(accessible_root()).as_posix()
    upsert_search_record(g.user, destination)
    if upload_id:
        db.execute(
            "INSERT INTO upload_receipts (user_id, upload_id, path, created_at) VALUES (?, ?, ?, ?)",
            (g.user["user_id"], upload_id, saved_path, iso_time(utc_now())),
        )
    get_db().commit()
    return jsonify({"filename": saved_filename, "path": saved_path, "item": item_payload(destination)}), 201


@app.post("/api/shares/<token>/files")
def upload_shared_file(token):
    share = get_share(token)
    share_edit_required(share)
    upload_id = request.headers.get("X-Upload-ID", "").strip()
    if upload_id and (len(upload_id) > 100 or not upload_id.replace("-", "").isalnum()):
        abort(400, description="Upload ID is invalid.")
    upload = request.files.get("file")
    filename = parse_upload_file(upload)
    incoming_size = upload_size(upload)
    folder, root = resolve_share_path(share, request.form.get("path", ""))
    if folder.exists() and not folder.is_dir():
        abort(409, description="A file already exists in the upload path.")
    folder.mkdir(parents=True, exist_ok=True)
    replace_existing = request.form.get("replace", "").lower() in {"1", "true", "yes"}
    saved_filename = filename if replace_existing else available_filename(folder, filename)
    destination = folder / saved_filename
    if replace_existing and destination.exists() and destination.is_dir():
        abort(409, description="A folder with that name already exists.")
    owner = get_db().execute("SELECT * FROM users WHERE id = ?", (share["owner_id"],)).fetchone()
    enforce_storage_limit(owner, incoming_size, destination if replace_existing else None)
    upload.save(destination)
    saved_path = destination.relative_to(root).as_posix()
    upsert_search_record(owner, destination, root=user_accessible_root(owner))
    get_db().commit()
    return jsonify({"filename": saved_filename, "path": saved_path, "item": share_item_payload(destination, root)}), 201


@app.get("/api/files/<path:filename>")
@login_required
def download_file(filename):
    file_path = resolve_upload_path(filename)
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="File was not found.")
    return send_from_directory(file_path.parent, file_path.name, as_attachment=True)


@app.get("/api/shares/<token>/files/<path:filename>")
def download_shared_file(token, filename):
    share = get_share(token)
    file_path, _root = resolve_share_path(share, filename)
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="File was not found.")
    return send_from_directory(file_path.parent, file_path.name, as_attachment=True)


@app.get("/api/previews/<path:filename>")
@login_required
def preview_file(filename):
    file_path = resolve_upload_path(filename)
    extension = file_path.suffix.lstrip(".").lower()
    if not file_path.exists() or not file_path.is_file() or extension not in IMAGE_PREVIEW_EXTENSIONS | VIDEO_PREVIEW_EXTENSIONS:
        abort(404, description="Preview was not found.")
    return send_from_directory(file_path.parent, file_path.name)


@app.get("/api/shares/<token>/previews/<path:filename>")
def preview_shared_file(token, filename):
    share = get_share(token)
    file_path, _root = resolve_share_path(share, filename)
    extension = file_path.suffix.lstrip(".").lower()
    if not file_path.exists() or not file_path.is_file() or extension not in IMAGE_PREVIEW_EXTENSIONS | VIDEO_PREVIEW_EXTENSIONS:
        abort(404, description="Preview was not found.")
    return send_from_directory(file_path.parent, file_path.name)


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True, threaded=True)
