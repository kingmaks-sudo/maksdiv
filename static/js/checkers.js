// ============================================================================
// Dames françaises (10x10) — moteur, IA, rendu, intégration Socket.IO
// Règles implémentées : prise obligatoire, prises multiples (rafle),
// dames "volantes" (déplacement/prise longue distance en diagonale).
// Simplification assumée : quand plusieurs rafles sont possibles, le joueur
// n'est PAS obligé de choisir celle qui capture le plus de pièces (règle de
// la "plus grande prise" non appliquée) — juste obligé de capturer si possible.
// ============================================================================

(function () {
    const SIZE = 10;

    // ---------------------------------------------------------------
    // État du plateau
    // ---------------------------------------------------------------
    function createInitialBoard() {
        const board = Array.from({ length: SIZE }, () => Array(SIZE).fill(null));
        for (let r = 0; r < SIZE; r++) {
            for (let c = 0; c < SIZE; c++) {
                if ((r + c) % 2 === 0) continue; // seules les cases sombres sont jouables
                if (r < 4) board[r][c] = { color: "b", king: false };
                else if (r > 5) board[r][c] = { color: "w", king: false };
            }
        }
        return board;
    }

    function cloneBoard(board) {
        return board.map((row) => row.map((cell) => (cell ? { ...cell } : null)));
    }

    function onBoard(r, c) {
        return r >= 0 && r < SIZE && c >= 0 && c < SIZE;
    }

    function forwardDir(color) {
        return color === "w" ? -1 : 1;
    }

    function promotionRow(color) {
        return color === "w" ? 0 : SIZE - 1;
    }

    // ---------------------------------------------------------------
    // Génération des coups pour UNE pièce (un seul "saut" à la fois)
    // ---------------------------------------------------------------
    function pieceCaptures(board, r, c) {
        const piece = board[r][c];
        if (!piece) return [];
        const results = [];
        const dirs = [[-1, -1], [-1, 1], [1, -1], [1, 1]];

        if (!piece.king) {
            for (const [dr, dc] of dirs) {
                const mr = r + dr, mc = c + dc;
                const lr = r + 2 * dr, lc = c + 2 * dc;
                if (!onBoard(lr, lc)) continue;
                const mid = board[mr] && board[mr][mc];
                if (mid && mid.color !== piece.color && board[lr][lc] === null) {
                    results.push({ to: [lr, lc], captured: [mr, mc] });
                }
            }
        } else {
            // Dame volante : parcourt chaque diagonale
            for (const [dr, dc] of dirs) {
                let rr = r + dr, cc = c + dc;
                // avance tant que la case est vide
                while (onBoard(rr, cc) && board[rr][cc] === null) {
                    rr += dr; cc += dc;
                }
                if (!onBoard(rr, cc)) continue;
                const target = board[rr][cc];
                if (target && target.color !== piece.color) {
                    // pièce adverse trouvée : les cases juste après (vides) sont des atterrissages possibles
                    let lr = rr + dr, lc = cc + dc;
                    while (onBoard(lr, lc) && board[lr][lc] === null) {
                        results.push({ to: [lr, lc], captured: [rr, cc] });
                        lr += dr; lc += dc;
                    }
                }
                // sinon (pièce de la même couleur) : direction bloquée, rien à faire
            }
        }
        return results;
    }

    function pieceSimpleMoves(board, r, c) {
        const piece = board[r][c];
        if (!piece) return [];
        const results = [];
        const dirs = piece.king
            ? [[-1, -1], [-1, 1], [1, -1], [1, 1]]
            : [[forwardDir(piece.color), -1], [forwardDir(piece.color), 1]];

        if (!piece.king) {
            for (const [dr, dc] of dirs) {
                const rr = r + dr, cc = c + dc;
                if (onBoard(rr, cc) && board[rr][cc] === null) {
                    results.push({ to: [rr, cc] });
                }
            }
        } else {
            for (const [dr, dc] of dirs) {
                let rr = r + dr, cc = c + dc;
                while (onBoard(rr, cc) && board[rr][cc] === null) {
                    results.push({ to: [rr, cc] });
                    rr += dr; cc += dc;
                }
            }
        }
        return results;
    }

    // Y a-t-il au moins une capture possible pour cette couleur sur tout le plateau ?
    function colorHasCapture(board, color) {
        for (let r = 0; r < SIZE; r++) {
            for (let c = 0; c < SIZE; c++) {
                const p = board[r][c];
                if (p && p.color === color && pieceCaptures(board, r, c).length > 0) return true;
            }
        }
        return false;
    }

    function applyStep(board, from, to, captured) {
        const [r, c] = from, [tr, tc] = to;
        const piece = board[r][c];
        board[r][c] = null;
        if (captured) board[captured[0]][captured[1]] = null;
        let promoted = false;
        if (!piece.king && tr === promotionRow(piece.color)) {
            piece.king = true;
            promoted = true;
        }
        board[tr][tc] = piece;
        return promoted;
    }

    // ---------------------------------------------------------------
    // Enumère les "tours complets" possibles (utilisé par l'IA et pour
    // valider un coup reçu de l'adversaire en multijoueur)
    // ---------------------------------------------------------------
    function enumerateFullTurns(board, color) {
        const mustCapture = colorHasCapture(board, color);
        const turns = [];

        function dfsCapture(curBoard, r, c, startPos, stepsSoFar, capturedSoFar) {
            const caps = pieceCaptures(curBoard, r, c);
            if (caps.length === 0) {
                turns.push({ from: startPos, steps: stepsSoFar, endBoard: curBoard, capturedCount: capturedSoFar });
                return;
            }
            for (const cap of caps) {
                const nextBoard = cloneBoard(curBoard);
                applyStep(nextBoard, [r, c], cap.to, cap.captured);
                dfsCapture(nextBoard, cap.to[0], cap.to[1], startPos, [...stepsSoFar, { to: cap.to, captured: cap.captured }], capturedSoFar + 1);
            }
        }

        for (let r = 0; r < SIZE; r++) {
            for (let c = 0; c < SIZE; c++) {
                const p = board[r][c];
                if (!p || p.color !== color) continue;
                if (mustCapture) {
                    if (pieceCaptures(board, r, c).length > 0) {
                        dfsCapture(board, r, c, [r, c], [], 0);
                    }
                } else {
                    for (const mv of pieceSimpleMoves(board, r, c)) {
                        const nextBoard = cloneBoard(board);
                        applyStep(nextBoard, [r, c], mv.to, null);
                        turns.push({ from: [r, c], steps: [{ to: mv.to, captured: null }], endBoard: nextBoard, capturedCount: 0 });
                    }
                }
            }
        }
        return turns;
    }

    function colorPieceCount(board, color) {
        let men = 0, kings = 0;
        for (let r = 0; r < SIZE; r++)
            for (let c = 0; c < SIZE; c++) {
                const p = board[r][c];
                if (p && p.color === color) p.king ? kings++ : men++;
            }
        return { men, kings };
    }

    function hasAnyMove(board, color) {
        return enumerateFullTurns(board, color).length > 0;
    }

    function checkGameOver(board, colorToPlay) {
        if (!hasAnyMove(board, colorToPlay)) {
            return colorToPlay === "w" ? "b" : "w"; // l'autre couleur gagne
        }
        return null;
    }

    // ---------------------------------------------------------------
    // IA — évaluation simple + minimax (profondeur 3) avec élagage alpha-bêta
    // ---------------------------------------------------------------
    function evaluateBoard(board, aiColor) {
        const opp = aiColor === "w" ? "b" : "w";
        const mine = colorPieceCount(board, aiColor);
        const theirs = colorPieceCount(board, opp);
        let score = (mine.men * 100 + mine.kings * 300) - (theirs.men * 100 + theirs.kings * 300);
        // léger bonus d'avancement pour les pions (encourage la progression)
        for (let r = 0; r < SIZE; r++) {
            for (let c = 0; c < SIZE; c++) {
                const p = board[r][c];
                if (!p || p.king) continue;
                const advance = p.color === "w" ? (SIZE - 1 - r) : r;
                score += (p.color === aiColor ? 1 : -1) * advance * 2;
            }
        }
        return score;
    }

    function minimax(board, color, aiColor, depth, alpha, beta) {
        const opp = color === "w" ? "b" : "w";
        const turns = enumerateFullTurns(board, color);
        if (depth === 0 || turns.length === 0) {
            if (turns.length === 0) {
                // ce joueur ne peut plus bouger : défaite pour lui
                return color === aiColor ? -100000 : 100000;
            }
            return evaluateBoard(board, aiColor);
        }
        if (color === aiColor) {
            let best = -Infinity;
            for (const t of turns) {
                const val = minimax(t.endBoard, opp, aiColor, depth - 1, alpha, beta);
                best = Math.max(best, val);
                alpha = Math.max(alpha, val);
                if (beta <= alpha) break;
            }
            return best;
        } else {
            let best = Infinity;
            for (const t of turns) {
                const val = minimax(t.endBoard, opp, aiColor, depth - 1, alpha, beta);
                best = Math.min(best, val);
                beta = Math.min(beta, val);
                if (beta <= alpha) break;
            }
            return best;
        }
    }

    function aiChooseTurn(board, aiColor, depth) {
        const turns = enumerateFullTurns(board, aiColor);
        if (turns.length === 0) return null;
        let best = null, bestScore = -Infinity;
        const opp = aiColor === "w" ? "b" : "w";
        for (const t of turns) {
            const score = minimax(t.endBoard, opp, aiColor, depth - 1, -Infinity, Infinity);
            if (score > bestScore) { bestScore = score; best = t; }
        }
        return best;
    }

    // ---------------------------------------------------------------
    // Export global
    // ---------------------------------------------------------------
    window.CheckersEngine = {
        SIZE,
        createInitialBoard,
        cloneBoard,
        pieceCaptures,
        pieceSimpleMoves,
        colorHasCapture,
        applyStep,
        enumerateFullTurns,
        checkGameOver,
        aiChooseTurn,
    };
})();
