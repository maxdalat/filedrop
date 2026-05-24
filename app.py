from pathlib import Path
import shutil

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException


app = Flask(__name__)
MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024 * 1024

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_SIZE_BYTES

UPLOAD_FOLDER = Path(app.root_path) / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {
    "7z",
    "aac",
    "ai",
    "ape",
    "avif",
    "avi",
    "bmp",
    "bz2",
    "csv",
    "doc",
    "docx",
    "eml",
    "epub",
    "flac",
    "gif",
    "gz",
    "heic",
    "heif",
    "ics",
    "jpeg",
    "jpg",
    "json",
    "key",
    "log",
    "m4a",
    "md",
    "mov",
    "mp3",
    "mp4",
    "mpeg",
    "mpg",
    "numbers",
    "ods",
    "odt",
    "ogg",
    "pages",
    "pdf",
    "png",
    "ppt",
    "pptx",
    "psd",
    "rar",
    "rtf",
    "svg",
    "tar",
    "tif",
    "tiff",
    "tsv",
    "txt",
    "wav",
    "webm",
    "webp",
    "wma",
    "wmv",
    "xls",
    "xlsx",
    "xml",
    "yaml",
    "yml",
    "zip",
}
BLOCKED_FILENAME_CHARS = {"/", "\\", "\x00"}


def parse_upload_file(upload):
    if not upload or not upload.filename:
        abort(400, description="No file was selected.")

    filename = upload.filename

    if not filename.strip():
        abort(400, description="Filenames must include at least one visible character.")

    if filename in {".", ".."} or any(char in filename for char in BLOCKED_FILENAME_CHARS):
        abort(400, description="Filenames cannot include path separators.")

    filename_for_extension = filename.rstrip()

    if "." not in filename_for_extension:
        abort(400, description="Files must include an extension.")

    extension = filename_for_extension.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        abort(400, description=f".{extension} files are not allowed.")

    return filename


def validate_name(name, label="Names"):
    if not name or not name.strip():
        abort(400, description=f"{label} must include at least one visible character.")

    if name in {".", ".."} or any(char in name for char in BLOCKED_FILENAME_CHARS):
        abort(400, description=f"{label} cannot include path separators.")


def resolve_upload_path(relative_path=""):
    relative_path = relative_path or ""
    parts = [part for part in relative_path.split("/") if part]

    for part in parts:
        validate_name(part, "Path segments")

    path = (UPLOAD_FOLDER / Path(*parts)).resolve() if parts else UPLOAD_FOLDER.resolve()

    if path != UPLOAD_FOLDER.resolve() and UPLOAD_FOLDER.resolve() not in path.parents:
        abort(400, description="Path is outside the upload folder.")

    return path


def item_payload(path):
    relative_path = path.relative_to(UPLOAD_FOLDER).as_posix()
    payload = {
        "name": path.name,
        "path": "" if relative_path == "." else relative_path,
        "type": "folder" if path.is_dir() else "file",
    }

    if path.is_file():
        payload["size"] = path.stat().st_size

    return payload


def available_filename(folder, filename):
    path = folder / filename
    if not path.exists():
        return filename

    stem = path.stem
    suffix = path.suffix
    counter = 1

    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if not (folder / candidate).exists():
            return candidate
        counter += 1


def list_uploaded_files():
    return sorted(path.name for path in UPLOAD_FOLDER.iterdir() if path.is_file())


def list_items(relative_path=""):
    folder = resolve_upload_path(relative_path)

    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")

    items = [item_payload(path) for path in folder.iterdir()]
    return sorted(items, key=lambda item: (item["type"] != "folder", item["name"].casefold()))


@app.errorhandler(HTTPException)
def handle_http_error(error):
    return jsonify({"message": error.description}), error.code


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/hello")
def hello():
    return jsonify({"message": "Hello from the Flask API"})


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/files")
def files():
    return jsonify({"files": list_uploaded_files()})


@app.get("/api/items")
def items():
    relative_path = request.args.get("path", "")
    folder = resolve_upload_path(relative_path)
    parent = folder.parent.relative_to(UPLOAD_FOLDER).as_posix() if folder != UPLOAD_FOLDER else ""

    return jsonify({
        "items": list_items(relative_path),
        "parent": parent,
        "path": "" if folder == UPLOAD_FOLDER else folder.relative_to(UPLOAD_FOLDER).as_posix(),
    })


@app.post("/api/folders")
def create_folder():
    data = request.get_json(silent=True) or {}
    folder = resolve_upload_path(data.get("path", ""))
    name = data.get("name", "")

    validate_name(name, "Folder names")

    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")

    new_folder = folder / name

    if new_folder.exists():
        abort(409, description="A file or folder with that name already exists.")

    new_folder.mkdir()
    return jsonify(item_payload(new_folder)), 201


@app.patch("/api/items")
def rename_item():
    data = request.get_json(silent=True) or {}
    item_path = resolve_upload_path(data.get("path", ""))
    new_name = data.get("name", "")

    validate_name(new_name)

    if item_path == UPLOAD_FOLDER.resolve() or not item_path.exists():
        abort(404, description="File or folder was not found.")

    destination = item_path.with_name(new_name)

    if destination.exists():
        abort(409, description="A file or folder with that name already exists.")

    item_path.rename(destination)
    return jsonify(item_payload(destination))


@app.delete("/api/items")
def delete_item():
    item_path = resolve_upload_path(request.args.get("path", ""))

    if item_path == UPLOAD_FOLDER.resolve() or not item_path.exists():
        abort(404, description="File or folder was not found.")

    if item_path.is_dir():
        shutil.rmtree(item_path)
    else:
        item_path.unlink()

    return "", 204


@app.post("/api/files")
def upload_file():
    filename = parse_upload_file(request.files.get("file"))
    folder = resolve_upload_path(request.form.get("path", ""))

    if not folder.exists() or not folder.is_dir():
        abort(404, description="Folder was not found.")

    saved_filename = available_filename(folder, filename)
    request.files["file"].save(folder / saved_filename)

    saved_path = (folder / saved_filename).relative_to(UPLOAD_FOLDER).as_posix()
    return jsonify({"filename": saved_filename, "path": saved_path}), 201


@app.get("/api/files/<path:filename>")
def download_file(filename):
    file_path = resolve_upload_path(filename)

    if not file_path.exists() or not file_path.is_file():
        abort(404, description="File was not found.")

    return send_from_directory(file_path.parent, file_path.name, as_attachment=True)


@app.delete("/api/files/<path:filename>")
def delete_file(filename):
    file_path = resolve_upload_path(filename)

    if not file_path.exists() or not file_path.is_file():
        abort(404, description="File was not found.")

    file_path.unlink()
    return "", 204


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
