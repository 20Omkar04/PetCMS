/* Floating chatbot widget: answers questions using stored metadata + memory logs */

const PetChatbot = (() => {
  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function appendMessage(role, text) {
    const container = document.getElementById("chat-messages");
    const el = document.createElement("div");
    el.className = "chat-msg " + (role === "user" ? "user" : "bot");
    el.textContent = text;
    container.appendChild(el);
    container.scrollTop = container.scrollHeight;
  }

  async function loadHistory() {
    const container = document.getElementById("chat-messages");
    container.innerHTML = "";
    try {
      const history = await PetAPI.get("/api/chat/history");
      if (history.length === 0) {
        appendMessage("bot", "Hi! Ask me about your pet photos — locations, dates, tags, or anything logged in your timeline.");
      } else {
        history.forEach((h) => appendMessage(h.role === "user" ? "user" : "bot", h.message));
      }
    } catch (e) {
      appendMessage("bot", "Hi! Ask me about your pet photos — locations, dates, tags, or anything logged in your timeline.");
    }
  }

  function init() {
    const toggleBtn = document.getElementById("chat-toggle-btn");
    const panel = document.getElementById("chat-panel");
    const closeBtn = document.getElementById("chat-close-btn");
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");

    toggleBtn.addEventListener("click", () => {
      panel.classList.toggle("hidden");
      if (!panel.classList.contains("hidden")) loadHistory();
    });
    closeBtn.addEventListener("click", () => panel.classList.add("hidden"));

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;
      appendMessage("user", message);
      input.value = "";
      appendMessage("bot", "…");
      try {
        const data = await PetAPI.post("/api/chat", { message });
        const container = document.getElementById("chat-messages");
        container.lastChild.textContent = data.answer;
      } catch (err) {
        const container = document.getElementById("chat-messages");
        container.lastChild.textContent = "Sorry, I couldn't process that: " + err.message;
      }
    });
  }

  return { init };
})();

window.PetChatbot = PetChatbot;
document.addEventListener("DOMContentLoaded", () => PetChatbot.init());
