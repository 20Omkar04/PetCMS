/* JWT inspector — decodes the current Supabase access token client-side for
   demonstration purposes. This is NOT how auth is actually enforced: every
   backend service independently verifies the token's signature and expiry
   against Supabase before trusting it (see require_auth() in common.py on
   the server). Decoding here just makes the token's claims visible in the UI. */

let jwtPanelView = "both"; // "both" | "header" | "payload" | "raw"

function base64UrlDecode(str) {
  let s = str.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const decoded = atob(s);
  try {
    return decodeURIComponent(
      decoded.split("").map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join("")
    );
  } catch (e) {
    return decoded;
  }
}

function decodeJWT(token) {
  const parts = token.split(".");
  if (parts.length !== 3) throw new Error("Not a valid JWT (expected 3 segments)");
  const header = JSON.parse(base64UrlDecode(parts[0]));
  const payload = JSON.parse(base64UrlDecode(parts[1]));
  return { header, payload, signaturePresent: parts[2].length > 0 };
}

function escapeHtmlLocal(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function jsonBlock(obj) {
  return `<pre style="background:var(--ground-alt); padding:10px; border-radius:8px; font-size:0.78rem; overflow-x:auto; margin:0;">${escapeHtmlLocal(JSON.stringify(obj, null, 2))}</pre>`;
}

function renderJwtPanel() {
  const container = document.getElementById("jwt-panel");
  if (!container) return;
  const token = PetAPI.getAccessToken();
  if (!token) {
    container.innerHTML = `<p class="sub">No active session token.</p>`;
    return;
  }

  let decoded;
  try {
    decoded = decodeJWT(token);
  } catch (e) {
    container.innerHTML = `<p class="error-text">Could not decode token: ${e.message}</p>`;
    return;
  }

  const { header, payload } = decoded;
  const expiresAt = payload.exp ? new Date(payload.exp * 1000) : null;
  const issuedAt = payload.iat ? new Date(payload.iat * 1000) : null;
  const now = new Date();
  const secondsLeft = expiresAt ? Math.round((expiresAt - now) / 1000) : null;
  const expired = secondsLeft !== null && secondsLeft <= 0;

  let detailHtml = "";
  if (jwtPanelView === "both") {
    detailHtml = `
      <div style="display:grid; grid-template-columns: 1fr; gap:16px; margin-bottom:14px;">
        <div><label style="margin-bottom:4px;">Header</label>${jsonBlock(header)}</div>
        <div><label style="margin-bottom:4px;">Payload (claims)</label>${jsonBlock(payload)}</div>
      </div>`;
  } else if (jwtPanelView === "header") {
    detailHtml = `<div style="margin-bottom:14px;"><label style="margin-bottom:4px;">Header</label>${jsonBlock(header)}</div>`;
  } else if (jwtPanelView === "payload") {
    detailHtml = `<div style="margin-bottom:14px;"><label style="margin-bottom:4px;">Payload (claims)</label>${jsonBlock(payload)}</div>`;
  } else if (jwtPanelView === "raw") {
    detailHtml = `<div style="margin-bottom:14px;"><label style="margin-bottom:4px;">Raw token (header.payload.signature)</label>
      <textarea readonly style="width:100%; font-size:0.72rem; height:90px;">${escapeHtmlLocal(token)}</textarea></div>`;
  }

  container.innerHTML = `
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:14px;">
      <div class="key-status ${expired ? "" : "set"}" style="margin-bottom:0;">
        <span class="dot"></span>
        <span>${expired ? "Token expired" : `Valid — expires in ${Math.floor(secondsLeft / 60)}m ${secondsLeft % 60}s`}</span>
      </div>
      <button class="btn btn-secondary" id="jwt-refresh-btn" type="button" style="margin-left:auto;">Refresh now</button>
    </div>

    <div class="field" style="max-width:260px;">
      <label for="jwt-view-select">Show</label>
      <select id="jwt-view-select">
        <option value="both">Header + payload</option>
        <option value="header">Header only</option>
        <option value="payload">Payload only</option>
        <option value="raw">Raw token</option>
      </select>
    </div>

    ${detailHtml}

    <div style="font-size:0.82rem; color:var(--ink-soft); display:grid; gap:4px;">
      <div><strong>sub (user id):</strong> ${escapeHtmlLocal(payload.sub || "—")}</div>
      <div><strong>role:</strong> ${escapeHtmlLocal(payload.role || "—")}</div>
      <div><strong>issued at:</strong> ${issuedAt ? issuedAt.toLocaleString() : "—"}</div>
      <div><strong>expires at:</strong> ${expiresAt ? expiresAt.toLocaleString() : "—"}</div>
      <div><strong>algorithm:</strong> ${escapeHtmlLocal(header.alg || "—")}</div>
    </div>
    <div class="error-text" id="jwt-refresh-error"></div>
  `;

  const select = document.getElementById("jwt-view-select");
  select.value = jwtPanelView;
  select.addEventListener("change", () => {
    jwtPanelView = select.value;
    renderJwtPanel();
  });

  document.getElementById("jwt-refresh-btn").addEventListener("click", async () => {
    const btn = document.getElementById("jwt-refresh-btn");
    const errorEl = document.getElementById("jwt-refresh-error");
    errorEl.textContent = "";
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const ok = await PetAPI.refreshAccessToken();
      if (!ok) throw new Error("Refresh token is missing or invalid — please log in again.");
      renderJwtPanel();
      showToast("Token refreshed — new expiry above.");
    } catch (e) {
      errorEl.textContent = e.message || "Could not refresh token.";
      btn.disabled = false;
      btn.textContent = "Refresh now";
    }
  });
}

window.PetJWT = { decodeJWT, renderJwtPanel };