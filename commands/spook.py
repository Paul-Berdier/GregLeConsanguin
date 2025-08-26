# commands/spook.py
import os
import asyncio
import random
from typing import Dict, Optional, List
import requests

import discord
from discord.ext import commands
from discord import app_commands


def _project_path(*parts) -> str:
    # Chemin stable: racine du projet = parent de /commands
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, *parts)


SFX_DIR = _project_path("assets", "spook")
SFX_EXTS = {".mp3", ".ogg", ".wav", ".m4a"}

# Defaults surchargeables via .env
def _as_int(env, default):
    try:
        return int(os.getenv(env, str(default)) or default)
    except Exception:
        return default

def _as_float(env, default):
    try:
        return float(os.getenv(env, str(default)) or default)
    except Exception:
        return default

DEFAULT_MIN_DELAY = max(5, _as_int("SPOOK_MIN_DELAY", 30))   # secondes
DEFAULT_MAX_DELAY = max(DEFAULT_MIN_DELAY, _as_int("SPOOK_MAX_DELAY", 120))
DEFAULT_VOLUME    = min(1.0, max(0.0, _as_float("SPOOK_VOLUME", 0.30)))  # 0.0 .. 1.0 (~30%)


def _guild_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.guild is None:
            raise app_commands.CheckFailure("guild_only")
        return True
    return app_commands.check(predicate)


