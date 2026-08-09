# Déploiement sur VPS — "Action ou Vérité"

Guide pas à pas pour mettre ton application en ligne sur un VPS Ubuntu, accessible
via un nom de domaine, en HTTPS, avec redémarrage automatique.

## 1. Choisir et créer ton VPS

Recommandations pour une bonne latence depuis la Guinée / Afrique de l'Ouest :
privilégie un **datacenter en Europe** (France, Pays-Bas, Allemagne) plutôt qu'aux
États-Unis — la latence est nettement meilleure.

Options courantes, du moins cher au plus complet :
- **Contabo** (Allemagne) — très bon rapport prix/ressources, offres à partir de ~5€/mois
- **Hetzner** (Allemagne/Finlande) — excellent rapport qualité/prix, fiable
- **OVH** (France) — datacenters en France, paiement possible en devises locales selon les cas

Configuration minimale suffisante : **1 vCPU, 2 Go RAM, Ubuntu 22.04 LTS**.

Après création, tu reçois une adresse IP publique et un accès root en SSH.

## 2. Se connecter et préparer le serveur

```bash
ssh root@TON_IP_VPS

apt update && apt upgrade -y
apt install -y python3-pip python3-venv nginx git ufw
```

Configurer le pare-feu de base :
```bash
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw enable
```

## 3. Déposer le code sur le serveur

Depuis ta machine, envoie le dossier `action_verite` (par exemple via `scp`) :
```bash
scp -r action_verite root@TON_IP_VPS:/var/www/action_verite
```

Ou si tu mets ton code sur GitHub/GitLab :
```bash
cd /var/www
git clone <url_de_ton_repo> action_verite
```

## 4. Installer l'environnement Python

```bash
cd /var/www/action_verite
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

Donner les bons droits au dossier :
```bash
chown -R www-data:www-data /var/www/action_verite
```

## 5. Changer la clé secrète Flask

Édite `app.py` et remplace la ligne :
```python
app.config["SECRET_KEY"] = "change-moi-en-production"
```
par une vraie valeur aléatoire, par exemple générée avec :
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## 6. Lancer l'app avec Gunicorn via systemd

Le fichier `deploy/action-verite.service` est déjà prêt. Copie-le :
```bash
cp /var/www/action_verite/deploy/action-verite.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable action-verite
systemctl start action-verite
systemctl status action-verite
```

Si tout est vert, l'app tourne en local sur `127.0.0.1:8000`.

## 7. Configurer Nginx comme reverse proxy

```bash
cp /var/www/action_verite/deploy/nginx_action_verite.conf /etc/nginx/sites-available/action-verite
```

Édite ce fichier si besoin — il est déjà pré-rempli avec `maksdiv.com`.
Assure-toi d'abord d'avoir pointé ton domaine vers l'IP de ton VPS via un
enregistrement DNS **A** (fait chez ton registrar, ex: Namecheap/name.com) :
```
Type: A     Nom: @              Valeur: TON_IP_VPS
Type: A     Nom: www            Valeur: TON_IP_VPS
```
La propagation DNS peut prendre de quelques minutes à quelques heures.

```bash
ln -s /etc/nginx/sites-available/action-verite /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

À ce stade, `http://tondomaine.com` doit afficher ton application.

## 8. Activer HTTPS (gratuit, avec Let's Encrypt)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d maksdiv.com -d www.maksdiv.com
```

Certbot configure automatiquement le certificat et le renouvellement. Ton site
sera accessible en `https://tondomaine.com`.

## 9. Vérifications finales

- Crée un salon, ouvre le lien d'invitation depuis un autre appareil/réseau (4G par
  exemple) pour confirmer que Socket.IO fonctionne bien à travers Nginx.
- Vérifie les logs en cas de souci :
```bash
journalctl -u action-verite -f
```

## Mises à jour futures du code

```bash
cd /var/www/action_verite
git pull            # ou scp des nouveaux fichiers
source venv/bin/activate
pip install -r requirements.txt
deactivate
systemctl restart action-verite
```

## Limites à connaître

- Les salons vivent en mémoire (RAM) du process Gunicorn : un redémarrage du
  service (`systemctl restart`) efface les salons actifs. Les confessions restent
  en SQLite (`app.db`), donc pas perdues.
- Un seul worker Gunicorn est utilisé (`--workers 1`) car l'état des salons est
  en mémoire locale — avec plusieurs workers, les salons ne seraient pas
  partagés entre eux. Si tu as besoin de scaler à beaucoup de trafic
  simultané, il faudra migrer le stockage des salons vers Redis.
- Pense à sauvegarder régulièrement `app.db` (contient les confessions) si tu
  veux les conserver en cas de problème serveur : `cp app.db app.db.backup`.
