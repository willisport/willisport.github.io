/* Service Worker: schneller Start + Offline-Betrieb.
   - Seite (HTML):                 Netz zuerst (immer aktuell), sonst letzter Stand
   - CSS/JS mit ?v= in der URL:    Cache zuerst (die Version steckt in der URL)
   - Daten (data/*.json, auch von raw.githubusercontent.com): Netz zuerst, sonst letzter Stand -> Plan auch ohne Netz sichtbar
   - alles andere (Icons, GitHub-API ...): unveraendert / Stale-while-revalidate
   Ausschalten: Seite mit ?nosw=1 oeffnen. */

const CACHE = "willi-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

const isDataFile = (u) => /\/data\/[^/]+\.json$/.test(u.pathname);
const stripQuery = (href) => { const u = new URL(href); u.search = ""; return u.toString(); };

async function networkFirst(req, key) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(key, res.clone()).catch(() => {});
    return res;
  } catch (err) {
    const cached = await cache.match(key);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(req) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(req);
  if (cached) return cached;
  const res = await fetch(req);
  if (res && res.ok) cache.put(req, res.clone()).catch(() => {});
  return res;
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(req);
  const fresh = fetch(req).then(res => { if (res && res.ok) cache.put(req, res.clone()).catch(() => {}); return res; }).catch(() => null);
  return cached || (await fresh) || Response.error();
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  const rawData = url.hostname === "raw.githubusercontent.com" && isDataFile(url);
  if (!sameOrigin && !rawData) return;                                    // GitHub-API, CDN-Skripte usw. nicht anfassen
  if (rawData || isDataFile(url)) { event.respondWith(networkFirst(req, stripQuery(req.url))); return; }
  if (req.mode === "navigate" || url.pathname.endsWith("/") || url.pathname.endsWith(".html")) {
    event.respondWith(networkFirst(req, url.origin + url.pathname)); return;
  }
  if (url.search.includes("v=")) { event.respondWith(cacheFirst(req)); return; }
  event.respondWith(staleWhileRevalidate(req));
});
