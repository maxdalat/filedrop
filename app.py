import base64
import hashlib
import secrets
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from filedrop_config import (
    ALLOWED_EXTENSIONS,
    AVATAR_COLORS,
    BLOCKED_FILENAME_CHARS,
    CSRF_TOKEN_BYTES,
    DATABASE_FILENAME,
    DEFAULT_UPLOAD_DIRECTORY,
    EMAIL_MAX_LENGTH,
    FORM_CONSTRAINTS,
    INSTANCE_PATH_ENV,
    MAX_UPLOAD_SIZE_BYTES,
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
UPLOAD_ROOT.mkdir(exist_ok=True)

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


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.context_processor
def inject_form_constraints():
    return {"form_constraints": FORM_CONSTRAINTS}


def init_db():
    db = get_db()
    db.executescript(
        """
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
        """
    )
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "is_initial_admin" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_initial_admin INTEGER NOT NULL DEFAULT 0")
    if not db.execute("SELECT 1 FROM users WHERE is_initial_admin = 1").fetchone():
        first_admin = db.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        if first_admin:
            db.execute("UPDATE users SET is_initial_admin = 1 WHERE id = ?", (first_admin["id"],))
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (iso_time(utc_now()),))
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
            return redirect(url_for("change_password"))
        return view(*args, **kwargs)
    return wrapped


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


def parse_upload_file(upload):
    if not upload or not upload.filename:
        abort(400, description="No file was selected.")
    filename = upload.filename
    validate_name(filename, "Filenames")
    filename_for_extension = filename.rstrip()
    if "." not in filename_for_extension:
        abort(400, description="Files must include an extension.")
    extension = filename_for_extension.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        abort(400, description=f".{extension} files are not allowed.")
    return filename


def accessible_root():
    if g.user["role"] == "admin":
        return UPLOAD_ROOT
    home = (UPLOAD_ROOT / g.user["username"]).resolve()
    home.mkdir(exist_ok=True)
    return home


def resolve_upload_path(relative_path=""):
    root = accessible_root()
    parts = [part for part in (relative_path or "").split("/") if part]
    for part in parts:
        validate_name(part, "Path segments")
    path = (root / Path(*parts)).resolve() if parts else root
    if path != root and root not in path.parents:
        abort(400, description="Path is outside your upload folder.")
    return path


def item_payload(path):
    root = accessible_root()
    relative_path = path.relative_to(root).as_posix()
    payload = {"name": path.name, "path": "" if relative_path == "." else relative_path, "type": "folder" if path.is_dir() else "file"}
    if path.is_file():
        payload["size"] = path.stat().st_size
    return payload


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


def prepare_item_moves(item_paths, destination_folder, replace_existing=False):
    root = accessible_root()
    moves = []
    for relative_path in item_paths:
        if not isinstance(relative_path, str):
            abort(400, description="Item paths must be text.")
        item_path = resolve_upload_path(relative_path)
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


def render_browser(relative_path=""):
    folder = resolve_upload_path(relative_path)
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    root = accessible_root()
    current_path = "" if folder == root else folder.relative_to(root).as_posix()
    return render_template("index.html", current_path=current_path, csrf_token=g.session["csrf_token"], user=g.user)


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"message": error.description}), error.code
    return render_template("message.html", title=f"Error {error.code}", message=error.description), error.code


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


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/items")
@login_required
def items():
    folder = resolve_upload_path(request.args.get("path", ""))
    root = accessible_root()
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    parent_path = folder.parent.relative_to(root).as_posix() if folder != root else ""
    return jsonify({"items": sorted((item_payload(path) for path in folder.iterdir()), key=lambda item: (item["type"] != "folder", item["name"].casefold())), "parent": "" if parent_path == "." else parent_path, "path": "" if folder == root else folder.relative_to(root).as_posix()})


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


@app.delete("/api/items")
@login_required
def delete_item():
    item_path = resolve_upload_path(request.args.get("path", ""))
    if item_path == accessible_root() or not item_path.exists():
        abort(404, description="File or folder was not found.")
    shutil.rmtree(item_path) if item_path.is_dir() else item_path.unlink()
    return "", 204


@app.post("/api/files")
@login_required
def upload_file():
    filename = parse_upload_file(request.files.get("file"))
    folder = resolve_upload_path(request.form.get("path", ""))
    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")
    replace_existing = request.form.get("replace", "").lower() in {"1", "true", "yes"}
    saved_filename = filename if replace_existing else available_filename(folder, filename)
    destination = folder / saved_filename
    if replace_existing and destination.exists() and destination.is_dir():
        abort(409, description="A folder with that name already exists.")
    request.files["file"].save(folder / saved_filename)
    return jsonify({"filename": saved_filename, "path": (folder / saved_filename).relative_to(accessible_root()).as_posix()}), 201


@app.get("/api/files/<path:filename>")
@login_required
def download_file(filename):
    file_path = resolve_upload_path(filename)
    if not file_path.exists() or not file_path.is_file():
        abort(404, description="File was not found.")
    return send_from_directory(file_path.parent, file_path.name, as_attachment=True)


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
