"""
Auth Service
Thin wrapper around Supabase Auth using real email + password —
no fake domains, no pseudo-emails. `username` is stored separately
as a display name in the `profiles` table.
"""
from flask import Flask, request, jsonify
from common import get_anon_client, get_admin_client, require_auth

app = Flask(__name__)


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}


@app.post("/register")
def register():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    username = (data.get("username") or "").strip() or email.split("@")[0]

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "please enter a valid email address"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400

    client = get_anon_client()
    try:
        result = client.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if not result.user:
        return jsonify({"error": "registration failed"}), 400

    admin = get_admin_client()
    try:
        admin.table("profiles").insert({
            "id": result.user.id,
            "username": username,
        }).execute()
    except Exception:
        pass  # profile row may already exist if the user retried

    session = result.session
    return jsonify({
        "user": {"id": result.user.id, "email": email, "username": username},
        "access_token": session.access_token if session else None,
        "refresh_token": session.refresh_token if session else None,
        "needs_email_confirmation": session is None,
    })


@app.post("/login")
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    client = get_anon_client()
    try:
        result = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception:
        return jsonify({"error": "invalid email or password"}), 401

    if not result.user or not result.session:
        return jsonify({"error": "invalid email or password"}), 401

    admin = get_admin_client()
    profile = admin.table("profiles").select("username").eq("id", result.user.id).limit(1).execute()
    username = profile.data[0]["username"] if profile.data else email.split("@")[0]

    return jsonify({
        "user": {"id": result.user.id, "email": email, "username": username},
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
    })


@app.post("/refresh")
def refresh():
    data = request.get_json(force=True) or {}
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return jsonify({"error": "refresh_token required"}), 400
    client = get_anon_client()
    try:
        result = client.auth.refresh_session(refresh_token)
    except Exception:
        return jsonify({"error": "could not refresh session"}), 401
    return jsonify({
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
    })


@app.get("/verify")
@require_auth
def verify(user):
    return jsonify({"id": user.id, "email": user.email})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)