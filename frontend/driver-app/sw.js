const CACHE_NAME = "fieldnote-driver-v25";
const APP_SHELL = [
    "/",
    "/static/driver-app/css/style.css",
    "/static/driver-app/js/app.js",
    "/static/driver-app/js/state.js",
    "/static/driver-app/js/storage.js",
    "/static/driver-app/js/api.js",
    "/static/driver-app/js/views.js",
    "/static/driver-app/js/components/navigation.js",
    "/static/driver-app/js/components/routes.js",
    "/static/driver-app/js/components/dashboard.js",
    "/static/driver-app/js/components/earnings.js",
    "/static/driver-app/js/components/deliveries.js",
    "/static/driver-app/js/components/activity.js",
    "/static/driver-app/js/components/profile.js",
    "/static/driver-app/js/components/scanner.js",
    "/static/driver-app/js/components/pod.js",
    "/static/driver-app/js/services/driver-events.js",
    "/static/driver-app/js/services/account.js"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(APP_SHELL.map((path) => new Request(path, { cache: "reload" }))))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);
    if (request.method !== "GET" || url.origin !== self.location.origin) return;

    if (request.mode === "navigate") {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response.ok) {
                        const copy = response.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put("/", copy));
                    }
                    return response;
                })
                .catch(async () => (await caches.match("/")) || Response.error())
        );
        return;
    }

    if (APP_SHELL.includes(url.pathname)) {
        event.respondWith(
            caches.match(request).then((cached) => {
                const update = fetch(request).then((response) => {
                    if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put(request, response.clone()));
                    return response;
                });
                return cached || update;
            })
        );
    }
});
