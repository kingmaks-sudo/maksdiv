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
import os
import random
import string
import time
import uuid
from datetime import datetime

import qrcode
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, send_from_directory, jsonify, abort
)
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, join_room as sio_join_room, leave_room as sio_leave_room, emit

import database as db

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-moi-en-production"  # à remplacer par une vraie clé secrète
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 Mo max par photo/vidéo
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet",
                     max_http_buffer_size=30 * 1024 * 1024)

db.init_db()

# --- Upload des preuves d'action (photo / vidéo) ----------------------------
UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "webm", "mp4", "mov"}
ACTION_MAX_DURATION = 60  # secondes, limite annoncée côté client

# --- Upload des photos de profil --------------------------------------------
AVATAR_FOLDER = os.path.join(app.root_path, "static", "avatars")
os.makedirs(AVATAR_FOLDER, exist_ok=True)
ALLOWED_AVATAR_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

# --- État en mémoire des salons actifs -------------------------------------
# ROOMS[code] = {
#   "players": { sid: {"pseudo": str, "last_seen": ts, "status": "online"} },
#   "used_questions": [ids],
#   "last_spin": pseudo|None,
#   "max_players": int|None,
#   "pending": {
#       "sid": str, "pseudo": str, "category": "action"|"verite",
#       "intensity": str, "question_text": str, "started_at": ts,
#   } | None   -> manche en cours : tant que ce n'est pas None, la bouteille
#                 est bloquée pour tout le salon jusqu'à ce que le joueur
#                 désigné réponde (vérité) ou envoie sa preuve (action).
#   "spin_order": [pseudo, ...] | None  -> ordre de passage pour APPUYER sur la
#                 bouteille, tiré aléatoirement une seule fois au premier lancer.
#   "spin_turn_index": int  -> index dans spin_order du joueur dont c'est le tour.
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
        players.append({
            "pseudo": info["pseudo"],
            "status": status,
            "avatar_url": info.get("avatar_url"),
        })
    return players


# --- Tour de rôle pour lancer la bouteille -----------------------------------

def get_current_turn_pseudo(room):
    order = room.get("spin_order")
    if not order:
        return None
    idx = room.get("spin_turn_index", 0) % len(order)
    return order[idx]


def broadcast_turn(code):
    room = ROOMS.get(code)
    if not room:
        return
    socketio.emit("turn_update", {"pseudo": get_current_turn_pseudo(room)}, to=code)


def advance_turn(room):
    order = room.get("spin_order")
    if not order:
        return
    room["spin_turn_index"] = (room.get("spin_turn_index", 0) + 1) % len(order)


def remove_from_spin_order(room, pseudo):
    """Retire un joueur qui part de l'ordre de passage, en réajustant l'index
    courant pour que le tour ne saute pas ou ne se bloque pas."""
    order = room.get("spin_order")
    if not order or pseudo not in order:
        return
    idx = order.index(pseudo)
    order.remove(pseudo)
    if not order:
        room["spin_order"] = None
        room["spin_turn_index"] = 0
        return
    current = room.get("spin_turn_index", 0)
    if idx < current:
        room["spin_turn_index"] = (current - 1) % len(order)
    else:
        room["spin_turn_index"] = current % len(order)


