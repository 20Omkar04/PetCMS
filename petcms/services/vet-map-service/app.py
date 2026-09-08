"""
Vet / Map Service
Given a latitude/longitude (usually from an image's EXIF GPS data), queries
the Overpass API (OpenStreetMap) for nearby veterinary clinics, and fills in
addresses via Nominatim reverse-geocoding when a clinic's OSM tags don't
already include a structured address.
"""
import os
import time
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

OVERPASS_URLS = [
    os.environ.get("OVERPASS_URL", "https://lz4.overpass-api.de/api/interpreter"),
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",  # load-balanced front door — last resort
]

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"

# OSM's Overpass/Nominatim instances reject requests with a generic/blank
# User-Agent per OSM's usage policy — identify the app here. Do NOT force
# an Accept header: 406 means the server can't satisfy it, and Overpass
# doesn't content-negotiate the way a forced "application/json" Accept implies.
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@app.get("/health")
def health():
    return {"status": "ok", "service": "vet-map-service"}


def _reverse_geocode(lat, lng):
    """OSM's Nominatim reverse-geocoder — used only when a vet POI itself
    has no addr:* tags. Nominatim's usage policy caps this at 1 req/sec
    and requires a descriptive User-Agent, so callers must rate-limit."""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"format": "jsonv2", "lat": lat, "lon": lng, "addressdetails": 1},
            headers=REQUEST_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("display_name")
    except Exception:
        return None


@app.get("/nearby-vets")
def nearby_vets():
    try:
        lat = float(request.args.get("lat"))
        lng = float(request.args.get("lng"))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng query params are required"}), 400
    radius_m = int(request.args.get("radius", 5000))

    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"="veterinary"](around:{radius_m},{lat},{lng});
      way["amenity"="veterinary"](around:{radius_m},{lat},{lng});
    );
    out center 20;
    """
    errors = []
    elements = []
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, headers=REQUEST_HEADERS, timeout=30)
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            errors = []
            break
        except requests.exceptions.HTTPError as e:
            errors.append(f"{url} -> {e} — server said: {resp.text[:300]}")
        except Exception as e:
            errors.append(f"{url} -> {e}")

    if errors:
        return jsonify({
            "error": "overpass query failed on all endpoints: " + " | ".join(errors),
            "vets": [],
            "hint": "If every attempt shows a DNS/name-resolution failure, this is a network/DNS issue on the machine or Docker host running vet-map-service, not an app bug — try: docker compose exec vet-map-service curl -v https://overpass-api.de/api/interpreter",
        }), 502

    MAX_REVERSE_GEOCODE = 8  # keeps worst-case response time bounded
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
            time.sleep(1)  # respect Nominatim's 1 request/second usage policy
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

    return jsonify({"vets": vets, "origin": {"lat": lat, "lng": lng}})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5011)