/* Landing page: login / register tabs + API key onboarding step */

(function () {
  const tabs = document.querySelectorAll(".auth-tab");
  const loginForm = document.getElementById("login-form");
  const registerForm = document.getElementById("register-form");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const which = tab.dataset.tab;
      loginForm.classList.toggle("hidden", which !== "login");
      registerForm.classList.toggle("hidden", which !== "register");
    });
  });

  function setBusy(form, busy) {
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = busy;
    const label = btn.querySelector(".btn-label");
    if (label) label.innerHTML = busy ? '<span class="spinner"></span>' : label.dataset.text || label.textContent;
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("login-error");
    errorEl.textContent = "";
    const email = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    setBusy(loginForm, true);
    try {
      const data = await PetAPI.post("/api/auth/login", { email, password });
      PetAPI.setSession(data.user, data.access_token, data.refresh_token);
      await window.PetCMSApp.enterApp();
    } catch (err) {
      errorEl.textContent = err.message || "Could not log in.";
    } finally {
      setBusy(loginForm, false);
    }
  });

  registerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("register-error");
    errorEl.textContent = "";
    const email = document.getElementById("reg-username").value.trim();
    const password = document.getElementById("reg-password").value;
    setBusy(registerForm, true);
    try {
      const data = await PetAPI.post("/api/auth/register", { email, password });
      if (!data.access_token) {
        errorEl.textContent = "Account created — check your email to confirm before logging in.";
        setBusy(registerForm, false);
        return;
      }
      PetAPI.setSession(data.user, data.access_token, data.refresh_token);
      goToStep(2);
    } catch (err) {
      errorEl.textContent = err.message || "Could not create account.";
    } finally {
      setBusy(registerForm, false);
    }
  });

  function goToStep(n) {
    document.getElementById("onboard-step-auth").classList.toggle("active", n === 1);
    document.getElementById("onboard-step-key").classList.toggle("active", n === 2);
    document.getElementById("dot-1").classList.toggle("active", n === 1);
    document.getElementById("dot-2").classList.toggle("active", n === 2);
  }

  const onboardKeyForm = document.getElementById("onboard-key-form");
  onboardKeyForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("onboard-error");
    errorEl.textContent = "";
    const provider = document.getElementById("onboard-provider").value;
    const api_key = document.getElementById("onboard-key").value.trim();
    if (!api_key) { await window.PetCMSApp.enterApp(); return; }
    try {
      await PetAPI.put("/api/users/me/api-key", { provider, api_key });
      showToast("API key saved.");
      await window.PetCMSApp.enterApp();
    } catch (err) {
      errorEl.textContent = err.message || "Could not save API key.";
    }
  });

  document.getElementById("onboard-skip").addEventListener("click", async () => {
    await window.PetCMSApp.enterApp();
  });

  window.PetCMSAuth = { goToStep };
})();