# --- Routes HTTP -------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/sw.js")
def service_worker():
    # Servi depuis la racine (et pas /static/sw.js) pour que la portée du
    # service worker couvre tout le site, pas seulement /static/.
    response = send_from_directory(
        os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript"
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


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
        "pending": None,
        "spin_order": None,
        "spin_turn_index": 0,
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


@app.route("/room/<code>/messages")
def room_messages(code):
    """Historique du chat instantané, avec l'avatar actuel de chaque pseudo."""
    code = code.upper()
    if not room_exists(code):
        abort(404)
    messages = db.get_chat_messages(code)
    avatars = db.get_profiles_map(code)
    for m in messages:
        m["avatar_url"] = avatars.get(m["pseudo"])
    return jsonify(messages)

@app.route("/room/<code>/private_messages/<other_pseudo>")
def room_private_messages(code):
    """Historique de la conversation privée entre l'utilisateur courant
    (retrouvé via la session) et un autre pseudo du même salon."""
    code = code.upper()
    if not room_exists(code):
        abort(404)
    my_pseudo = session.get("pseudo")
    if not my_pseudo:
        abort(403)
    other_pseudo = request.view_args["other_pseudo"]
    return jsonify(db.get_private_conversation(code, my_pseudo, other_pseudo))


def allowed_action_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in ALLOWED_EXTENSIONS


@app.route("/room/<code>/submit_action", methods=["POST"])
def submit_action(code):
    """Réception de la preuve (photo/vidéo) pour une manche 'Action' en cours."""
    code = code.upper()
    room = ROOMS.get(code)
    if not room:
        return jsonify({"ok": False, "error": "Salon introuvable."}), 404

    pending = room.get("pending")
    pseudo = (request.form.get("pseudo") or "").strip()
    if not pending or pending["category"] != "action" or pending["pseudo"] != pseudo:
        return jsonify({"ok": False, "error": "Aucune manche 'action' en attente pour ce joueur."}), 400

    file = request.files.get("media")
    if not file or file.filename == "":
        return jsonify({"ok": False, "error": "Aucun fichier reçu."}), 400
    if not allowed_action_file(file.filename):
        return jsonify({"ok": False, "error": "Format de fichier non autorisé."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower()
    unique_name = secure_filename(f"{code}_{uuid.uuid4().hex}.{ext}")
    room_dir = os.path.join(UPLOAD_FOLDER, code)
    os.makedirs(room_dir, exist_ok=True)
    file.save(os.path.join(room_dir, unique_name))

    media_kind = "video" if ext in ("webm", "mp4", "mov") else "image"
    media_url = url_for("static", filename=f"uploads/{code}/{unique_name}")

    room["pending"] = None
    socketio.emit(
        "round_result",
        {
            "type": "action",
            "pseudo": pending["pseudo"],
            "intensity": pending["intensity"],
            "question": pending["question_text"],
            "media_url": media_url,
            "media_kind": media_kind,
        },
        to=code,
    )
    return jsonify({"ok": True, "media_url": media_url})


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(e):
    return jsonify({"ok": False, "error": "Fichier trop volumineux (30 Mo max)."}), 413


@app.route("/room/<code>/set_avatar", methods=["POST"])
def set_avatar(code):
    """Upload (ou remplacement) de la photo de profil d'un joueur du salon."""
    code = code.upper()
    room = ROOMS.get(code)
    if not room:
        return jsonify({"ok": False, "error": "Salon introuvable."}), 404

    pseudo = (request.form.get("pseudo") or "").strip()[:24]
    if not pseudo:
        return jsonify({"ok": False, "error": "Pseudo requis."}), 400

    file = request.files.get("avatar")
    if not file or file.filename == "":
        return jsonify({"ok": False, "error": "Aucun fichier reçu."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({"ok": False, "error": "Format d'image non autorisé (jpg, png, webp)."}), 400

    unique_name = secure_filename(f"{code}_{pseudo}_{uuid.uuid4().hex}.{ext}")
    room_dir = os.path.join(AVATAR_FOLDER, code)
    os.makedirs(room_dir, exist_ok=True)
    file.save(os.path.join(room_dir, unique_name))

    avatar_url = url_for("static", filename=f"avatars/{code}/{unique_name}")

    # Persisté en base pour survivre aux redémarrages/reconnexions.
    db.set_profile_avatar(code, pseudo, avatar_url)

    # Mise à jour immédiate de l'état en mémoire pour ce joueur (peu importe son sid).
    for info in room["players"].values():
        if info["pseudo"].lower() == pseudo.lower():
            info["avatar_url"] = avatar_url

    socketio.emit("presence_update", {"players": get_players_list(code)}, to=code)
    return jsonify({"ok": True, "avatar_url": avatar_url})


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

    # Vérifier l'unicité du pseudo dans le salon.
    # Si un ancien sid porte déjà ce pseudo, on considère qu'il s'agit d'une
    # RECONNEXION (Socket.IO change de sid à chaque reconnexion) et on
    # remplace l'ancienne entrée au lieu de bloquer le joueur.
    for old_sid, info in list(room["players"].items()):
        if info["pseudo"].lower() == pseudo.lower() and old_sid != request.sid:
            del room["players"][old_sid]

    sio_join_room(code)
    room["players"][request.sid] = {
        "pseudo": pseudo,
        "last_seen": time.time(),
        "status": "online",
        "avatar_url": db.get_profile_avatar(code, pseudo),
    }
    session["pseudo"] = pseudo
    session["code"] = code

    # Si la partie a déjà commencé (ordre de passage établi) et que ce pseudo
    # n'y figure pas encore (nouveau joueur en cours de partie), on l'ajoute
    # à la fin de la file — il aura son tour plus tard, sans perturber l'ordre déjà tiré.
    if room.get("spin_order") and pseudo not in room["spin_order"]:
        room["spin_order"].append(pseudo)

    emit("joined", {"pseudo": pseudo, "code": code})
    emit("presence_update", {"players": get_players_list(code)}, to=code)
    emit(
        "system_message",
        {"message": f"{pseudo} a rejoint le salon."},
        to=code,
    )

    # On informe ce client précis (et tout le salon, au cas où la liste a
    # changé) de qui a la main pour lancer la bouteille.
    emit("turn_update", {"pseudo": get_current_turn_pseudo(room)})
    if room.get("spin_order"):
        broadcast_turn(code)

    # Si une manche était déjà en cours (ex: reconnexion après coupure réseau),
    # on renvoie son état à ce client précis pour qu'il retrouve l'UI de blocage.
    pending = room.get("pending")
    if pending:
        emit(
            "question_drawn",
            {
                "category": pending["category"],
                "intensity": pending["intensity"],
                "text": pending["question_text"],
                "chosen_by": pending["pseudo"],
            },
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

    if room.get("pending"):
        emit("error_message", {"message": "Une manche est en cours, attends la réponse avant de relancer la bouteille."})
        return

    players = list(room["players"].values())
    if len(players) < 2:
        emit("error_message", {"message": "Il faut au moins 2 joueurs pour lancer la bouteille."})
        return

    # Premier lancer de la partie : on tire l'ordre de passage une seule fois.
    if not room.get("spin_order"):
        pseudos = [p["pseudo"] for p in players]
        random.shuffle(pseudos)
        room["spin_order"] = pseudos
        room["spin_turn_index"] = 0
        broadcast_turn(code)

    current_turn_pseudo = get_current_turn_pseudo(room)
    sender_info = room["players"].get(request.sid)
    if not sender_info or sender_info["pseudo"] != current_turn_pseudo:
        emit(
            "error_message",
            {"message": f"Ce n'est pas ton tour de lancer la bouteille. C'est à {current_turn_pseudo}."},
        )
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

    # Le lancer a été utilisé : on passe la main au joueur suivant dans l'ordre.
    advance_turn(room)
    broadcast_turn(code)


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

    # Seul le joueur désigné par la bouteille peut choisir, et une seule fois.
    player_info = room["players"].get(request.sid)
    if not player_info or player_info["pseudo"] != room.get("last_spin"):
        emit("error_message", {"message": "Ce n'est pas ton tour."})
        return
    if room.get("pending"):
        emit("error_message", {"message": "Une manche est déjà en cours."})
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

    # Ouvre la manche : bloque la bouteille pour tout le monde jusqu'à
    # ce que le joueur désigné réponde (vérité) ou envoie sa preuve (action).
    room["pending"] = {
        "sid": request.sid,
        "pseudo": pseudo,
        "category": choice,
        "intensity": intensity,
        "question_text": question["text"],
        "started_at": time.time(),
    }

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


@socketio.on("submit_truth_answer")
def handle_truth_answer(data):
    code = (data.get("code") or "").upper()
    answer = (data.get("answer") or "").strip()[:800]

    room = ROOMS.get(code)
    if not room:
        emit("error_message", {"message": "Salon introuvable."})
        return

    pending = room.get("pending")
    player_info = room["players"].get(request.sid)
    if not pending or pending["category"] != "verite" or not player_info \
            or player_info["pseudo"] != pending["pseudo"]:
        emit("error_message", {"message": "Aucune manche 'vérité' en attente pour toi."})
        return
    if not answer:
        emit("error_message", {"message": "La réponse ne peut pas être vide."})
        return

    room["pending"] = None
    emit(
        "round_result",
        {
            "type": "verite",
            "pseudo": pending["pseudo"],
            "intensity": pending["intensity"],
            "question": pending["question_text"],
            "answer": answer,
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

    confession_id = db.save_confession(code, pseudo, message, anonymous)
    display_name = "Anonyme" if anonymous else pseudo

    emit(
        "new_confession",
        {
            "id": confession_id,
            "pseudo": display_name,
            "message": message,
            "created_at": datetime.utcnow().strftime("%H:%M"),
        },
        to=code,
    )


@socketio.on("post_comment")
def handle_comment(data):
    code = (data.get("code") or "").upper()
    pseudo = (data.get("pseudo") or "Anonyme").strip()[:24]
    message = (data.get("message") or "").strip()[:300]
    confession_id = data.get("confession_id")

    if not room_exists(code) or not message or not confession_id:
        return

    db.save_comment(confession_id, code, pseudo, message)

    emit(
        "new_comment",
        {
            "confession_id": confession_id,
            "pseudo": pseudo,
            "message": message,
            "created_at": datetime.utcnow().strftime("%H:%M"),
        },
        to=code,
    )


@socketio.on("send_chat_message")
def handle_chat_message(data):
    """Discussion instantanée : diffusion immédiate à tout le salon (+ historique en base)."""
    code = (data.get("code") or "").upper()
    message = (data.get("message") or "").strip()[:1000]

    room = ROOMS.get(code)
    if not room or not message:
        return

    player_info = room["players"].get(request.sid)
    if not player_info:
        emit("error_message", {"message": "Tu dois être dans le salon pour discuter."})
        return
    pseudo = player_info["pseudo"]

    message_id = db.save_chat_message(code, pseudo, message)

    emit(
        "new_chat_message",
        {
            "id": message_id,
            "pseudo": pseudo,
            "avatar_url": player_info.get("avatar_url"),
            "message": message,
            "created_at": datetime.utcnow().strftime("%H:%M"),
        },
        to=code,
    )


@socketio.on("send_private_message")
def handle_private_message(data):
    """Message privé entre deux joueurs d'un même salon. Diffusé uniquement
    aux sockets des deux personnes concernées (pas à tout le salon)."""
    code = (data.get("code") or "").upper()
    recipient = (data.get("recipient") or "").strip()[:24]
    message = (data.get("message") or "").strip()[:1000]

    room = ROOMS.get(code)
    if not room or not message or not recipient:
        return

    sender_info = room["players"].get(request.sid)
    if not sender_info:
        emit("error_message", {"message": "Tu dois être dans le salon pour envoyer un message privé."})
        return
    sender = sender_info["pseudo"]

    if recipient.lower() == sender.lower():
        return

    message_id = db.save_private_message(code, sender, recipient, message)
    payload = {
        "id": message_id,
        "sender": sender,
        "recipient": recipient,
        "message": message,
        "created_at": datetime.utcnow().strftime("%H:%M"),
    }

    # Envoi uniquement au destinataire (tous ses sids, en cas de multi-onglets)
    # et à l'expéditeur lui-même (pour que son propre message s'affiche aussi).
    for sid, info in room["players"].items():
        if info["pseudo"].lower() in (sender.lower(), recipient.lower()):
            emit("new_private_message", payload, to=sid)


@socketio.on("disconnect")
def handle_disconnect():
    for code, room in list(ROOMS.items()):
        if request.sid in room["players"]:
            pseudo = room["players"][request.sid]["pseudo"]
            del room["players"][request.sid]
            emit("presence_update", {"players": get_players_list(code)}, to=code)
            emit("system_message", {"message": f"{pseudo} a quitté le salon."}, to=code)

            # Retire le joueur de l'ordre de passage de la bouteille (s'il y
            # figurait) et notifie le salon du tour éventuellement mis à jour.
            remove_from_spin_order(room, pseudo)
            broadcast_turn(code)

            # Si le joueur qui partait était en pleine manche, on débloque
            # le salon pour ne pas laisser tout le monde bloqué indéfiniment.
            pending = room.get("pending")
            if pending and pending["sid"] == request.sid:
                room["pending"] = None
                emit(
                    "round_cancelled",
                    {"pseudo": pseudo, "message": f"{pseudo} a quitté avant de terminer sa manche."},
                    to=code,
                )
            break


if __name__ == "__main__":
    print("Serveur lancé sur http://localhost:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
