"""
AI Tagging Service
Generates descriptive tags for an uploaded pet photo using the user's own
saved AI API key (OpenAI or Gemini vision models). Fails soft: if no key is
configured, or the provider call errors, returns an empty tag list rather
than blocking the upload.

Two entry points share this module's logic:
  - app.py (this file)  — a synchronous HTTP endpoint, kept for manual/direct
    re-tagging use cases.
  - worker.py            — the RQ background worker that actually services
    uploads now (see upload-service/app.py, which enqueues jobs instead of
    calling /tag synchronously).
"""
import io
import os
import base64
import requests
from flask import Flask, request, jsonify
from PIL import Image
from common import decrypt_secret

app = Flask(__name__)
from prometheus_flask_exporter import PrometheusMetrics
PrometheusMetrics(app)  # exposes GET /metrics for Prometheus scraping

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5002")

OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-3.7-flash"

TAG_PROMPT = (
    "You are labelling a pet photo for a personal pet gallery app. "
    "Look at the image and return 3 to 8 short, lowercase, comma-separated tags "
    "describing the pet (species/breed if visible), its action/pose, setting, and mood. "
    "Return ONLY the comma-separated tags, nothing else."
)


def normalize_image(file_bytes):
    """Re-encode any input (WEBP, CMYK/paletted JPEG, PNG with alpha, a
    mismatched-extension web download, etc.) into a clean sRGB JPEG. Vision
    APIs will silently reject some of those source formats/color modes, and
    without this, tagging on web-downloaded images fails invisibly. Falls
    back to the original bytes/mimetype if the file genuinely can't be
    opened, so a truly corrupt upload still gets *some* attempt rather than
    a hard error here.
    """
    try:
        image = Image.open(io.BytesIO(file_bytes))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=90)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return file_bytes, "image/jpeg"


def get_user_key(user_id):
    resp = requests.get(f"{USER_SERVICE_URL}/internal/api-key/{user_id}", timeout=10)
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    return decrypt_secret(data["encrypted_api_key"]), data.get("api_key_provider", "openai")


def tag_with_openai(api_key, image_b64, mime):
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": OPENAI_MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": TAG_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }],
            "max_tokens": 60,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def tag_with_gemini(api_key, image_b64, mime):
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}",
        json={
            "contents": [{
                "parts": [
                    {"text": TAG_PROMPT},
                    {"inline_data": {"mime_type": mime, "data": image_b64}},
                ]
            }]
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def generate_tags(file_bytes, user_id):
    """Core tagging logic, shared by the sync endpoint and the async worker.
    Returns (tags: list[str], issue: str|None) — issue is a human-readable
    note when tagging was skipped or failed, for visibility in the UI."""
    normalized_bytes, mime = normalize_image(file_bytes)
    image_b64 = base64.b64encode(normalized_bytes).decode()

    api_key, provider = get_user_key(user_id)
    if not api_key:
        return [], "no AI API key configured for this user"

    try:
        raw_text = tag_with_gemini(api_key, image_b64, mime) if provider == "gemini" \
            else tag_with_openai(api_key, image_b64, mime)
        tags = [t.strip().lower() for t in raw_text.replace("\n", ",").split(",") if t.strip()]
        return tags[:8], None
    except Exception as e:
        return [], f"tagging call failed: {e}"


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-tagging-service"}


@app.post("/tag")
def tag():
    """Expects multipart/form-data: file=<image>, user_id=<uuid>. Kept for
    manual/direct re-tagging; normal uploads go through the async worker."""
    user_id = request.form.get("user_id")
    if not user_id or "file" not in request.files:
        return jsonify({"error": "user_id and file are required"}), 400

    file_bytes = request.files["file"].read()
    tags, issue = generate_tags(file_bytes, user_id)
    if issue and not tags:
        return jsonify({"tags": [], "note": issue} if "no AI API key" in issue else {"tags": [], "error": issue})
    return jsonify({"tags": tags})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5006)
