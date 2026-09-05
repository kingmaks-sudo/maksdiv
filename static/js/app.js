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

// Mémorisation du pseudo par salon : permet de revenir sur le lien plus
// tard et de retrouver automatiquement ses données (avatar, historique...)
// sans avoir à retaper son pseudo.
const PSEUDO_STORAGE_KEY = `maksdiv_pseudo_${ROOM_CODE}`;
const savedPseudo = localStorage.getItem(PSEUDO_STORAGE_KEY);
let autoJoinAttempted = false;

// Mémorisation du DERNIER salon actif (tous salons confondus) : permet à la
// page d'accueil de rediriger automatiquement dessus si l'app est fermée
// puis rouverte (PWA) pendant qu'un salon est toujours en cours.
const LAST_ROOM_KEY = "maksdiv_last_room";
localStorage.setItem(LAST_ROOM_KEY, ROOM_CODE);

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

// ---------- Navigation par onglets (barre du bas) ----------
let activeTabId = "tab-game";

document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        activeTabId = btn.dataset.tab;
        document.getElementById(activeTabId).classList.add("active");

        // En ouvrant la discussion, on considère les messages comme lus.
        if (activeTabId === "tab-chat") {
            unreadChatCount = 0;
            updateChatBadge();
        }
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

// ---------- Onglet 2 : MAKS IA ----------
const maksiaList = document.getElementById("maksia-list");
const maksiaInput = document.getElementById("maksia-input");
const maksiaSubmit = document.getElementById("maksia-submit");
const maksiaFileInput = document.getElementById("maksia-file-input");
const maksiaFilePreview = document.getElementById("maksia-file-preview");

let maksiaPendingFile = null; // { base64, mime, name }

maksiaFileInput.addEventListener("change", () => {
    const file = maksiaFileInput.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        // reader.result ressemble à "data:image/png;base64,AAAA..." : on retire le préfixe.
        const base64 = reader.result.split(",")[1];
        maksiaPendingFile = { base64, mime: file.type, name: file.name };
        maksiaFilePreview.style.display = "flex";
        maksiaFilePreview.innerHTML = `
            <span>📎 ${escapeHtml(file.name)}</span>
            <button id="maksia-file-remove" type="button">✕</button>
        `;
        document.getElementById("maksia-file-remove").addEventListener("click", () => {
            maksiaPendingFile = null;
            maksiaFileInput.value = "";
            maksiaFilePreview.style.display = "none";
            maksiaFilePreview.innerHTML = "";
        });
    };
    reader.readAsDataURL(file);
});

function sendMaksIaMessage() {
    const message = maksiaInput.value.trim();
    if (!message && !maksiaPendingFile) return;

    appendMaksIaMessage("user", message, maksiaPendingFile ? maksiaPendingFile.name : null);
    appendMaksIaThinking();

    socket.emit("send_maks_ia_message", {
        code: ROOM_CODE,
        pseudo: myPseudo,
        message,
        file_base64: maksiaPendingFile ? maksiaPendingFile.base64 : null,
        file_mime: maksiaPendingFile ? maksiaPendingFile.mime : null,
        file_name: maksiaPendingFile ? maksiaPendingFile.name : null,
    });

    maksiaInput.value = "";
    maksiaPendingFile = null;
    maksiaFileInput.value = "";
    maksiaFilePreview.style.display = "none";
    maksiaFilePreview.innerHTML = "";
}

maksiaSubmit.addEventListener("click", sendMaksIaMessage);
maksiaInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendMaksIaMessage();
});

function renderMaksIaMarkdown(text) {
    // Convertit le markdown (titres, gras, listes, tableaux...) en HTML, puis
    // nettoie ce HTML pour éviter tout risque avant de l'insérer dans la page.
    try {
        const rawHtml = marked.parse(text || "");
        return DOMPurify.sanitize(rawHtml);
    } catch (e) {
        return escapeHtml(text || "");
    }
}

