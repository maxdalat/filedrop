import os


MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024 * 1024
SESSION_COOKIE_NAME = "filedrop_session"
SESSION_LIFETIME_HOURS = 24
SECURE_COOKIE_VALUES = {"1", "true", "yes"}
PASSWORD_HASH_METHOD = "scrypt"
SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32
TEMPORARY_PASSWORD_BYTES = 12
RSA_PUBLIC_EXPONENT = 65537
RSA_KEY_SIZE = 3072
DEFAULT_PARALLEL_UPLOADS = 3
MIN_PARALLEL_UPLOADS = 1
MAX_PARALLEL_UPLOADS = 99

DATABASE_FILENAME = "filedrop.db"
PRIVATE_KEY_FILENAME = "session_private.pem"
PUBLIC_KEY_FILENAME = "session_public.pem"
DEFAULT_UPLOAD_DIRECTORY = "uploads"

INSTANCE_PATH_ENV = "FILEDROP_INSTANCE_PATH"
UPLOAD_PATH_ENV = "FILEDROP_UPLOAD_PATH"
SECURE_COOKIES_ENV = "FILEDROP_SECURE_COOKIES"

PASSWORD_MIN_LENGTH = 10
USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 40
EMAIL_MAX_LENGTH = 254
USERNAME_CHARACTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"

ALLOWED_EXTENSIONS = {
    "3ds", "3mf", "7z", "aac", "ai", "amf", "ape", "avif", "avi", "blend", "bmp", "bz2",
    "cbddlp", "ctb", "csv", "dae", "doc", "docx", "eml", "epub", "fbx", "flac", "gif",
    "glb", "gltf", "gcode", "gz", "heic", "heif", "ics", "iges", "igs", "jpeg", "jpg",
    "json", "key", "log", "m4a", "md", "mov", "mp3", "mp4", "mpeg", "mpg", "numbers",
    "obj", "ods", "odt", "ogg", "pages", "pdf", "photon", "photons", "ply", "png", "ppt",
    "pptx", "psd", "pwmx", "pwmo", "pws", "rar", "rtf", "scad", "slc", "step", "stl",
    "stp", "svg", "tar", "tif", "tiff", "tsv", "txt", "wav", "webm", "webp", "wma",
    "wmv", "wrl", "x3d", "xls", "xlsx", "xml", "yaml", "yml", "zip",
}
BLOCKED_FILENAME_CHARS = {"/", "\\", "\x00"}
AVATAR_COLORS = ("#6d5dfc", "#d05a7a", "#168aad", "#9b5de5", "#cc7722", "#2a9d8f", "#52796f", "#b56576")
FORM_CONSTRAINTS = {
    "password_min_length": PASSWORD_MIN_LENGTH,
    "username_min_length": USERNAME_MIN_LENGTH,
    "username_max_length": USERNAME_MAX_LENGTH,
    "email_max_length": EMAIL_MAX_LENGTH,
}
IMAGE_PREVIEW_EXTENSIONS = {"avif", "gif", "jpeg", "jpg", "png", "svg", "webp"}
VIDEO_PREVIEW_EXTENSIONS = {"mov", "mp4", "mpeg", "mpg", "webm"}


def env_value(name, default=None):
    return os.environ.get(name, default)


def env_flag(name):
    return env_value(name, "").lower() in SECURE_COOKIE_VALUES
