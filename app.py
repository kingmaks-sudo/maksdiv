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
    loadChatMessages();
});

socket.on("error_message", (data) => {
    pseudoError.textContent = data.message;
    pseudoError.style.display = "block";
    // Si l'erreur survient pendant une tentative de spin qui échoue (pas
    // assez de joueurs, pas son tour, etc.), on remet le bouton dans son
    // état correct (activé seulement si c'est vraiment le tour du joueur).
    if (typeof updateTurnUI === "function" && !roundInProgress) {
        updateTurnUI();
    }
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
const bottleContainer = document.querySelector(".bottle-container");
const spinBtn = document.getElementById("spin-btn");
const spinResult = document.getElementById("spin-result");
const turnIndicator = document.getElementById("turn-indicator");
const choiceZone = document.getElementById("choice-zone");
const questionCard = document.getElementById("question-card");
const roundActionZone = document.getElementById("round-action-zone");
const roundWaitingZone = document.getElementById("round-waiting-zone");
const roundResultZone = document.getElementById("round-result-zone");

const ACTION_MAX_DURATION_MS = 60000; // 1 minute max pour la vidéo d'action
const BOTTLE_SPIN_DURATION_MS = 4000; // doit correspondre à la durée de transition CSS (.bottle)

let roundInProgress = false; // true dès qu'une question est tirée, jusqu'à round_result/round_cancelled
let currentTurnPseudo = null; // pseudo du joueur dont c'est le tour de lancer la bouteille
let mediaStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let capturedBlob = null;
let recordCountdownHandle = null;
let recordTimeoutHandle = null;

// Recalcule l'état du bouton "Tourner" + le message au-dessus, à chaque
// changement de tour ou de manche en cours.
function updateTurnUI() {
    if (roundInProgress) {
        // Une manche (choix/réponse/action) est en cours : le tour de spin
        // reste affiché mais le bouton est de toute façon désactivé ailleurs.
        return;
    }
    if (!currentTurnPseudo) {
        turnIndicator.textContent = "";
        spinBtn.disabled = false;
        return;
    }
    if (currentTurnPseudo === myPseudo) {
        turnIndicator.textContent = "🎯 C'est ton tour de lancer la bouteille !";
        turnIndicator.classList.add("my-turn");
        spinBtn.disabled = false;
    } else {
        turnIndicator.textContent = `⏳ C'est au tour de ${currentTurnPseudo} de lancer la bouteille.`;
        turnIndicator.classList.remove("my-turn");
        spinBtn.disabled = true;
    }
}

socket.on("turn_update", (data) => {
    currentTurnPseudo = data.pseudo;
    updateTurnUI();
});

spinBtn.addEventListener("click", () => {
    spinBtn.disabled = true;
    questionCard.style.display = "none";
    choiceZone.style.display = "none";
    roundResultZone.style.display = "none";
    socket.emit("spin_bottle", { code: ROOM_CODE });
});

socket.on("bottle_result", (data) => {
    currentRotation += data.rotation;
    bottleEl.style.transform = `rotate(${currentRotation}deg)`;
    bottleContainer.classList.add("spinning");
    setTimeout(() => {
        bottleContainer.classList.remove("spinning");
        spinResult.textContent = `🎯 ${data.chosen_pseudo} a été désigné(e) !`;
        if (data.chosen_pseudo === myPseudo) {
            choiceZone.style.display = "block";
        }
        // Le bouton reste désactivé : la manche (choix + réponse/preuve)
        // doit se terminer avant de pouvoir relancer la bouteille.
    }, BOTTLE_SPIN_DURATION_MS);
});

document.getElementById("btn-action").addEventListener("click", () => makeChoice("action"));
document.getElementById("btn-verite").addEventListener("click", () => makeChoice("verite"));


function makeChoice(choice) {
    const intensity = document.querySelector('input[name="intensity"]:checked').value;
    socket.emit("make_choice", { code: ROOM_CODE, choice, intensity, pseudo: myPseudo });
    choiceZone.style.display = "none";
}

// ----- Une question est tirée : la manche commence et bloque la bouteille -----
socket.on("question_drawn", (data) => {
    stopCamera();
    roundInProgress = true;
    spinBtn.disabled = true;
    roundResultZone.style.display = "none";

    const label = data.category === "action" ? "🎬 Action" : "🗣️ Vérité";
    const intensityLabel = { leger: "Léger", ose: "Osé", tres_ose: "Très osé" }[data.intensity];
    questionCard.innerHTML = `
        <strong>${label}</strong> — ${escapeHtml(data.chosen_by)}
        <p style="margin:14px 0 0;">${escapeHtml(data.text)}</p>
        <span class="q-meta">Niveau : ${intensityLabel}</span>
    `;
    questionCard.style.display = "block";

    if (data.chosen_by === myPseudo) {
        roundWaitingZone.style.display = "none";
        if (data.category === "verite") {
            renderTruthForm();
        } else {
            renderActionCapture();
        }
    } else {
        roundActionZone.style.display = "none";
        roundActionZone.innerHTML = "";
        roundWaitingZone.style.display = "block";
        const verb = data.category === "verite" ? "réponde" : "envoie sa photo/vidéo";
        roundWaitingZone.innerHTML = `<p class="waiting-msg">⏳ En attente que <strong>${escapeHtml(data.chosen_by)}</strong> ${verb}...</p>`;
    }
});

// ----- Vérité : réponse obligatoire, envoyée à tout le salon -----
function renderTruthForm() {
    roundActionZone.style.display = "block";
    roundActionZone.innerHTML = `
        <p class="round-instructions">C'est ton tour : réponds en vérité. Le jeu reste bloqué pour tout le monde jusqu'à ton envoi.</p>
        <textarea id="truth-answer-input" maxlength="800" placeholder="Écris ta réponse ici..."></textarea>
        <button id="truth-answer-submit" class="btn-primary">Envoyer ma réponse</button>
        <p id="truth-answer-error" class="alert-error" style="display:none;"></p>
    `;
    document.getElementById("truth-answer-submit").addEventListener("click", () => {
        const input = document.getElementById("truth-answer-input");
        const answer = input.value.trim();
        const errEl = document.getElementById("truth-answer-error");
        if (!answer) {
            errEl.textContent = "La réponse ne peut pas être vide.";
            errEl.style.display = "block";
            return;
        }
        document.getElementById("truth-answer-submit").disabled = true;
        socket.emit("submit_truth_answer", { code: ROOM_CODE, answer });
    });
}

// ----- Action : caméra activée jusqu'à capture d'une photo ou vidéo (≤ 1 min) -----
function renderActionCapture() {
    roundActionZone.style.display = "block";
    roundActionZone.innerHTML = `
        <p class="round-instructions">C'est ton tour : réalise l'action, puis filme-la ou prends une photo (vidéo limitée à 1 minute). Le jeu reste bloqué pour tout le monde jusqu'à ton envoi.</p>
        <video id="camera-preview" autoplay playsinline muted></video>
        <div class="camera-controls" id="camera-controls">
            <button id="camera-start-btn" class="btn-primary">🎥 Activer la caméra</button>
        </div>
        <p id="action-error" class="alert-error" style="display:none;"></p>
    `;
    document.getElementById("camera-start-btn").addEventListener("click", startCamera);
}

async function startCamera() {
    const errEl = document.getElementById("action-error");
    const preview = document.getElementById("camera-preview");
    const controls = document.getElementById("camera-controls");
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    } catch (e) {
        errEl.textContent = "Impossible d'accéder à la caméra : " + e.message;
        errEl.style.display = "block";
        return;
    }
    preview.srcObject = mediaStream;
    controls.innerHTML = `
        <button id="photo-btn" class="btn-secondary">📸 Prendre une photo</button>
        <button id="record-btn" class="btn-primary">⏺️ Filmer (max 1 min)</button>
    `;
    document.getElementById("photo-btn").addEventListener("click", capturePhoto);
    document.getElementById("record-btn").addEventListener("click", startRecording);
}

function capturePhoto() {
    const preview = document.getElementById("camera-preview");
    const canvas = document.createElement("canvas");
    canvas.width = preview.videoWidth;
    canvas.height = preview.videoHeight;
    canvas.getContext("2d").drawImage(preview, 0, 0);
    canvas.toBlob((blob) => {
        capturedBlob = blob;
        finishCapture("image/jpeg");
    }, "image/jpeg", 0.9);
}

function startRecording() {
    recordedChunks = [];
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
        ? "video/webm;codecs=vp9" : "video/webm";
    mediaRecorder = new MediaRecorder(mediaStream, { mimeType });
    mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
    mediaRecorder.onstop = () => {
        capturedBlob = new Blob(recordedChunks, { type: mimeType });
        finishCapture(mimeType);
    };
    mediaRecorder.start();

    let remaining = 60;
    const controls = document.getElementById("camera-controls");
    controls.innerHTML = `<button id="stop-record-btn" class="btn-secondary">⏹️ Arrêter (<span id="record-countdown">${remaining}</span>s)</button>`;
    document.getElementById("stop-record-btn").addEventListener("click", stopRecording);

    recordCountdownHandle = setInterval(() => {
        remaining -= 1;
        const el = document.getElementById("record-countdown");
        if (el) el.textContent = remaining;
        if (remaining <= 0) stopRecording();
    }, 1000);
    recordTimeoutHandle = setTimeout(stopRecording, ACTION_MAX_DURATION_MS);
}

function stopRecording() {
    clearInterval(recordCountdownHandle);
    clearTimeout(recordTimeoutHandle);
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }
}

