"""
Application web multi-joueurs de divertissement social.
- Onglet 1 : Action ou Vérité (bouteille virtuelle)
- Onglet 2 : Confessions / partages personnels
- Onglet 3 : Présence en ligne
- Onglet 4 : Invitation (lien + QR code)

Lancement : python app.py
Puis ouvrir http://localhost:5000
"""

import eventlet
eventlet.monkey_patch()

import io
import random
import string
import time
from datetime import datetime

import qrcode
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, jsonify, abort
)
from flask_socketio import SocketIO, join_room as sio_join_room, leave_room as sio_leave_room, emit

import database as db

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-moi-en-production"  # à remplacer par une vraie clé secrète
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

db.init_db()

# --- État en mémoire des salons actifs -------------------------------------
# ROOMS[code] = {
#   "players": { sid: {"pseudo": str, "last_seen": ts, "status": "online"} },
#   "used_questions": [ids],
#   "last_spin": pseudo|None,
#   "max_players": int|None,
# }
ROOMS = {}

HEARTBEAT_TIMEOUT = 60  # secondes avant de considérer un joueur "inactif"


def generate_room_code(length=6):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choices(alphabet, k=length))
        if code not in ROOMS:
            return code


def room_exists(code):
    return code in ROOMS and not db.is_room_expired(code)


def get_players_list(code):
    room = ROOMS.get(code)
    if not room:
        return []
    now = time.time()
    players = []
    for sid, info in room["players"].items():
        status = "online" if (now - info["last_seen"]) < HEARTBEAT_TIMEOUT else "inactif"
        players.append({"pseudo": info["pseudo"], "status": status})
    return players


# --- Routes HTTP -------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create_room", methods=["POST"])
def create_room():
    max_players = request.form.get("max_players", type=int) or None
    expires_hours = request.form.get("expires_hours", type=int) or None

    code = generate_room_code()
    ROOMS[code] = {
        "players": {},
        "used_questions": [],
        "last_spin": None,
        "max_players": max_players,
    }
    db.register_room(code, expires_hours=expires_hours, max_players=max_players)
    return redirect(url_for("room_page", code=code))


@app.route("/join/<code>")
def join_link(code):
    """Point d'entrée pour un lien d'invitation direct."""
    code = code.upper()
    if not room_exists(code):
        return render_template("index.html", error=f"Le salon {code} n'existe pas ou a expiré.")
    return redirect(url_for("room_page", code=code))


@app.route("/join_by_code", methods=["POST"])
def join_by_code():
    code = (request.form.get("code") or "").strip().upper()
    if not room_exists(code):
        return render_template("index.html", error=f"Le salon {code} n'existe pas ou a expiré.")
    return redirect(url_for("room_page", code=code))


@app.route("/room/<code>")
def room_page(code):
    code = code.upper()
    if not room_exists(code):
        return render_template("index.html", error=f"Le salon {code} n'existe pas ou a expiré.")
    join_url = request.host_url.rstrip("/") + url_for("join_link", code=code)
    room_meta = db.get_room_meta(code)
    return render_template(
        "room.html",
        code=code,
        join_url=join_url,
        max_players=room_meta.get("max_players") if room_meta else None,
    )


