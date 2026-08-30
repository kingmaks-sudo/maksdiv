// ============================================================================
// Dames — Interface (rendu + interactions + solo IA + multijoueur Socket.IO)
// Dépend de : checkers.js (window.CheckersEngine), et des variables globales
// déjà définies dans app.js : socket, myPseudo, ROOM_CODE, escapeHtml().
// ============================================================================

(function () {
    const Engine = window.CheckersEngine;
    const SIZE = Engine.SIZE;

    // ---------- Sons (générés en direct, aucun fichier audio requis) ----------
    let audioCtx = null;
    function ensureAudio() {
        if (!audioCtx) {
            try {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            } catch (e) {
                audioCtx = null;
            }
        } else if (audioCtx.state === "suspended") {
            audioCtx.resume();
        }
        return audioCtx;
    }
    function playTone(freq, duration, type, volume, delay) {
        const ctx = ensureAudio();
        if (!ctx) return;
        const t0 = ctx.currentTime + (delay || 0);
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = type || "sine";
        osc.frequency.setValueAtTime(freq, t0);
        gain.gain.setValueAtTime(0, t0);
        gain.gain.linearRampToValueAtTime(volume || 0.15, t0 + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.001, t0 + duration);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(t0);
        osc.stop(t0 + duration + 0.03);
    }
    function sfxSelect() { playTone(720, 0.06, "square", 0.10); }
    function sfxMove() { playTone(320, 0.13, "sine", 0.16); }
    function sfxCapture() {
        playTone(480, 0.09, "triangle", 0.18);
        playTone(230, 0.15, "triangle", 0.16, 0.09);
    }
    function sfxKing() {
        playTone(520, 0.1, "sine", 0.16);
        playTone(660, 0.1, "sine", 0.16, 0.1);
        playTone(880, 0.18, "sine", 0.18, 0.2);
    }

    // ---------- Éléments DOM (voir templates/room.html) ----------
    const menuEl = document.getElementById("checkers-mode-menu");
    const soloBtn = document.getElementById("checkers-solo-btn");
    const multiBtn = document.getElementById("checkers-multi-btn");
    const difficultyPanel = document.getElementById("checkers-difficulty-panel");
    const difficultyBackBtn = document.getElementById("checkers-difficulty-back-btn");
    const invitePanel = document.getElementById("checkers-invite-panel");
    const inviteList = document.getElementById("checkers-invite-list");
    const inviteBanner = document.getElementById("checkers-invite-banner");
    const gameArea = document.getElementById("checkers-game-area");
    const boardEl = document.getElementById("checkers-board");
    const statusEl = document.getElementById("checkers-status");
    const newGameBtn = document.getElementById("checkers-new-game-btn");
    const resignBtn = document.getElementById("checkers-resign-btn");
    const backBtn = document.getElementById("checkers-back-btn");

    const DIFFICULTIES = {
        beginner: { label: "Débutant", depth: 1, randomness: 0.5 },
        hard: { label: "Difficile", depth: 3, randomness: 0 },
        expert: { label: "Expert", depth: 5, randomness: 0 },
        master: { label: "Maître", depth: 7, randomness: 0 },
    };

    // ---------- État de la partie en cours (local) ----------
    let state = null;
    /* state = {
        mode: 'solo' | 'multi',
        board, currentColor, myColor,
        matchId, opponentPseudo,
        selected: [r,c] | null,
        destinations: [{to:[r,c], captured:[r,c]|null}],
        forcedContinue: bool,
        turnFrom: [r,c] | null,
        turnSteps: [{to, captured}],
        over: bool,
    } */

    let otherPlayers = []; // pseudos des autres joueurs en ligne dans le salon

    // ---------- Aide : perspective (chaque joueur voit ses pièces en bas) ----------
    function flipFor(color) {
        return color === "b"; // les "noirs" voient le plateau retourné
    }
    function visualToLogical(vr, vc, flip) {
        return flip ? [SIZE - 1 - vr, SIZE - 1 - vc] : [vr, vc];
    }

    const tabPanel = document.getElementById("tab-checkers");
    const descriptionEl = tabPanel ? tabPanel.querySelector(".tab-description") : null;

    // ---------- Menu ----------
    function showMenu() {
        state = null;
        menuEl.style.display = "block";
        difficultyPanel.style.display = "none";
        invitePanel.style.display = "none";
        inviteBanner.style.display = "none";
        gameArea.style.display = "none";
        if (tabPanel) tabPanel.classList.remove("checkers-fullscreen");
        if (descriptionEl) descriptionEl.style.display = "block";
    }

    function showDifficultyPanel() {
        menuEl.style.display = "none";
        difficultyPanel.style.display = "block";
    }

    function showInvitePanel() {
        menuEl.style.display = "none";
        invitePanel.style.display = "block";
        renderInviteList();
    }

    function renderInviteList() {
        inviteList.innerHTML = "";
        const others = otherPlayers.filter((p) => p !== myPseudo);
        if (others.length === 0) {
            inviteList.innerHTML = `<p class="waiting-msg">Aucun autre joueur en ligne pour l'instant.</p>`;
            return;
        }
        others.forEach((pseudo) => {
            const item = document.createElement("div");
            item.className = "checkers-invite-item";
            item.innerHTML = `<span>${escapeHtml(pseudo)}</span><button class="btn-primary checkers-invite-send-btn">Inviter</button>`;
            item.querySelector(".checkers-invite-send-btn").addEventListener("click", () => {
                socket.emit("checkers_invite", { code: ROOM_CODE, to_pseudo: pseudo });
                item.querySelector("button").textContent = "Invitation envoyée...";
                item.querySelector("button").disabled = true;
            });
            inviteList.appendChild(item);
        });
    }

    soloBtn.addEventListener("click", () => showDifficultyPanel());
    multiBtn.addEventListener("click", () => showInvitePanel());
    backBtn.addEventListener("click", () => showMenu());
    difficultyBackBtn.addEventListener("click", () => showMenu());

    Object.keys(DIFFICULTIES).forEach((key) => {
        const btn = document.getElementById("checkers-diff-" + key);
        if (btn) btn.addEventListener("click", () => startSoloGame(DIFFICULTIES[key]));
    });

    // ---------- Démarrage d'une partie ----------
    function startSoloGame(difficulty) {
        state = {
            mode: "solo",
            board: Engine.createInitialBoard(),
            currentColor: "w",
            myColor: "w",
            matchId: null,
            opponentPseudo: "Ordinateur (" + difficulty.label + ")",
            aiDepth: difficulty.depth,
            aiRandomness: difficulty.randomness,
            selected: null,
            destinations: [],
            turnFrom: null,
            turnSteps: [],
            over: false,
            animating: false,
        };
        openGameArea();
    }

    function startMultiGame(matchId, myColor, opponentPseudo, startingColor) {
        state = {
            mode: "multi",
            board: Engine.createInitialBoard(),
            currentColor: startingColor,
            myColor,
            matchId,
            opponentPseudo,
            selected: null,
            destinations: [],
            turnFrom: null,
            turnSteps: [],
            over: false,
            animating: false,
        };
        openGameArea();
    }

    function openGameArea() {
        menuEl.style.display = "none";
        difficultyPanel.style.display = "none";
        invitePanel.style.display = "none";
        inviteBanner.style.display = "none";
        gameArea.style.display = "block";
        if (tabPanel) tabPanel.classList.add("checkers-fullscreen");
        if (descriptionEl) descriptionEl.style.display = "none";
        renderBoard();
        updateStatus();
    }

    // ---------- Quelles pièces sont jouables maintenant (avant sélection) ----------
    function getSelectablePositions(board, color) {
        const mustCapture = Engine.colorHasCapture(board, color);
        const positions = [];
        for (let r = 0; r < SIZE; r++) {
            for (let c = 0; c < SIZE; c++) {
                const p = board[r][c];
                if (!p || p.color !== color) continue;
                const moves = mustCapture ? Engine.pieceCaptures(board, r, c) : Engine.pieceSimpleMoves(board, r, c);
                if (moves.length > 0) positions.push([r, c]);
            }
        }
        return positions;
    }

    // ---------- Rendu du plateau ----------
    function renderBoard() {
        boardEl.innerHTML = "";
        const flip = flipFor(state.myColor);
        // Surbrillance dorée : uniquement quand c'est mon tour et qu'aucune pièce
        // n'est encore sélectionnée (dès qu'une capture est en cours, on la cache
        // pour ne pas distraire pendant une rafle forcée).
        const showPlayable = state.currentColor === state.myColor && !state.selected;
        const selectable = showPlayable ? getSelectablePositions(state.board, state.myColor) : [];

        for (let vr = 0; vr < SIZE; vr++) {
            for (let vc = 0; vc < SIZE; vc++) {
                const [lr, lc] = visualToLogical(vr, vc, flip);
                const dark = (lr + lc) % 2 === 1;
                const sq = document.createElement("div");
                sq.className = "checkers-square " + (dark ? "dark" : "light");
                sq.dataset.r = lr;
                sq.dataset.c = lc;

                if (dark) {
                    const isSelected = state.selected && state.selected[0] === lr && state.selected[1] === lc;
                    const isDest = state.destinations.some((d) => d.to[0] === lr && d.to[1] === lc);
                    if (isSelected) sq.classList.add("selected");
                    if (isDest) sq.classList.add("destination");

                    const piece = state.board[lr][lc];
                    if (piece) {
                        const pieceEl = document.createElement("div");
                        pieceEl.className = "checkers-piece " + (piece.color === "w" ? "piece-w" : "piece-b");
                        if (piece.king) pieceEl.classList.add("king");
                        if (selectable.some((p) => p[0] === lr && p[1] === lc)) {
                            pieceEl.classList.add("playable");
                        }
                        sq.appendChild(pieceEl);
                    }
                    sq.addEventListener("click", () => handleSquareClick(lr, lc));
                }
                boardEl.appendChild(sq);
            }
        }
    }

    function updateStatus() {
        if (state.over) return;
        if (state.currentColor === state.myColor) {
            statusEl.textContent = "🎯 À toi de jouer.";
            statusEl.classList.add("my-turn");
        } else {
            const label = state.mode === "solo" ? "L'ordinateur réfléchit..." : `En attente de ${state.opponentPseudo}...`;
            statusEl.textContent = "⏳ " + label;
            statusEl.classList.remove("my-turn");
        }
    }

    function findSquareEl(r, c) {
        return boardEl.querySelector('.checkers-square[data-r="' + r + '"][data-c="' + c + '"]');
    }

    // Anime visuellement UN saut (glissement + fondu de la pièce mangée), joue le son
    // correspondant, puis applique réellement le coup au modèle et rafraîchit le plateau.
    function animateAndApply(from, dest, onDone) {
        const fromSq = findSquareEl(from[0], from[1]);
        const toSq = findSquareEl(dest.to[0], dest.to[1]);
        const pieceEl = fromSq ? fromSq.querySelector(".checkers-piece") : null;
        const capturedSq = dest.captured ? findSquareEl(dest.captured[0], dest.captured[1]) : null;
        const capturedPieceEl = capturedSq ? capturedSq.querySelector(".checkers-piece") : null;

        if (pieceEl && fromSq && toSq) {
            const fromRect = fromSq.getBoundingClientRect();
            const toRect = toSq.getBoundingClientRect();
            const dx = toRect.left - fromRect.left;
            const dy = toRect.top - fromRect.top;
            pieceEl.style.zIndex = "5";
            pieceEl.style.transition = "transform 0.28s ease";
            requestAnimationFrame(() => {
                pieceEl.style.transform = "translate(" + dx + "px, " + dy + "px)";
            });
        }
        if (capturedPieceEl) {
            capturedPieceEl.style.transition = "transform 0.22s ease, opacity 0.22s ease";
            capturedPieceEl.style.transform = "scale(0.3)";
            capturedPieceEl.style.opacity = "0";
        }

        if (dest.captured) sfxCapture(); else sfxMove();

        setTimeout(() => {
            const promoted = Engine.applyStep(state.board, from, dest.to, dest.captured || null);
            if (promoted) sfxKing();
            renderBoard();
            onDone(promoted);
        }, 300);
    }

    // Enchaîne l'animation de plusieurs sauts à la suite (rafle, ou tour adverse reçu)
    function animateStepsSequentially(fromPos, steps, index, onAllDone) {
        if (index >= steps.length) { onAllDone(); return; }
        const dest = steps[index];
        animateAndApply(fromPos, dest, () => {
            animateStepsSequentially(dest.to, steps, index + 1, onAllDone);
        });
    }

    // ---------- Interaction ----------
    function handleSquareClick(r, c) {
        if (state.over || state.animating) return;
        if (state.currentColor !== state.myColor) return; // pas mon tour

        const piece = state.board[r][c];

        // Cas 1 : on clique sur une destination déjà en surbrillance -> jouer le coup
        const destMatch = state.destinations.find((d) => d.to[0] === r && d.to[1] === c);
        if (state.selected && destMatch) {
            playStep(state.selected, destMatch);
            return;
        }

        // Cas 2 : si on doit continuer une rafle avec la même pièce, interdit de sélectionner autre chose
        if (state.turnSteps.length > 0 && state.selected) {
            return;
        }

        // Cas 3 : sélectionner une pièce jouable
        if (!piece || piece.color !== state.myColor) {
            state.selected = null;
            state.destinations = [];
            renderBoard();
            return;
        }
        const mustCapture = Engine.colorHasCapture(state.board, state.myColor);
        const caps = Engine.pieceCaptures(state.board, r, c);
        if (mustCapture && caps.length === 0) {
            // cette pièce n'a pas de prise alors qu'une prise existe ailleurs : non sélectionnable
            return;
        }
        state.selected = [r, c];
        state.destinations = mustCapture ? caps : Engine.pieceSimpleMoves(state.board, r, c);
        sfxSelect();
        renderBoard();
    }

    function playStep(from, dest) {
        state.animating = true;
        state.selected = null;
        state.destinations = [];
        animateAndApply(from, dest, () => {
            state.animating = false;
            state.turnFrom = state.turnFrom || from;
            state.turnSteps.push({ to: dest.to, captured: dest.captured || null });

            if (dest.captured) {
                const further = Engine.pieceCaptures(state.board, dest.to[0], dest.to[1]);
                if (further.length > 0) {
                    state.selected = dest.to;
                    state.destinations = further;
                    renderBoard();
                    return;
                }
            }
            finishTurn();
        });
    }

    // Détermine à qui revient réellement la main : si le camp candidat a des
    // pions mais ne peut pas jouer, son tour est passé (au lieu de perdre).
    // La partie ne se termine que par élimination totale d'un camp, ou par
    // un blocage total des deux camps (match nul, situation extrêmement rare).
    function resolveNextTurn(candidateColor) {
        let current = candidateColor;
        let guard = 0;
        while (guard < 40) {
            const winner = Engine.checkGameOver(state.board, current);
            if (winner) return { type: "winner", color: winner };
            if (Engine.hasAnyMove(state.board, current)) {
                return { type: "play", color: current };
            }
            current = current === "w" ? "b" : "w";
            guard++;
        }
        return { type: "draw" };
    }

    function endGameDraw() {
        state.over = true;
        statusEl.textContent = "🤝 Match nul — plus aucun coup possible pour personne.";
        statusEl.classList.remove("my-turn");
    }

    function finishTurn() {
        const finishedColor = state.currentColor;
        const opponentColor = finishedColor === "w" ? "b" : "w";
        state.selected = null;
        state.destinations = [];

        // En multijoueur, on transmet le tour complet à l'adversaire
        if (state.mode === "multi") {
            socket.emit("checkers_move", {
                code: ROOM_CODE,
                match_id: state.matchId,
                from: state.turnFrom,
                steps: state.turnSteps,
            });
        }
        state.turnFrom = null;
        state.turnSteps = [];

        const resolution = resolveNextTurn(opponentColor);
        if (resolution.type === "winner") { endGame(resolution.color); return; }
        if (resolution.type === "draw") { endGameDraw(); return; }
        state.currentColor = resolution.color;
        renderBoard();
        updateStatus();

        if (state.mode === "solo" && state.currentColor !== state.myColor) {
            setTimeout(playAiTurn, 600);
        }
    }

    function playAiTurn() {
        const aiColor = state.currentColor;
        const turn = Engine.aiChooseTurn(state.board, aiColor, state.aiDepth || 3, state.aiRandomness || 0);
        if (!turn) {
            endGame(aiColor === "w" ? "b" : "w");
            return;
        }
        state.animating = true;
        animateStepsSequentially(turn.from, turn.steps, 0, () => {
            state.animating = false;
            const opponentColor = aiColor === "w" ? "b" : "w";
            const resolution = resolveNextTurn(opponentColor);
            if (resolution.type === "winner") {
                renderBoard();
                endGame(resolution.color);
                return;
            }
            if (resolution.type === "draw") {
                renderBoard();
                endGameDraw();
                return;
            }
            state.currentColor = resolution.color;
            renderBoard();
            updateStatus();
        });
    }

    function endGame(winnerColor) {
        state.over = true;
        const iWon = winnerColor === state.myColor;
        statusEl.textContent = iWon ? "🏆 Tu as gagné !" : "😔 Partie perdue.";
        statusEl.classList.remove("my-turn");
    }

    // ---------- Boutons de contrôle ----------
    newGameBtn.addEventListener("click", () => {
        if (state && state.mode === "multi" && !state.over) {
            socket.emit("checkers_resign", { code: ROOM_CODE, match_id: state.matchId });
        }
        showMenu();
    });

    resignBtn.addEventListener("click", () => {
        if (!state || state.over) return;
        if (state.mode === "multi") {
            socket.emit("checkers_resign", { code: ROOM_CODE, match_id: state.matchId });
        }
        endGame(state.myColor === "w" ? "b" : "w");
    });

    // ---------- Événements Socket.IO (multijoueur) ----------
    socket.on("presence_update", (data) => {
        otherPlayers = data.players.map((p) => p.pseudo);
        if (invitePanel.style.display === "block") renderInviteList();
        // Si l'adversaire courant a quitté le salon en pleine partie
        if (state && state.mode === "multi" && !state.over && state.opponentPseudo) {
            if (!otherPlayers.includes(state.opponentPseudo)) {
                state.over = true;
                statusEl.textContent = `⚠️ ${state.opponentPseudo} a quitté le salon.`;
                statusEl.classList.remove("my-turn");
            }
        }
    });

    socket.on("checkers_invite_received", (data) => {
        inviteBanner.style.display = "block";
        inviteBanner.innerHTML = `
            <p>${escapeHtml(data.from_pseudo)} t'invite à une partie de dames !</p>
            <div class="camera-controls">
                <button id="checkers-accept-btn" class="btn-primary">Accepter</button>
                <button id="checkers-decline-btn" class="btn-secondary">Refuser</button>
            </div>
        `;
        document.getElementById("checkers-accept-btn").addEventListener("click", () => {
            socket.emit("checkers_accept", { code: ROOM_CODE, from_pseudo: data.from_pseudo });
            inviteBanner.style.display = "none";
        });
        document.getElementById("checkers-decline-btn").addEventListener("click", () => {
            socket.emit("checkers_decline", { code: ROOM_CODE, from_pseudo: data.from_pseudo });
            inviteBanner.style.display = "none";
        });
    });

    socket.on("checkers_invite_declined", (data) => {
        alert(`${data.pseudo} a refusé l'invitation.`);
    });

    socket.on("checkers_game_start", (data) => {
        // data: { match_id, players: {pseudo: color}, starting_color }
        const myColor = data.players[myPseudo];
        if (!myColor) return; // ce message ne me concerne pas
        const opponentPseudo = Object.keys(data.players).find((p) => p !== myPseudo);
        startMultiGame(data.match_id, myColor, opponentPseudo, data.starting_color);
    });

    socket.on("checkers_move_made", (data) => {
        if (!state || state.mode !== "multi" || data.match_id !== state.matchId) return;
        if (data.pseudo === myPseudo) return; // c'est mon propre coup qui revient
        state.animating = true;
        animateStepsSequentially(data.from, data.steps, 0, () => {
            state.animating = false;
            const opponentColor = state.currentColor === "w" ? "b" : "w";
            const resolution = resolveNextTurn(opponentColor);
            if (resolution.type === "winner") {
                renderBoard();
                endGame(resolution.color);
                return;
            }
            if (resolution.type === "draw") {
                renderBoard();
                endGameDraw();
                return;
            }
            state.currentColor = resolution.color;
            renderBoard();
            updateStatus();
        });
    });

    socket.on("checkers_resign_notice", (data) => {
        if (!state || state.mode !== "multi" || data.match_id !== state.matchId) return;
        state.over = true;
        statusEl.textContent = `🏆 ${data.pseudo} a abandonné — tu as gagné !`;
        statusEl.classList.remove("my-turn");
    });

    // ---------- Initialisation ----------
    showMenu();
})();