function finishCapture(mimeType) {
    stopCamera();
    const isVideo = mimeType.startsWith("video");
    roundActionZone.innerHTML = `
        <p class="round-instructions">Aperçu de ta preuve :</p>
        ${isVideo
            ? `<video src="${URL.createObjectURL(capturedBlob)}" controls style="max-width:100%;border-radius:10px;"></video>`
            : `<img src="${URL.createObjectURL(capturedBlob)}" style="max-width:100%;border-radius:10px;">`}
        <div class="camera-controls">
            <button id="action-retry-btn" class="btn-secondary">🔁 Recommencer</button>
            <button id="action-send-btn" class="btn-primary">✅ Envoyer</button>
        </div>
        <p id="action-error" class="alert-error" style="display:none;"></p>
    `;
    document.getElementById("action-retry-btn").addEventListener("click", renderActionCapture);
    document.getElementById("action-send-btn").addEventListener("click", sendActionProof);
}

function sendActionProof() {
    const sendBtn = document.getElementById("action-send-btn");
    const errEl = document.getElementById("action-error");
    sendBtn.disabled = true;
    const ext = capturedBlob.type.includes("video") ? "webm" : "jpg";
    const formData = new FormData();
    formData.append("pseudo", myPseudo);
    formData.append("media", capturedBlob, `proof.${ext}`);

    fetch(`/room/${ROOM_CODE}/submit_action`, { method: "POST", body: formData })
        .then((r) => r.json())
        .then((res) => {
            if (!res.ok) {
                errEl.textContent = res.error || "Erreur lors de l'envoi.";
                errEl.style.display = "block";
                sendBtn.disabled = false;
            }
            // Si ok, le serveur diffuse "round_result" qui nettoie l'UI pour tout le monde.
        })
        .catch(() => {
            errEl.textContent = "Erreur réseau lors de l'envoi.";
            errEl.style.display = "block";
            sendBtn.disabled = false;
        });
}

