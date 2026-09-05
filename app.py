"""
Application web multi-joueurs de divertissement social.
- Onglet 1 : Action ou Vérité (bouteille virtuelle)
- Onglet 2 : Confessions / partages personnels
- Onglet 3 : Présence en ligne
- Onglet 4 : Invitation (lien + QR code)
- Onglet 5 : Dames (solo IA ou multijoueur)
- Onglet 6 : MAKS IA (chatbot Gemini)

Lancement : python app.py
Puis ouvrir http://localhost:5000
"""

import eventlet
eventlet.monkey_patch()

import base64
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
from google import genai
from google.genai import types

import database as db

app = Flask(__name__)
app.config["SECRET_KEY"] = "change-moi-en-production"  # à remplacer par une vraie clé secrète
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024  # 30 Mo max par photo/vidéo
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet",
                     max_http_buffer_size=30 * 1024 * 1024)

db.init_db()

# --- MAKS IA (chatbot Gemini) -------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
GEMINI_MODEL = "gemini-3.6-flash"

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


@app.route("/health")
def health_check():
    """Ping de santé : interroge la base pour éviter la pause Supabase après 7 jours d'inactivité."""
    try:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/sw.js")
def service_worker():
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
        "checkers_matches": {},
    }
    db.register_room(code, expires_hours=expires_hours, max_players=max_players)
    return redirect(url_for("room_page", code=code))


@app.route("/join/<code>")
def join_link(code):
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

    db.set_profile_avatar(code, pseudo, avatar_url)

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

    if room["max_players"] and len(room["players"]) >= room["max_players"]:
        already_in = any(p["pseudo"] == pseudo for p in room["players"].values())
        if not already_in:
            emit("error_message", {"message": "Le salon est complet."})
            return

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

    if room.get("spin_order") and pseudo not in room["spin_order"]:
        room["spin_order"].append(pseudo)

    emit("joined", {"pseudo": pseudo, "code": code})
    emit("presence_update", {"players": get_players_list(code)}, to=code)
    emit(
        "system_message",
        {"message": f"{pseudo} a rejoint le salon."},
        to=code,
    )

    emit("turn_update", {"pseudo": get_current_turn_pseudo(room)})
    if room.get("spin_order"):
        broadcast_turn(code)

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

# Dictionnaire global pour conserver la mémoire des conversations
MAKS_SESSIONS = {}

# Dictionnaire global pour conserver la mémoire des conversations MAKS IA
MAKS_SESSIONS = {}

@socketio.on("send_maks_ia_message")
def handle_maks_ia_message(data):
    code = (data.get("code") or "").upper()
    message = (data.get("message") or "").strip()[:4000]
    file_base64 = data.get("file_base64")
    file_mime = data.get("file_mime")
    file_name = data.get("file_name")

    room = ROOMS.get(code)
    if not room:
        return
    sender_info = room["players"].get(request.sid)
    if not sender_info:
        emit("error_message", {"message": "Tu dois être dans le salon pour utiliser MAKS IA."})
        return

    if not gemini_client:
        emit("maks_ia_response", {"error": "MAKS IA n'est pas configuré (clé API manquante côté serveur)."})
        return
    if not message and not file_base64:
        return

    # Clé unique pour la session conversationnelle par utilisateur
    session_key = f"{code}_{sender_info['pseudo']}"
    
    if session_key not in MAKS_SESSIONS:
        MAKS_SESSIONS[session_key] = gemini_client.chats.create(model=GEMINI_MODEL)

    chat = MAKS_SESSIONS[session_key]

    contents = []
    if file_base64 and file_mime:
        file_bytes = base64.b64decode(file_base64)
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime))
    if message:
        contents.append(message)

    try:
        response = chat.send_message(contents)
        answer = response.text or "(Réponse vide.)"
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            answer = "⏳ Quota quotidien atteint pour le modèle gratuit. Attends un instant ou réessaie plus tard !"
        elif "503" in err_str or "UNAVAILABLE" in err_str:
            answer = "⚠️ Le service Google IA est temporairement surchargé. Reessaie dans quelques secondes."
        else:
            answer = f"⚠️ Erreur MAKS IA : {e}"

    emit(
        "maks_ia_response",
        {
            "question": message,
            "file_name": file_name,
            "answer": answer,
            "created_at": datetime.utcnow().strftime("%H:%M"),
        },
    )


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

    rotation_degrees = random.randint(3, 6) * 360 + random.randint(0, 359)

    emit(
        "bottle_result",
        {"chosen_pseudo": chosen["pseudo"], "rotation": rotation_degrees},
        to=code,
    )

    advance_turn(room)
    broadcast_turn(code)


@socketio.on("make_choice")
def handle_choice(data):
    code = (data.get("code") or "").upper()
    choice = data.get("choice")
    intensity = data.get("intensity", "leger")
    pseudo = data.get("pseudo", "?")

    room = ROOMS.get(code)
    if not room:
        emit("error_message", {"message": "Salon introuvable."})
        return
    if choice not in ("action", "verite"):
        emit("error_message", {"message": "Choix invalide."})
        return

    player_info = room["players"].get(request.sid)
    if not player_info or player_info["pseudo"] != room.get("last_spin"):
        emit("error_message", {"message": "Ce n'est pas ton tour."})
        return
    if room.get("pending"):
        emit("error_message", {"message": "Une manche est déjà en cours."})
        return

    question = db.get_random_question(choice, intensity, exclude_ids=room["used_questions"])
    if question is None:
        room["used_questions"] = []
        question = db.get_random_question(choice, intensity, exclude_ids=[])

    if question is None:
        emit("error_message", {"message": "Aucune question disponible pour cette catégorie."})
        return

    room["used_questions"].append(question["id"])

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
    if not pending or pending["category"] != "verite" or not player_info             or player_info["pseudo"] != pending["pseudo"]:
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

    for sid, info in room["players"].items():
        if info["pseudo"].lower() in (sender.lower(), recipient.lower()):
            emit("new_private_message", payload, to=sid)


