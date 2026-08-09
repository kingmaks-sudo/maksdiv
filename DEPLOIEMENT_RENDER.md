# Déploiement 100% gratuit sur Render — MAKSDIV

Aucune carte bancaire, aucun VPS à payer. Ton site sera accessible à
`https://maksdiv.onrender.com` (ou un nom proche si "maksdiv" est déjà pris
sur Render).

## 1. Mettre le code sur GitHub (gratuit)

1. Crée un compte sur **github.com** (gratuit)
2. Crée un nouveau dépôt (repository), par exemple `maksdiv`
3. Depuis ton ordinateur, dans le dossier `action_verite` :
```bash
cd action_verite
git init
git add .
git commit -m "Version initiale MAKSDIV"
git branch -M main
git remote add origin https://github.com/TON_PSEUDO/maksdiv.git
git push -u origin main
```

Si tu n'as pas `git` installé ou que tu préfères une méthode sans ligne de
commande : sur la page de ton nouveau dépôt GitHub, il y a un bouton
**"uploading an existing file"** — tu peux glisser-déposer tous les fichiers
du dossier `action_verite` directement depuis ton navigateur.

## 2. Créer le compte Render

1. Va sur **render.com**, inscris-toi avec ton email ou ton compte GitHub
   (aucune carte bancaire demandée pour le plan gratuit)
2. Clique sur **New +** → **Web Service**
3. Connecte ton dépôt GitHub `maksdiv`

## 3. Configurer le service

Render détecte automatiquement le fichier `render.yaml` inclus dans le
projet et pré-remplit tout. Vérifie que c'est bien :
- **Environment** : Python
- **Build Command** : `pip install -r requirements.txt`
- **Start Command** : `gunicorn -k eventlet -w 1 app:app`
- **Plan** : Free

Clique sur **Create Web Service**. Le premier déploiement prend 2-5 minutes.

## 4. Choisir le nom de ton site

Dans les réglages du service (**Settings**), tu peux changer le sous-domaine
par défaut pour `maksdiv` → ton site sera sur `https://maksdiv.onrender.com`.
Si ce nom est déjà pris par quelqu'un d'autre sur Render, essaie
`maksdiv-app` ou `maksdiv-officiel`.

## 5. Tester

Une fois déployé, ouvre l'URL. Crée un salon, partage le lien d'invitation
avec quelqu'un sur un autre réseau (4G) pour vérifier que le Socket.IO
fonctionne bien à travers Render.

## Mettre à jour le code plus tard

```bash
git add .
git commit -m "Mise à jour"
git push
```
Render redéploie automatiquement à chaque `push`.

## Limites du plan gratuit à connaître

- **Mise en veille** : après 15 minutes sans visite, le service s'endort.
  Le premier visiteur après une pause attend ~30-50 secondes le temps du
  réveil — normal, pas un bug.
- **Stockage non garanti permanent** : la base SQLite (`app.db`, qui
  contient les confessions) peut être réinitialisée à chaque nouveau
  déploiement du code. Pour un usage occasionnel entre amis ce n'est
  généralement pas gênant ; si tu veux vraiment conserver les confessions
  sur le long terme, on pourra migrer vers une base de données gratuite
  externe (ex: Supabase gratuit) plus tard.
- **1 seul worker** : suffisant pour un usage entre amis (quelques dizaines
  de personnes en simultané), pas pour un très gros volume de trafic.

## Si tu veux un vrai nom de domaine plus tard (gratuit)

Quand tu auras un peu de budget, ou si tu veux un nom sans "onrender.com",
tu pourras :
1. Prendre un sous-domaine gratuit sur **DuckDNS** (`maksdiv.duckdns.org`)
   et le pointer vers Render via un enregistrement CNAME, ou
2. Acheter `maksdiv.com` quand ce sera possible et le connecter à Render
   dans **Settings → Custom Domain** (gratuit une fois le domaine acheté,
   Render fournit le certificat HTTPS automatiquement).