function appendMaksIaMessage(role, text, fileName) {
    const item = document.createElement("div");
    item.className = "chat-msg" + (role === "user" ? " chat-msg-mine" : "");
    const fileTag = fileName ? `<div class="maksia-file-tag">📎 ${escapeHtml(fileName)}</div>` : "";
    const isAssistant = role === "assistant";
    const bodyHtml = isAssistant
        ? renderMaksIaMarkdown(text)
        : escapeHtml(text || "");

    item.innerHTML = `
        <div class="chat-bubble">
            ${isAssistant ? `<div class="chat-pseudo">🧠 MAKS IA</div>` : ""}
            ${fileTag}
            <div class="chat-text${isAssistant ? " maksia-markdown" : ""}">${bodyHtml}</div>
            ${isAssistant ? `<button class="maksia-copy-btn" type="button">📋 Copier</button>` : ""}
        </div>
    `;
    maksiaList.appendChild(item);

    if (isAssistant) {
        const copyBtn = item.querySelector(".maksia-copy-btn");
        copyBtn.addEventListener("click", () => {
            navigator.clipboard.writeText(text || "").then(() => {
                const original = copyBtn.textContent;
                copyBtn.textContent = "✅ Copié";
                copyBtn.disabled = true;
                setTimeout(() => {
                    copyBtn.textContent = original;
                    copyBtn.disabled = false;
                }, 1500);
            });
        });
    }

    scrollMaksIaToBottom();
    return item;
}

let maksiaThinkingEl = null;

function appendMaksIaThinking() {
    maksiaThinkingEl = document.createElement("div");
    maksiaThinkingEl.className = "chat-msg";
    maksiaThinkingEl.innerHTML = `
        <div class="chat-bubble">
            <div class="chat-pseudo">🧠 MAKS IA</div>
            <div class="chat-text maksia-thinking">...</div>
        </div>
    `;
    maksiaList.appendChild(maksiaThinkingEl);
    scrollMaksIaToBottom();
}

socket.on("maks_ia_response", (data) => {
    if (maksiaThinkingEl) {
        maksiaThinkingEl.remove();
        maksiaThinkingEl = null;
    }
    if (data.error) {
        appendMaksIaMessage("assistant", `⚠️ ${data.error}`);
        return;
    }
    appendMaksIaMessage("assistant", data.answer);
});

