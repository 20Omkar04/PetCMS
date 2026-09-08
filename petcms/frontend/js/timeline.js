/* Memory timeline page */

const PetTimeline = (() => {
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function load() {
    const list = document.getElementById("timeline-list");
    list.innerHTML = "";
    let events = [];
    try {
      events = await PetAPI.get("/api/timeline");
    } catch (e) {
      showToast("Could not load timeline.", true);
      return;
    }
    if (events.length === 0) {
      list.innerHTML = `<div class="empty-state"><span class="paw"><svg><use href="#paw-icon"/></svg></span>Nothing logged yet — upload a photo to start your timeline.</div>`;
      return;
    }
    events.forEach((ev) => {
      const li = document.createElement("li");
      li.className = "timeline-item";
      const icon = { upload: "📤", deleted: "🗑", note: "📝" }[ev.event_type] || "•";
      li.innerHTML = `
        <span class="paw"><svg><use href="#paw-icon"/></svg></span>
        <div class="t-desc">${icon} ${escapeHtml(ev.description)}</div>
        <div class="t-time">${new Date(ev.event_time).toLocaleString()}</div>
      `;
      list.appendChild(li);
    });
  }

  function initForm() {
    document.getElementById("note-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = document.getElementById("note-input");
      const description = input.value.trim();
      if (!description) return;
      try {
        await PetAPI.post("/api/timeline/notes", { description });
        input.value = "";
        load();
      } catch (err) {
        showToast("Could not add note: " + err.message, true);
      }
    });
  }

  return { load, initForm };
})();

window.PetTimeline = PetTimeline;
document.addEventListener("DOMContentLoaded", () => PetTimeline.initForm());
