"""
AI Tagging Service
Generates descriptive tags for an uploaded pet photo using the user's own
saved AI API key (OpenAI or Gemini vision models). Fails soft: if no key is
configured, or the provider call errors, returns an empty tag list rather
than blocking the upload.
"""
import os
import base64
import requests
from flask import Flask, request, jsonify
from common import decrypt_secret

app = Flask(__name__)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5002")

OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = "gemini-3.7-flash"

TAG_PROMPT = (
    "You are labelling a pet photo for a personal pet gallery app. "
    "Look at the image and return 3 to 8 short, lowercase, comma-separated tags "
    "describing the pet (species/breed if visible), its action/pose, setting, and mood. "
    "Return ONLY the comma-separated tags, nothing else."
)


def _get_user_key(user_id):
    resp = requests.get(f"{USER_SERVICE_URL}/internal/api-key/{user_id}", timeout=10)
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    return decrypt_secret(data["encrypted_api_key"]), data.get("api_key_provider", "openai")


def _tag_with_openai(api_key, image_b64, mime):
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
    text = resp.json()["choices"][0]["message"]["content"]
    return text


def _tag_with_gemini(api_key, image_b64, mime):
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


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-tagging-service"}


@app.post("/tag")
def tag():
    """Expects multipart/form-data: file=<image>, user_id=<uuid>"""
    user_id = request.form.get("user_id")
    if not user_id or "file" not in request.files:
        return jsonify({"error": "user_id and file are required"}), 400

    file = request.files["file"]
    mime = file.mimetype or "image/jpeg"
    image_b64 = base64.b64encode(file.read()).decode()

    api_key, provider = _get_user_key(user_id)
    if not api_key:
        return jsonify({"tags": [], "note": "no AI API key configured for this user"})

    try:
        if provider == "gemini":
            raw_text = _tag_with_gemini(api_key, image_b64, mime)
        else:
            raw_text = _tag_with_openai(api_key, image_b64, mime)
        tags = [t.strip().lower() for t in raw_text.replace("\n", ",").split(",") if t.strip()]
        return jsonify({"tags": tags[:8]})
    except Exception as e:
        return jsonify({"tags": [], "error": f"tagging call failed: {e}"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5006)