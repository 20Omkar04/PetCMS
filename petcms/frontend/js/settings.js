/* Settings page: AI API key management and custom categories */

const PetSettings = (() => {
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function load() {
    if (window.PetJWT) window.PetJWT.renderJwtPanel();
    try {
      const me = await PetAPI.get("/api/users/me");
      const statusEl = document.getElementById("key-status");
      const statusText = document.getElementById("key-status-text");
      statusEl.classList.toggle("set", !!me.has_api_key);
      statusText.textContent = me.has_api_key
        ? `Key configured (${me.api_key_provider || "unknown provider"})`
        : "No key configured";
      if (me.api_key_provider) document.getElementById("settings-provider").value = me.api_key_provider;
    } catch (e) {
      showToast("Could not load account settings.", true);
    }
    await loadCategories();
  }

  async function loadCategories() {
    const listEl = document.getElementById("settings-category-list");
    listEl.innerHTML = "";
    let cats = [];
    try { cats = await PetAPI.get("/api/categories"); } catch (e) { /* ignore */ }
    if (cats.length === 0) {
      listEl.innerHTML = `<span class="sub">No categories yet.</span>`;
      return;
    }
    cats.forEach((c) => {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.innerHTML = `${escapeHtml(c.name)} <button style="background:none;border:none;margin-left:6px;color:var(--danger);font-weight:700;">✕</button>`;
      chip.querySelector("button").addEventListener("click", async () => {
        try {
          await PetAPI.del(`/api/categories/${c.id}`);
          loadCategories();
        } catch (e) {
          showToast("Could not remove category.", true);
        }
      });
      listEl.appendChild(chip);
    });
  }

  function initForms() {
    document.getElementById("settings-key-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errorEl = document.getElementById("settings-error");
      errorEl.textContent = "";
      const provider = document.getElementById("settings-provider").value;
      const api_key = document.getElementById("settings-key").value.trim();
      if (!api_key) { errorEl.textContent = "Enter a key to save."; return; }
      try {
        await PetAPI.put("/api/users/me/api-key", { provider, api_key });
        document.getElementById("settings-key").value = "";
        showToast("API key saved.");
        load();
      } catch (err) {
        errorEl.textContent = err.message || "Could not save key.";
      }
    });

    document.getElementById("remove-key-btn").addEventListener("click", async () => {
      if (!confirm("Remove your saved API key? AI tagging and the chatbot will fall back to basic mode.")) return;
      try {
        await PetAPI.del("/api/users/me/api-key");
        showToast("API key removed.");
        load();
      } catch (err) {
        showToast("Could not remove key.", true);
      }
    });

    document.getElementById("add-category-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("new-category-input");
      const name = input.value.trim();
      if (!name) return;
      try {
        await PetAPI.post("/api/categories", { name });
        input.value = "";
        loadCategories();
      } catch (err) {
        showToast("Could not add category: " + err.message, true);
      }
    });
  }

  return { load, initForms };
})();

window.PetSettings = PetSettings;
document.addEventListener("DOMContentLoaded", () => PetSettings.initForms());