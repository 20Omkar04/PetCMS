"""
Category Management Service
CRUD for a user's custom categories (e.g. "Backyard", "Vet Visits", "Puppy Era").
Manual tags on images themselves are just free-text and are set directly on the
image record by the upload/search services, so this service focuses on the
reusable named categories used for filtering.
"""
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "category-service"}


@app.get("/categories")
@require_auth
def list_categories(user):
    admin = get_admin_client()
    res = admin.table("categories").select("*").eq("owner_id", user.id).order("name").execute()
    return jsonify(res.data)


@app.post("/categories")
@require_auth
def create_category(user):
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    admin = get_admin_client()
    try:
        res = admin.table("categories").insert({"owner_id": user.id, "name": name}).execute()
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(res.data[0] if res.data else {"name": name})


@app.delete("/categories/<category_id>")
@require_auth
def delete_category(user, category_id):
    admin = get_admin_client()
    admin.table("categories").delete().eq("id", category_id).eq("owner_id", user.id).execute()
    return jsonify({"status": "deleted"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5007)
