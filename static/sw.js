// Enregistrement du service worker (rend l'app installable + un peu de cache).
// Servi depuis la racine (/sw.js) pour que sa portée (scope) couvre tout le site.
if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js").catch((err) => {
            console.warn("Échec d'enregistrement du service worker :", err);
        });
    });
}

// ---------- Bannière "Installer l'application" ----------
let deferredInstallPrompt = null;

function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

function isIos() {
    return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
}

function createInstallBanner(mode) {
    if (document.getElementById("pwa-install-banner")) return;
    if (isStandalone()) return;
    if (localStorage.getItem("pwa-install-dismissed") === "1") return;

    const banner = document.createElement("div");
    banner.id = "pwa-install-banner";
    banner.className = "pwa-install-banner";

    if (mode === "ios") {
        banner.innerHTML = `
            <span>📲 Installe MAKSDIV : appuie sur <strong>Partager</strong> puis <strong>« Sur l'écran d'accueil »</strong>.</span>
            <button id="pwa-install-close" aria-label="Fermer">✕</button>
        `;
    } else {
        banner.innerHTML = `
            <span>📲 Installe MAKSDIV sur ton appareil pour un accès plus rapide.</span>
            <button id="pwa-install-btn" class="pwa-install-btn">Installer</button>
            <button id="pwa-install-close" aria-label="Fermer">✕</button>
        `;
    }

    document.body.appendChild(banner);

    document.getElementById("pwa-install-close").addEventListener("click", () => {
        banner.remove();
        localStorage.setItem("pwa-install-dismissed", "1");
    });

    if (mode !== "ios") {
        document.getElementById("pwa-install-btn").addEventListener("click", async () => {
            if (!deferredInstallPrompt) return;
            deferredInstallPrompt.prompt();
            await deferredInstallPrompt.userChoice;
            deferredInstallPrompt = null;
            banner.remove();
        });
    }
}

// Chrome/Android (et la plupart des navigateurs basés Chromium) déclenchent
// cet événement quand l'app est installable.
window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    createInstallBanner("android");
});

window.addEventListener("appinstalled", () => {
    const banner = document.getElementById("pwa-install-banner");
    if (banner) banner.remove();
    localStorage.setItem("pwa-install-dismissed", "1");
});

// iOS Safari ne déclenche jamais "beforeinstallprompt" : on affiche des
// instructions manuelles après un court délai, si l'app n'est pas déjà installée.
if (isIos() && !isStandalone()) {
    window.addEventListener("load", () => {
        setTimeout(() => createInstallBanner("ios"), 2000);
    });
}
