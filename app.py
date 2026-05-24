from pathlib import Path

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


def available_filename(filename):
    path = UPLOAD_FOLDER / filename
    if not path.exists():
        return filename

    stem = path.stem
    suffix = path.suffix
    counter = 1

    while True:
        candidate = f"{stem}_{counter}{suffix}"
        if not (UPLOAD_FOLDER / candidate).exists():
            return candidate
        counter += 1


def list_uploaded_files():
    return sorted(path.name for path in UPLOAD_FOLDER.iterdir() if path.is_file())


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


@app.post("/api/files")
def upload_file():
    filename = parse_upload_file(request.files.get("file"))
    saved_filename = available_filename(filename)
    request.files["file"].save(UPLOAD_FOLDER / saved_filename)

    return jsonify({"filename": saved_filename}), 201


@app.get("/api/files/<path:filename>")
def download_file(filename):
    if filename not in list_uploaded_files():
        abort(404, description="File was not found.")

    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)


@app.delete("/api/files/<path:filename>")
def delete_file(filename):
    if filename not in list_uploaded_files():
        abort(404, description="File was not found.")

    (UPLOAD_FOLDER / filename).unlink()
    return "", 204


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
