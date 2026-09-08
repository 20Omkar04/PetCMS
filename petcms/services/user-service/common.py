"""
Shared helpers copied into every PetCMS microservice.
Keeps each service a self-contained Docker build context while avoiding
copy-pasted bugs -- edit here, then re-run scripts/sync_shared.sh (see repo root).
"""
import os
import base64
import hashlib
from functools import wraps

from flask import request, jsonify
from supabase import create_client, Client
from cryptography.fernet import Fernet

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "pet-images")


def get_admin_client() -> Client:
    """Service-role client: bypasses RLS. Only used server-side for operations
    the user is already authorized for (we always filter by owner_id ourselves)."""
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def get_anon_client() -> Client:
    """Anon client: used for auth flows (sign up / sign in / token verification)."""
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_user_from_token(access_token: str):
    """Validate a Supabase JWT and return the user object, or None if invalid."""
    if not access_token:
        return None
    try:
        client = get_anon_client()
        resp = client.auth.get_user(access_token)
        return resp.user if resp and resp.user else None
    except Exception:
        return None


def require_auth(f):
    """Decorator for Flask routes: extracts Bearer token, validates it with
    Supabase, and injects `user` (with .id / .email) as the first arg."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else None
        user = get_user_from_token(token)
        if not user:
            return jsonify({"error": "unauthorized"}), 401
        return f(user, *args, **kwargs)
    return wrapper


def _fernet():
    secret = os.environ.get("API_KEY_ENCRYPTION_SECRET", "insecure-dev-secret")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
