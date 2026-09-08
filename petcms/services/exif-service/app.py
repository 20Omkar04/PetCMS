"""
EXIF Processing Service
Extracts GPS coordinates, timestamp, and device/camera info from an
uploaded image's EXIF data, using Pillow's modern public Exif API
(Image.getexif() + get_ifd) rather than the deprecated private
_getexif(), which silently returns nothing for many valid files.
"""
import io
from flask import Flask, request, jsonify
from PIL import Image, ExifTags

app = Flask(__name__)

GPS_TAG_ID = next((k for k, v in ExifTags.TAGS.items() if v == "GPSInfo"), 34853)


@app.get("/health")
def health():
    return {"status": "ok", "service": "exif-service"}


def _convert_to_degrees(value):
    d, m, s = value[0], value[1], value[2]
    return float(d) + float(m) / 60.0 + float(s) / 3600.0


def _extract_gps(gps_ifd):
    try:
        gps_tags = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
        lat = _convert_to_degrees(gps_tags["GPSLatitude"])
        if gps_tags.get("GPSLatitudeRef", "N") != "N":
            lat = -lat
        lng = _convert_to_degrees(gps_tags["GPSLongitude"])
        if gps_tags.get("GPSLongitudeRef", "E") != "E":
            lng = -lng
        return lat, lng
    except Exception:
        return None, None


@app.post("/extract")
def extract():
    if "file" not in request.files:
        return jsonify({"error": "file is required"}), 400
    file_bytes = request.files["file"].read()

    result = {
        "gps_lat": None,
        "gps_lng": None,
        "taken_at": None,
        "device": None,
        "raw": {},
        "debug": {},  # remove once this is confirmed working end-to-end
    }

    try:
        image = Image.open(io.BytesIO(file_bytes))
        result["debug"]["format"] = image.format
        exif = image.getexif()
    except Exception as e:
        result["debug"]["open_error"] = str(e)
        return jsonify(result)

    if not exif or len(exif) == 0:
        result["debug"]["note"] = "Image opened fine but contains no EXIF tags at all."
        return jsonify(result)

    decoded = {}
    for tag_id, value in exif.items():
        tag = ExifTags.TAGS.get(tag_id, tag_id)
        decoded[tag] = value if isinstance(value, (str, int, float)) else str(value)

    gps_ifd = exif.get_ifd(GPS_TAG_ID) if hasattr(exif, "get_ifd") else None
    if gps_ifd:
        lat, lng = _extract_gps(gps_ifd)
        result["gps_lat"], result["gps_lng"] = lat, lng
    else:
        result["debug"]["note"] = "EXIF present but no GPSInfo block — this photo has no location tag."

    result["taken_at"] = decoded.get("DateTimeOriginal") or decoded.get("DateTime")
    make = decoded.get("Make", "")
    model = decoded.get("Model", "")
    device = f"{make} {model}".strip()
    result["device"] = device or None
    result["raw"] = decoded

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)