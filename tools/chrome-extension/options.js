const FIELDS = ["server", "token", "paused", "exclude"];
const DEFAULT_SERVER = "http://127.0.0.1:8765";

async function load() {
  const cfg = await chrome.storage.local.get(FIELDS);
  document.getElementById("server").value = cfg.server || DEFAULT_SERVER;
  document.getElementById("token").value = cfg.token || "";
  document.getElementById("paused").checked = !!cfg.paused;
  if (cfg.exclude !== undefined) document.getElementById("exclude").value = cfg.exclude;
  else {
    // the defaults live in the service worker: ask it once by reading them from storage after install
    document.getElementById("exclude").value = "mail.google.com\naccounts.google.com\npasswords.google.com\npay.google.com\npaypal.com\n*bank*\n*.banque*\nimpots.gouv.fr\nameli.fr\nbinance.com\ncoinbase.com\nkraken.com";
  }
}

document.getElementById("save").addEventListener("click", async () => {
  const server = document.getElementById("server").value.trim() || DEFAULT_SERVER;
  await chrome.storage.local.set({
    server,
    token: document.getElementById("token").value.trim(),
    paused: document.getElementById("paused").checked,
    exclude: document.getElementById("exclude").value,
  });
  const state = document.getElementById("state");
  state.textContent = "Enregistré.";
  setTimeout(() => { state.textContent = ""; }, 2500);
});

load();
