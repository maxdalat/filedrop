import base64
import hashlib
import os
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from filedrop_config import (
    AVATAR_COLORS,
    BLOCKED_FILENAME_CHARS,
    CSRF_TOKEN_BYTES,
    DATABASE_FILENAME,
    DEFAULT_PARALLEL_UPLOADS,
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
        CREATE TABLE IF NOT EXISTS app_migrations (
            name TEXT PRIMARY KEY
        );
        """
    )
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "is_initial_admin" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_initial_admin INTEGER NOT NULL DEFAULT 0")
    preference_columns = {row["name"] for row in db.execute("PRAGMA table_info(user_preferences)")}
    if "sort_by" not in preference_columns:
        db.execute("ALTER TABLE user_preferences ADD COLUMN sort_by TEXT NOT NULL DEFAULT 'manual'")
    if "sort_direction" not in preference_columns:
        db.execute("ALTER TABLE user_preferences ADD COLUMN sort_direction TEXT NOT NULL DEFAULT 'asc'")
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
                      users.must_change_password, users.avatar_color
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
        return replacement
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


def accessible_root():
    home = (UPLOAD_ROOT / g.user["username"]).resolve()
    home.mkdir(exist_ok=True)
    return home


def user_accessible_root(user):
    home = (UPLOAD_ROOT / user["username"]).resolve()
    home.mkdir(exist_ok=True)
    return home


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
    items = [item_payload(path, root=root) for path in folder.iterdir()]
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
        )
    )
    response.headers["Cache-Control"] = "private, no-cache"
    return response


def user_preferences():
    db = get_db()
    db.execute("INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)", (g.user["user_id"],))
    db.commit()
    row = db.execute("SELECT * FROM user_preferences WHERE user_id = ?", (g.user["user_id"],)).fetchone()
    return {
        "theme": row["theme"],
        "conflictMode": row["conflict_mode"],
        "parallelUploads": row["parallel_uploads"],
        "confirmSingleDelete": bool(row["confirm_single_delete"]),
        "confirmBulkDelete": bool(row["confirm_bulk_delete"]),
        "fullView": bool(row["full_view"]),
        "sortBy": row["sort_by"],
        "sortDirection": row["sort_direction"],
    }


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
    users = get_db().execute("SELECT * FROM users ORDER BY status != 'pending', username COLLATE NOCASE").fetchall()
    return render_template("admin.html", users=users, csrf_token=g.session["csrf_token"])


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
    users = get_db().execute("SELECT * FROM users ORDER BY status != 'pending', username COLLATE NOCASE").fetchall()
    return render_template("admin.html", users=users, csrf_token=g.session["csrf_token"], temporary_password=temporary_password, reset_username=user["username"])


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


@app.patch("/api/preferences")
@login_required
def update_preferences():
    data = request.get_json(silent=True) or {}
    if set(data) - {"theme", "conflictMode", "parallelUploads", "confirmSingleDelete", "confirmBulkDelete", "fullView", "sortBy", "sortDirection"}:
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
    get_db().execute(
        """UPDATE user_preferences
           SET theme = ?, conflict_mode = ?, parallel_uploads = ?,
               confirm_single_delete = ?, confirm_bulk_delete = ?, full_view = ?,
               sort_by = ?, sort_direction = ?
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
            g.user["user_id"],
        ),
    )
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
    return "", 204


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
    return "", 204


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
    return jsonify({"items": ordered_items(folder), "parent": "" if parent_path == "." else parent_path, "path": "" if folder == root else folder.relative_to(root).as_posix()})


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
        created += 1
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
        created += 1
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
    item_path.rename(destination)
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
    item_path.rename(destination)
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
    return jsonify({"moved": execute_item_moves(moves, replace_existing=replace_existing)})


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
    return jsonify({"moved": execute_item_moves(moves, replace_existing=replace_existing)})


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


@app.delete("/api/items")
@login_required
def delete_item():
    item_path = resolve_upload_path(request.args.get("path", ""))
    if item_path == accessible_root() or not item_path.exists():
        abort(404, description="File or folder was not found.")
    shutil.rmtree(item_path) if item_path.is_dir() else item_path.unlink()
    return "", 204


@app.delete("/api/shares/<token>/items")
def delete_shared_item(token):
    share = get_share(token)
    share_edit_required(share)
    item_path, root = resolve_share_path(share, request.args.get("path", ""))
    if item_path == root or not item_path.exists():
        abort(404, description="File or folder was not found.")
    shutil.rmtree(item_path) if item_path.is_dir() else item_path.unlink()
    return "", 204


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
            return jsonify({"filename": Path(receipt["path"]).name, "path": receipt["path"]}), 200
    filename = parse_upload_file(request.files.get("file"))
    folder = resolve_upload_path(request.form.get("path", ""))
    if folder.exists() and not folder.is_dir():
        abort(409, description="A file already exists in the upload path.")
    folder.mkdir(parents=True, exist_ok=True)
    replace_existing = request.form.get("replace", "").lower() in {"1", "true", "yes"}
    saved_filename = filename if replace_existing else available_filename(folder, filename)
    destination = folder / saved_filename
    if replace_existing and destination.exists() and destination.is_dir():
        abort(409, description="A folder with that name already exists.")
    request.files["file"].save(folder / saved_filename)
    saved_path = (folder / saved_filename).relative_to(accessible_root()).as_posix()
    if upload_id:
        db.execute(
            "INSERT INTO upload_receipts (user_id, upload_id, path, created_at) VALUES (?, ?, ?, ?)",
            (g.user["user_id"], upload_id, saved_path, iso_time(utc_now())),
        )
        db.commit()
    return jsonify({"filename": saved_filename, "path": saved_path}), 201


@app.post("/api/shares/<token>/files")
def upload_shared_file(token):
    share = get_share(token)
    share_edit_required(share)
    upload_id = request.headers.get("X-Upload-ID", "").strip()
    if upload_id and (len(upload_id) > 100 or not upload_id.replace("-", "").isalnum()):
        abort(400, description="Upload ID is invalid.")
    filename = parse_upload_file(request.files.get("file"))
    folder, root = resolve_share_path(share, request.form.get("path", ""))
    if folder.exists() and not folder.is_dir():
        abort(409, description="A file already exists in the upload path.")
    folder.mkdir(parents=True, exist_ok=True)
    replace_existing = request.form.get("replace", "").lower() in {"1", "true", "yes"}
    saved_filename = filename if replace_existing else available_filename(folder, filename)
    destination = folder / saved_filename
    if replace_existing and destination.exists() and destination.is_dir():
        abort(409, description="A folder with that name already exists.")
    request.files["file"].save(destination)
    saved_path = destination.relative_to(root).as_posix()
    return jsonify({"filename": saved_filename, "path": saved_path}), 201


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
