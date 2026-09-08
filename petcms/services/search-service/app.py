"""
Search Service
Lists and filters the authenticated user's images by free-text query,
category, tag, pet type, and date range. Also supports "has location" for
the map page.
"""
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "search-service"}


@app.get("/images")
@require_auth
def search_images(user):
    admin = get_admin_client()
    q = admin.table("images").select("*").eq("owner_id", user.id)

    pet_type = request.args.get("pet_type")
    if pet_type:
        q = q.eq("pet_type", pet_type)

    category = request.args.get("category")
    if category:
        q = q.contains("categories", [category])

    tag = request.args.get("tag")
    if tag:
        q = q.contains("tags", [tag])

    date_from = request.args.get("date_from")
    if date_from:
        q = q.gte("taken_at", date_from)

    date_to = request.args.get("date_to")
    if date_to:
        q = q.lte("taken_at", date_to)

    has_location = request.args.get("has_location")
    if has_location == "true":
        q = q.not_.is_("gps_lat", "null")

    q = q.order("taken_at", desc=True)
    res = q.execute()
    rows = res.data or []

    text = (request.args.get("q") or "").strip().lower()
    if text:
        def matches(row):
            haystack = " ".join([
                row.get("caption") or "",
                row.get("filename") or "",
                " ".join(row.get("tags") or []),
                " ".join(row.get("categories") or []),
                row.get("pet_type") or "",
            ]).lower()
            return text in haystack
        rows = [r for r in rows if matches(r)]

    return jsonify(rows)


@app.get("/images/<image_id>")
@require_auth
def get_image(user, image_id):
    admin = get_admin_client()
    res = admin.table("images").select("*").eq("id", image_id).eq("owner_id", user.id).limit(1).execute()
    if not res.data:
        return jsonify({"error": "not found"}), 404
    return jsonify(res.data[0])


@app.patch("/images/<image_id>")
@require_auth
def update_image(user, image_id):
    """Allows editing caption / tags / categories / pet_type after upload."""
    data = request.get_json(force=True) or {}
    allowed = {"caption", "pet_type", "categories", "manual_tags", "tags"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        return jsonify({"error": "no editable fields provided"}), 400

    admin = get_admin_client()
    # "tags" sent explicitly = the user is directly editing the full tag list
    # (e.g. removing an AI-generated tag) — respect it as-is, don't re-merge.
    if "manual_tags" in update and "tags" not in update:
        existing = admin.table("images").select("ai_tags").eq("id", image_id).eq("owner_id", user.id).execute()
        ai_tags = existing.data[0]["ai_tags"] if existing.data else []
        update["tags"] = sorted(set(ai_tags) | set(update["manual_tags"]))
    if "tags" in update:
        update["tags"] = sorted(set(t.strip().lower() for t in update["tags"] if t.strip()))

    res = admin.table("images").update(update).eq("id", image_id).eq("owner_id", user.id).execute()
    if not res.data:
        return jsonify({"error": "not found"}), 404
    return jsonify(res.data[0])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5008)