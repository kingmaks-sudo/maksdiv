// ------------------------------------------------------------------
// Service Worker — MAKSDIV (Action ou Vérité)
// Objectif : rendre l'app installable/rapide, PAS de vrai mode hors-ligne
// jouable (c'est un jeu multijoueur temps réel, ça n'aurait pas de sens).
// ------------------------------------------------------------------

const CACHE_VERSION = "maksdiv-v1";
const STATIC_CACHE = `static-${CACHE_VERSION}`;

// Fichiers indispensables mis en cache dès l'installation.
const CORE_ASSETS = [
    "/static/css/style.css",
    "/static/js/app.js",
    "/static/js/pwa.js",
    "/static/manifest.json",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
    "/static/offline.html",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => cache.addAll(CORE_ASSETS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(
                keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k))
            ))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const req = event.request;
    const url = new URL(req.url);

    // Socket.IO et toutes les routes de données du jeu (confessions, chat,
    // avatars, preuves d'action, QR code...) : JAMAIS de cache, toujours le
    // réseau. Ce sont des données vivantes, les mettre en cache casserait le jeu.
    const isDynamic =
        url.pathname.startsWith("/socket.io/") ||
        url.pathname.includes("/confessions") ||
        url.pathname.includes("/messages") ||
        url.pathname.includes("/submit_action") ||
        url.pathname.includes("/set_avatar") ||
        url.pathname.includes("/qrcode") ||
        url.pathname.startsWith("/room/") ||
        url.pathname.startsWith("/create_room") ||
        url.pathname.startsWith("/join");

    if (isDynamic) {
        return; // laisse passer normalement, pas d'interception
    }

    // Fichiers statiques (css, js, icônes) : on sert le cache immédiatement
    // si dispo, tout en rafraîchissant le cache en arrière-plan.
    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(req).then((cached) => {
                const network = fetch(req)
                    .then((res) => {
                        caches.open(STATIC_CACHE).then((cache) => cache.put(req, res.clone()));
                        return res;
                    })
                    .catch(() => cached);
                return cached || network;
            })
        );
        return;
    }

    // Navigation vers une page (ex: ouverture de l'app) : réseau en priorité,
    // page "hors-ligne" en secours si pas de connexion.
    if (req.mode === "navigate") {
        event.respondWith(
            fetch(req).catch(() => caches.match("/static/offline.html"))
        );
    }
});
