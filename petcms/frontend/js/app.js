/* Core app shell: routing between views, gallery rendering, filters, upload modal */

const PetCMSApp = (() => {
  let currentRoute = "gallery";
  let allTagsSeen = new Set();
  let activeTagFilter = "";
  let imageUrlCache = {}; // storage_path -> signed url

  function switchRoute(route) {
    currentRoute = route;
    document.querySelectorAll(".route-view").forEach((el) => el.classList.add("hidden"));
    document.getElementById(`route-${route}`).classList.remove("hidden");
    document.querySelectorAll(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.route === route));
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("nav-scrim").classList.remove("show");

    if (route === "gallery") loadGallery();
    if (route === "map") window.PetMap.init();
    if (route === "timeline") window.PetTimeline.load();
    if (route === "profile") loadProfile();
    if (route === "settings") window.PetSettings.load();
  }

  function initNav() {
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => switchRoute(btn.dataset.route));
    });
    document.getElementById("logout-btn").addEventListener("click", () => {
      PetAPI.clearSession();
      location.reload();
    });
    document.getElementById("menu-toggle").addEventListener("click", () => {
      document.getElementById("sidebar").classList.add("open");
      document.getElementById("nav-scrim").classList.add("show");
    });
    document.getElementById("nav-scrim").addEventListener("click", () => {
      document.getElementById("sidebar").classList.remove("open");
      document.getElementById("nav-scrim").classList.remove("show");
    });
  }

  async function enterApp() {
    document.getElementById("view-landing").classList.add("hidden");
    document.getElementById("view-app").classList.remove("hidden");
    document.getElementById("chat-toggle-btn").classList.remove("hidden");

    const user = PetAPI.getUser();
    document.getElementById("sidebar-username").textContent = user ? user.username : "—";

    await loadCategoriesIntoFilters();
    switchRoute("gallery");
  }

  // -------------------------------------------------------------- gallery
  async function resolveImageUrl(storagePath) {
    if (imageUrlCache[storagePath]) return imageUrlCache[storagePath];
    try {
      const data = await PetAPI.get("/api/storage/signed-url", { path: storagePath });
      imageUrlCache[storagePath] = data.signed_url;
      return data.signed_url;
    } catch (e) {
      return "";
    }
  }

  function petTypeLabel(pt) {
    const map = { dog: "Dog", cat: "Cat", bird: "Bird", small_mammal: "Small mammal", reptile: "Reptile", other: "Other" };
    return map[pt] || "Other";
  }

  async function loadGallery() {
    const grid = document.getElementById("gallery-grid");
    const empty = document.getElementById("gallery-empty");
    const query = {
      q: document.getElementById("search-input").value.trim(),
      pet_type: document.getElementById("filter-pet-type").value,
      category: document.getElementById("filter-category").value,
      date_from: document.getElementById("filter-date-from").value,
      date_to: document.getElementById("filter-date-to").value,
      tag: activeTagFilter,
    };
    let images = [];
    try {
      images = await PetAPI.get("/api/images", query);
    } catch (e) {
      showToast("Could not load gallery: " + e.message, true);
    }

    images.forEach((img) => (img.tags || []).forEach((t) => allTagsSeen.add(t)));
    renderTagChips();

    grid.innerHTML = "";
    empty.classList.toggle("hidden", images.length > 0);

    for (const img of images) {
      const card = document.createElement("div");
      card.className = "pcard";
      const thumb = document.createElement("div");
      thumb.className = "thumb";
      thumb.innerHTML = `<span class="pet-type-badge">${petTypeLabel(img.pet_type)}</span>`;
      resolveImageUrl(img.storage_path).then((url) => {
        if (url) thumb.style.backgroundImage = `url('${url}')`;
      });
      thumb.addEventListener("click", () => openDetail(img));

      const body = document.createElement("div");
      body.className = "body";
      const takenDate = img.taken_at ? new Date(img.taken_at).toLocaleDateString() : "Unknown date";
      body.innerHTML = `
        <div class="caption">${escapeHtml(img.caption || img.filename || "Untitled")}</div>
        <div class="meta">📅 ${takenDate} ${img.gps_lat ? " · 📍 located" : ""}</div>
        <div class="tags">${(img.tags || []).slice(0, 5).map((t) => `<span class="tag-pill">${escapeHtml(t)}</span>`).join("")}</div>
        <div class="card-actions">
          <button class="btn btn-secondary btn-view">View</button>
          <button class="btn btn-danger btn-delete">Delete</button>
        </div>
      `;
      body.querySelector(".btn-view").addEventListener("click", () => openDetail(img));
      body.querySelector(".btn-delete").addEventListener("click", () => confirmDelete(img));

      card.appendChild(thumb);
      card.appendChild(body);
      grid.appendChild(card);
    }
  }

  function renderTagChips() {
    const row = document.getElementById("tag-chip-row");
    row.innerHTML = "";
    const allChip = document.createElement("button");
    allChip.className = "chip" + (activeTagFilter === "" ? " active" : "");
    allChip.textContent = "All tags";
    allChip.addEventListener("click", () => { activeTagFilter = ""; loadGallery(); });
    row.appendChild(allChip);

    Array.from(allTagsSeen).slice(0, 16).forEach((tag) => {
      const chip = document.createElement("button");
      chip.className = "chip" + (activeTagFilter === tag ? " active" : "");
      chip.textContent = tag;
      chip.addEventListener("click", () => { activeTagFilter = tag; loadGallery(); });
      row.appendChild(chip);
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function confirmDelete(img) {
    if (!confirm("Delete this photo? This can't be undone.")) return;
    try {
      await PetAPI.del(`/api/images/${img.id}`);
      showToast("Photo deleted.");
      loadGallery();
    } catch (e) {
      showToast("Could not delete: " + e.message, true);
    }
  }

  function openDetail(img) {
    const modal = document.getElementById("detail-modal");
    const content = document.getElementById("detail-modal-content");
    const takenDate = img.taken_at ? new Date(img.taken_at).toLocaleString() : "Unknown";
    let editableTags = [...(img.tags || [])]; // local working copy until Save is clicked

    function renderTagEditor() {
      const row = content.querySelector("#detail-tags-row");
      row.innerHTML = editableTags.map((t) => `
        <span class="tag-pill" style="display:inline-flex; align-items:center; gap:6px;">
          ${escapeHtml(t)}
          <button type="button" data-tag="${escapeHtml(t)}" class="tag-remove-btn" style="background:none; border:none; color:var(--danger); font-weight:700; cursor:pointer; padding:0; line-height:1;">✕</button>
        </span>
      `).join("") || `<span class="sub">No tags yet.</span>`;
      row.querySelectorAll(".tag-remove-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          editableTags = editableTags.filter((t) => t !== btn.dataset.tag);
          renderTagEditor();
        });
      });
    }

    content.innerHTML = `
      <h3>${escapeHtml(img.caption || img.filename || "Untitled")}</h3>
      <p class="sub">${petTypeLabel(img.pet_type)} · ${takenDate}${img.device ? " · " + escapeHtml(img.device) : ""}</p>
      <div style="width:100%; aspect-ratio:4/3; background:var(--ground-alt); border-radius:12px; overflow:hidden; margin-bottom:16px;" id="detail-img-holder"></div>

      <label style="margin-bottom:6px;">Tags</label>
      <div class="tags" id="detail-tags-row" style="margin-bottom:10px;"></div>
      <div style="display:flex; gap:8px; margin-bottom:14px;">
        <input id="detail-new-tag-input" placeholder="Add a tag…" style="flex:1;" />
        <button type="button" class="btn btn-secondary" id="detail-add-tag-btn">Add</button>
        <button type="button" class="btn btn-primary" id="detail-save-tags-btn">Save tags</button>
      </div>
      <div class="error-text" id="detail-tags-error"></div>

      ${img.gps_lat ? `<p class="sub">📍 ${img.gps_lat.toFixed(5)}, ${img.gps_lng.toFixed(5)}</p>` : `<p class="sub">No location data on this photo.</p>`}
      <div class="modal-actions">
        <button class="btn btn-ghost" id="detail-close-btn">Close</button>
        ${img.gps_lat ? `<button class="btn btn-secondary" id="detail-map-btn">View on map</button>` : ""}
        <button class="btn btn-danger" id="detail-delete-btn">Delete</button>
      </div>
    `;
    renderTagEditor();

    resolveImageUrl(img.storage_path).then((url) => {
      if (url) document.getElementById("detail-img-holder").style.cssText += `background:url('${url}') center/cover;`;
    });
    modal.classList.remove("hidden");
    content.querySelector("#detail-close-btn").addEventListener("click", () => modal.classList.add("hidden"));
    content.querySelector("#detail-delete-btn").addEventListener("click", async () => {
      modal.classList.add("hidden");
      await confirmDelete(img);
    });
    const mapBtn = content.querySelector("#detail-map-btn");
    if (mapBtn) mapBtn.addEventListener("click", () => {
      modal.classList.add("hidden");
      switchRoute("map");
      setTimeout(() => window.PetMap.focusOn(img), 300);
    });

    const newTagInput = content.querySelector("#detail-new-tag-input");
    function addTagFromInput() {
      const val = newTagInput.value.trim().toLowerCase();
      if (val && !editableTags.includes(val)) {
        editableTags.push(val);
        renderTagEditor();
      }
      newTagInput.value = "";
    }
    content.querySelector("#detail-add-tag-btn").addEventListener("click", addTagFromInput);
    newTagInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); addTagFromInput(); }
    });

    content.querySelector("#detail-save-tags-btn").addEventListener("click", async () => {
      const errorEl = content.querySelector("#detail-tags-error");
      errorEl.textContent = "";
      try {
        const updated = await PetAPI.patch(`/api/images/${img.id}`, { tags: editableTags });
        img.tags = updated.tags;
        showToast("Tags saved.");
        loadGallery();
      } catch (err) {
        errorEl.textContent = err.message || "Could not save tags.";
      }
    });
  }

  // -------------------------------------------------------------- filters
  async function loadCategoriesIntoFilters() {
    let cats = [];
    try { cats = await PetAPI.get("/api/categories"); } catch (e) { /* ignore */ }
    const select = document.getElementById("filter-category");
    select.innerHTML = '<option value="">All categories</option>' +
      cats.map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`).join("");
  }

  function initFilters() {
    document.getElementById("filter-apply-btn").addEventListener("click", loadGallery);
    document.getElementById("filter-clear-btn").addEventListener("click", () => {
      document.getElementById("filter-pet-type").value = "";
      document.getElementById("filter-category").value = "";
      document.getElementById("filter-date-from").value = "";
      document.getElementById("filter-date-to").value = "";
      document.getElementById("search-input").value = "";
      activeTagFilter = "";
      loadGallery();
    });
    let searchTimer;
    document.getElementById("search-input").addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(loadGallery, 350);
    });
  }

  // -------------------------------------------------------------- upload modal
  function initUploadModal() {
    const modal = document.getElementById("upload-modal");
    const form = document.getElementById("upload-form");
    const fileInput = document.getElementById("upload-file-input");
    const dropzoneLabel = document.getElementById("dropzone-label");

    document.getElementById("open-upload-btn").addEventListener("click", () => {
      form.reset();
      dropzoneLabel.textContent = "Click to choose a photo, or drag one here";
      document.getElementById("dropzone").classList.remove("has-file");
      document.getElementById("upload-error").textContent = "";
      modal.classList.remove("hidden");
    });
    document.getElementById("upload-cancel-btn").addEventListener("click", () => modal.classList.add("hidden"));

    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) {
        dropzoneLabel.textContent = fileInput.files[0].name;
        document.getElementById("dropzone").classList.add("has-file");
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById("upload-error");
      errorEl.textContent = "";
      if (!fileInput.files[0]) { errorEl.textContent = "Please choose a photo."; return; }

      const submitBtn = document.getElementById("upload-submit-btn");
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner"></span>';

      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      fd.append("caption", document.getElementById("upload-caption").value.trim());
      fd.append("pet_type", document.getElementById("upload-pet-type").value);
      fd.append("manual_tags", document.getElementById("upload-tags").value.trim());
      fd.append("categories", document.getElementById("upload-categories").value.trim());

      try {
        await PetAPI.postForm("/api/images", fd);
        modal.classList.add("hidden");
        showToast("Photo uploaded — tagging may take a few seconds to appear.");
        loadGallery();
      } catch (err) {
        errorEl.textContent = err.message || "Upload failed.";
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = "Upload";
      }
    });
  }

  // -------------------------------------------------------------- profile
  async function loadProfile() {
    try {
      const me = await PetAPI.get("/api/users/me");
      document.getElementById("profile-username").textContent = me.username || "—";
      document.getElementById("profile-since").textContent = me.created_at ? new Date(me.created_at).toLocaleDateString() : "—";
      const images = await PetAPI.get("/api/images", {});
      const located = images.filter((i) => i.gps_lat).length;
      document.getElementById("profile-stats").innerHTML = `
        <div>📷 ${images.length} photo${images.length === 1 ? "" : "s"} uploaded</div>
        <div>📍 ${located} with location data</div>
        <div>🔑 AI API key: ${me.has_api_key ? "configured" : "not set"}</div>
      `;
    } catch (e) {
      showToast("Could not load profile.", true);
    }
  }

  function init() {
    initNav();
    initFilters();
    initUploadModal();
  }

  return { init, enterApp, switchRoute, getCurrentRoute: () => currentRoute };
})();

window.PetCMSApp = PetCMSApp;