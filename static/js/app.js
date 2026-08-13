// ---------- Écran de saisie du pseudo ----------
const pseudoOverlay = document.getElementById("pseudo-overlay");
const pseudoInput = document.getElementById("pseudo-input");
const pseudoSubmit = document.getElementById("pseudo-submit");
const pseudoError = document.getElementById("pseudo-error");
const appEl = document.getElementById("app");

// Mémorisation du pseudo par salon : permet de revenir sur le lien plus
// tard et de retrouver automatiquement ses données (avatar, historique...)
// sans avoir à retaper son pseudo.
const PSEUDO_STORAGE_KEY = `maksdiv_pseudo_${ROOM_CODE}`;
const savedPseudo = localStorage.getItem(PSEUDO_STORAGE_KEY);
let autoJoinAttempted = false;

function attemptJoin(pseudoOverride) {
    const pseudo = pseudoOverride || pseudoInput.value.trim();
    if (!pseudo) return;
    pseudoError.style.display = "none";
    socket.emit("join_room_event", { code: ROOM_CODE, pseudo });
}

pseudoSubmit.addEventListener("click", () => attemptJoin());
pseudoInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") attemptJoin();
});

// Si un pseudo est déjà enregistré pour ce salon précis, on tente de
// rejoindre directement, sans afficher l'écran de saisie.
if (savedPseudo) {
    pseudoInput.value = savedPseudo;
    autoJoinAttempted = true;
    attemptJoin(savedPseudo);
}

let heartbeatTimer = null;

socket.on("joined", (data) => {
    myPseudo = data.pseudo;
    localStorage.setItem(PSEUDO_STORAGE_KEY, myPseudo);
    pseudoOverlay.style.display = "none";
    appEl.style.display = "block";
    document.getElementById("my-pseudo-label").textContent = "👤 " + myPseudo;
    // Heartbeat régulier pour indiquer la présence
    // (on nettoie l'ancien timer pour éviter d'en empiler un nouveau à chaque reconnexion)
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    heartbeatTimer = setInterval(() => {
        socket.emit("heartbeat", { code: ROOM_CODE });
    }, 20000);
    loadConfessions();
    loadChatMessages();
});

socket.on("error_message", (data) => {
    // Si la reconnexion automatique échoue (ex: salon supprimé entre-temps),
    // on efface le pseudo mémorisé et on laisse l'écran de saisie normal.
    if (autoJoinAttempted) {
        localStorage.removeItem(PSEUDO_STORAGE_KEY);
        autoJoinAttempted = false;
    }
    pseudoError.textContent = data.message;
    pseudoError.style.display = "block";
    // Si l'erreur survient pendant une tentative de spin qui échoue (pas
    // assez de joueurs, pas son tour, etc.), on remet le bouton dans son
    // état correct (activé seulement si c'est vraiment le tour du joueur).
    if (typeof updateTurnUI === "function" && !roundInProgress) {
        updateTurnUI();
    }
});
