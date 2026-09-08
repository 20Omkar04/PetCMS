/* Map page: plots image GPS locations on Leaflet/OpenStreetMap, and looks up
   nearby veterinary clinics via the vet-map-service (Overpass API). */

const PetMap = (() => {
  let map = null;
  let markersLayer = null;
  let locatedImages = [];

  function ensureMap() {
    if (map) return;
    map = L.map("mapview").setView([20, 0], 2);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
    }).addTo(map);
    markersLayer = L.layerGroup().addTo(map);
  }

  async function init() {
    ensureMap();
    setTimeout(() => map.invalidateSize(), 100);

    let images = [];
    try {
      images = await PetAPI.get("/api/images", { has_location: "true" });
    } catch (e) {
      showToast("Could not load located photos.", true);
    }
    locatedImages = images.filter((i) => i.gps_lat && i.gps_lng);

    markersLayer.clearLayers();
    const select = document.getElementById("map-photo-select");
    select.innerHTML = '<option value="">Select a located photo…</option>';

    if (locatedImages.length === 0) {
      document.getElementById("vet-list").innerHTML =
        `<div class="empty-state"><span class="paw"><svg><use href="#paw-icon"/></svg></span>No photos with location data yet — GPS is read automatically from EXIF when available.</div>`;
      return;
    }

    const bounds = [];
    locatedImages.forEach((img, idx) => {
      const marker = L.marker([img.gps_lat, img.gps_lng]).addTo(markersLayer);
      marker.bindPopup(`<strong>${escapeHtml(img.caption || img.filename || "Photo")}</strong><br/>${img.taken_at ? new Date(img.taken_at).toLocaleDateString() : ""}`);
      bounds.push([img.gps_lat, img.gps_lng]);

      const opt = document.createElement("option");
      opt.value = idx;
      opt.textContent = img.caption || img.filename || `Photo ${idx + 1}`;
      select.appendChild(opt);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function findVets(lat, lng) {
    const listEl = document.getElementById("vet-list");
    listEl.innerHTML = `<div class="sub">Searching OpenStreetMap for nearby vets…</div>`;
    let data;
    try {
      data = await PetAPI.get("/api/vets/nearby", { lat, lng, radius: 8000 });
    } catch (e) {
      listEl.innerHTML = `<div class="error-text">Could not fetch nearby vets: ${e.message}</div>`;
      return;
    }
    const vets = data.vets || [];
    if (vets.length === 0) {
      listEl.innerHTML = `<div class="sub">No veterinary clinics found in OpenStreetMap data within range.</div>`;
      return;
    }
    listEl.innerHTML = "";
    vets.forEach((v) => {
      if (v.lat && v.lng) {
        L.circleMarker([v.lat, v.lng], { radius: 7, color: "#33513E", fillColor: "#C98A3D", fillOpacity: 1 })
          .addTo(markersLayer)
          .bindPopup(`<strong>${escapeHtml(v.name)}</strong>${v.phone ? "<br/>" + escapeHtml(v.phone) : ""}`);
      }
      const card = document.createElement("div");
      card.className = "vet-card";
      card.innerHTML = `
        <div class="v-name">🏥 ${escapeHtml(v.name)}</div>
        <div class="v-meta">${v.address ? escapeHtml(v.address) : "Address unavailable"}</div>
        <div class="v-meta">${v.phone ? "📞 " + escapeHtml(v.phone) : ""} ${v.opening_hours ? " · 🕒 " + escapeHtml(v.opening_hours) : ""}</div>
      `;
      listEl.appendChild(card);
    });
  }

  function focusOn(img) {
    ensureMap();
    if (img.gps_lat && img.gps_lng) {
      map.setView([img.gps_lat, img.gps_lng], 13);
    }
  }

  function initControls() {
    document.getElementById("find-vets-btn").addEventListener("click", () => {
      const idx = document.getElementById("map-photo-select").value;
      if (idx === "") { showToast("Pick a located photo first.", true); return; }
      const img = locatedImages[idx];
      map.setView([img.gps_lat, img.gps_lng], 13);
      findVets(img.gps_lat, img.gps_lng);
    });
  }

  return { init, initControls, focusOn };
})();

window.PetMap = PetMap;
document.addEventListener("DOMContentLoaded", () => PetMap.initControls());
