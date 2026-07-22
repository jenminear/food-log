// Service worker — caches the app shell for offline load
const CACHE = 'food-log-v1'
const SHELL = ['/recipes/', '/recipes/index.html']

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', e => {
  // Only handle same-origin GET requests
  if (e.request.method !== 'GET') return
  const url = new URL(e.request.url)
  if (url.origin !== self.location.origin) return

  // API calls: network-only
  if (url.pathname.startsWith('/recipes/api/')) return

  // Everything else: network first, fall back to cache (app shell for nav)
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const copy = res.clone()
        caches.open(CACHE).then(c => c.put(e.request, copy))
        return res
      })
      .catch(() => caches.match(e.request).then(r => r || caches.match('/recipes/')))
  )
})
