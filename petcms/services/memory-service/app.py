"""
Memory Logs Service
Records and serves the auto-generated "memory timeline" of events
(uploads, tags added, deletions, user notes). The chatbot-service reads
from this same timeline to answer questions.
"""
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "memory-service"}


@app.get("/timeline")
@require_auth
def timeline(user):
    admin = get_admin_client()
    limit = int(request.args.get("limit", 100))
    res = admin.table("memory_events").select("*").eq("owner_id", user.id) \
        .order("event_time", desc=True).limit(limit).execute()
    return jsonify(res.data)


@app.post("/timeline/notes")
@require_auth
def add_note(user):
    data = request.get_json(force=True) or {}
    description = (data.get("description") or "").strip()
    if not description:
        return jsonify({"error": "description is required"}), 400
    admin = get_admin_client()
    res = admin.table("memory_events").insert({
        "owner_id": user.id,
        "image_id": data.get("image_id"),
        "event_type": "note",
        "description": description,
    }).execute()
    return jsonify(res.data[0] if res.data else {}), 201


# Internal endpoint — called by upload-service / other services, not via gateway auth
@app.post("/internal/events")
def internal_add_event():
    data = request.get_json(force=True) or {}
    required = {"owner_id", "event_type", "description"}
    if not required.issubset(data):
        return jsonify({"error": f"required fields: {sorted(required)}"}), 400
    admin = get_admin_client()
    res = admin.table("memory_events").insert({
        "owner_id": data["owner_id"],
        "image_id": data.get("image_id"),
        "event_type": data["event_type"],
        "description": data["description"],
    }).execute()
    return jsonify(res.data[0] if res.data else {}), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5009)
