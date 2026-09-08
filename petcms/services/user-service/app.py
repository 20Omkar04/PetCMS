"""
User Service
Manages profile data and the user's saved AI API key (encrypted at rest).
"""
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth, encrypt_secret

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "user-service"}


@app.get("/me")
@require_auth
def me(user):
    admin = get_admin_client()
    res = admin.table("profiles").select("id,username,api_key_provider,created_at") \
        .eq("id", user.id).limit(1).execute()
    profile = res.data[0] if res.data else {"id": user.id, "username": None}
    profile["has_api_key"] = _has_api_key(admin, user.id)
    return jsonify(profile)


@app.put("/me/api-key")
@require_auth
def save_api_key(user):
    data = request.get_json(force=True) or {}
    api_key = (data.get("api_key") or "").strip()
    provider = (data.get("provider") or "openai").strip().lower()
    if not api_key:
        return jsonify({"error": "api_key is required"}), 400
    if provider not in ("openai", "gemini"):
        return jsonify({"error": "provider must be 'openai' or 'gemini'"}), 400

    encrypted = encrypt_secret(api_key)
    admin = get_admin_client()
    admin.table("profiles").upsert({
        "id": user.id,
        "encrypted_api_key": encrypted,
        "api_key_provider": provider,
    }).execute()
    return jsonify({"status": "saved", "provider": provider})


@app.delete("/me/api-key")
@require_auth
def delete_api_key(user):
    admin = get_admin_client()
    admin.table("profiles").update({
        "encrypted_api_key": None,
        "api_key_provider": None,
    }).eq("id", user.id).execute()
    return jsonify({"status": "deleted"})


def _has_api_key(admin, user_id):
    res = admin.table("profiles").select("encrypted_api_key").eq("id", user_id).limit(1).execute()
    return bool(res.data and res.data[0].get("encrypted_api_key"))


# Internal endpoint used only by ai-tagging-service (not exposed via gateway)
@app.get("/internal/api-key/<user_id>")
def internal_get_api_key(user_id):
    admin = get_admin_client()
    res = admin.table("profiles").select("encrypted_api_key,api_key_provider") \
        .eq("id", user_id).limit(1).execute()
    if not res.data or not res.data[0].get("encrypted_api_key"):
        return jsonify({"error": "no api key on file"}), 404
    return jsonify(res.data[0])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
