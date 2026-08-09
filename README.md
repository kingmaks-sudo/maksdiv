# Action ou Vérité — Jeu social multi-joueurs

Application web temps réel : les joueurs rejoignent un salon via un code
ou un lien, sous pseudo (pas de compte requis).

## Installation

```bash
cd action_verite
pip install -r requirements.txt
python app.py
```

Puis ouvre **http://localhost:5000** dans ton navigateur.

Pour que d'autres personnes rejoignent depuis leur propre appareil (même
réseau WiFi), utilise ton adresse IP locale au lieu de `localhost`,
par exemple `http://192.168.1.23:5000`. Pour un accès depuis Internet,
il faudra déployer l'app sur un serveur (Render, Railway, VPS, etc.) et
utiliser un vrai nom de domaine ou une IP publique.

## Fonctionnalités

- **Créer un salon** : génère un code à 6 caractères + lien direct
  `/join/<code>`, avec options de nombre de places max et d'expiration.
- **Onglet Action ou Vérité** : bouteille animée qui désigne un joueur au
  hasard ; questions tirées d'une banque SQLite (3 niveaux d'intensité),
  sans répétition dans une même session.
- **Onglet Confessions** : chaque participant peut publier un message sur
  lui-même (pseudo ou anonyme), stocké en base et visible par tous les
  membres du salon. Conçu comme un espace d'auto-expression volontaire —
  pas un espace pour désigner ou "outer" quelqu'un d'autre sans son accord.
- **Onglet En ligne** : liste des participants connectés en temps réel
  avec statut en ligne / inactif (heartbeat toutes les 20s).
- **Onglet Inviter** : QR code généré à la volée + lien copiable.

## Structure du projet

```
action_verite/
├── app.py                  # Serveur Flask + Socket.IO (routes + événements temps réel)
├── database.py              # Accès SQLite (questions, confessions, salons)
├── questions_seed.json      # Banque de questions de départ (modifiable)
├── requirements.txt
├── templates/
│   ├── index.html            # Accueil : créer / rejoindre un salon
│   └── room.html              # Interface du salon (4 onglets)
└── static/
    ├── css/style.css          # Thème sombre
    └── js/app.js               # Logique client Socket.IO
```

## Personnaliser les questions

Édite `questions_seed.json` avant le premier lancement (il est importé une
seule fois dans `app.db`). Pour réinitialiser la banque de questions,
supprime `app.db` et relance l'app.

## Notes importantes

- Le "18 ans ou plus" sur la page d'accueil est une **auto-déclaration**,
  pas une vérification d'âge réelle — à garder à l'esprit si tu diffuses
  le lien largement.
- Les salons sont stockés en mémoire (RAM) : si tu redémarres le serveur,
  les salons actifs et les compteurs de présence sont perdus (les
  confessions, elles, restent en base SQLite).
- Pour un usage en production avec beaucoup de monde simultanément,
  remplace le stockage en mémoire des salons par Redis, et utilise
  `eventlet` ou `gevent` comme worker Socket.IO au lieu de `threading`.
