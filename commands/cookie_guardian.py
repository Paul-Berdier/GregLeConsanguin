# cogs/cookie_guardian.py
from discord.ext import tasks, commands
from yt_dlp import YoutubeDL
import os, time, base64, gzip

TEST_URL = os.getenv("YTC_TEST_URL", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
yt_user = os.getenv("YTBOT_USER") or "<non défini>"
yt_pass = os.getenv("YTBOT_PASS") or "<non défini>"

class CookieGuardian(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.notify_channel_id = int(os.getenv("YTC_NOTIFY_CHANNEL_ID", "1061712671017283595") or 1061712671017283595)
        self.path = (os.getenv("YTDLP_COOKIES_FILE")
                     or ("youtube.com_cookies.txt" if os.path.exists("youtube.com_cookies.txt") else None))
        self.probe.start()

    def cog_unload(self):
        self.probe.cancel()

    def _is_valid(self):
        if not self.path or not os.path.exists(self.path):
            return False, "missing_cookiefile"
        ydl_opts = {"quiet": True, "noprogress": True, "cookiefile": self.path}
        try:
            with YoutubeDL(ydl_opts) as ydl:
                # Pas besoin de download, juste un extract_info
                ydl.extract_info(TEST_URL, download=False)
            return True, None
        except Exception as e:
            s = str(e)
            if ("Sign in to confirm you're not a bot" in s) or ("HTTP Error 403" in s):
                return False, "auth_required"
            return False, s

    def _try_reload_from_env(self):
        b64 = os.getenv("YTDLP_COOKIES_B64")
        if not b64:
            return False
        try:
            blob = base64.b64decode(b64)
            if len(blob) >= 2 and blob[:2] == b"\x1f\x8b":
                blob = gzip.decompress(blob)
            content = blob.decode("utf-8", "ignore")
            target = "/tmp/youtube.com_cookies.txt"
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            try:
                os.chmod(target, 0o600)
            except Exception:
                pass
            os.environ["YTDLP_COOKIES_FILE"] = target
            self.path = target
            return True
        except Exception:
            return False

    async def _notify(self, text: str):
        if not self.notify_channel_id:
            return
        ch = self.bot.get_channel(self.notify_channel_id)
        if ch:
            try:
                await ch.send(text)
            except Exception:
                pass

    @tasks.loop(hours=6)
    async def probe(self):
        ok, err = self._is_valid()
        if ok:
            return
        # 2) sinon, notifier
        msg = (
            "⚠️ **Cookies YouTube invalides ou expirés !**\n"
            f"Erreur: `{err}`\n\n"
            "👉 Utilisez le compte Google fourni pour Greg :\n"
            f"**Email :** `{yt_user}`\n"
            f"**Mot de passe :** `{yt_pass}`\n\n"
            "1. Connectez-vous à ce compte sur Google Chrome.\n"
            "2. Installez l’extension officielle : [Get cookies.txt (clean)]"
            "(https://chromewebstore.google.com/detail/get-cookiestxt-clean/ahmnmhfbokciafffnknlekllgcnafnie?hl=fr&utm_source=ext_sidebar)\n"
            "3. Allez sur [YouTube](https://youtube.com), cliquez sur l’icône de l’extension → *Export Netscape cookies.txt*.\n"
            "4. Faites la commande `/yt_cookies_update` et uploadez le fichier exporté.\n\n"
            "✅ Cela mettra à jour les cookies pour tous les utilisateurs du bot."
        )
        await self._notify(msg)

    @probe.before_loop
    async def before_probe(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(CookieGuardian(bot))