function stopCamera() {
    clearInterval(recordCountdownHandle);
    clearTimeout(recordTimeoutHandle);
    if (mediaStream) {
        mediaStream.getTracks().forEach((t) => t.stop());
        mediaStream = null;
    }
    mediaRecorder = null;
}

// ----- Fin de manche (vérité ou action) : résultat diffusé à tout le monde -----
socket.on("round_result", (data) => {
    stopCamera();
    roundInProgress = false;
    roundActionZone.style.display = "none";
    roundActionZone.innerHTML = "";
    roundWaitingZone.style.display = "none";
    questionCard.style.display = "none";

    const label = data.type === "verite" ? "🗣️ Vérité" : "🎬 Action";
    let bodyHtml;
    if (data.type === "verite") {
        bodyHtml = `<p class="truth-answer">💬 ${escapeHtml(data.answer)}</p>`;
    } else {
        bodyHtml = data.media_kind === "video"
            ? `<video src="${data.media_url}" controls style="max-width:100%;border-radius:10px;margin-top:10px;"></video>`
            : `<img src="${data.media_url}" style="max-width:100%;border-radius:10px;margin-top:10px;">`;
    }
    roundResultZone.innerHTML = `
        <strong>${label}</strong> — ${escapeHtml(data.pseudo)}
        <p style="margin:10px 0 0;">${escapeHtml(data.question)}</p>
        ${bodyHtml}
    `;
    roundResultZone.style.display = "block";
    spinResult.textContent = "";
    updateTurnUI();
});

