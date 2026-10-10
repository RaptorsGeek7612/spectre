// Spectre service worker: caches the app shell so the UI opens instantly and installs as an app.
// API calls (/api/...) are never cached: runs, history and settings always come from the server.
const CACHE = "spectre-shell-v4";
const SHELL = [
  "./", "index.html", "app.css", "app.js", "demo.json", "favicon.svg", "logo.svg", "manifest.webmanifest",
  "fonts/fonts.css", "icons/icon-192.png",
];

const LAUNCHER = "/lanceur/";
// Shown on the phone when nothing answers at all: the PC sleeps, is off, or the network is down.
const OFFLINE = `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#121315">
<title>Spectre · PC injoignable</title><style>
body{margin:0;min-height:100dvh;display:grid;place-items:center;padding:24px 16px;background:#121315;color:#e9e4d8;font:16px/1.5 "Segoe UI",system-ui,sans-serif}
main{width:min(420px,100%);display:grid;gap:14px;padding:28px 22px;border:1px solid #4a4c52;background:#1b1c1f}
h1{margin:0;font-weight:500;font-size:1.9rem;letter-spacing:.32em;text-transform:uppercase}
p{margin:0;color:#8f8a7f} b{color:#ef5f6f;font-weight:500} li{color:#b3aea2}
button{min-height:52px;border:1px solid #4fc3f7;background:none;color:#e9e4d8;font:inherit;letter-spacing:.2em;text-transform:uppercase}
</style></head><body><main><h1>Spectre</h1><p><b>Le PC ne répond pas.</b></p>
<ul><li>il est en veille ou éteint (sur batterie, il peut s'endormir) ;</li>
<li>il n'a plus de réseau ;</li><li>Tailscale est coupé sur ce téléphone.</li></ul>
<p>Rallume ou branche le PC, vérifie Tailscale, puis réessaie.</p>
<button onclick="location.reload()">Réessayer</button></main></body></html>`;
const offline = () => new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  const remote = url.hostname !== "127.0.0.1" && url.hostname !== "localhost";
  if (event.request.mode === "navigate" && remote) {
    // From the phone: Spectre closed on the PC -> Tailscale answers 502: go to the launcher,
    // which stays on and can start it again. Nothing answers at all -> the PC sleeps or is off.
    const toLauncher = !url.pathname.startsWith(LAUNCHER);
    event.respondWith(
      fetch(event.request)
        .then((response) => (toLauncher && response.status >= 502 ? Response.redirect(LAUNCHER, 302) : response))
        .catch(offline),
    );
    return;
  }
  if (url.pathname.startsWith(LAUNCHER)) return;
  // Network first (fresh after an upgrade), cache as offline fallback.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("index.html"))),
  );
});
