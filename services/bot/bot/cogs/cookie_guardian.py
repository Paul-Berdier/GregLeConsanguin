# cogs/cookie_guardian.py
from __future__ import annotations

import os
import json
import time
import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Tuple

import discord
from discord.ext import commands, tasks

logger = logging.getLogger("greg.announce")

# =========================
#   Config & constants
# =========================

ANNOUNCE_STORE = os.getenv("ANNOUNCE_STORE", ".announcements.json")  # fichier persistant
OWNER_ID = int(os.getenv("GREG_OWNER_ID", "0") or 0)

# Plancher des annonces répétées (anti-spam) : le scheduler tourne toutes les 20 s.
MIN_EVERY_SECONDS = 300
# Annonces : jamais de @everyone/@here ni de ping de rôle (les mentions d'users restent actives).
ANNOUNCE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=False)

# CookieGuardian (héritage de l'ancien fichier)
# NB : les identifiants du compte Google (YTBOT_USER / YTBOT_PASS) ne sont JAMAIS
# postés sur Discord. Le chemin des cookies n'est plus figé à l'import : il est
# résolu à chaque run via youtube._pick_cookiefile(None) (contrat C6).
TEST_URL = os.getenv("YTC_TEST_URL", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
DEFAULT_NOTIFY_CHANNEL_ID = int(os.getenv("YTC_NOTIFY_CHANNEL_ID", "0") or 0)

# =========================
#   Helpers
# =========================

async def _is_owner(inter: discord.Interaction) -> bool:
    # Owner absolu
    if OWNER_ID and inter.user.id == OWNER_ID:
        return True
    # Fallback: owner de l'application
    try:
        app = await inter.client.application_info()
        if inter.user.id == app.owner.id:
            return True
    except Exception:
        pass
    return False

def _owner_or_manage():
    # app_commands.check (et PAS commands.check, ignoré par les slash commands)
    async def predicate(inter: discord.Interaction):
        if await _is_owner(inter):
            return True
        # Manage Guild ?
        perms = getattr(getattr(inter, "user", None), "guild_permissions", None)
        if perms and perms.manage_guild:
            return True
        raise discord.app_commands.CheckFailure("owner_or_manage_required")
    return discord.app_commands.check(predicate)

def _owner_only():
    # Config globale à tous les serveurs (CookieGuardian) → owner uniquement
    async def predicate(inter: discord.Interaction):
        if await _is_owner(inter):
            return True
        raise discord.app_commands.CheckFailure("owner_only")
    return discord.app_commands.check(predicate)

def _clamp_every(sec: int) -> int:
    """0 = one-shot ; sinon au moins MIN_EVERY_SECONDS."""
    if sec <= 0:
        return 0
    return max(MIN_EVERY_SECONDS, sec)

def _resolve_cookiefile() -> Optional[str]:
    """Même résolution que la lecture (upload > legacy > YTDLP_COOKIES_B64 matérialisé),
    évaluée à chaque appel. Bloquant (peut écrire le fichier B64) → à lancer en thread."""
    try:
        from greg_shared.extractors import youtube as yt
        return yt._pick_cookiefile(None)
    except Exception as e:
        logger.warning("CookieGuardian: résolution du cookiefile impossible: %s", e)
        return None

def _yt_cookies_valid_sync(cookiefile: Optional[str]) -> Tuple[bool, str]:
    """Validation yt-dlp BLOQUANTE (réseau + solveur JS) → toujours via asyncio.to_thread."""
    try:
        from yt_dlp import YoutubeDL
    except Exception as e:
        return False, f"yt-dlp manquant: {e}"
    if not cookiefile or not os.path.exists(cookiefile):
        return False, "missing_cookiefile"

    from greg_shared.extractors.youtube import cookiefile_copy

    try:
        # Copie privée : yt-dlp réécrit son cookiejar à la fermeture et écraserait
        # un upload /yt_cookies_update fait pendant la validation.
        with cookiefile_copy(cookiefile) as ck:
            if not ck:
                return False, "missing_cookiefile"
            opts = {
                "quiet": True, "noprogress": True, "cookiefile": ck, "nocheckcertificate": True,
                "skip_download": True, "socket_timeout": 10,
            }
            with YoutubeDL(opts) as ydl:
                # process=False : le "Sign in to confirm you're not a bot" sort de l'extraction,
                # inutile de lancer la sélection de formats.
                ydl.extract_info(TEST_URL, download=False, process=False)
        return True, "ok"
    except Exception as e:
        s = str(e)
        if ("Sign in to confirm you're not a bot" in s) or ("HTTP Error 403" in s):
            return False, "auth_required"
        return False, s

def _now() -> int:
    return int(time.time())

def _parse_every(every: str) -> int:
    """
    Convertit une fréquence texte en secondes.
    Ex: '30s', '5m', '1h', '6h', '2d'. (insensible à la casse)
    """
    every = (every or "").strip().lower()
    if not every:
        return 0
    try:
        if every.endswith("s"):
            return int(float(every[:-1]))
        if every.endswith("m"):
            return int(float(every[:-1]) * 60)
        if every.endswith("h"):
            return int(float(every[:-1]) * 3600)
        if every.endswith("d"):
            return int(float(every[:-1]) * 86400)
        # fallback: nombre brut = secondes
        return int(float(every))
    except Exception:
        return 0

def _human_every(sec: int) -> str:
    if sec % 86400 == 0:
        return f"{sec // 86400}d"
    if sec % 3600 == 0:
        return f"{sec // 3600}h"
    if sec % 60 == 0:
        return f"{sec // 60}m"
    return f"{sec}s"

def _read_store() -> Dict[str, Any]:
    if not os.path.exists(ANNOUNCE_STORE):
        return {"announcements": [], "cookie_guardian": {}}
    try:
        with open(ANNOUNCE_STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"announcements": [], "cookie_guardian": {}}

def _write_store(data: Dict[str, Any]) -> None:
    try:
        tmp = ANNOUNCE_STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, ANNOUNCE_STORE)
    except Exception:
        pass

