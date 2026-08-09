// Enregistrement du service worker (rend l'app installable + un peu de cache).
// Servi depuis la racine (/sw.js) pour que sa portée (scope) couvre tout le site.
if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/sw.js").catch((err) => {
            console.warn("Échec d'enregistrement du service worker :", err);
        });
    });
}
