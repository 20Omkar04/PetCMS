"""
Storage Service
Thin wrapper around Supabase Storage: uploads bytes into the user's own
folder (pet-images/<user_id>/<filename>) and issues signed URLs for viewing.
"""
import uuid
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth, STORAGE_BUCKET

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "storage-service"}


@app.post("/upload")
@require_auth
def upload(user):
    if "file" not in request.files:
        return jsonify({"error": "file is required (multipart/form-data)"}), 400
    file = request.files["file"]
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "jpg").lower()
    object_name = f"{user.id}/{uuid.uuid4().hex}.{ext}"

    admin = get_admin_client()
    file_bytes = file.read()
    admin.storage.from_(STORAGE_BUCKET).upload(
        object_name, file_bytes, {"content-type": file.mimetype or "application/octet-stream"}
    )
    signed = admin.storage.from_(STORAGE_BUCKET).create_signed_url(object_name, 60 * 60 * 24 * 7)
    return jsonify({
        "storage_path": object_name,
        "signed_url": signed.get("signedURL") or signed.get("signed_url"),
        "size_bytes": len(file_bytes),
        "raw_bytes_available": True,
    })


@app.get("/signed-url")
@require_auth
def signed_url(user):
    path = request.args.get("path", "")
    if not path.startswith(f"{user.id}/"):
        return jsonify({"error": "forbidden"}), 403
    admin = get_admin_client()
    signed = admin.storage.from_(STORAGE_BUCKET).create_signed_url(path, 60 * 60)
    return jsonify({"signed_url": signed.get("signedURL") or signed.get("signed_url")})


@app.delete("/delete")
@require_auth
def delete(user):
    data = request.get_json(force=True) or {}
    path = data.get("path", "")
    if not path.startswith(f"{user.id}/"):
        return jsonify({"error": "forbidden"}), 403
    admin = get_admin_client()
    admin.storage.from_(STORAGE_BUCKET).remove([path])
    return jsonify({"status": "deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004)
