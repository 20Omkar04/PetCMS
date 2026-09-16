"""
Storage Service
Thin wrapper around Supabase Storage: uploads bytes into the user's own
folder (pet-images/<user_id>/<filename>) and issues signed URLs for viewing.
"""
import uuid
from flask import Flask, request, jsonify, Response
from common import get_admin_client, require_auth, STORAGE_BUCKET

app = Flask(__name__)
from prometheus_flask_exporter import PrometheusMetrics
PrometheusMetrics(app)  # exposes GET /metrics for Prometheus scraping


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


# Internal endpoint — called only by ai-tagging-worker (not exposed via gateway,
# not behind @require_auth since the worker has no user JWT, only a stored path
# it already received from upload-service at enqueue time).
@app.get("/internal/download")
def internal_download():
    path = request.args.get("path", "")
    if not path:
        return jsonify({"error": "path is required"}), 400
    admin = get_admin_client()
    try:
        file_bytes = admin.storage.from_(STORAGE_BUCKET).download(path)
    except Exception as e:
        return jsonify({"error": f"could not download: {e}"}), 502
    return Response(file_bytes, mimetype="application/octet-stream")


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
