"""
Vet / Map Service
Given a latitude/longitude (usually from an image's EXIF GPS data), queries
the Overpass API (OpenStreetMap) for nearby veterinary clinics, and fills in
addresses via Nominatim reverse-geocoding when a clinic's OSM tags don't
already include a structured address.

Successful results are cached in Redis by rounded coordinates. This is a
direct response to a documented, repeated finding during this project's own
testing: the public Overpass mirrors are unreliable enough (406s during
shared WAF issues, DNS failures, timeouts, sometimes all five at once) that
retrying different endpoints stopped being a productive fix. Caching means
that once any lookup for a given area has ever succeeded, the feature keeps
working for that area even while every live endpoint is down.
"""
import os
import time
import json
import hashlib
import requests
from flask import Flask, request, jsonify
from redis import Redis

app = Flask(__name__)
from prometheus_flask_exporter import PrometheusMetrics
PrometheusMetrics(app)  # exposes GET /metrics for Prometheus scraping

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days — vet clinics don't move often

OVERPASS_URLS = [
    os.environ.get("OVERPASS_URL", "https://lz4.overpass-api.de/api/interpreter"),
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",  # load-balanced front door — last resort
]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@app.get("/health")
def health():
    return {"status": "ok", "service": "vet-map-service"}


def _cache_key(lat, lng, radius_m):
    # Round to ~1.1km grid cells so nearby-but-not-identical coordinates
    # (e.g. two photos taken a street apart) still share a cache entry.
    rounded = f"{round(lat, 2)}:{round(lng, 2)}:{radius_m}"
    return "vets:" + hashlib.sha1(rounded.encode()).hexdigest()


def _reverse_geocode(lat, lng):
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"format": "jsonv2", "lat": lat, "lon": lng, "addressdetails": 1},
            headers=REQUEST_HEADERS,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("display_name")
    except Exception:
        return None


def _query_overpass(query):
    """Returns (elements, errors). errors is empty on success."""
    errors = []
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, headers=REQUEST_HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.json().get("elements", []), []
        except requests.exceptions.HTTPError as e:
            errors.append(f"{url} -> {e} — server said: {resp.text[:300]}")
        except Exception as e:
            errors.append(f"{url} -> {e}")
    return [], errors


@app.get("/nearby-vets")
def nearby_vets():
    try:
        lat = float(request.args.get("lat"))
        lng = float(request.args.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng query params are required"}), 400
    radius_m = int(request.args.get("radius", 5000))

    cache_key = _cache_key(lat, lng, radius_m)
    cached = None
    try:
        cached = redis_conn.get(cache_key)
    except Exception:
        pass  # Redis being briefly unavailable shouldn't break the whole request

    query = f"""
    [out:json][timeout:60];
    (
      node["amenity"="veterinary"](around:{radius_m},{lat},{lng});
      way["amenity"="veterinary"](around:{radius_m},{lat},{lng});
    );
    out center 20;
    """
    elements, errors = _query_overpass(query)

    if errors:
        if cached:
            payload = json.loads(cached)
            payload["served_from_cache"] = True
            payload["note"] = "Live Overpass lookup failed; showing the last successful result for this area."
            return jsonify(payload)
        return jsonify({
            "error": "overpass query failed on all endpoints: " + " | ".join(errors),
            "vets": [],
            "hint": "This is a known, documented reliability issue with the free public Overpass "
                    "infrastructure (see the project's Limitations section) — no cached result exists "
                    "yet for this area to fall back on. Try again later, or try a different photo location.",
        }), 502

    MAX_REVERSE_GEOCODE = 16
    geocode_count = 0
    vets = []
    for el in elements:
        tags = el.get("tags", {})
        center = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
        lat_c, lng_c = center.get("lat"), center.get("lon")

        structured = ", ".join(filter(None, [
            tags.get("addr:housenumber"), tags.get("addr:street"),
            tags.get("addr:city"), tags.get("addr:postcode"),
        ]))
        if structured:
            address = structured
        elif lat_c and lng_c and geocode_count < MAX_REVERSE_GEOCODE:
            geocode_count += 1
            time.sleep(1)
            address = _reverse_geocode(lat_c, lng_c)
        else:
            address = None

        vets.append({
            "name": tags.get("name", "Unnamed veterinary clinic"),
            "lat": lat_c,
            "lng": lng_c,
            "address": address,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "opening_hours": tags.get("opening_hours"),
        })

    result = {"vets": vets, "origin": {"lat": lat, "lng": lng}, "served_from_cache": False}
    try:
        redis_conn.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(result))
    except Exception:
        pass  # caching is a nice-to-have; never let it break a successful response

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5011)
