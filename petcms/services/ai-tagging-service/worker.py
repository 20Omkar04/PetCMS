"""
AI Tagging Worker
Consumes jobs from the "petcms-tagging" Redis queue (enqueued by
upload-service on every photo upload) and does the actual AI tagging call
in the background — this is what decouples a slow/unreliable third-party
AI call from the upload request itself.

Run as its own container (see docker-compose.yml: ai-tagging-worker),
built from the same image as ai-tagging-service but started with
`rq worker` instead of gunicorn, so it can be scaled independently:
    docker compose up --scale ai-tagging-worker=3
"""
import os
import requests

from common import get_admin_client
from app import generate_tags

STORAGE_SERVICE_URL = os.environ.get("STORAGE_SERVICE_URL", "http://storage-service:5004")
MEMORY_SERVICE_URL = os.environ.get("MEMORY_SERVICE_URL", "http://memory-service:5009")


def _log_timeline_note(owner_id, image_id, description):
    try:
        requests.post(
            f"{MEMORY_SERVICE_URL}/internal/events",
            json={"owner_id": owner_id, "image_id": image_id, "event_type": "note", "description": description},
            timeout=120,
        )
    except Exception:
        pass


def process_tagging_job(image_id, user_id, storage_path, filename, mime_type, manual_tags):
    """The job function RQ executes. Must be importable as 'worker.process_tagging_job'
    (upload-service enqueues it by that string, without importing this module itself)."""
    admin = get_admin_client()

    # Fetch the actual bytes back from storage — the queue only carries the
    # path, not the (potentially large) file itself, to keep Redis payloads small.
    try:
        dl_resp = requests.get(f"{STORAGE_SERVICE_URL}/internal/download", params={"path": storage_path}, timeout=30)
        dl_resp.raise_for_status()
        file_bytes = dl_resp.content
    except Exception as e:
        admin.table("images").update({"tagging_status": "failed"}).eq("id", image_id).execute()
        _log_timeline_note(user_id, image_id, f"AI tagging failed for {filename}: could not fetch image from storage ({e})")
        return

    tags, issue = generate_tags(file_bytes, user_id)
    all_tags = sorted(set(tags) | set(manual_tags or []))

    status = "ready"
    if issue and not tags:
        status = "skipped_no_key" if "no AI API key" in issue else "failed"

    admin.table("images").update({
        "ai_tags": tags,
        "tags": all_tags,
        "tagging_status": status,
    }).eq("id", image_id).execute()

    if issue:
        _log_timeline_note(user_id, image_id, f"AI tagging for {filename}: {issue}")
