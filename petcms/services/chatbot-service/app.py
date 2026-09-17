"""
PetCMS Chatbot Service

Answers questions about the authenticated user's own:
- Pet photos
- AI/manual tags
- Categories
- EXIF metadata
- Memory timeline

The service uses the user's saved AI API key when available.
If the AI provider is unavailable, times out, or returns an error,
the service automatically falls back to rule-based answers.

Endpoints:
    GET  /health
    POST /chat
    GET  /chat/history
"""

import os
import time
import requests

from flask import Flask, request, jsonify
from prometheus_flask_exporter import PrometheusMetrics

from common import get_admin_client, require_auth, decrypt_secret


 # Flask
 
app = Flask(__name__)

PrometheusMetrics(app)


 # Configuration
 
USER_SERVICE_URL = os.environ.get(
    "USER_SERVICE_URL",
    "http://user-service:5002"
)

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.7-flash"
)

OPENAI_MODEL = os.environ.get(
    "OPENAI_MODEL",
    "gpt-4o-mini"
)

# Keep these relatively short so the PetCMS API does not hang.
API_CONNECT_TIMEOUT = float(
    os.environ.get("CHATBOT_CONNECT_TIMEOUT", "10")
)

API_READ_TIMEOUT = float(
    os.environ.get("CHATBOT_READ_TIMEOUT", "45")
)

# Number of provider attempts.
MAX_RETRIES = int(
    os.environ.get("CHATBOT_MAX_RETRIES", "2")
)

# Maximum amount of context sent to the AI.
MAX_IMAGES = int(
    os.environ.get("CHATBOT_MAX_IMAGES", "20")
)

MAX_EVENTS = int(
    os.environ.get("CHATBOT_MAX_EVENTS", "20")
)

MAX_HISTORY = int(
    os.environ.get("CHATBOT_MAX_HISTORY", "10")
)


 # System prompt
 
SYSTEM_PROMPT = """
You are the assistant inside PetCMS, a personal pet photo gallery.

Answer the user's question using ONLY the information contained
in the supplied JSON context and conversation history.

Rules:
- Do not invent facts.
- Do not guess missing information.
- If the information is not available, say that you do not have
  that information yet.
- Be concise, friendly, and useful.
- When dates are available, use them.
- When answering about photos, use the filename, caption, tags,
  categories, pet type, EXIF data, and date when relevant.
- When answering about memories or events, use the timeline.
""".strip()


 # Context
 
def _build_context(admin, user_id):
    """
    Build a limited context from the authenticated user's data.

    Smaller context = faster AI requests and less chance of
    provider timeouts.
    """

    images = (
        admin.table("images")
        .select(
            "filename,"
            "caption,"
            "pet_type,"
            "tags,"
            "categories,"
            "taken_at,"
            "gps_lat,"
            "gps_lng,"
            "device"
        )
        .eq("owner_id", user_id)
        .order("taken_at", desc=True)
        .limit(MAX_IMAGES)
        .execute()
        .data
        or []
    )

    events = (
        admin.table("memory_events")
        .select(
            "event_type,"
            "description,"
            "event_time"
        )
        .eq("owner_id", user_id)
        .order("event_time", desc=True)
        .limit(MAX_EVENTS)
        .execute()
        .data
        or []
    )

    return {
        "images": images,
        "timeline": events
    }


 # User API key
 
def _get_user_key(user_id):
    """
    Retrieve and decrypt the user's saved AI API key.
    """

    url = f"{USER_SERVICE_URL}/internal/api-key/{user_id}"

    response = requests.get(
        url,
        timeout=(5, 10)
    )

    if response.status_code != 200:
        return None, None

    data = response.json()

    encrypted_key = data.get("encrypted_api_key")

    if not encrypted_key:
        return None, None

    api_key = decrypt_secret(encrypted_key)

    provider = data.get(
        "api_key_provider",
        "openai"
    ).lower()

    return api_key, provider


 # HTTP retry helper
 
