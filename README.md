# **👑 Greg le Consanguin - Bot Discord** 🎵🎙️  

**Le seul bot qui joue de la musique tout en méprisant son public.**  
💀 **Un larbin noble, fatigué, servile et snob.**  
💬 **Vous êtes son roi, mais il vous hait profondément.**  

---

## **🚀 Fonctionnalités**
✔ **Rejoint et quitte un salon vocal (à contrecœur).**  
✔ **Télécharge et joue des musiques YouTube avec `yt-dlp` et `FFmpeg`.**  
✔ **Affiche la file d’attente et permet de naviguer entre les musiques.**  
✔ **Permet de rechercher une musique par texte et de choisir parmi les 3 meilleures.**  
✔ **Se déconnecte après 5 minutes d’inactivité, parce qu’il n’a pas que ça à faire.**  
✔ **Vous insulte subtilement (ou pas).**  

---

## **📜 Installation sur Railway avec Docker**
### **1️⃣ Créer un projet sur Railway**
1. **Créez un compte** sur Railway → [https://railway.app/](https://railway.app/)  
2. **Créez un projet** (`New Project`)  
3. **Connectez votre dépôt GitHub**  

---

### **2️⃣ Ajouter un Dockerfile**
Ajoutez un fichier **Dockerfile** à la racine du projet :
```dockerfile
FROM python:3.12-slim

# Installer les dépendances système
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers du projet
COPY . .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Lancer le bot
CMD ["python", "main.py"]
```

**Commit et push sur Railway :**
```sh
git add Dockerfile
git commit -m "Ajout du Dockerfile"
git push railway main
```

### **3️⃣ Configurer Railway pour utiliser Docker**
- **Sur l’interface Railway** :  
  `Settings` → `Build Type` → **Docker**  
- **Ou via la CLI** :
  ```sh
  railway settings set "Build Type" to "Docker"
  ```

---

### **4️⃣ Ajouter les Variables d’Environnement**
Dans **Railway → Variables**, ajoutez :

| Nom de la Variable      | Valeur                           | Description |
|------------------------|--------------------------------|-------------|
| `DISCORD_TOKEN`        | `VOTRE_TOKEN_DISCORD`          | Clé API du bot |
| `YOUTUBE_COOKIES_PATH` | `/app/youtube.com_cookies.txt` | Chemin des cookies YouTube |

Si YouTube bloque certaines vidéos, ajoutez **vos cookies** (via l'extension **Get Cookies.txt** sur Chrome/Firefox), et uploadez le fichier `youtube.com_cookies.txt` sur Railway.

---

### **5️⃣ Commandes utiles pour Railway**
📌 **Lancer Railway en local :**
```sh
npm install -g @railway/cli
railway login
railway link -p VOTRE_ID_PROJET
railway shell
```

📌 **Déploiement et debug :**
```sh
railway up
railway logs
```

📌 **Tester si `ffmpeg` fonctionne :**
```sh
railway run ffmpeg -version
```

---

## **🎮 Commandes du bot**
| Commande | Description |
|----------|------------|
| `!join` | Greg rejoint le vocal (en râlant). |
| `!leave` | Greg quitte le vocal (soulagé). |
| `!play <url/recherche>` | Ajoute une musique YouTube ou cherche une vidéo. |
| `!pause` | Met en pause la musique avec un soupir exaspéré. |
| `!resume` | Reprend la musique (contraint et forcé). |
| `!skip` | Passe à la musique suivante en insultant votre goût musical. |
| `!stop` | Stoppe la musique et vide la file d’attente. |
| `!playlist` | Affiche la file d’attente en commentant vos choix douteux. |
| `!current` | Affiche la musique en cours avec dédain. |

---

## **🐛 Debug & Problèmes**
### **🔴 `ffmpeg not found`**
1. **Tester si `ffmpeg` est installé** :
   ```sh
   railway run ffmpeg -version
   ```
2. **Forcer `yt-dlp` à trouver `ffmpeg`** :
   ```python
   ydl_opts = {
       'ffmpeg_location': "ffmpeg"
   }
   ```
3. **Essayer avec Docker si ça persiste.**

---

## **💡 Greg le Consanguin : Un serviteur fatigué, mais docile**
✔ **Railway + Docker = Un Greg stable et performant**  
✔ **Insultes raffinées et obéissance contrainte**  
✔ **Un bot prêt à vous haïr avec la plus grande révérence**  

🔥 **Faites tourner Greg et laissez-le vous mépriser en musique !** 🎶👑