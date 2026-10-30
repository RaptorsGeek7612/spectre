const state = document.getElementById("state");
const pause = document.getElementById("pause");

async function refresh() {
  const { paused } = await chrome.storage.local.get("paused");
  pause.textContent = paused ? "Reprendre l'envoi automatique" : "Mettre en pause";
  state.textContent = paused ? "En pause : rien n'est envoyé tout seul." : "Les pages que tu ouvres sont envoyées à Spectre.";
}

document.getElementById("send").addEventListener("click", async () => {
  state.textContent = "Envoi…";
  const res = await chrome.runtime.sendMessage({ type: "send-now" });
  state.textContent = res ? res.result : "pas de réponse";
});
pause.addEventListener("click", async () => {
  const { paused } = await chrome.storage.local.get("paused");
  await chrome.storage.local.set({ paused: !paused });
  refresh();
});
document.getElementById("options").addEventListener("click", () => chrome.runtime.openOptionsPage());

refresh();