@app.route("/room/<code>/qrcode.png")
def room_qrcode(code):
    code = code.upper()
    if not room_exists(code):
        abort(404)
    join_url = request.host_url.rstrip("/") + url_for("join_link", code=code)
    img = qrcode.make(join_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/room/<code>/confessions")
def room_confessions(code):
    code = code.upper()
    if not room_exists(code):
        abort(404)
    return jsonify(db.get_confessions(code))


# --- Événements Socket.IO ----------------------------------------------------

@socketio.on("join_room_event")
def handle_join(data):
    code = (data.get("code") or "").upper()
    pseudo = (data.get("pseudo") or "").strip()[:24]

    if not room_exists(code):
        emit("error_message", {"message": "Salon introuvable ou expiré."})
        return
    if not pseudo:
        emit("error_message", {"message": "Pseudo requis."})
        return

    room = ROOMS[code]

    # Vérifier la limite de places
    if room["max_players"] and len(room["players"]) >= room["max_players"]:
        already_in = any(p["pseudo"] == pseudo for p in room["players"].values())
        if not already_in:
            emit("error_message", {"message": "Le salon est complet."})
            return

    # Vérifier l'unicité du pseudo dans le salon
    for info in room["players"].values():
        if info["pseudo"].lower() == pseudo.lower():
            emit("error_message", {"message": "Ce pseudo est déjà pris dans ce salon."})
            return

    sio_join_room(code)
    room["players"][request.sid] = {
        "pseudo": pseudo,
        "last_seen": time.time(),
        "status": "online",
    }
    session["pseudo"] = pseudo
    session["code"] = code

    emit("joined", {"pseudo": pseudo, "code": code})
    emit("presence_update", {"players": get_players_list(code)}, to=code)
    emit(
        "system_message",
        {"message": f"{pseudo} a rejoint le salon."},
        to=code,
    )


@socketio.on("heartbeat")
def handle_heartbeat(data):
    code = (data.get("code") or "").upper()
    room = ROOMS.get(code)
    if room and request.sid in room["players"]:
        room["players"][request.sid]["last_seen"] = time.time()


@socketio.on("spin_bottle")
def handle_spin(data):
    code = (data.get("code") or "").upper()
    room = ROOMS.get(code)
    if not room:
        emit("error_message", {"message": "Salon introuvable."})
        return

    players = list(room["players"].values())
    if len(players) < 2:
        emit("error_message", {"message": "Il faut au moins 2 joueurs pour lancer la bouteille."})
        return

    chosen = random.choice(players)
    room["last_spin"] = chosen["pseudo"]

    # Angle de rotation aléatoire pour l'animation côté client (plusieurs tours + offset)
    rotation_degrees = random.randint(3, 6) * 360 + random.randint(0, 359)

    emit(
        "bottle_result",
        {"chosen_pseudo": chosen["pseudo"], "rotation": rotation_degrees},
        to=code,
    )


@socketio.on("make_choice")
def handle_choice(data):
    code = (data.get("code") or "").upper()
    choice = data.get("choice")  # 'action' ou 'verite'
    intensity = data.get("intensity", "leger")  # 'leger', 'ose', 'tres_ose'
    pseudo = data.get("pseudo", "?")

    room = ROOMS.get(code)
    if not room:
        emit("error_message", {"message": "Salon introuvable."})
        return
    if choice not in ("action", "verite"):
        emit("error_message", {"message": "Choix invalide."})
        return

    question = db.get_random_question(choice, intensity, exclude_ids=room["used_questions"])
    if question is None:
        # Toutes les questions ont été utilisées : on réinitialise le cycle pour cette catégorie
        room["used_questions"] = []
        question = db.get_random_question(choice, intensity, exclude_ids=[])

    if question is None:
        emit("error_message", {"message": "Aucune question disponible pour cette catégorie."})
        return

    room["used_questions"].append(question["id"])

    emit(
        "question_drawn",
        {
            "category": choice,
            "intensity": intensity,
            "text": question["text"],
            "chosen_by": pseudo,
        },
        to=code,
    )


@socketio.on("post_confession")
def handle_confession(data):
    code = (data.get("code") or "").upper()
    pseudo = data.get("pseudo", "Anonyme")
    message = (data.get("message") or "").strip()[:500]
    anonymous = bool(data.get("anonymous", False))

    if not room_exists(code) or not message:
        return

    db.save_confession(code, pseudo, message, anonymous)
    display_name = "Anonyme" if anonymous else pseudo

    emit(
        "new_confession",
        {
            "pseudo": display_name,
            "message": message,
            "created_at": datetime.utcnow().strftime("%H:%M"),
        },
        to=code,
    )


@socketio.on("disconnect")
def handle_disconnect():
    for code, room in list(ROOMS.items()):
        if request.sid in room["players"]:
            pseudo = room["players"][request.sid]["pseudo"]
            del room["players"][request.sid]
            emit("presence_update", {"players": get_players_list(code)}, to=code)
            emit("system_message", {"message": f"{pseudo} a quitté le salon."}, to=code)
            break


if __name__ == "__main__":
    print("Serveur lancé sur http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
from flask import render_template_string, request, Response

# Mot de passe pour accéder à la page admin (à modifier)
ADMIN_PASSWORD = "KEMA03062002"

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    auth = request.authorization
    if not auth or auth.password != ADMIN_PASSWORD:
        return Response(
            'Accès refusé.', 401,
            {'WWW-Authenticate': 'Basic realm="Accès Admin"'}
        )

    from database import get_all_rooms, delete_room

    # Action de suppression
    if request.method == 'POST' and 'delete_code' in request.form:
        delete_room(request.form['delete_code'])

    rooms = get_all_rooms()

    html = """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Panneau Admin Complete</title>
        <style>
            body { font-family: sans-serif; background: #121212; color: #fff; padding: 15px; }
            h1 { color: #a855f7; }
            table { width: 100%; border-collapse: collapse; margin-top: 15px; }
            th, td { border: 1px solid #333; padding: 10px; text-align: left; font-size: 14px; }
            th { background: #1e1e2e; }
            .btn-del { background: #ef4444; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }
        </style>
    </head>
    <body>
        <h1>📊 Tableau de bord Admin</h1>
        <p><strong>Salons actifs :</strong> {{ rooms|length }}</p>

        <table>
            <thead>
                <tr>
                    <th>Code</th>
                    <th>Créateurs / Joueurs</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {% for room in rooms %}
                <tr>
                    <td><strong>{{ room['code'] }}</strong></td>
                    <td>{{ room['players'] if 'players' in room.keys() and room['players'] else 'Aucun joueur inscrit' }}</td>
                    <td>
                        <form method="POST" style="display:inline;">
                            <input type="hidden" name="delete_code" value="{{ room['code'] }}">
                            <button type="submit" class="btn-del" onclick="return confirm('Supprimer ce salon ?')">Supprimer</button>
                        </form>
                    </td>
                </tr>
                {% else %}
                <tr><td colspan="3">Aucun salon actif.</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </body>
    </html>
    """
    return render_template_string(html, rooms=rooms)
@socketio.on('send_verite_answer')
def handle_verite_answer(data):
    room = data.get('room')
    answer = data.get('answer')
    player = session.get('pseudo', 'Un joueur')
    
    # Broadcast de la réponse à tous les membres de la pièce
    emit('verite_answer_received', {'player': player, 'answer': answer}, room=room)
@socketio.on('send_action_proof')
def handle_action_proof(data):
    room = data.get('room')
    image_data = data.get('image')
    player = session.get('pseudo', 'Un joueur')
    
    # Transmet la photo reçue à l'ensemble de la pièce
    emit('action_proof_received', {'player': player, 'image': image_data}, room=room)
