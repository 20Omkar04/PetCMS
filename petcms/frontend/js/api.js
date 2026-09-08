/* API helper: wraps fetch with auth headers, token storage, and refresh. */

const PetAPI = (() => {
  const TOKEN_KEY = "petcms_access_token";
  const REFRESH_KEY = "petcms_refresh_token";
  const USER_KEY = "petcms_user";

  function getAccessToken() { return localStorage.getItem(TOKEN_KEY); }
  function getRefreshToken() { return localStorage.getItem(REFRESH_KEY); }
  function getUser() {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  }
  function setSession(user, accessToken, refreshToken) {
    localStorage.setItem(TOKEN_KEY, accessToken);
    if (refreshToken) localStorage.setItem(REFRESH_KEY, refreshToken);
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  }
  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  }

  async function refreshAccessToken() {
    const refresh_token = getRefreshToken();
    if (!refresh_token) return false;
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.access_token);
    if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token);
    return true;
  }

  /**
   * request(path, { method, json, form, query, retry })
   * - json: object -> sent as application/json
   * - form: FormData -> sent as multipart
   */
  async function request(path, opts = {}) {
    const { method = "GET", json, form, query, _retried } = opts;
    let url = path;
    if (query) {
      const params = new URLSearchParams();
      Object.entries(query).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") params.set(k, v); });
      const qs = params.toString();
      if (qs) url += (path.includes("?") ? "&" : "?") + qs;
    }

    const headers = {};
    const token = getAccessToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const fetchOpts = { method, headers };
    if (form) {
      fetchOpts.body = form;
    } else if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      fetchOpts.body = JSON.stringify(json);
    }

    const res = await fetch(url, fetchOpts);

    if (res.status === 401 && !_retried) {
      const ok = await refreshAccessToken();
      if (ok) return request(path, { ...opts, _retried: true });
    }

    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }

    if (!res.ok) {
      const err = new Error((data && (data.error || data.detail)) || `Request failed (${res.status})`);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  return {
    getAccessToken, getRefreshToken, getUser, setSession, clearSession,
    request, refreshAccessToken,
    get: (path, query) => request(path, { method: "GET", query }),
    post: (path, json) => request(path, { method: "POST", json }),
    put: (path, json) => request(path, { method: "PUT", json }),
    patch: (path, json) => request(path, { method: "PATCH", json }),
    del: (path, json) => request(path, { method: "DELETE", json }),
    postForm: (path, form) => request(path, { method: "POST", form }),
  };
})();

function showToast(message, isError) {
  const root = document.getElementById("toast-root");
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " error" : "");
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}