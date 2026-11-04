// Lets the on-set page open with no signal, once it has opened once with some. It only keeps the page's own three files: never the list, ticks or token, which stay in the page's own storage.
"use strict";
const CACHE = "on-set-1";
const FILES = ["on_set.html", "on_set.js", "on_set_logic.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || !/\/static\/on_set(\.html|\.js|_logic\.js)$/.test(url.pathname)) return;
  // The network first, so an update arrives as soon as there's signal, and the saved copy when there isn't.
  event.respondWith(
    fetch(event.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(url.pathname, copy)); }
      return res;
    }).catch(() => caches.match(url.pathname).then((hit) => hit || Response.error()))
  );
});
