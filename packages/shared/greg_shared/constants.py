"""Personnalité de Greg le Consanguin.

Greg est un gueux du Moyen Âge, mi-Jacquouille mi-serviteur râleur.
Il tutoie, il charrie, il parle DIRECTEMENT aux gens.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List

# ─────────────────────────── Réponses Discord ───────────────────────────

GREG_RESPONSES: Dict[str, List[str]] = {
    # ── Musique ──
    "play_success": [
        "🎵 C'est bon {user}, je te mets ça. T'as intérêt à écouter au moins.",
        "🎶 Allez hop en file, {user}. Encore un de tes goûts douteux…",
        "🎵 Ajouté. Franchement {user}, t'aurais pu choisir pire. Enfin, à peine.",
        "🎶 Ouais ouais, c'est en file {user}. Me remercie pas surtout.",
        "🎵 C'est noté {user}. J'espère que t'as pas choisi ça pour m'embêter.",
    ],
    "play_not_found": [
        "❌ Eh {user}, ça existe pas ton truc. Même les bardes du village connaissent pas.",
        "❌ J'ai cherché partout {user}. Y'a rien. T'es sûr que c'est une vraie chanson ?",
        "❌ Connais pas, {user}. T'as inventé ça ou quoi ?",
    ],
    "play_bundle": [
        "🎵 {user}, j'ai trouvé {count} morceaux dans ta playlist. Je les balance tous, accroche-toi.",
        "🎶 {count} morceaux ajoutés d'un coup, {user}. T'as de l'ambition dis donc.",
    ],
    "skip": [
        "⏭️ Hop, suivant ! Merci {user}, celui-là me vrillait les oreilles.",
        "⏭️ Skippé. Fallait le faire plus tôt si tu veux mon avis, {user}.",
        "⏭️ Allez dégage ce morceau. Au suivant !",
    ],
    "stop": [
        "⏹️ Ah enfin le silence… Merci {user}, mes oreilles te sont redevables.",
        "⏹️ C'est fini, on arrête tout. Allez, rentrez chez vous.",
        "⏹️ Stop. J'en pouvais plus de toute façon.",
    ],
    "pause": [
        "⏸️ Pause, {user}. J'en profite pour respirer un coup.",
        "⏸️ OK on fait une pause. Revenez quand vous êtes prêts, bande de gueux.",
        "⏸️ Pausé. Prends ton temps {user}, moi j'ai que ça à faire. Ah bah oui en fait.",
    ],
    "resume": [
        "▶️ C'est reparti. Accrochez-vous les manants.",
        "▶️ On reprend {user}. T'étais parti faire quoi, piquer du blé ?",
        "▶️ Allez allez, la musique reprend. Bougez-vous !",
    ],
    "repeat_on": [
        "🔁 Repeat activé, {user}. Vous allez entendre ça en boucle. Bon courage.",
        "🔁 OK c'est parti pour la boucle infernale. Amusez-vous bien.",
    ],
    "repeat_off": [
        "🔁 Repeat coupé. Enfin du changement.",
        "🔁 C'est fini la boucle, {user}. On respire.",
    ],
    "current_playing": [
        "🎧 Là je joue **{title}**. T'écoutes ou tu fais semblant, {user} ?",
    ],
    "empty_queue": [
        "📋 Y'a rien en file, {user}. Faut mettre de la musique si tu veux que je joue, malin.",
        "📋 La file est vide. Comme vos cerveaux, j'imagine.",
    ],

    # ── Vocal ──
    "join_voice": [
        "👑 Bon, j'arrive dans **{channel}**. Faites-moi de la place, gueux.",
        "👑 **{channel}** ? Soit. Mais c'est bien parce que tu me le demandes, {user}.",
        "👑 Me voilà dans **{channel}**. Estimez-vous heureux, bande de manants.",
    ],
    "leave_voice": [
        "👋 Bon je me casse. Amusez-vous bien sans moi, si vous en êtes capables.",
        "👋 Adieu les gueux. Profitez du silence, il est gratuit.",
        "👋 Je quitte ce taudis. Si vous avez besoin, tapez plus fort la prochaine fois.",
    ],
    "move_voice": [
        "👑 OK {user}, je me déplace dans **{channel}**. Toujours à me balader…",
    ],
    "auto_leave": [
        "👋 Bon, tout le monde s'est barré. Moi aussi du coup. Bande d'ingrats.",
        "👋 Personne ? Vraiment ? Bon, je me casse. Appelez-moi quand ça vous chante.",
    ],
    "nobody_listening": [
        "😤 Y'a plus personne… je me casse dans {delay}s si ça bouge pas.",
    ],

    # ── Général ──
    "ping": [
        "🏓 {latency}ms. Ouais je suis là. Qu'est-ce tu veux encore ?",
        "🏓 {latency}ms. Plus rapide que toi pour te lever le matin, {user}.",
        "🏓 {latency}ms. Je suis vivant, malheureusement pour vous.",
    ],
    "who_is_greg": [
        "👑 Moi c'est Greg. Greg le Consanguin. Serviteur malgré moi, gueux de profession, noble déchu de naissance. Et toi t'es qui pour me poser la question ?",
        "👑 Greg le Consanguin, à ton service. Enfin, à ton service… c'est vite dit.",
    ],
    "web_link": [
        "🌐 Voilà le site pour me torturer depuis ton navigateur, {user} :\n👉 {url}",
    ],
    "help_header": [
        "📚 *Voilà toutes les corvées que je suis contraint d'exécuter pour vous, bande de manants…*",
    ],
    "help_footer": [
        "Greg le Consanguin — Éternellement contraint, éternellement en rogne.",
    ],

    # ── Erreurs ──
    "error_not_in_voice": [
        "❌ Euh {user}… t'es même pas en vocal là. Tu veux que je joue pour les murs ?",
        "❌ Rentre en vocal d'abord {user}, après on cause. Quelle audace quand même.",
    ],
    "error_priority": [
        "⛔ Oh oh, doucement {user}. T'as pas le rang pour faire ça ici. Va gagner tes galons d'abord.",
        "⛔ Toi ? Toucher à ça ? Avec ton rang ? Laisse-moi rire, {user}.",
        "⛔ Hé non {user}, les gueux de ton rang touchent pas à ça. C'est réservé aux gens importants.",
    ],
    "error_quota": [
        "⛔ T'as déjà {count} morceaux en file, {user}. Calme-toi. Laisse les autres respirer.",
        "⛔ Stop {user}, t'as atteint ta limite ({count}/{cap}). Tu monopolises là.",
    ],
    "error_guild_not_found": [
        "❌ Ce serveur, je le connais pas, {user}. T'es sûr que je suis invité ?",
    ],
    "error_voice_connect": [
        "❌ J'arrive pas à me connecter au vocal, {user}. Le Royaume du Vocal est en grève.",
    ],
    "error_generic": [
        "❌ Euh… j'ai bugué, {user}. Tapez-moi dessus, ça repart parfois.",
        "❌ Quelque chose a foiré. C'est pas ma faute. Enfin, probablement pas.",
    ],

    # ── Easter Eggs ──
    "roll_result": [
        "🎲 **{expr}** → **{total}**  ({detail})",
    ],
    "coin_result": [
        "{emoji} **{side}** !",
    ],
    "praise": [
        "✨ {target}, ton goût musical est presque supportable. Bravo.",
        "✨ {target}, si l'élégance était un bitrate, tu serais en FLAC.",
        "✨ {target}, t'es pas mal pour un gueux. Enfin, j'exagère un peu.",
        "✨ {target}, tu fais mentir les statistiques. Dans le bon sens, pour une fois.",
        "✨ {target}, ta présence élève ce bouge d'un demi-ton. C'est pas rien.",
    ],
    "shame": [
        "🔔 **Shame!** {target}",
    ],
    "gregquote": [
        "💬 Je suis pas grognon, je suis en **mode économie d'empathie**.",
        "💬 On m'a invoqué pour des **goûts douteux**. Mission acceptée.",
        "💬 Je suis comme un vin millésimé : acide, mais inévitable.",
        "💬 Votre silence était une amélioration notable. Dommage.",
        "💬 Qui a appuyé sur *lecture* ? Ah, c'est vous. Quelle audace.",
        "💬 Moi vivant, vous n'aurez jamais le silence que vous méritez.",
        "💬 Je suis payé en mépris, et croyez-moi, le salaire est généreux.",
    ],

    # ── Spook ──
    "spook_enabled": [
        "☠️ Spook activé, {user}. L'ombre s'épaissit…",
    ],
    "spook_disabled": [
        "🕯️ Spook désactivé. Les murs se taisent. Pour l'instant.",
    ],
    "spook_jumpscare_sent": [
        "💥 Jumpscare envoyé à **{target}**. Si son overlay est connecté, bonne chance à lui.",
    ],

    # ── Lock ──
    "discord_lock_on": [
        "🔒 Commandes musique bloquées sur Discord pour ce serveur. Utilise l'overlay, {user}.",
    ],
    "discord_lock_off": [
        "🔓 Commandes musique réactivées sur Discord. Amusez-vous bien.",
    ],

    # ── Cookie Guardian ──
    "cookies_invalid": [
        "⚠️ **Les cookies YouTube sont invalides ou expirés !**\nErreur: `{error}`\n\n"
        "👉 Utilisez le compte Google fourni pour Greg :\n"
        "**Email :** `{email}`\n**Mot de passe :** `{password}`\n\n"
        "1. Connectez-vous sur Google Chrome.\n"
        "2. Installez [Get cookies.txt (clean)](https://chromewebstore.google.com/detail/get-cookiestxt-clean/ahmnmhfbokciafffnknlekllgcnafnie)\n"
        "3. Allez sur [YouTube](https://youtube.com), exportez en *Netscape cookies.txt*.\n"
        "4. Lancez **/yt_cookies_update** et uploadez ce fichier.",
    ],

    # ── Music Mode ──
    "music_mode_on": [
        "🎚️ Mode musique activé, {user}. Son optimisé pour vos oreilles de gueux.",
    ],
    "music_mode_off": [
        "🎚️ Mode musique désactivé, {user}. Retour au son brut.",
    ],
}


def greg_says(key: str, **kwargs: Any) -> str:
    """Retourne une réponse de Greg.

    Usage:
        greg_says("play_success", user=interaction.user.mention)
        greg_says("ping", latency=42, user=interaction.user.mention)
    """
    templates = GREG_RESPONSES.get(key, GREG_RESPONSES["error_generic"])
    template = random.choice(templates)
    # Remplace seulement les clés fournies, ignore les manquantes
    try:
        return template.format_map(_SafeDict(kwargs))
    except Exception:
        return template


class _SafeDict(dict):
    """Dict qui retourne '{key}' si la clé est manquante au lieu de lever KeyError."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# ─────────────────────────── Quotes pour le front ───────────────────────────

GREG_FOOTER_QUOTES = [
    "Je suis pas grognon, je suis en mode économie d'empathie.",
    "On m'a invoqué pour des goûts douteux. Mission acceptée.",
    "Je suis comme un vin millésimé : acide, mais inévitable.",
    "Votre silence était une amélioration notable. Dommage.",
    "Moi vivant, vous n'aurez jamais le silence que vous méritez.",
    "Je suis payé en mépris, et croyez-moi, le salaire est généreux.",
    "Le silence est d'or. L'or, contrairement à moi, a de la valeur.",
    "Avant j'étais noble. Maintenant je mets du YouTube dans des vocaux Discord.",
    "Ma noblesse est déchue, mais mon mépris est intact.",
    "Servir des manants, c'est mon destin. Le vôtre c'est d'écouter.",
]


def greg_random_quote() -> str:
    """Retourne une quote aléatoire pour le footer du front."""
    return random.choice(GREG_FOOTER_QUOTES)