// ----- Le joueur désigné a quitté avant de terminer : on débloque -----
socket.on("round_cancelled", (data) => {
    stopCamera();
    roundInProgress = false;
    roundActionZone.style.display = "none";
    roundActionZone.innerHTML = "";
    roundWaitingZone.style.display = "none";
    questionCard.style.display = "none";
    spinResult.textContent = `⚠️ ${data.message}`;
    updateTurnUI();
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
    appendConfession(data.id, data.pseudo, data.message, data.created_at, []);
    scrollConfessionsToBottom();
});

socket.on("new_comment", (data) => {
    appendComment(data.confession_id, data.pseudo, data.message, data.created_at);
    scrollConfessionsToBottom();
});

// Ajoute une confession EN BAS de la liste (les plus récentes apparaissent
// en dernier, comme un fil de discussion classique).
function appendConfession(id, pseudo, message, time, comments) {
    const item = document.createElement("div");
    item.className = "confess-item";
    item.dataset.confessionId = id;
    item.innerHTML = `
        <div class="c-header">
            <span class="c-pseudo">${escapeHtml(pseudo)}</span>
            <span>${time || ""}</span>
        </div>
        <div class="c-body">${escapeHtml(message)}</div>
        <div class="c-actions">
            <button class="c-action-btn c-mention-btn" title="Mentionner cette personne">🔗 Mentionner</button>
            <button class="c-action-btn c-comment-toggle-btn" title="Commenter">💬 Commenter</button>
        </div>
        <div class="c-comments"></div>
        <div class="c-comment-form" style="display:none;">
            <input type="text" class="c-comment-input" maxlength="300" placeholder="Écris un commentaire...">
            <button class="btn-secondary c-comment-send-btn">Envoyer</button>
        </div>
    `;

    item.querySelector(".c-mention-btn").addEventListener("click", () => {
        mentionConfession(pseudo);
    });

    const toggleBtn = item.querySelector(".c-comment-toggle-btn");
    const form = item.querySelector(".c-comment-form");
    toggleBtn.addEventListener("click", () => {
        form.style.display = form.style.display === "none" ? "flex" : "none";
        if (form.style.display === "flex") form.querySelector(".c-comment-input").focus();
    });

    const sendCommentBtn = item.querySelector(".c-comment-send-btn");
    const commentInput = item.querySelector(".c-comment-input");
    const sendComment = () => {
        const message2 = commentInput.value.trim();
        if (!message2) return;
        socket.emit("post_comment", {
            code: ROOM_CODE,
            confession_id: id,
            pseudo: myPseudo,
            message: message2,
        });
        commentInput.value = "";
    };
    sendCommentBtn.addEventListener("click", sendComment);
    commentInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendComment();
    });

    confessList.appendChild(item);

    (comments || []).forEach((c) => {
        const ctime = new Date(c.created_at + "Z").toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
        appendComment(id, c.pseudo, c.message, ctime);
    });
}

