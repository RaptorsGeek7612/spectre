// Spectre service worker: caches the app shell so the UI opens instantly and installs as an app.
// API calls (/api/...) are never cached: runs, history and settings always come from the server.
const CACHE = "spectre-shell-v3";
const SHELL = [
  "./", "index.html", "app.css", "app.js", "demo.json", "favicon.svg", "logo.svg", "manifest.webmanifest",
  "fonts/fonts.css", "icons/icon-192.png",
];

const LAUNCHER = "/lanceur/";

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
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith(LAUNCHER)) return;
  if (event.request.mode === "navigate" && url.hostname !== "127.0.0.1" && url.hostname !== "localhost") {
    // From the phone: when Spectre is closed on the PC, Tailscale answers 502 (or nothing).
    // Go to the launcher, which stays on and can start Spectre again.
    event.respondWith(
      fetch(event.request)
        .then((response) => (response.status >= 502 ? Response.redirect(LAUNCHER, 302) : response))
        .catch(() => Response.redirect(LAUNCHER, 302)),
    );
    return;
  }
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
