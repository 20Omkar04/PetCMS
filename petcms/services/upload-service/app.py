"""
Upload Service
Orchestrates a single image upload across several services:
  1. storage-service   -> stores the file in Supabase Storage
  2. exif-service       -> extracts GPS / timestamp / device metadata
  3. ai-tagging-service -> generates AI tags using the user's own API key
  4. writes the resulting `images` row itself (this service owns that table)
  5. memory-service     -> logs an "upload" event to the timeline
"""
import os
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth

app = Flask(__name__)

STORAGE_SERVICE_URL = os.environ.get("STORAGE_SERVICE_URL", "http://storage-service:5004")
EXIF_SERVICE_URL = os.environ.get("EXIF_SERVICE_URL", "http://exif-service:5005")
AI_TAGGING_SERVICE_URL = os.environ.get("AI_TAGGING_SERVICE_URL", "http://ai-tagging-service:5006")
MEMORY_SERVICE_URL = os.environ.get("MEMORY_SERVICE_URL", "http://memory-service:5009")


@app.get("/health")
def health():
    return {"status": "ok", "service": "upload-service"}


@app.post("/images")
@require_auth
def upload_image(user):
    if "file" not in request.files:
        return jsonify({"error": "file is required (multipart/form-data)"}), 400

    file = request.files["file"]
    caption = request.form.get("caption", "")
    pet_type = request.form.get("pet_type", "other")
    manual_tags = [t.strip().lower() for t in request.form.get("manual_tags", "").split(",") if t.strip()]
    categories = [c.strip() for c in request.form.get("categories", "").split(",") if c.strip()]

    file_bytes = file.read()
    auth_header = request.headers.get("Authorization")

    # 1) store the file
    storage_resp = requests.post(
        f"{STORAGE_SERVICE_URL}/upload",
        headers={"Authorization": auth_header},
        files={"file": (file.filename, file_bytes, file.mimetype)},
        timeout=30,
    )
    if storage_resp.status_code != 200:
        return jsonify({"error": "storage upload failed", "detail": storage_resp.text}), 502
    storage_data = storage_resp.json()

    # 2) extract EXIF
    exif_data = {"gps_lat": None, "gps_lng": None, "taken_at": None, "device": None, "raw": {}}
    try:
        exif_resp = requests.post(
            f"{EXIF_SERVICE_URL}/extract",
            files={"file": (file.filename, file_bytes, file.mimetype)},
            timeout=20,
        )
        if exif_resp.status_code == 200:
            exif_data = exif_resp.json()
    except Exception:
        pass

    # 3) AI tagging (best-effort; never blocks the upload)
    ai_tags = []
    ai_tag_issue = None
    try:
        ai_resp = requests.post(
            f"{AI_TAGGING_SERVICE_URL}/tag",
            data={"user_id": user.id},
            files={"file": (file.filename, file_bytes, file.mimetype)},
            timeout=35,
        )
        if ai_resp.status_code == 200:
            ai_json = ai_resp.json()
            ai_tags = ai_json.get("tags", [])
            ai_tag_issue = ai_json.get("error") or ai_json.get("note")
        else:
            ai_tag_issue = f"ai-tagging-service returned HTTP {ai_resp.status_code}"
    except Exception as e:
        ai_tag_issue = f"could not reach ai-tagging-service: {e}"

    all_tags = sorted(set(ai_tags) | set(manual_tags))
    taken_at = exif_data.get("taken_at") or datetime.now(timezone.utc).isoformat()

    admin = get_admin_client()
    row = {
        "owner_id": user.id,
        "storage_path": storage_data["storage_path"],
        "filename": file.filename,
        "caption": caption,
        "pet_type": pet_type,
        "categories": categories,
        "tags": all_tags,
        "ai_tags": ai_tags,
        "manual_tags": manual_tags,
        "exif": exif_data.get("raw", {}),
        "gps_lat": exif_data.get("gps_lat"),
        "gps_lng": exif_data.get("gps_lng"),
        "taken_at": taken_at,
        "device": exif_data.get("device"),
    }
    insert_res = admin.table("images").insert(row).execute()
    image_row = insert_res.data[0] if insert_res.data else row

    # 4) log to memory timeline (best-effort)
    try:
        requests.post(
            f"{MEMORY_SERVICE_URL}/internal/events",
            json={
                "owner_id": user.id,
                "image_id": image_row.get("id"),
                "event_type": "upload",
                "description": f"Uploaded {file.filename}" + (f" — {caption}" if caption else ""),
            },
            timeout=10,
        )
    except Exception:
        pass

    if ai_tag_issue:
        try:
            requests.post(
                f"{MEMORY_SERVICE_URL}/internal/events",
                json={
                    "owner_id": user.id,
                    "image_id": image_row.get("id"),
                    "event_type": "note",
                    "description": f"AI tagging skipped for {file.filename}: {ai_tag_issue}",
                },
                timeout=10,
            )
        except Exception:
            pass

    return jsonify(image_row), 201


@app.delete("/images/<image_id>")
@require_auth
def delete_image(user, image_id):
    admin = get_admin_client()
    res = admin.table("images").select("storage_path").eq("id", image_id).eq("owner_id", user.id).execute()
    if not res.data:
        return jsonify({"error": "not found"}), 404
    storage_path = res.data[0]["storage_path"]

    auth_header = request.headers.get("Authorization")
    try:
        requests.delete(
            f"{STORAGE_SERVICE_URL}/delete",
            headers={"Authorization": auth_header},
            json={"path": storage_path},
            timeout=15,
        )
    except Exception:
        pass

    admin.table("images").delete().eq("id", image_id).eq("owner_id", user.id).execute()

    try:
        requests.post(
            f"{MEMORY_SERVICE_URL}/internal/events",
            json={
                "owner_id": user.id,
                "image_id": None,
                "event_type": "deleted",
                "description": "Deleted a photo from the gallery",
            },
            timeout=10,
        )
    except Exception:
        pass

    return jsonify({"status": "deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)