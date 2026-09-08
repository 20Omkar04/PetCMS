"""
Chatbot Service
Lightweight assistant that answers questions about the user's own pet
photos and memory timeline (e.g. "when did I last visit the vet?",
"how many photos of Milo are tagged outdoors?"). Uses the user's own
saved AI API key; if none is configured, falls back to simple rule-based
answers over the stored metadata so the feature still works.
"""
import os
import requests
from flask import Flask, request, jsonify
from common import get_admin_client, require_auth, decrypt_secret

app = Flask(__name__)

USER_SERVICE_URL = os.environ.get("USER_SERVICE_URL", "http://user-service:5002")

SYSTEM_PROMPT = (
    "You are the assistant inside PetCMS, a personal pet photo gallery app. "
    "Answer the user's question using ONLY the JSON context of their images and "
    "memory timeline events provided below. Be concise and warm. If the answer "
    "isn't in the context, say you don't have that information yet."
)


def _build_context(admin, user_id):
    images = admin.table("images").select(
        "filename,caption,pet_type,tags,categories,taken_at,gps_lat,gps_lng,device"
    ).eq("owner_id", user_id).order("taken_at", desc=True).limit(50).execute().data or []
    events = admin.table("memory_events").select("event_type,description,event_time") \
        .eq("owner_id", user_id).order("event_time", desc=True).limit(50).execute().data or []
    return {"images": images, "timeline": events}


def _get_user_key(user_id):
    resp = requests.get(f"{USER_SERVICE_URL}/internal/api-key/{user_id}", timeout=10)
    if resp.status_code != 200:
        return None, None
    data = resp.json()
    return decrypt_secret(data["encrypted_api_key"]), data.get("api_key_provider", "openai")


def _ask_openai(api_key, context, question, history):
    messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\nContext: {context}"}]
    messages += history
    messages.append({"role": "user", "content": question})
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 300},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _ask_gemini(api_key, context, question, history):
    convo = "\n".join(f"{m['role']}: {m['content']}" for m in history)
    prompt = f"{SYSTEM_PROMPT}\n\nContext: {context}\n\n{convo}\nuser: {question}"
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _rule_based_fallback(context, question):
    q = question.lower()
    images = context["images"]
    if "how many" in q and "photo" in q:
        return f"You have {len(images)} photos in your recent history."
    if "vet" in q:
        vet_events = [e for e in context["timeline"] if "vet" in e["description"].lower()]
        if vet_events:
            latest = vet_events[0]
            return f"The most recent vet-related entry I see is: \"{latest['description']}\" ({latest['event_time']})."
        return "I don't see any vet-related entries in your timeline yet."
    if images:
        latest = images[0]
        return (f"Your most recent photo is \"{latest.get('filename')}\""
                f"{' — ' + latest['caption'] if latest.get('caption') else ''}, "
                f"tagged: {', '.join(latest.get('tags') or []) or 'no tags yet'}.")
    return "I don't have enough data yet — try uploading some photos first! Add an AI API key in Settings for richer answers."


@app.get("/health")
def health():
    return {"status": "ok", "service": "chatbot-service"}


@app.post("/chat")
@require_auth
def chat(user):
    data = request.get_json(force=True) or {}
    question = (data.get("message") or "").strip()
    if not question:
        return jsonify({"error": "message is required"}), 400

    admin = get_admin_client()
    context = _build_context(admin, user.id)

    history_res = admin.table("chat_history").select("role,message") \
        .eq("owner_id", user.id).order("created_at", desc=True).limit(10).execute()
    history = [{"role": h["role"], "content": h["message"]} for h in reversed(history_res.data or [])]

    api_key, provider = _get_user_key(user.id)
    try:
        if api_key and provider == "gemini":
            answer = _ask_gemini(api_key, context, question, history)
        elif api_key:
            answer = _ask_openai(api_key, context, question, history)
        else:
            answer = _rule_based_fallback(context, question)
    except Exception:
        answer = _rule_based_fallback(context, question)

    admin.table("chat_history").insert([
        {"owner_id": user.id, "role": "user", "message": question},
        {"owner_id": user.id, "role": "assistant", "message": answer},
    ]).execute()

    return jsonify({"answer": answer})


@app.get("/chat/history")
@require_auth
def chat_history(user):
    admin = get_admin_client()
    res = admin.table("chat_history").select("*").eq("owner_id", user.id) \
        .order("created_at").limit(200).execute()
    return jsonify(res.data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010)