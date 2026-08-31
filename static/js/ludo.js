// ============================================================================
// Ludo — moteur de jeu (2 à 4 joueurs), IA incluse
// Modèle : chaque pion a une position RELATIVE à son propre parcours :
//   -1        => encore dans la maison (pas sorti)
//   0 à 50    => sur le parcours commun (52 cases), 0 = case de départ de sa couleur
//   51 à 56   => dans le couloir privé menant au centre (6 cases)
//   57        => arrivé au centre (pion terminé)
// La case réelle sur le plateau commun (pour vérifier les captures) est :
//   (ENTRY[couleur] + position) % 52   — uniquement valable si position <= 50
// ============================================================================

(function () {
    const COLORS = ["red", "blue", "yellow", "green"];
    const ENTRY = { red: 0, blue: 13, yellow: 26, green: 39 };
    const TRACK_LEN = 52;
    const HOME_STRETCH = 6;
    const FINISH_POS = TRACK_LEN - 1 + HOME_STRETCH; // 57 -> position d'arrivée

    // Cases sûres (non capturables) : les 4 départs + 4 cases "étoile" (8 cases après chaque départ)
    const SAFE_SQUARES = new Set();
    COLORS.forEach((c) => {
        SAFE_SQUARES.add(ENTRY[c]);
        SAFE_SQUARES.add((ENTRY[c] + 8) % TRACK_LEN);
    });

    function globalSquare(color, pos) {
        if (pos < 0 || pos > TRACK_LEN - 2) return null; // maison ou couloir privé : pas sur le plateau commun
        return (ENTRY[color] + pos) % TRACK_LEN;
    }

    function createGame(playerColors) {
        // playerColors: tableau de 2 à 4 couleurs parmi COLORS, dans l'ordre de jeu
        const tokens = {};
        playerColors.forEach((color) => {
            tokens[color] = [-1, -1, -1, -1]; // 4 pions, tous à la maison au départ
        });
        return {
            players: playerColors.slice(),
            tokens, // { color: [pos, pos, pos, pos] }
            currentPlayerIndex: 0,
            consecutiveSixes: 0,
            finished: [], // couleurs ayant terminé leurs 4 pions, dans l'ordre d'arrivée
        };
    }

    function currentColor(game) {
        return game.players[game.currentPlayerIndex];
    }

    // Renvoie les indices de pions (0-3) de `color` qui peuvent bouger de `roll` cases
    function movableTokens(game, color, roll) {
        const positions = game.tokens[color];
        const result = [];
        positions.forEach((pos, i) => {
            if (pos === FINISH_POS) return; // déjà arrivé
            if (pos === -1) {
                if (roll === 6) result.push(i); // sortie de maison uniquement avec un 6
                return;
            }
            const newPos = pos + roll;
            if (newPos <= FINISH_POS) result.push(i); // pas de dépassement autorisé
        });
        return result;
    }

    // Applique le déplacement du pion `tokenIndex` de `color` de `roll` cases.
    // Renvoie { captured: [{color, tokenIndex}], finishedToken: bool, wonGame: bool }
    function moveToken(game, color, tokenIndex, roll) {
        const positions = game.tokens[color];
        const pos = positions[tokenIndex];
        const newPos = pos === -1 ? 0 : pos + roll;
        positions[tokenIndex] = newPos;

        const captured = [];
        const landedSquare = globalSquare(color, newPos);
        if (landedSquare !== null && !SAFE_SQUARES.has(landedSquare)) {
            game.players.forEach((otherColor) => {
                if (otherColor === color) return;
                game.tokens[otherColor].forEach((otherPos, otherIdx) => {
                    if (otherPos < 0 || otherPos > TRACK_LEN - 2) return;
                    if (globalSquare(otherColor, otherPos) === landedSquare) {
                        game.tokens[otherColor][otherIdx] = -1; // renvoyé à la maison
                        captured.push({ color: otherColor, tokenIndex: otherIdx });
                    }
                });
            });
        }

        const finishedToken = newPos === FINISH_POS;
        let wonGame = false;
        if (finishedToken && positions.every((p) => p === FINISH_POS) && !game.finished.includes(color)) {
            game.finished.push(color);
            wonGame = true;
        }
        return { captured, finishedToken, wonGame };
    }

    // Fait avancer `game.currentPlayerIndex` au prochain joueur qui n'a pas encore fini,
    // en sautant les couleurs déjà arrivées (4 pions à la maison finale).
    function advancePlayer(game) {
        const n = game.players.length;
        let guard = 0;
        do {
            game.currentPlayerIndex = (game.currentPlayerIndex + 1) % n;
            guard++;
        } while (game.finished.includes(currentColor(game)) && guard <= n);
        game.consecutiveSixes = 0;
    }

    function isGameOver(game) {
        // Terminé quand il ne reste qu'un seul joueur n'ayant pas fini (ou zéro)
        return game.finished.length >= game.players.length - 1;
    }

    function rollDie() {
        return 1 + Math.floor(Math.random() * 6);
    }

    // ---------------------------------------------------------------
    // IA simple : choisit quel pion bouger parmi les coups valides
    // ---------------------------------------------------------------
    function aiChooseToken(game, color, roll, validIndices) {
        if (validIndices.length === 1) return validIndices[0];
        // Priorité : 1) capturer un adversaire  2) sortir un pion de la maison
        // si aucun n'est encore sorti  3) faire avancer le pion le plus proche du but
        let bestIdx = validIndices[0];
        let bestScore = -Infinity;
        validIndices.forEach((idx) => {
            const pos = game.tokens[color][idx];
            const newPos = pos === -1 ? 0 : pos + roll;
            let score = newPos; // avancer davantage = mieux, par défaut

            const landedSquare = globalSquare(color, newPos);
            if (landedSquare !== null && !SAFE_SQUARES.has(landedSquare)) {
                game.players.forEach((otherColor) => {
                    if (otherColor === color) return;
                    game.tokens[otherColor].forEach((otherPos) => {
                        if (otherPos < 0 || otherPos > TRACK_LEN - 2) return;
                        if (globalSquare(otherColor, otherPos) === landedSquare) {
                            score += 100; // grosse priorité à la capture
                        }
                    });
                });
            }
            if (pos === -1) score += 40; // encourage à sortir des pions de la maison
            if (newPos === FINISH_POS) score += 60; // priorité à terminer un pion

            if (score > bestScore) { bestScore = score; bestIdx = idx; }
        });
        return bestIdx;
    }

    window.LudoEngine = {
        COLORS,
        ENTRY,
        TRACK_LEN,
        HOME_STRETCH,
        FINISH_POS,
        SAFE_SQUARES,
        globalSquare,
        createGame,
        currentColor,
        movableTokens,
        moveToken,
        advancePlayer,
        isGameOver,
        rollDie,
        aiChooseToken,
    };
})();
