"""
Gateway / API Service
Single public entry point. Serves the static frontend and reverse-proxies
/api/* calls to the appropriate internal microservice, so the browser only
ever talks to one origin.
"""
import os
import requests
from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder=None)

SERVICES = {
    "auth": os.environ.get("AUTH_SERVICE_URL", "http://auth-service:5001"),
    "user": os.environ.get("USER_SERVICE_URL", "http://user-service:5002"),
    "upload": os.environ.get("UPLOAD_SERVICE_URL", "http://upload-service:5003"),
    "storage": os.environ.get("STORAGE_SERVICE_URL", "http://storage-service:5004"),
    "category": os.environ.get("CATEGORY_SERVICE_URL", "http://category-service:5007"),
    "search": os.environ.get("SEARCH_SERVICE_URL", "http://search-service:5008"),
    "memory": os.environ.get("MEMORY_SERVICE_URL", "http://memory-service:5009"),
    "chatbot": os.environ.get("CHATBOT_SERVICE_URL", "http://chatbot-service:5010"),
    "vetmap": os.environ.get("VET_MAP_SERVICE_URL", "http://vet-map-service:5011"),
}

FRONTEND_DIR = "/app/frontend"


def proxy(base_url, path, method=None):
    method = method or request.method
    url = f"{base_url}{path}"
    headers = {}
    if "Authorization" in request.headers:
        headers["Authorization"] = request.headers["Authorization"]

    kwargs = {"headers": headers, "params": request.args, "timeout": 90}
    if request.files:
        kwargs["files"] = {k: (f.filename, f.stream, f.mimetype) for k, f in request.files.items()}
        kwargs["data"] = request.form
    elif request.is_json:
        kwargs["json"] = request.get_json(silent=True)
    elif request.data:
        kwargs["data"] = request.data
        headers["Content-Type"] = request.headers.get("Content-Type", "application/octet-stream")

    resp = requests.request(method, url, **kwargs)
    excluded = {"content-encoding", "transfer-encoding", "connection", "content-length"}
    out_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded]
    return Response(resp.content, resp.status_code, out_headers)


# ---------------------------------------------------------------- auth
@app.route("/api/auth/<path:sub>", methods=["GET", "POST"])
def auth_proxy(sub):
    return proxy(SERVICES["auth"], f"/{sub}")


# ---------------------------------------------------------------- user / api key
@app.route("/api/users/me", methods=["GET"])
def user_me():
    return proxy(SERVICES["user"], "/me")


@app.route("/api/users/me/api-key", methods=["PUT", "DELETE"])
def user_api_key():
    return proxy(SERVICES["user"], "/me/api-key")


# ---------------------------------------------------------------- images (upload/delete)
@app.route("/api/images", methods=["POST"])
def images_create():
    return proxy(SERVICES["upload"], "/images", method="POST")


@app.route("/api/images/<image_id>", methods=["DELETE"])
def images_delete(image_id):
    return proxy(SERVICES["upload"], f"/images/{image_id}", method="DELETE")


# ---------------------------------------------------------------- images (search/list/get/edit)
@app.route("/api/images", methods=["GET"])
def images_list():
    return proxy(SERVICES["search"], "/images", method="GET")


@app.route("/api/images/<image_id>", methods=["GET", "PATCH"])
def images_get_or_patch(image_id):
    return proxy(SERVICES["search"], f"/images/{image_id}")


# ---------------------------------------------------------------- storage (signed urls)
@app.route("/api/storage/signed-url", methods=["GET"])
def storage_signed_url():
    return proxy(SERVICES["storage"], "/signed-url")


# ---------------------------------------------------------------- categories
@app.route("/api/categories", methods=["GET", "POST"])
def categories():
    return proxy(SERVICES["category"], "/categories")


@app.route("/api/categories/<category_id>", methods=["DELETE"])
def categories_delete(category_id):
    return proxy(SERVICES["category"], f"/categories/{category_id}")


# ---------------------------------------------------------------- memory timeline
@app.route("/api/timeline", methods=["GET"])
def timeline():
    return proxy(SERVICES["memory"], "/timeline")


@app.route("/api/timeline/notes", methods=["POST"])
def timeline_notes():
    return proxy(SERVICES["memory"], "/timeline/notes")


# ---------------------------------------------------------------- chatbot
@app.route("/api/chat", methods=["POST"])
def chat():
    return proxy(SERVICES["chatbot"], "/chat")


@app.route("/api/chat/history", methods=["GET"])
def chat_history():
    return proxy(SERVICES["chatbot"], "/chat/history")


# ---------------------------------------------------------------- vet/map
@app.route("/api/vets/nearby", methods=["GET"])
def nearby_vets():
    return proxy(SERVICES["vetmap"], "/nearby-vets")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "gateway"})


# ---------------------------------------------------------------- static frontend
@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def frontend(path):
    full_path = os.path.join(FRONTEND_DIR, path)
    if not os.path.isfile(full_path):
        path = "index.html"
    return send_from_directory(FRONTEND_DIR, path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