def _post_with_retry(
    url,
    *,
    headers=None,
    json=None,
    retries=MAX_RETRIES,
    timeout=None
):
    """
    POST request with a small retry policy.

    Retries ONLY on:
        - timeout
        - connection errors
        - HTTP 429
        - HTTP 500
        - HTTP 502
        - HTTP 503
        - HTTP 504

    Other HTTP errors such as 400, 401, 403 and 404 are returned
    immediately because retrying them normally will not help.
    """

    if timeout is None:
        timeout = (
            API_CONNECT_TIMEOUT,
            API_READ_TIMEOUT
        )

    retry_statuses = {
        429,
        500,
        502,
        503,
        504
    }

    last_exception = None

    for attempt in range(retries):

        try:
            response = requests.post(
                url,
                headers=headers,
                json=json,
                timeout=timeout
            )

            # Successful response.
            if response.ok:
                return response

            # Do not retry authentication, bad request,
            # invalid model, etc.
            if response.status_code not in retry_statuses:
                response.raise_for_status()

            last_exception = requests.exceptions.HTTPError(
                f"AI provider returned HTTP "
                f"{response.status_code}: "
                f"{response.text[:500]}",
                response=response
            )

            print(
                f"[chatbot] Provider returned "
                f"{response.status_code}, "
                f"attempt {attempt + 1}/{retries}",
                flush=True
            )

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as exc:

            last_exception = exc

            print(
                f"[chatbot] Provider connection error "
                f"on attempt {attempt + 1}/{retries}: "
                f"{exc}",
                flush=True
            )

        # Small exponential backoff.
        if attempt < retries - 1:
            delay = 1.5 * (2 ** attempt)

            print(
                f"[chatbot] Retrying in {delay:.1f}s...",
                flush=True
            )

            time.sleep(delay)

    raise last_exception or RuntimeError(
        "AI provider request failed"
    )


 # OpenAI
 
def _ask_openai(
    api_key,
    context,
    question,
    history
):
    """
    Ask OpenAI using the user's API key.
    """

    messages = [
        {
            "role": "system",
            "content": (
                f"{SYSTEM_PROMPT}\n\n"
                f"PETCMS DATA:\n{context}"
            )
        }
    ]

    messages.extend(history)

    messages.append(
        {
            "role": "user",
            "content": question
        }
    )

    response = _post_with_retry(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": OPENAI_MODEL,
            "messages": messages,
            "max_tokens": 300,
            "temperature": 0.2
        }
    )

    data = response.json()

    choices = data.get("choices") or []

    if not choices:
        raise RuntimeError(
            f"OpenAI returned no choices: {data}"
        )

    answer = (
        choices[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )

    if not answer:
        raise RuntimeError(
            "OpenAI returned an empty answer"
        )

    return answer


 # Gemini
 
def _ask_gemini(
    api_key,
    context,
    question,
    history
):
    """
    Ask Gemini using the user's API key.

    Uses a single combined prompt rather than repeatedly sending
    unnecessary conversation structures.
    """

    conversation = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in history
    )

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"PETCMS DATA:\n"
        f"{context}\n\n"
        f"CONVERSATION HISTORY:\n"
        f"{conversation}\n\n"
        f"CURRENT USER QUESTION:\n"
        f"{question}"
    )

    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{GEMINI_MODEL}:generateContent"
        f"?key={api_key}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 300
        }
    }

    response = _post_with_retry(
        url,
        headers={
            "Content-Type": "application/json"
        },
        json=payload
    )

    data = response.json()

    candidates = data.get("candidates") or []

    if not candidates:
        raise RuntimeError(
            f"Gemini returned no candidates: {data}"
        )

    content = candidates[0].get("content") or {}

    parts = content.get("parts") or []

    answer = "".join(
        part.get("text", "")
        for part in parts
    ).strip()

    if not answer:
        raise RuntimeError(
            f"Gemini returned an empty answer: {data}"
        )

    return answer


 # Rule-based fallback
 