// Insère une référence "@pseudo" dans le champ de saisie principal, pour
// écrire une nouvelle confession qui mentionne cette personne.
function mentionConfession(pseudo) {
    document.querySelector('.tab-btn[data-tab="tab-confess"]').click();
    const prefix = `@${pseudo} `;
    if (!confessInput.value.startsWith(prefix)) {
        confessInput.value = prefix + confessInput.value;
    }
    confessInput.focus();
    confessInput.setSelectionRange(confessInput.value.length, confessInput.value.length);
}

function appendComment(confessionId, pseudo, message, time) {
    const parent = confessList.querySelector(`.confess-item[data-confession-id="${confessionId}"] .c-comments`);
    if (!parent) return;
    const item = document.createElement("div");
    item.className = "c-comment-item";
    item.innerHTML = `
        <span class="c-comment-pseudo">${escapeHtml(pseudo)}</span>
        <span class="c-comment-body">${escapeHtml(message)}</span>
        <span class="c-comment-time">${time || ""}</span>
    `;
    parent.appendChild(item);
}

function scrollConfessionsToBottom() {
    confessList.scrollTop = confessList.scrollHeight;
}

function loadConfessions() {
    fetch(`/room/${ROOM_CODE}/confessions`)
        .then((r) => r.json())
        .then((rows) => {
            confessList.innerHTML = "";
            // Le serveur renvoie déjà les confessions triées du plus ancien
            // au plus récent (avec leurs commentaires imbriqués).
            rows.forEach((row) => {
                const displayName = row.anonymous ? "Anonyme" : row.pseudo;
                const time = new Date(row.created_at + "Z").toLocaleTimeString("fr-FR", {
                    hour: "2-digit",
                    minute: "2-digit",
                });
                appendConfession(row.id, displayName, row.message, time, row.comments);
            });
            scrollConfessionsToBottom();
        });
}

// ---------- Onglet 3 : Discussion instantanée ----------
const chatList = document.getElementById("chat-list");
const chatInput = document.getElementById("chat-input");
const chatSubmit = document.getElementById("chat-submit");

function sendChatMessage() {
    const message = chatInput.value.trim();
    if (!message) return;
    socket.emit("send_chat_message", { code: ROOM_CODE, message });
    chatInput.value = "";
}

chatSubmit.addEventListener("click", sendChatMessage);
chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendChatMessage();
});

socket.on("new_chat_message", (data) => {
    appendChatMessage(data.pseudo, data.avatar_url, data.message, data.created_at);
    scrollChatToBottom();
});

function appendChatMessage(pseudo, avatarUrl, message, time) {
    const mine = pseudo === myPseudo;
    const item = document.createElement("div");
    item.className = "chat-msg" + (mine ? " chat-msg-mine" : "");
    item.innerHTML = `
        <div class="chat-avatar">${avatarUrl ? `<img src="${avatarUrl}" alt="">` : escapeHtml(initials(pseudo))}</div>
        <div class="chat-bubble">
            ${mine ? "" : `<div class="chat-pseudo">${escapeHtml(pseudo)}</div>`}
            <div class="chat-text">${escapeHtml(message)}</div>
            <div class="chat-time">${time || ""}</div>
        </div>
    `;
    chatList.appendChild(item);
}

function initials(pseudo) {
    return (pseudo || "?").trim().charAt(0).toUpperCase();
}

function scrollChatToBottom() {
    chatList.scrollTop = chatList.scrollHeight;
}

