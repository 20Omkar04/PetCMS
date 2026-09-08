/* Boots the app: if a session already exists, skip the landing page. */

(async function boot() {
  PetCMSApp.init();

  const token = PetAPI.getAccessToken();
  if (token) {
    try {
      await PetAPI.get("/api/users/me"); // validates the token (refreshes if needed)
      await PetCMSApp.enterApp();
      return;
    } catch (e) {
      PetAPI.clearSession();
    }
  }
  // otherwise stay on the landing page for login/register
})();