def _rule_based_fallback(context, question):
    """
    Simple fallback so the chatbot still works when an AI provider
    is unavailable.
    """

    q = question.lower().strip()

    images = context.get("images") or []
    timeline = context.get("timeline") or []

    # ---------------------------------------------------------------
    # Photo count
    # ---------------------------------------------------------------

    if (
        "how many" in q
        and ("photo" in q or "photos" in q)
    ):
        return (
            f"You have {len(images)} photos "
            f"in the recent PetCMS history."
        )

    # ---------------------------------------------------------------
    # Vet questions
    # ---------------------------------------------------------------

    if "vet" in q:

        vet_events = [
            event
            for event in timeline
            if "vet" in (
                event.get("description") or ""
            ).lower()
        ]

        if vet_events:

            latest = vet_events[0]

            description = (
                latest.get("description")
                or "Vet-related event"
            )

            event_time = (
                latest.get("event_time")
                or "date unknown"
            )

            return (
                f"The most recent vet-related entry "
                f"I see is: \"{description}\" "
                f"({event_time})."
            )

        return (
            "I don't see any vet-related entries "
            "in your timeline yet."
        )

    # ---------------------------------------------------------------
    # Latest photo
    # ---------------------------------------------------------------

    if images:

        latest = images[0]

        filename = (
            latest.get("filename")
            or "Unnamed photo"
        )

        caption = latest.get("caption")

        tags = latest.get("tags") or []

        answer = (
            f'Your most recent photo is "{filename}"'
        )

        if caption:
            answer += f" — {caption}"

        answer += (
            f". Tagged: "
            f"{', '.join(tags) if tags else 'no tags yet'}."
        )

        return answer

    # ---------------------------------------------------------------
    # No data
    # ---------------------------------------------------------------

    return (
        "I don't have enough data yet. "
        "Try uploading some pet photos first, "
        "or add an AI API key in Settings "
        "for richer answers."
    )


 # Health
 
@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "chatbot-service"
    })


 # Chat
 
@app.post("/chat")
@require_auth
def chat(user):

    # ---------------------------------------------------------------
    # Validate request
    # ---------------------------------------------------------------

    data = request.get_json(silent=True) or {}

    question = (
        data.get("message") or ""
    ).strip()

    if not question:
        return jsonify({
            "error": "message is required"
        }), 400

    # ---------------------------------------------------------------
    # Database
    # ---------------------------------------------------------------

    admin = get_admin_client()

    context = _build_context(
        admin,
        user.id
    )

    # ---------------------------------------------------------------
    # Chat history
    # ---------------------------------------------------------------

    history_result = (
        admin.table("chat_history")
        .select("role,message")
        .eq("owner_id", user.id)
        .order("created_at", desc=True)
        .limit(MAX_HISTORY)
        .execute()
    )

    history = [
        {
            "role": item["role"],
            "content": item["message"]
        }
        for item in reversed(
            history_result.data or []
        )
    ]

    # ---------------------------------------------------------------
    # Get user's AI key
    # ---------------------------------------------------------------

    try:
        api_key, provider = _get_user_key(user.id)

    except Exception as exc:

        print(
            f"[chatbot] Could not retrieve API key "
            f"for user {user.id}: {exc}",
            flush=True
        )

        api_key = None
        provider = None

    # ---------------------------------------------------------------
    # Ask AI
    # ---------------------------------------------------------------

    try:

        if not api_key:

            print(
                f"[chatbot] No AI key for user {user.id}; "
                f"using rule-based fallback",
                flush=True
            )

            answer = _rule_based_fallback(
                context,
                question
            )

        elif provider == "gemini":

            print(
                f"[chatbot] Using Gemini "
                f"model={GEMINI_MODEL}",
                flush=True
            )

            answer = _ask_gemini(
                api_key,
                context,
                question,
                history
            )

        else:

            print(
                f"[chatbot] Using OpenAI "
                f"model={OPENAI_MODEL}",
                flush=True
            )

            answer = _ask_openai(
                api_key,
                context,
                question,
                history
            )

    except Exception as exc:

        print(
            f"[chatbot] AI call failed "
            f"for user {user.id} "
            f"(provider={provider}): {exc}",
            flush=True
        )

        # Always preserve chatbot functionality.
        answer = _rule_based_fallback(
            context,
            question
        )

    # ---------------------------------------------------------------
    # Save conversation
    # ---------------------------------------------------------------

    try:

        admin.table("chat_history").insert([
            {
                "owner_id": user.id,
                "role": "user",
                "message": question
            },
            {
                "owner_id": user.id,
                "role": "assistant",
                "message": answer
            }
        ]).execute()

    except Exception as exc:

        # Chat should still succeed even if history storage fails.
        print(
            f"[chatbot] Could not save chat history: "
            f"{exc}",
            flush=True
        )

    
    # Response
    

    return jsonify({
        "answer": answer
    })


 # Chat history
 
@app.get("/chat/history")
@require_auth
def chat_history(user):

    admin = get_admin_client()

    result = (
        admin.table("chat_history")
        .select("*")
        .eq("owner_id", user.id)
        .order("created_at")
        .limit(200)
        .execute()
    )

    return jsonify(
        result.data or []
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5010
    )