function scrollMaksIaToBottom() {
    maksiaList.scrollTop = maksiaList.scrollHeight;
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

let unreadChatCount = 0;
const chatBadge = document.getElementById("badge-chat");

function updateChatBadge() {
    if (unreadChatCount > 0) {
        chatBadge.textContent = unreadChatCount > 9 ? "9+" : unreadChatCount;
        chatBadge.style.display = "flex";
    } else {
        chatBadge.style.display = "none";
    }
}

socket.on("new_chat_message", (data) => {
    appendChatMessage(data.pseudo, data.avatar_url, data.message, data.created_at);
    scrollChatToBottom();

    // On ne compte pas comme "non lu" le message qu'on vient d'envoyer soi-même,
    // ni les messages reçus pendant qu'on a déjà l'onglet Discussion ouvert.
    if (activeTabId !== "tab-chat" && data.pseudo !== myPseudo) {
        unreadChatCount += 1;
        updateChatBadge();
    }
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

// ---------- Onglet 5 : Présence ----------
const presenceList = document.getElementById("presence-list");
const presenceBadge = document.getElementById("badge-presence");
const presenceStrip = document.getElementById("presence-strip");

// Rangée "Stories" des participants en ligne, visible en haut sur tous les onglets.
function renderPresenceStrip(players) {
    presenceStrip.innerHTML = "";
    players.forEach((p) => {
        const isMe = p.pseudo === myPseudo;
        const bubble = document.createElement("div");
        bubble.className = "story-bubble" + (isMe ? " story-bubble-me" : "");
        bubble.title = `${p.pseudo} — ${p.status === "inactif" ? "inactif" : "en ligne"}`;
        bubble.innerHTML = `
            <div class="story-avatar-ring ${p.status === "inactif" ? "inactif" : ""}">
                <div class="story-avatar">${p.avatar_url ? `<img src="${p.avatar_url}" alt="">` : escapeHtml(initials(p.pseudo))}</div>
            </div>
            <span class="story-name">${escapeHtml(isMe ? "Toi" : p.pseudo)}</span>
        `;
        presenceStrip.appendChild(bubble);
    });
}

socket.on("presence_update", (data) => {
    presenceBadge.textContent = data.players.length > 9 ? "9+" : data.players.length;

    presenceList.innerHTML = "";
    data.players.forEach((p) => {
        const li = document.createElement("li");
        const isMe = p.pseudo === myPseudo;
        li.innerHTML = `
            <span class="status-dot ${p.status === "inactif" ? "inactif" : ""}"></span>
            <span class="presence-avatar">${p.avatar_url ? `<img src="${p.avatar_url}" alt="">` : escapeHtml(initials(p.pseudo))}</span>
            ${escapeHtml(p.pseudo)}
        `;
        if (!isMe) {
            li.classList.add("presence-item-clickable");
            li.addEventListener("click", () => openPrivateChat(p.pseudo, p.avatar_url));
        }
        presenceList.appendChild(li);
    });

    renderPresenceStrip(data.players);

    // Met à jour mon propre aperçu si mon avatar a changé (ex: après upload).
    const me = data.players.find((p) => p.pseudo === myPseudo);
    if (me) setMyAvatarPreview(me.avatar_url);
});

socket.on("system_message", (data) => {
    console.log(data.message);
});

// ---------- Onglet Présence : photo de profil ----------
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

// ---------- Onglet Invitation ----------
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

// ---------- Messagerie privée ----------
let privateChatWith = null; // pseudo du destinataire actuellement ouvert

const privateOverlay = document.getElementById("private-chat-overlay");
const privateTitle = document.getElementById("private-chat-title");
const privateList = document.getElementById("private-chat-list");
const privateInput = document.getElementById("private-chat-input");
const privateSubmit = document.getElementById("private-chat-submit");
const privateClose = document.getElementById("private-chat-close");

function openPrivateChat(pseudo, avatarUrl) {
    privateChatWith = pseudo;
    privateTitle.textContent = "💌 " + pseudo;
    privateList.innerHTML = "";
    privateOverlay.style.display = "flex";
    privateInput.value = "";
    privateInput.focus();

    fetch(`/room/${ROOM_CODE}/private_messages/${encodeURIComponent(pseudo)}`)
        .then((r) => r.json())
        .then((rows) => {
            rows.forEach((row) => {
                const time = new Date(row.created_at + "Z").toLocaleTimeString("fr-FR", {
                    hour: "2-digit",
                    minute: "2-digit",
                });
                appendPrivateMessage(row.sender, row.message, time);
            });
            scrollPrivateToBottom();
        });
}

function closePrivateChat() {
    privateOverlay.style.display = "none";
    privateChatWith = null;
}

privateClose.addEventListener("click", closePrivateChat);

function sendPrivateMessage() {
    const message = privateInput.value.trim();
    if (!message || !privateChatWith) return;
    socket.emit("send_private_message", {
        code: ROOM_CODE,
        recipient: privateChatWith,
        message,
    });
    privateInput.value = "";
}

privateSubmit.addEventListener("click", sendPrivateMessage);
privateInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendPrivateMessage();
});

function appendPrivateMessage(sender, message, time) {
    const mine = sender === myPseudo;
    const item = document.createElement("div");
    item.className = "chat-msg" + (mine ? " chat-msg-mine" : "");
    item.innerHTML = `
        <div class="chat-bubble">
            <div class="chat-text">${escapeHtml(message)}</div>
            <div class="chat-time">${time || ""}</div>
        </div>
    `;
    privateList.appendChild(item);
}

function scrollPrivateToBottom() {
    privateList.scrollTop = privateList.scrollHeight;
}

// Réception d'un message privé (envoyé par moi ou reçu d'un autre joueur).
socket.on("new_private_message", (data) => {
    const otherParty = data.sender === myPseudo ? data.recipient : data.sender;
    // On n'affiche le message que si la conversation avec cette personne
    // précise est actuellement ouverte à l'écran.
    if (privateChatWith === otherParty) {
        appendPrivateMessage(data.sender, data.message, data.created_at);
        scrollPrivateToBottom();
    }
});

// ---------- Utilitaire ----------
function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
