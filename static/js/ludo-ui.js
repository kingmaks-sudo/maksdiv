// ============================================================================
// Ludo — Interface (plateau, dés, interactions, bots)
// Phase 1 : mode solo/bots uniquement. Le multijoueur en ligne arrive ensuite.
// Dépend de : ludo.js (window.LudoEngine), et des globales déjà définies dans
// app.js : socket, myPseudo, ROOM_CODE, escapeHtml().
// ============================================================================

(function () {
    const Engine = window.LudoEngine;
    const GRID = 15;

    const COLOR_HEX = { red: "#e64545", blue: "#4570e6", yellow: "#e6c845", green: "#45b34a" };
    const COLOR_LABEL = { red: "Rouge", blue: "Bleu", yellow: "Jaune", green: "Vert" };

    // ---------- Géométrie du plateau (15x15), calculée une fois ----------
    function buildSharedPath() {
        const path = [];
        for (let r = 5; r >= 0; r--) path.push([r, 6]);
        path.push([0, 7]);
        for (let r = 0; r <= 5; r++) path.push([r, 8]);
        for (let c = 9; c <= 14; c++) path.push([6, c]);
        path.push([7, 14]);
        for (let c = 14; c >= 9; c--) path.push([8, c]);
        for (let r = 9; r <= 14; r++) path.push([r, 8]);
        path.push([14, 7]);
        for (let r = 14; r >= 9; r--) path.push([r, 6]);
        for (let c = 5; c >= 0; c--) path.push([8, c]);
        path.push([7, 0]);
        for (let c = 0; c <= 5; c++) path.push([6, c]);
        return path; // 52 cellules
    }
    const SHARED_PATH = buildSharedPath();

    const STRETCH = {
        red: [1, 2, 3, 4, 5, 6].map((r) => [r, 7]),
        blue: [13, 12, 11, 10, 9, 8].map((c) => [7, c]),
        yellow: [13, 12, 11, 10, 9, 8].map((r) => [r, 7]),
        green: [1, 2, 3, 4, 5, 6].map((c) => [7, c]),
    };

    const YARD_BASE = { red: [0, 0], blue: [0, 10], yellow: [10, 10], green: [10, 0] };
    const YARD_OFFSETS = [[1, 1], [1, 3], [3, 1], [3, 3]];
    function yardSlot(color, idx) {
        const [br, bc] = YARD_BASE[color];
        const [dr, dc] = YARD_OFFSETS[idx];
        return [br + dr, bc + dc];
    }
    const CENTER = [7, 7];

    function cellForToken(color, pos) {
        if (pos === -1) return null;
        if (pos === Engine.FINISH_POS) return CENTER;
        if (pos <= Engine.TRACK_LEN - 2) {
            const g = Engine.globalSquare(color, pos);
            return SHARED_PATH[g];
        }
        return STRETCH[color][pos - (Engine.TRACK_LEN - 1)];
    }

    // ---------- Éléments DOM (ajoutés dans templates/room.html) ----------
    const menuEl = document.getElementById("ludo-mode-menu");
    const botsBtn = document.getElementById("ludo-bots-btn");
    const playerCountPanel = document.getElementById("ludo-playercount-panel");
    const gameArea = document.getElementById("ludo-game-area");
    const boardEl = document.getElementById("ludo-board");
    const statusEl = document.getElementById("ludo-status");
    const diceBtn = document.getElementById("ludo-dice-btn");
    const diceResultEl = document.getElementById("ludo-dice-result");
    const newGameBtn = document.getElementById("ludo-new-game-btn");
    const tabPanel = document.getElementById("tab-ludo");
    const descriptionEl = tabPanel ? tabPanel.querySelector(".tab-description") : null;

    let state = null;

    // ---------- Sons (réutilise le même principe que les dames) ----------
    let audioCtx = null;
    function ensureAudio() {
        if (!audioCtx) {
            try { audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { audioCtx = null; }
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
    function sfxDiceRoll() { playTone(300, 0.05, "square", 0.08); playTone(400, 0.05, "square", 0.08, 0.06); }
    function sfxMove() { playTone(500, 0.07, "sine", 0.12); }
    function sfxCapture() { playTone(500, 0.09, "triangle", 0.18); playTone(230, 0.15, "triangle", 0.16, 0.09); }
    function sfxFinishToken() { playTone(700, 0.1, "sine", 0.16); playTone(900, 0.15, "sine", 0.18, 0.1); }
    function sfxVictory() {
        playTone(523, 0.15, "sine", 0.18);
        playTone(659, 0.15, "sine", 0.18, 0.13);
        playTone(784, 0.15, "sine", 0.18, 0.26);
        playTone(1046, 0.28, "sine", 0.2, 0.39);
    }

    // ---------- Menu ----------
    function showMenu() {
        state = null;
        menuEl.style.display = "block";
        playerCountPanel.style.display = "none";
        gameArea.style.display = "none";
        if (tabPanel) tabPanel.classList.remove("checkers-fullscreen");
        if (descriptionEl) descriptionEl.style.display = "block";
    }

    botsBtn.addEventListener("click", () => {
        menuEl.style.display = "none";
        playerCountPanel.style.display = "block";
    });

    document.querySelectorAll(".ludo-count-btn").forEach((btn) => {
        btn.addEventListener("click", () => startBotsGame(parseInt(btn.dataset.count, 10)));
    });
    document.getElementById("ludo-count-back-btn").addEventListener("click", () => showMenu());
    newGameBtn.addEventListener("click", () => showMenu());

    function startBotsGame(numPlayers) {
        const colors = Engine.COLORS.slice(0, numPlayers);
        const isBot = {};
        colors.forEach((c, i) => { isBot[c] = i !== 0; }); // le premier (rouge) = le joueur humain
        state = {
            mode: "bots",
            colors,
            myColor: colors[0],
            isBot,
            game: Engine.createGame(colors),
            diceValue: null,
            validTokens: [],
            awaitingChoice: false,
            over: false,
        };
        openGameArea();
    }

    function openGameArea() {
        menuEl.style.display = "none";
        playerCountPanel.style.display = "none";
        gameArea.style.display = "block";
        if (tabPanel) tabPanel.classList.add("checkers-fullscreen");
        if (descriptionEl) descriptionEl.style.display = "none";
        buildBoardDom();
        renderTokens();
        updateStatus();
        maybeAutoRollForBot();
    }

    // ---------- Construction du plateau (une seule fois par partie) ----------
    function buildBoardDom() {
        boardEl.innerHTML = "";
        boardEl.style.setProperty("--ludo-grid", GRID);

        const cellType = {}; // "r,c" -> {kind, color}
        Engine.COLORS.forEach((color) => {
            const [br, bc] = YARD_BASE[color];
            for (let r = br; r < br + 5; r++) {
                for (let c = bc; c < bc + 5; c++) {
                    cellType[r + "," + c] = { kind: "yard", color };
                }
            }
        });
        SHARED_PATH.forEach(([r, c], idx) => {
            const isSafe = Object.values(Engine.ENTRY).includes(idx) || [8, 21, 34, 47].includes(idx);
            cellType[r + "," + c] = { kind: "path", safe: isSafe };
        });
        Engine.COLORS.forEach((color) => {
            STRETCH[color].forEach(([r, c]) => {
                cellType[r + "," + c] = { kind: "stretch", color };
            });
        });
        cellType[CENTER[0] + "," + CENTER[1]] = { kind: "center" };

        for (let r = 0; r < GRID; r++) {
            for (let c = 0; c < GRID; c++) {
                const info = cellType[r + "," + c];
                const cell = document.createElement("div");
                cell.className = "ludo-cell";
                if (info) {
                    if (info.kind === "yard") { cell.classList.add("ludo-yard", "ludo-color-" + info.color); }
                    else if (info.kind === "path") { cell.classList.add("ludo-path"); if (info.safe) cell.classList.add("ludo-safe"); }
                    else if (info.kind === "stretch") { cell.classList.add("ludo-stretch", "ludo-color-" + info.color); }
                    else if (info.kind === "center") { cell.classList.add("ludo-center"); }
                } else {
                    cell.classList.add("ludo-empty");
                }
                cell.style.gridRow = (r + 1);
                cell.style.gridColumn = (c + 1);
                boardEl.appendChild(cell);
            }
        }

        // Petits blocs de couleur décoratifs au centre des maisons (zone des pions)
        Engine.COLORS.forEach((color) => {
            const [br, bc] = YARD_BASE[color];
            const inner = document.createElement("div");
            inner.className = "ludo-yard-inner ludo-color-" + color;
            inner.style.gridRow = (br + 2) + " / span 1";
            inner.style.gridColumn = (bc + 2) + " / span 1";
            boardEl.appendChild(inner);
        });

        // Couche pour les pions (positionnés en absolu par-dessus la grille)
        const tokenLayer = document.createElement("div");
        tokenLayer.id = "ludo-token-layer";
        tokenLayer.className = "ludo-token-layer";
        boardEl.appendChild(tokenLayer);
    }

    // ---------- Rendu des pions ----------
    function renderTokens() {
        const layer = document.getElementById("ludo-token-layer");
        if (!layer) return;
        layer.innerHTML = "";
        const cellPercent = 100 / GRID;

        state.colors.forEach((color) => {
            state.game.tokens[color].forEach((pos, idx) => {
                let rc;
                if (pos === -1) rc = yardSlot(color, idx);
                else rc = cellForToken(color, pos);
                if (!rc) return;
                const [r, c] = rc;
                const el = document.createElement("div");
                el.className = "ludo-token ludo-color-" + color;
                el.style.left = (c * cellPercent) + "%";
                el.style.top = (r * cellPercent) + "%";
                el.style.width = cellPercent + "%";
                el.style.height = cellPercent + "%";

                const isMovable = state.awaitingChoice && color === Engine.currentColor(state.game) &&
                    color === state.myColor && state.validTokens.includes(idx);
                if (isMovable) {
                    el.classList.add("ludo-token-movable");
                    el.addEventListener("click", () => chooseToken(idx));
                }
                layer.appendChild(el);
            });
        });
    }

    // ---------- Statut / tour ----------
    function updateStatus() {
        if (state.over) return;
        const color = Engine.currentColor(state.game);
        const isMe = color === state.myColor;
        statusEl.innerHTML =
            "<span class='ludo-turn-color ludo-color-text-" + color + "'>" + COLOR_LABEL[color] + "</span>" +
            (isMe ? " — à toi de jouer" : " réfléchit...");
        diceBtn.disabled = !isMe || state.awaitingChoice;
    }

    function maybeAutoRollForBot() {
        const color = Engine.currentColor(state.game);
        if (state.isBot[color] && !state.over) {
            setTimeout(rollDice, 700);
        }
    }

    // ---------- Lancer de dé ----------
    diceBtn.addEventListener("click", () => {
        if (diceBtn.disabled) return;
        rollDice();
    });

    function rollDice() {
        if (state.over) return;
        const color = Engine.currentColor(state.game);
        const value = Engine.rollDie();
        state.diceValue = value;
        state.game.consecutiveSixes = value === 6 ? (state.game.consecutiveSixes + 1) : 0;
        sfxDiceRoll();
        diceResultEl.textContent = "🎲 " + value;
        diceBtn.disabled = true;

        const valid = Engine.movableTokens(state.game, color, value);
        if (valid.length === 0) {
            statusEl.innerHTML = "<span class='ludo-turn-color ludo-color-text-" + color + "'>" + COLOR_LABEL[color] + "</span> ne peut pas jouer ce coup.";
            setTimeout(() => {
                Engine.advancePlayer(state.game);
                proceedToNextTurn();
            }, 800);
            return;
        }

        if (state.isBot[color]) {
            const idx = Engine.aiChooseToken(state.game, color, value, valid);
            setTimeout(() => applyMove(color, idx), 600);
        } else {
            state.validTokens = valid;
            state.awaitingChoice = true;
            renderTokens();
            statusEl.textContent = "🎲 " + value + " — choisis le pion à déplacer.";
        }
    }

    function chooseToken(idx) {
        if (!state.awaitingChoice) return;
        state.awaitingChoice = false;
        applyMove(state.myColor, idx);
    }

    function applyMove(color, idx) {
        const result = Engine.moveToken(state.game, color, idx, state.diceValue);
        renderTokens();

        if (result.captured.length > 0) sfxCapture();
        else if (result.finishedToken) sfxFinishToken();
        else sfxMove();

        if (result.wonGame) {
            if (Engine.isGameOver(state.game)) {
                finishMatch();
                return;
            }
            Engine.advancePlayer(state.game);
            proceedToNextTurn();
            return;
        }

        const extra = (state.diceValue === 6 && state.game.consecutiveSixes < 3) ||
            result.captured.length > 0 || result.finishedToken;
        if (!extra) Engine.advancePlayer(state.game);
        proceedToNextTurn();
    }

    function proceedToNextTurn() {
        state.diceValue = null;
        state.validTokens = [];
        state.awaitingChoice = false;
        updateStatus();
        maybeAutoRollForBot();
    }

    function finishMatch() {
        state.over = true;
        const winner = state.game.finished[0];
        const iWon = winner === state.myColor;
        statusEl.innerHTML = iWon
            ? "🏆 Tu as gagné la partie !"
            : "🏁 Partie terminée — <span class='ludo-turn-color ludo-color-text-" + winner + "'>" + COLOR_LABEL[winner] + "</span> a gagné.";
        diceBtn.disabled = true;
        if (iWon) sfxVictory();
    }

    // ---------- Initialisation ----------
    showMenu();
})();