function loadChatMessages() {
    fetch(`/room/${ROOM_CODE}/messages`)
        .then((r) => r.json())
        .then((rows) => {
            chatList.innerHTML = "";
            rows.forEach((row) => {
                const time = new Date(row.created_at + "Z").toLocaleTimeString("fr-FR", {
                    hour: "2-digit",
                    minute: "2-digit",
                });
                appendChatMessage(row.pseudo, row.avatar_url, row.message, time);
            });
            scrollChatToBottom();
        });
}

// ---------- Onglet 3 : Présence ----------
const presenceList = document.getElementById("presence-list");

socket.on("presence_update", (data) => {
    presenceList.innerHTML = "";
    data.players.forEach((p) => {
        const li = document.createElement("li");
        li.innerHTML = `
            <span class="status-dot ${p.status === "inactif" ? "inactif" : ""}"></span>
            <span class="presence-avatar">${p.avatar_url ? `<img src="${p.avatar_url}" alt="">` : escapeHtml(initials(p.pseudo))}</span>
            ${escapeHtml(p.pseudo)}
        `;
        presenceList.appendChild(li);
    });

    // Met à jour mon propre aperçu si mon avatar a changé (ex: après upload).
    const me = data.players.find((p) => p.pseudo === myPseudo);
    if (me) setMyAvatarPreview(me.avatar_url);
});

socket.on("system_message", (data) => {
    console.log(data.message);
});

// ---------- Onglet 4 (Présence) : photo de profil ----------
const avatarInput = document.getElementById("avatar-input");
const avatarPreview = document.getElementById("my-avatar-preview");
const avatarError = document.getElementById("avatar-error");

function setMyAvatarPreview(avatarUrl) {
    avatarPreview.innerHTML = avatarUrl
        ? `<img src="${avatarUrl}" alt="">`
        : escapeHtml(initials(myPseudo));
}

avatarInput.addEventListener("change", () => {
    const file = avatarInput.files[0];
    if (!file) return;
    avatarError.style.display = "none";

    const formData = new FormData();
    formData.append("pseudo", myPseudo);
    formData.append("avatar", file);

    fetch(`/room/${ROOM_CODE}/set_avatar`, { method: "POST", body: formData })
        .then((r) => r.json())
        .then((res) => {
            if (!res.ok) {
                avatarError.textContent = res.error || "Erreur lors de l'envoi.";
                avatarError.style.display = "block";
                return;
            }
            setMyAvatarPreview(res.avatar_url);
            // Le serveur diffuse aussi "presence_update" à tout le salon,
            // donc le chat et la liste des participants se mettent à jour tout seuls.
        })
        .catch(() => {
            avatarError.textContent = "Erreur réseau lors de l'envoi.";
            avatarError.style.display = "block";
        });
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

(function setupShare() {
    const inviteLink = document.getElementById("invite-link").value;
    const shareText = `Rejoins mon salon "Action ou Vérité" ! Code : ${ROOM_CODE}`;
    const fullMessage = `${shareText} ${inviteLink}`;

    const nativeShareBtn = document.getElementById("native-share-btn");
    nativeShareBtn.addEventListener("click", async () => {
        if (navigator.share) {
            try {
                await navigator.share({ title: "Action ou Vérité", text: shareText, url: inviteLink });
            } catch (e) {
                // Annulé par l'utilisateur ou non supporté : rien à faire.
            }
        } else {
            // Pas de support natif (souvent le cas sur desktop) : on affiche
            // les liens de partage directs juste en dessous.
            document.getElementById("share-links").scrollIntoView({ behavior: "smooth", block: "center" });
        }
    });

    document.getElementById("share-whatsapp").href =
        `https://wa.me/?text=${encodeURIComponent(fullMessage)}`;
    document.getElementById("share-facebook").href =
        `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(inviteLink)}`;
    document.getElementById("share-telegram").href =
        `https://t.me/share/url?url=${encodeURIComponent(inviteLink)}&text=${encodeURIComponent(shareText)}`;
    document.getElementById("share-x").href =
        `https://twitter.com/intent/tweet?text=${encodeURIComponent(fullMessage)}`;
})();

// ---------- Utilitaire ----------
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