# --- MAKS IA : chatbot Gemini (texte, image, PDF en entrée) ------------------

@socketio.on("send_maks_ia_message")
def handle_maks_ia_message(data):
    code = (data.get("code") or "").upper()
    message = (data.get("message") or "").strip()[:4000]
    file_base64 = data.get("file_base64")
    file_mime = data.get("file_mime")
    file_name = data.get("file_name")

    room = ROOMS.get(code)
    if not room:
        return
    sender_info = room["players"].get(request.sid)
    if not sender_info:
        emit("error_message", {"message": "Tu dois être dans le salon pour utiliser MAKS IA."})
        return

    if not gemini_client:
        emit("maks_ia_response", {"error": "MAKS IA n'est pas configuré (clé API manquante côté serveur)."})
        return
    if not message and not file_base64:
        return

    try:
        contents = []
        if file_base64 and file_mime:
            file_bytes = base64.b64decode(file_base64)
            contents.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime))
        if message:
            contents.append(message)

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
        )
        answer = response.text or "(Réponse vide.)"
    except Exception as e:
        answer = f"⚠️ Erreur MAKS IA : {e}"

    emit(
        "maks_ia_response",
        {
            "question": message,
            "file_name": file_name,
            "answer": answer,
            "created_at": datetime.utcnow().strftime("%H:%M"),
        },
    )


# --- Jeu de dames -------------------------------------------------------------

@socketio.on("checkers_invite")
def handle_checkers_invite(data):
    code = (data.get("code") or "").upper()
    to_pseudo = (data.get("to_pseudo") or "").strip()
    room = ROOMS.get(code)
    if not room:
        return
    sender_info = room["players"].get(request.sid)
    if not sender_info:
        return
    from_pseudo = sender_info["pseudo"]

    for sid, info in room["players"].items():
        if info["pseudo"] == to_pseudo:
            emit("checkers_invite_received", {"from_pseudo": from_pseudo}, to=sid)


@socketio.on("checkers_decline")
def handle_checkers_decline(data):
    code = (data.get("code") or "").upper()
    from_pseudo = (data.get("from_pseudo") or "").strip()
    room = ROOMS.get(code)
    if not room:
        return
    decliner_info = room["players"].get(request.sid)
    if not decliner_info:
        return

    for sid, info in room["players"].items():
        if info["pseudo"] == from_pseudo:
            emit("checkers_invite_declined", {"pseudo": decliner_info["pseudo"]}, to=sid)


@socketio.on("checkers_accept")
def handle_checkers_accept(data):
    code = (data.get("code") or "").upper()
    from_pseudo = (data.get("from_pseudo") or "").strip()
    room = ROOMS.get(code)
    if not room:
        return
    accepter_info = room["players"].get(request.sid)
    if not accepter_info:
        return
    to_pseudo = accepter_info["pseudo"]

    match_id = uuid.uuid4().hex[:8]
    players = {from_pseudo: "w", to_pseudo: "b"}
    room["checkers_matches"][match_id] = {"players": players, "starting_color": "w"}

    emit(
        "checkers_game_start",
        {"match_id": match_id, "players": players, "starting_color": "w"},
        to=code,
    )


@socketio.on("checkers_move")
def handle_checkers_move(data):
    code = (data.get("code") or "").upper()
    match_id = data.get("match_id")
    from_pos = data.get("from")
    steps = data.get("steps")
    room = ROOMS.get(code)
    if not room:
        return
    sender_info = room["players"].get(request.sid)
    match = room["checkers_matches"].get(match_id)
    if not sender_info or not match:
        return

    emit(
        "checkers_move_made",
        {"match_id": match_id, "pseudo": sender_info["pseudo"], "from": from_pos, "steps": steps},
        to=code,
        include_self=False,
    )


@socketio.on("checkers_resign")
def handle_checkers_resign(data):
    code = (data.get("code") or "").upper()
    match_id = data.get("match_id")
    room = ROOMS.get(code)
    if not room:
        return
    sender_info = room["players"].get(request.sid)
    if not sender_info:
        return

    room["checkers_matches"].pop(match_id, None)
    emit(
        "checkers_resign_notice",
        {"match_id": match_id, "pseudo": sender_info["pseudo"]},
        to=code,
        include_self=False,
    )


@socketio.on("disconnect")
def handle_disconnect():
    for code, room in list(ROOMS.items()):
        if request.sid in room["players"]:
            pseudo = room["players"][request.sid]["pseudo"]
            del room["players"][request.sid]
            emit("presence_update", {"players": get_players_list(code)}, to=code)
            emit("system_message", {"message": f"{pseudo} a quitté le salon."}, to=code)

            remove_from_spin_order(room, pseudo)
            broadcast_turn(code)

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
