// Spectre — pages ouvertes. When a tab finishes loading or becomes active, its address, title
// and visible text go to Spectre on this PC (POST /browser/page, with the key from Spectre's
// settings). Nothing leaves the PC; paused or excluded sites are never read.

const DEFAULTS = {
  server: "http://127.0.0.1:8765",
  token: "",
  paused: false,
  exclude: [
    "mail.google.com", "accounts.google.com", "passwords.google.com", "pay.google.com",
    "paypal.com", "outlook.live.com", "web.whatsapp.com", "messenger.com",
    "*.banque*", "*bank*", "*.credit-agricole.fr", "*.bnpparibas", "*.societegenerale.fr",
    "*.lcl.fr", "*.labanquepostale.fr", "*.caisse-epargne.fr", "*.boursorama.com",
    "impots.gouv.fr", "ameli.fr", "binance.com", "coinbase.com", "kraken.com",
  ].join("\n"),
};
const MAX_TEXT = 200000;
const lastSent = new Map(); // tabId -> url + length, so a page is not sent twice for nothing

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(Object.keys(DEFAULTS))) };
}

function excluded(url, patterns) {
  let host = "";
  try { host = new URL(url).hostname.toLowerCase(); } catch { return true; }
  return patterns.split("\n").map((p) => p.trim().toLowerCase()).filter(Boolean).some((p) => {
    if (!p.includes("*")) return host === p || host.endsWith(`.${p}`);
    const re = new RegExp(`^${p.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`);
    return re.test(host);
  });
}

function readPage() {
  // runs in the page: what a person sees, not scripts or hidden parts
  const text = (document.body ? document.body.innerText : "") || "";
  return { title: document.title || "", text, url: location.href };
}

async function send(tab, force = false) {
  const cfg = await settings();
  if (!tab || !tab.id || !tab.url || !/^https?:/.test(tab.url)) return { ok: false, result: "page non lisible" };
  if (!cfg.token) return { ok: false, result: "clé manquante : ouvre les options de l'extension" };
  if (!force && cfg.paused) return { ok: false, result: "en pause" };
  if (excluded(tab.url, cfg.exclude)) return { ok: false, result: "site exclu" };
  if (tab.url.startsWith(cfg.server.replace(/\/$/, ""))) return { ok: false, result: "c'est Spectre lui-même" };
  let page;
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: readPage });
    page = res && res.result;
  } catch (err) { return { ok: false, result: `lecture impossible : ${err.message}` }; }
  if (!page) return { ok: false, result: "page vide" };
  const mark = `${page.url}|${page.text.length}`;
  if (!force && lastSent.get(tab.id) === mark) return { ok: true, result: "déjà envoyée" };
  try {
    const r = await fetch(`${cfg.server.replace(/\/$/, "")}/browser/page`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.token}` },
      body: JSON.stringify({ url: page.url, title: page.title, text: page.text.slice(0, MAX_TEXT) }),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok) lastSent.set(tab.id, mark);
    chrome.action.setBadgeText({ tabId: tab.id, text: r.ok ? "✓" : "!" });
    chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: r.ok ? "#2e7d32" : "#c62828" });
    return { ok: r.ok, result: data.result || `HTTP ${r.status}` };
  } catch (err) {
    return { ok: false, result: `Spectre injoignable (${err.message})` };
  }
}

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === "complete" && tab.active) send(tab);
});
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  try { send(await chrome.tabs.get(tabId)); } catch { /* tab closed */ }
});
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "send-now") {
    chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => send(tab, true)).then(reply);
    return true; // async reply
  }
  return false;
});
chrome.runtime.onInstalled.addListener(async () => {
  const cfg = await chrome.storage.local.get(Object.keys(DEFAULTS));
  if (cfg.exclude === undefined) await chrome.storage.local.set({ exclude: DEFAULTS.exclude });
  if (!cfg.token) chrome.runtime.openOptionsPage();
});