# =========================
#   Data model
# =========================

@dataclass
class Announcement:
    id: int
    channel_id: int
    message: str
    every_seconds: int  # 0 = pas de répétition
    next_run_ts: int    # timestamp unix du prochain envoi
    enabled: bool = True
    pin: bool = False
    delete_after: Optional[int] = None  # en secondes
    last_message_id: Optional[int] = None  # suivi pour pin/update
    # Guild propriétaire, figée à la création : l'annonce reste gérable même si son
    # salon est supprimé. None = entrée héritée (complétée dès que le salon est résolu).
    guild_id: Optional[int] = None

# =========================
#   Cog principal
# =========================

class Announcer(commands.Cog):
    """
    Système d'annonces textuelles planifiées.
    - /announce add|list|remove|toggle|edit|send
    - CookieGuardian intégré : vérifie périodiquement les cookies et poste/épingle un message si invalides.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg = _read_store()
        self.announcements: Dict[int, Announcement] = {}

        # Charger annonces persistées
        for a in self.cfg.get("announcements", []):
            try:
                an = Announcement(**a)
                self.announcements[an.id] = an
            except Exception:
                continue

        # Initialiser CookieGuardian (toujours présent)
        cg = self.cfg.get("cookie_guardian") or {}
        # defaults si absent
        if not cg:
            cg = {
                "enabled": True,
                "channel_id": DEFAULT_NOTIFY_CHANNEL_ID,
                "every_seconds": 6 * 3600,
                "next_run_ts": _now() + 10,
                "pin": True,
                "last_message_id": None
            }
            self.cfg["cookie_guardian"] = cg
            _write_store(self.cfg)

        self._scheduler.start()

    def cog_unload(self):
        self._scheduler.cancel()

    # ================
    #  Persistance
    # ================
    def _flush(self):
        self.cfg["announcements"] = [asdict(a) for a in self.announcements.values()]
        _write_store(self.cfg)

    def _new_id(self) -> int:
        return 1 + max([0] + list(self.announcements.keys()))

    # Le store est global à tous les serveurs : une annonce appartient à SA guild
    # (guild_id stocké), et un admin ne voit/modifie que celles de SA guild.
    def _ann_guild_id(self, a: Announcement) -> Optional[int]:
        if a.guild_id:
            return int(a.guild_id)
        # Entrée héritée : guild déduite du salon, puis mémorisée (persistée au prochain
        # _flush) pour qu'elle reste gérable si le salon disparaît ensuite.
        ch = self.bot.get_channel(a.channel_id)
        g = getattr(ch, "guild", None)
        if g is None:
            return None
        a.guild_id = int(g.id)
        return a.guild_id

    def _backfill_guild_ids(self) -> bool:
        """Complète guild_id des entrées héritées dont le salon est résolu (cache prêt)."""
        changed = False
        for a in self.announcements.values():
            if not a.guild_id and self._ann_guild_id(a) is not None:
                changed = True
        return changed

    async def _can_manage(self, inter: discord.Interaction, a: Announcement) -> bool:
        gid = self._ann_guild_id(a)
        if gid is not None:
            return gid == inter.guild_id
        # Entrée héritée dont le salon n'existe plus : guild inconnue → owner uniquement
        # (sinon elle resterait ingérable à vie, sauf édition manuelle du JSON).
        return await _is_owner(inter)

    async def _get_ann(self, inter: discord.Interaction, ann_id: int) -> Optional[Announcement]:
        a = self.announcements.get(int(ann_id))
        if a is None or not await self._can_manage(inter, a):
            return None
        return a

    # ================
    #  Scheduler
    # ================
    @tasks.loop(seconds=20)  # battement
    async def _scheduler(self):
        # 1) annonces classiques
        now = _now()
        for a in list(self.announcements.values()):
            if not a.enabled:
                continue
            if a.next_run_ts and now >= a.next_run_ts:
                await self._send_announcement(a)
                # replanifier
                if a.every_seconds > 0:
                    # planif suivante sans dérive (alignée)
                    a.next_run_ts = now + a.every_seconds
                else:
                    # one-shot -> désactiver
                    a.enabled = False
                self._flush()

        # 2) CookieGuardian (toujours évalué)
        cgc = self.cfg.get("cookie_guardian") or {}
        if cgc.get("enabled"):
            nxt = int(cgc.get("next_run_ts") or 0)
            ev = int(cgc.get("every_seconds") or (6 * 3600))
            if now >= nxt:
                await self._run_cookie_guardian_once(cgc)
                cgc["next_run_ts"] = now + ev
                self.cfg["cookie_guardian"] = cgc
                _write_store(self.cfg)

    @_scheduler.before_loop
    async def _before_scheduler(self):
        await self.bot.wait_until_ready()
        if self._backfill_guild_ids():
            self._flush()

    # ================
    #  Send logic
    # ================
    async def _send_announcement(self, a: Announcement) -> Optional[int]:
        ch = self.bot.get_channel(a.channel_id)
        if ch is None or not isinstance(ch, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            return None
        try:
            msg = await ch.send(a.message, allowed_mentions=ANNOUNCE_MENTIONS)
            if a.pin:
                # dé-épingler l'ancien si on en avait un (pour “toujours là”)
                if a.last_message_id and a.last_message_id != msg.id:
                    try:
                        old = await ch.fetch_message(a.last_message_id)
                        if old and old.pinned:
                            await old.unpin()
                    except Exception:
                        pass
                await msg.pin(reason="Announcement pin")
                a.last_message_id = msg.id
            if a.delete_after and a.delete_after > 0:
                try:
                    # Suppression différée en arrière-plan : un sleep ici bloquait
                    # tout le scheduler (annonces + CookieGuardian) pendant delete_after.
                    await msg.delete(delay=a.delete_after)
                except Exception:
                    pass
            return msg.id
        except Exception:
            return None

    # ================
    #  CookieGuardian
    # ================
    async def _run_cookie_guardian_once(self, cgc: Dict[str, Any]):
        """
        Vérifie la validité des cookies via yt-dlp.extract_info().
        Si invalide/absent → poste un message (et l’épingle si pin=True).
        """
        channel_id = int(cgc.get("channel_id") or 0)
        if channel_id <= 0:
            return  # pas de canal configuré → silencieux
        ch = self.bot.get_channel(channel_id)
        if ch is None:
            return

        # 1) cookiefile résolu À CHAQUE RUN, exactement comme la lecture
        #    (upload /yt_cookies_update > legacy > YTDLP_COOKIES_B64 matérialisé).
        #    Plus de fichier /tmp ni de mutation d'os.environ (qui masquaient l'upload).
        path = await asyncio.to_thread(_resolve_cookiefile)

        # 2) validation yt-dlp (hors event loop)
        ok, err = await self._yt_cookies_valid(path)
        if ok:
            return  # tout va bien → pas de bruit

        # 3) message d’aide (toujours là si pin) — SANS identifiants : le salon est lisible
        #    par des membres et les épingles restent consultables indéfiniment.
        text = (
            "⚠️ **Cookies YouTube invalides ou expirés !**\n"
            f"Erreur: `{str(err)[:300]}`\n\n"
            "👉 Le propriétaire de Greg doit rafraîchir les cookies du compte Google dédié "
            "(identifiants dans le gestionnaire de secrets, jamais sur Discord) :\n"
            "1. Connectez-vous à ce compte sur Google Chrome.\n"
            "2. Installez l’extension officielle : "
            "[Get cookies.txt (clean)](https://chromewebstore.google.com/detail/get-cookiestxt-clean/ahmnmhfbokciafffnknlekllgcnafnie)\n"
            "3. Allez sur [YouTube](https://youtube.com), exportez en *Netscape cookies.txt*.\n"
            "4. Lancez la commande **/yt_cookies_update** (owner) et uploadez ce fichier.\n\n"
            "✅ Cela mettra à jour les cookies pour tous les serveurs du bot."
        )

        pin = bool(cgc.get("pin", True))
        last_id = cgc.get("last_message_id")
        try:
            msg = await ch.send(text, allowed_mentions=discord.AllowedMentions.none())
            # L'alerte précédente est obsolète (et les anciennes versions y postaient
            # les identifiants du compte) → on la supprime au lieu de simplement la désépingler.
            if last_id and last_id != msg.id:
                try:
                    old = await ch.fetch_message(int(last_id))
                    if old:
                        await old.delete()
                except Exception:
                    pass
            cgc["last_message_id"] = msg.id
            if pin:
                await msg.pin(reason="CookieGuardian")
        except Exception:
            pass

    async def _yt_cookies_valid(self, cookiefile: Optional[str]) -> Tuple[bool, str]:
        # extract_info est bloquant (réseau + Deno/EJS) → thread, sinon l'event loop
        # Discord/Redis gèle plusieurs secondes après chaque déploiement puis toutes les 6 h.
        return await asyncio.to_thread(_yt_cookies_valid_sync, cookiefile)

    # =========================
    #   Slash-commands
    # =========================
    # guild_only + default_permissions : masqué aux membres par défaut (défense en
    # profondeur — le vrai contrôle reste les app_commands.check ci-dessous).
    announce = discord.app_commands.Group(
        name="announce",
        description="Gérer les annonces textuelles",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @announce.command(name="add", description="Créer une annonce (répétition optionnelle).")
    @_owner_or_manage()
    @discord.app_commands.describe(
        channel="Salon cible",
        message="Contenu du message (Markdown autorisé)",
        every="Fréquence (ex: 30m, 1h, 6h, 2d). Vide = one-shot",
        pin="Épingler chaque envoi (et désépingler l'ancien)",
        delete_after="Supprimer après N secondes (optionnel)",
        start_in="Décalage initial (ex: 10m, 1h) avant le 1er envoi"
    )
    async def add(
        self,
        inter: discord.Interaction,
        channel: discord.TextChannel,
        message: str,
        every: Optional[str] = None,
        pin: Optional[bool] = False,
        delete_after: Optional[int] = None,
        start_in: Optional[str] = None
    ):
        await inter.response.defer(ephemeral=True)
        ev_sec = _parse_every(every or "")
        offset = _parse_every(start_in or "") if start_in else 0
        a = Announcement(
            id=self._new_id(),
            channel_id=channel.id,
            message=message,
            every_seconds=_clamp_every(ev_sec),
            next_run_ts=_now() + max(5, offset or 0),
            enabled=True,
            pin=bool(pin),
            delete_after=(int(delete_after) if delete_after else None),
            last_message_id=None,
            guild_id=inter.guild_id,
        )
        self.announcements[a.id] = a
        self._flush()
        await inter.followup.send(
            f"✅ Annonce **#{a.id}** créée pour <#{a.channel_id}> — "
            f"every=`{_human_every(a.every_seconds) if a.every_seconds else 'once'}` ; "
            f"next=`<t:{a.next_run_ts}:R>` ; pin=`{a.pin}` ; delete_after=`{a.delete_after}`",
            ephemeral=True
        )

    @announce.command(name="list", description="Lister les annonces.")
    @_owner_or_manage()
    async def list_cmd(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        mine = [a for a in self.announcements.values() if await self._can_manage(inter, a)]
        if not mine:
            await inter.followup.send("📭 Aucune annonce.", ephemeral=True)
            return
        lines = []
        for a in sorted(mine, key=lambda x: x.id):
            orphan = " — ⚠️ salon introuvable" if self.bot.get_channel(a.channel_id) is None else ""
            lines.append(
                f"**#{a.id}** — <#{a.channel_id}> — enabled={a.enabled} — "
                f"every=`{_human_every(a.every_seconds) if a.every_seconds else 'once'}` — "
                f"next=`<t:{a.next_run_ts}:R>` — pin=`{a.pin}` — delete_after=`{a.delete_after}`{orphan}"
            )
        await inter.followup.send("\n".join(lines), ephemeral=True)

    @announce.command(name="remove", description="Supprimer une annonce.")
    @_owner_or_manage()
    @discord.app_commands.describe(ann_id="ID de l'annonce")
    async def remove(self, inter: discord.Interaction, ann_id: int):
        await inter.response.defer(ephemeral=True)
        a = await self._get_ann(inter, ann_id)
        if a:
            self.announcements.pop(a.id, None)
        self._flush()
        await inter.followup.send(
            f"{'🗑️ Supprimée' if a else '❌ Introuvable'} (#{ann_id}).", ephemeral=True
        )

    @announce.command(name="toggle", description="Activer/désactiver une annonce.")
    @_owner_or_manage()
    @discord.app_commands.describe(ann_id="ID de l'annonce", enabled="ON/OFF")
    async def toggle(self, inter: discord.Interaction, ann_id: int, enabled: bool):
        await inter.response.defer(ephemeral=True)
        a = await self._get_ann(inter, ann_id)
        if not a:
            return await inter.followup.send("❌ Annonce introuvable.", ephemeral=True)
        a.enabled = bool(enabled)
        # si on réactive et next_run passé, on repart dans 10s
        if a.enabled and a.next_run_ts < _now():
            a.next_run_ts = _now() + 10
        self._flush()
        await inter.followup.send(f"✅ Annonce #{a.id}: enabled={a.enabled}", ephemeral=True)

    @announce.command(name="edit", description="Modifier une annonce.")
    @_owner_or_manage()
    @discord.app_commands.describe(
        ann_id="ID",
        channel="Nouveau salon (optionnel)",
        message="Nouveau message (optionnel)",
        every="Nouvelle fréquence (ex: 30m, 1h, 6h, 2d) ; vide = inchangé",
        pin="Pin ON/OFF (optionnel)",
        delete_after="Durée de vie (sec) ; 0 pour désactiver (optionnel)",
        next_in="Décalage avant prochain envoi (ex: 5m) — sinon replanif auto"
    )
    async def edit(
        self,
        inter: discord.Interaction,
        ann_id: int,
        channel: Optional[discord.TextChannel] = None,
        message: Optional[str] = None,
        every: Optional[str] = None,
        pin: Optional[bool] = None,
        delete_after: Optional[int] = None,
        next_in: Optional[str] = None,
    ):
        await inter.response.defer(ephemeral=True)
        a = await self._get_ann(inter, ann_id)
        if not a:
            return await inter.followup.send("❌ Annonce introuvable.", ephemeral=True)
        if channel:
            a.channel_id = channel.id
            # Le salon choisi appartient forcément à la guild de la commande.
            a.guild_id = inter.guild_id
        if message is not None:
            a.message = message
        if every is not None:
            ev = _parse_every(every or "")
            a.every_seconds = _clamp_every(ev)
        if pin is not None:
            a.pin = bool(pin)
        if delete_after is not None:
            a.delete_after = (int(delete_after) if delete_after > 0 else None)
        if next_in:
            a.next_run_ts = _now() + max(5, _parse_every(next_in))
        else:
            # si fréquence change et next passé → replanif auto
            if a.next_run_ts < _now():
                a.next_run_ts = _now() + 10
        self._flush()
        await inter.followup.send("✅ Annonce mise à jour.", ephemeral=True)

    @announce.command(name="send", description="Envoyer l'annonce immédiatement (et replanifier).")
    @_owner_or_manage()
    @discord.app_commands.describe(ann_id="ID")
    async def send_now(self, inter: discord.Interaction, ann_id: int):
        await inter.response.defer(ephemeral=True)
        a = await self._get_ann(inter, ann_id)
        if not a:
            return await inter.followup.send("❌ Annonce introuvable.", ephemeral=True)
        await self._send_announcement(a)
        # replanif
        if a.every_seconds > 0:
            a.next_run_ts = _now() + a.every_seconds
        else:
            a.enabled = False
        self._flush()
        await inter.followup.send("📣 Envoyée.", ephemeral=True)

    # ---- CookieGuardian management ----
    @announce.command(name="cookie_guardian", description="Configurer l’annonce CookieGuardian (toujours active).")
    @_owner_only()
    @discord.app_commands.describe(
        channel="Salon de notification",
        every="Fréquence (ex: 6h, 12h) — défaut 6h",
        enabled="Activer/Désactiver",
        pin="Épingler le dernier message d’alerte"
    )
    async def cookie_guardian_config(
        self,
        inter: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        every: Optional[str] = None,
        enabled: Optional[bool] = None,
        pin: Optional[bool] = None,
    ):
        await inter.response.defer(ephemeral=True)
        cgc = self.cfg.get("cookie_guardian") or {}
        if channel:
            cgc["channel_id"] = channel.id
        if every is not None:
            sec = _parse_every(every)
            cgc["every_seconds"] = sec if sec > 0 else 6 * 3600
        if enabled is not None:
            cgc["enabled"] = bool(enabled)
        if pin is not None:
            cgc["pin"] = bool(pin)
        # si on réactive, replanifie dans 10s
        if cgc.get("enabled") and int(cgc.get("next_run_ts", 0)) < _now():
            cgc["next_run_ts"] = _now() + 10
        self.cfg["cookie_guardian"] = cgc
        _write_store(self.cfg)
        await inter.followup.send(
            f"✅ CookieGuardian: enabled={cgc.get('enabled')} channel=<#{cgc.get('channel_id', 0)}> "
            f"every={_human_every(int(cgc.get('every_seconds', 6*3600)))} pin={cgc.get('pin', True)}",
            ephemeral=True
        )

# Entrée du cog
async def setup(bot: commands.Bot):
    await bot.add_cog(Announcer(bot))
