// ------------------------------------------------------------------
// Client Socket.IO — salon "Action ou Vérité"
// ------------------------------------------------------------------

const socket = io();
let myPseudo = null;
let currentRotation = 0;

// ---------- Écran de saisie du pseudo ----------
const pseudoOverlay = document.getElementById("pseudo-overlay");
const pseudoInput = document.getElementById("pseudo-input");
const pseudoSubmit = document.getElementById("pseudo-submit");
const pseudoError = document.getElementById("pseudo-error");
const appEl = document.getElementById("app");

function attemptJoin() {
    const pseudo = pseudoInput.value.trim();
    if (!pseudo) return;
    socket.emit("join_room_event", { code: ROOM_CODE, pseudo });
}

pseudoSubmit.addEventListener("click", attemptJoin);
pseudoInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") attemptJoin();
});

let heartbeatTimer = null;

socket.on("joined", (data) => {
    myPseudo = data.pseudo;
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
});

socket.on("error_message", (data) => {
    pseudoError.textContent = data.message;
    pseudoError.style.display = "block";
});

// ---------- Reconnexion automatique ----------
// Après une coupure réseau (ex: mise en veille du serveur Render), Socket.IO
// se reconnecte avec un NOUVEAU sid côté serveur. Il faut donc rejouer
// explicitement "join_room_event" pour que le serveur remette le client
// dans la room et dans la liste des joueurs.
socket.on("connect", () => {
    if (myPseudo) {
        socket.emit("join_room_event", { code: ROOM_CODE, pseudo: myPseudo });
    }
});

socket.io.on("reconnect_attempt", () => {
    if (myPseudo) {
        console.log("Reconnexion en cours...");
    }
});

// ---------- Navigation par onglets ----------
document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(btn.dataset.tab).classList.add("active");
    });
});

// ---------- Onglet 1 : Bouteille ----------
const bottleEl = document.getElementById("bottle");
const spinBtn = document.getElementById("spin-btn");
const spinResult = document.getElementById("spin-result");
const choiceZone = document.getElementById("choice-zone");
const questionCard = document.getElementById("question-card");

spinBtn.addEventListener("click", () => {
    spinBtn.disabled = true;
    questionCard.style.display = "none";
    choiceZone.style.display = "none";
    socket.emit("spin_bottle", { code: ROOM_CODE });
});

socket.on("bottle_result", (data) => {
    currentRotation += data.rotation;
    bottleEl.style.transform = `rotate(${currentRotation}deg)`;
    setTimeout(() => {
        spinResult.textContent = `🎯 ${data.chosen_pseudo} a été désigné(e) !`;
        spinBtn.disabled = false;
        if (data.chosen_pseudo === myPseudo) {
            choiceZone.style.display = "block";
        }
    }, 3600);
});

document.getElementById("btn-action").addEventListener("click", () => makeChoice("action"));
document.getElementById("btn-verite").addEventListener("click", () => makeChoice("verite"));

function makeChoice(choice) {
    const intensity = document.querySelector('input[name="intensity"]:checked').value;
    socket.emit("make_choice", { code: ROOM_CODE, choice, intensity, pseudo: myPseudo });
    choiceZone.style.display = "none";
}

socket.on("question_drawn", (data) => {
    const label = data.category === "action" ? "🎬 Action" : "🗣️ Vérité";
    const intensityLabel = { leger: "Léger", ose: "Osé", tres_ose: "Très osé" }[data.intensity];
    questionCard.innerHTML = `
        <strong>${label}</strong> — ${data.chosen_by}
        <p style="margin:14px 0 0;">${escapeHtml(data.text)}</p>
        <span class="q-meta">Niveau : ${intensityLabel}</span>
    `;
    questionCard.style.display = "block";
});

// ---------- Onglet 2 : Confessions ----------
const confessInput = document.getElementById("confess-input");
const confessAnon = document.getElementById("confess-anon");
const confessSubmit = document.getElementById("confess-submit");
const confessList = document.getElementById("confess-list");

confessSubmit.addEventListener("click", () => {
    const message = confessInput.value.trim();
    if (!message) return;
    socket.emit("post_confession", {
        code: ROOM_CODE,
        pseudo: myPseudo,
        message,
        anonymous: confessAnon.checked,
    });
    confessInput.value = "";
});

socket.on("new_confession", (data) => {
    prependConfession(data.pseudo, data.message, data.created_at);
});

function prependConfession(pseudo, message, time) {
    const item = document.createElement("div");
    item.className = "confess-item";
    item.innerHTML = `
        <div class="c-header">
            <span class="c-pseudo">${escapeHtml(pseudo)}</span>
            <span>${time || ""}</span>
        </div>
        <div class="c-body">${escapeHtml(message)}</div>
    `;
    confessList.prepend(item);
}

function loadConfessions() {
    fetch(`/room/${ROOM_CODE}/confessions`)
        .then((r) => r.json())
        .then((rows) => {
            confessList.innerHTML = "";
            rows.forEach((row) => {
                const displayName = row.anonymous ? "Anonyme" : row.pseudo;
                const time = new Date(row.created_at + "Z").toLocaleTimeString("fr-FR", {
                    hour: "2-digit",
                    minute: "2-digit",
                });
                prependConfession(displayName, row.message, time);
            });
        });
}

// ---------- Onglet 3 : Présence ----------
const presenceList = document.getElementById("presence-list");

socket.on("presence_update", (data) => {
    presenceList.innerHTML = "";
    data.players.forEach((p) => {
        const li = document.createElement("li");
        li.innerHTML = `<span class="status-dot ${p.status === "inactif" ? "inactif" : ""}"></span> ${escapeHtml(p.pseudo)}`;
        presenceList.appendChild(li);
    });
});

socket.on("system_message", (data) => {
    console.log(data.message);
});

// ---------- Onglet 4 : Invitation ----------
document.getElementById("copy-link-btn").addEventListener("click", () => {
    const input = document.getElementById("invite-link");
    input.select();
    navigator.clipboard.writeText(input.value).then(() => {
        const btn = document.getElementById("copy-link-btn");
        const original = btn.textContent;
        btn.textContent = "Copié !";
        setTimeout(() => (btn.textContent = original), 1500);
    });
});

// ---------- Utilitaire ----------
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
