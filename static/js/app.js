const socket = io();
let currentRoomCode = typeof ROOM_CODE !== 'undefined' ? ROOM_CODE : '';

// 1. Connexion au salon
socket.on('connect', () => {
    const savedPseudo = localStorage.getItem('user_pseudo');
    if (savedPseudo && currentRoomCode) {
        socket.emit('join_room', { room: currentRoomCode, pseudo: savedPseudo });
    }
});

// 2. Gestion de l'affichage de la question (Vérité / Action)
function displayQuestionData(data) {
    // Masquer l'ancienne carte de question si elle existe
    const oldCard = document.getElementById('question-card');
    if (oldCard) oldCard.style.display = 'none';

    const gameZone = document.getElementById('game-zone');
    const titleElem = document.getElementById('question-title');
    const textElem = document.getElementById('question-text');
    const veriteSec = document.getElementById('verite-section');
    const actionSec = document.getElementById('action-section');

    if (gameZone && titleElem && textElem) {
        gameZone.style.display = 'block';
        titleElem.innerText = (data.type === 'action' ? '⚡ Action' : '🗣️ Vérité') + ' — ' + (data.player || 'Joueur');
        textElem.innerText = data.question || data.text || '';

        // Masquer le choix d'intensité/boutons
        const choiceZone = document.getElementById('choice-zone');
        if (choiceZone) choiceZone.style.display = 'none';

        // Afficher la bonne section
        if (data.type === 'action') {
            if (veriteSec) veriteSec.style.display = 'none';
            if (actionSec) actionSec.style.display = 'block';
        } else {
            if (veriteSec) veriteSec.style.display = 'block';
            if (actionSec) actionSec.style.display = 'none';
        }
    }
}

// Écoute de tous les noms d'événements possibles envoyés par le serveur
socket.on('question_drawn', displayQuestionData);
socket.on('show_question', displayQuestionData);
socket.on('question', displayQuestionData);

// 3. Envoi de la réponse Vérité
function submitVerite() {
    const input = document.getElementById('verite-input');
    if (!input) return;
    const val = input.value.trim();

    if (!val) {
        alert("La réponse est obligatoire !");
        return;
    }

    socket.emit('send_verite_answer', { room: currentRoomCode, answer: val });
    input.value = '';
    document.getElementById('verite-section').style.display = 'none';
}

// 4. Gestion de la Caméra pour Action
let mediaStream = null;

async function startCamera() {
    try {
        mediaStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" }, audio: false });
        const video = document.getElementById('camera-stream');
        video.srcObject = mediaStream;
        video.style.display = 'block';
        document.getElementById('btn-start-cam').style.display = 'none';
        document.getElementById('btn-take-photo').style.display = 'block';
    } catch (err) {
        alert("Erreur d'accès à la caméra : " + err.message);
    }
}

function captureAndSend() {
    const video = document.getElementById('camera-stream');
    const canvas = document.getElementById('photo-canvas');
    canvas.width = video.videoWidth || 300;
    canvas.height = video.videoHeight || 400;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const imgData = canvas.toDataURL('image/jpeg', 0.6);

    if (mediaStream) {
        mediaStream.getTracks().forEach(t => t.stop());
    }

    document.getElementById('action-section').style.display = 'none';
    socket.emit('send_action_proof', { room: currentRoomCode, image: imgData });
}

// 5. Réception des résultats
socket.on('verite_answer_received', (data) => {
    const log = document.getElementById('answers-log');
    const txt = document.getElementById('last-answer-text');
    if (log && txt) {
        log.style.display = 'block';
        txt.innerText = data.player + " a répondu : " + data.answer;
    }
});

socket.on('action_proof_received', (data) => {
    const log = document.getElementById('answers-log');
    const img = document.getElementById('proof-image');
    if (log && img) {
        log.style.display = 'block';
        img.src = data.image;
        img.style.display = 'block';
    }
});