class Spook(commands.Cog):
    """Fait jouer de petits bruits sinistres quand une seule personne reste avec Greg (et que la musique est à l'arrêt)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.enabled: Dict[int, bool] = {}          # {guild_id: bool}
        self.tasks: Dict[int, asyncio.Task] = {}    # {guild_id: task}
        self.min_delay: Dict[int, int] = {}
        self.max_delay: Dict[int, int] = {}
        self.volume: Dict[int, float] = {}
        self._sfx_cache: Optional[List[str]] = None  # cache des fichiers disponibles
        self.ffmpeg_path = self._detect_ffmpeg()

    # ---------------- Utils ----------------

    def _detect_ffmpeg(self) -> str:
        candidates = [
            "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg",
            "ffmpeg", r"D:\Paul Berdier\ffmpeg\bin\ffmpeg.exe"
        ]
        for p in candidates:
            try:
                if p == "ffmpeg" or os.path.exists(p):
                    return p
            except Exception:
                pass
        return "ffmpeg"

    def _guild_conf(self, gid: int):
        if gid not in self.min_delay:
            self.min_delay[gid] = DEFAULT_MIN_DELAY
        if gid not in self.max_delay:
            self.max_delay[gid] = DEFAULT_MAX_DELAY
        if gid not in self.volume:
            self.volume[gid] = DEFAULT_VOLUME

    def _list_sfx(self) -> List[str]:
        if self._sfx_cache is not None:
            return self._sfx_cache
        files: List[str] = []
        try:
            os.makedirs(SFX_DIR, exist_ok=True)
            for name in os.listdir(SFX_DIR):
                ext = os.path.splitext(name)[1].lower()
                if ext in SFX_EXTS:
                    files.append(os.path.join(SFX_DIR, name))
        except Exception:
            pass
        self._sfx_cache = files
        return files

    def _reload_sfx_cache(self):
        self._sfx_cache = None
        return self._list_sfx()

    def _pick_sfx(self) -> Optional[str]:
        files = self._list_sfx()
        if not files:
            return None
        return random.choice(files)

    def _is_alone_with_bot(self, guild: discord.Guild) -> bool:
        vc = guild.voice_client
        if not vc or not vc.channel:
            return False
        # Compte des humains (non-bots) dans le canal
        humans = sum(1 for m in vc.channel.members if not m.bot)
        return humans == 1  # exactement une personne + le bot (ou d'autres bots)

    def _is_music_active(self, guild: discord.Guild) -> bool:
        # 1) Vérifie voice_client
        vc = guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            return True
        # 2) Si Cog Music existe, regarde son état interne (best effort)
        try:
            music_cog = self.bot.get_cog("Music")
            if music_cog and isinstance(getattr(music_cog, "is_playing", None), dict):
                gid = int(guild.id)
                return bool(music_cog.is_playing.get(gid, False))
        except Exception:
            pass
        return False

    async def _play_sfx_once(self, guild: discord.Guild) -> bool:
        """Joue un sfx (si dispo) sans empiéter sur une lecture en cours. Retourne True si lecture lancée."""
        vc = guild.voice_client
        if not vc or not vc.channel:
            return False
        if vc.is_playing() or vc.is_paused():
            return False  # prudence: ne pas interrompre quoi que ce soit

        path = self._pick_sfx()
        if not path:
            return False

        try:
            # FFmpeg source
            src = discord.FFmpegPCMAudio(executable=self.ffmpeg_path, source=path)
            # Volume
            vol = float(self.volume.get(guild.id, DEFAULT_VOLUME))
            src = discord.PCMVolumeTransformer(src, volume=max(0.0, min(vol, 1.0)))

            # Lecture (bloque la source du voice client pendant le sfx)
            done = asyncio.get_running_loop().create_future()

            def after(err):
                try:
                    if err:
                        print(f"[Spook] Erreur lecture SFX: {err}")
                finally:
                    if not done.done():
                        done.set_result(True)

            vc.play(src, after=after)
            # Attendre fin
            await done
            return True
        except Exception as e:
            print(f"[Spook] Impossible de jouer SFX '{path}': {e}")
            return False

    async def _spook_loop(self, guild_id: int):
        """Boucle tant que c'est activé ; joue des sfx aléatoires si seul avec le bot et musique inactive."""
        try:
            guild = self.bot.get_guild(guild_id)
            while self.enabled.get(guild_id, False):
                await asyncio.sleep(2)  # petite respiration

                guild = guild or self.bot.get_guild(guild_id)
                if guild is None or guild.voice_client is None:
                    continue

                # Conditions runtime
                if not self._is_alone_with_bot(guild):
                    await asyncio.sleep(5)
                    continue

                if self._is_music_active(guild):
                    await asyncio.sleep(5)
                    continue

                # Seul, musique off → attente random puis re-check
                self._guild_conf(guild_id)
                dmin, dmax = self.min_delay[guild_id], self.max_delay[guild_id]
                if dmax < dmin:
                    dmax = dmin
                delay = random.randint(dmin, dmax)
                await asyncio.sleep(delay)

                # Re-check avant de jouer
                if self.enabled.get(guild_id, False) and self._is_alone_with_bot(guild) and not self._is_music_active(guild):
                    await self._play_sfx_once(guild)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Spook] loop error gid={guild_id}: {e}")
        finally:
            # Fin de boucle
            self.tasks.pop(guild_id, None)

    def _ensure_task(self, guild_id: int):
        if guild_id in self.tasks:
            return
        self.tasks[guild_id] = self.bot.loop.create_task(self._spook_loop(guild_id))

    def _cancel_task(self, guild_id: int):
        t = self.tasks.pop(guild_id, None)
        if t and not t.done():
            t.cancel()

    def cog_unload(self):
        # Nettoyage propre si le cog est rechargé
        for gid in list(self.tasks.keys()):
            self._cancel_task(gid)

    # ---------------- Events ----------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Démarre/arrête la boucle en fonction de la population du canal."""
        # On ne réagit que si le bot est déjà connecté quelque part
        if not member.guild.voice_client:
            return

        gid = member.guild.id
        if self.enabled.get(gid, False):
            # (Re)lance si conditions réunies, sinon laisser la boucle dormir
            self._ensure_task(gid)

    # ---------------- Slash commands (ADMIN) ----------------

    @app_commands.command(
        name="spook_scare",
        description="Envoie un jump scare à un membre (nécessite son overlay actif).",
    )
    @_guild_only()
    @app_commands.describe(
        member="Membre à cibler",
        effect="Nom d'effet (ex: scream)",
        duration_ms="Durée d'affichage (ms)",
        message="Message optionnel (affiché à l'écran)",
        img="URL image (override)",
        sound="URL son (override)"
    )
    async def spook_scare(self,
                          interaction: discord.Interaction,
                          member: discord.Member,
                          effect: str = "scream",
                          duration_ms: int = 1500,
                          message: Optional[str] = None,
                          img: Optional[str] = None,
                          sound: Optional[str] = None):
        # Permissions: Admin ou Manage Guild
        if not (interaction.user.guild_permissions.administrator or
                interaction.user.guild_permissions.manage_guild):
            return await interaction.response.send_message(
                "🚫 Il faut être Admin ou avoir 'Gérer le serveur'.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        ok = False
        # 1) Bridge direct: le web a été accroché sur le bot (même process)
        web_app = getattr(self.bot, "web_app", None)
        if web_app and hasattr(web_app, "push_jumpscare"):
            try:
                web_app.push_jumpscare(
                    member.id, effect=effect, img=img, sound=sound,
                    duration_ms=int(duration_ms), message=message
                )
                ok = True
            except Exception as e:
                print(f"[Spook] push_jumpscare direct KO: {e}")

        # 2) Fallback HTTP interne (si configuré)
        if not ok:
            token = os.getenv("OVERLAY_INTERNAL_TOKEN")
            url   = os.getenv("OVERLAY_INTERNAL_URL", "http://127.0.0.1:3000/api/jumpscare")
            if token:
                try:
                    r = requests.post(url, json={
                        "user_id": str(member.id),
                        "effect": effect,
                        "duration_ms": int(duration_ms),
                        "message": message,
                        "img": img,
                        "sound": sound,
                    }, headers={"X-Overlay-Token": token}, timeout=3)
                    ok = r.ok
                except Exception as e:
                    print(f"[Spook] HTTP fallback KO: {e}")

        if ok:
            await interaction.followup.send(
                f"💥 Jumpscare envoyé à **{member.display_name}** (si overlay connecté).", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ Impossible d'envoyer le jumpscare (overlay non connecté ou bridge web indisponible).",
                ephemeral=True
            )

    @app_commands.command(
        name="spook_enable",
        description="Active/désactive les bruits sinistres (admin).",
    )
    @_guild_only()
    @app_commands.describe(enable="true/false")
    async def spook_enable(self, interaction: discord.Interaction, enable: bool):
        gid = interaction.guild_id
        self.enabled[gid] = bool(enable)
        if enable:
            self._ensure_task(gid)
            await interaction.response.send_message("☠️ Spook **activé**. L’ombre s’épaissit.", ephemeral=True)
        else:
            self._cancel_task(gid)
            await interaction.response.send_message("🕯️ Spook **désactivé**. Les murs se taisent.", ephemeral=True)

    @app_commands.command(
        name="spook_settings",
        description="Règle délai et volume des bruits (admin).",
    )
    @_guild_only()
    @app_commands.describe(min_delay="délai mini entre deux sons (s)", max_delay="délai maxi (s)", volume="0.0 - 1.0 (ex: 0.30)")
    async def spook_settings(self, interaction: discord.Interaction, min_delay: int = DEFAULT_MIN_DELAY,
                             max_delay: int = DEFAULT_MAX_DELAY, volume: float = DEFAULT_VOLUME):
        gid = interaction.guild_id
        self.min_delay[gid] = max(5, int(min_delay))
        self.max_delay[gid] = max(self.min_delay[gid], int(max_delay))
        self.volume[gid] = max(0.0, min(float(volume), 1.0))
        await interaction.response.send_message(
            f"⚙️ Spook réglé : delay **{self.min_delay[gid]}–{self.max_delay[gid]}s**, volume **{self.volume[gid]:.2f}**",
            ephemeral=True
        )

    @app_commands.command(
        name="spook_status",
        description="Affiche l’état du Spook (admin).",
    )
    @_guild_only()
    async def spook_status(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        self._guild_conf(gid)
        en = self.enabled.get(gid, False)
        vc = interaction.guild.voice_client
        humans = 0
        if vc and vc.channel:
            humans = sum(1 for m in vc.channel.members if not m.bot)

        embed = discord.Embed(
            title="Spook — État",
            description=(
                f"**Activé :** {'✅' if en else '❌'}\n"
                f"**Délais :** {self.min_delay[gid]}–{self.max_delay[gid]}s\n"
                f"**Volume :** {self.volume[gid]:.2f}\n"
                f"**Fichiers :** {len(self._list_sfx())} dans `assets/spook`\n"
                f"**Humains dans le channel :** {humans}\n"
            ),
            color=discord.Color.dark_teal() if en else discord.Color.dark_grey()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="spook_test",
        description="Joue un bruit maintenant (si conditions ok).",
    )
    @_guild_only()
    async def spook_test(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        vc = interaction.guild.voice_client
        if not vc or not vc.channel:
            return await interaction.followup.send("❌ Greg n’est dans aucun salon vocal.", ephemeral=True)

        if self._is_music_active(interaction.guild):
            return await interaction.followup.send("⏸️ La musique joue/est en pause. Test annulé pour ne pas couper.", ephemeral=True)

        ok = await self._play_sfx_once(interaction.guild)
        if ok:
            await interaction.followup.send("✅ Bruit joué.", ephemeral=True)
        else:
            await interaction.followup.send(
                "❌ Impossible de jouer un son (aucun fichier ? place des sfx dans `assets/spook`).",
                ephemeral=True
            )

    @app_commands.command(
        name="spook_files",
        description="Liste les fichiers SFX trouvés (admin).",
    )
    @_guild_only()
    async def spook_files(self, interaction: discord.Interaction):
        files = self._list_sfx()
        if not files:
            return await interaction.response.send_message("🚫 Aucun fichier SFX trouvé dans `assets/spook`.", ephemeral=True)
        names = [os.path.basename(p) for p in files]
        preview = "\n".join(f"- {n}" for n in names[:20])
        more = f"\n… (+{len(names)-20})" if len(names) > 20 else ""
        await interaction.response.send_message(
            f"**{len(names)}** fichier(s) détecté(s) dans `assets/spook`:\n{preview}{more}",
            ephemeral=True
        )

    @app_commands.command(
        name="spook_reload",
        description="Recharge la liste des SFX depuis le disque (admin).",
    )
    @_guild_only()
    async def spook_reload(self, interaction: discord.Interaction):
        files = self._reload_sfx_cache()
        await interaction.response.send_message(f"🔄 Cache rechargé — **{len(files)}** SFX.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Spook(bot))
    print("✅ Cog 'Spook' chargé — bruits sinistres activables.")
