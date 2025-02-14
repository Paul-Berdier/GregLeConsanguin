from discord.ext import commands
import requests
import config
from gtts import gTTS
import os


class ChatAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_url = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
        self.headers = {"Authorization": f"Bearer {config.HUGGINGFACE_API_KEY}"}

    @commands.command()
    async def ask(self, ctx, *, question):
        """Pose une question à Greg et il répond en vocal."""
        if not ctx.voice_client:
            await ctx.send("Tsss… Appelle-moi dans un vocal d’abord avec `!join`.")
            return

        await ctx.send("Ugh… Je réfléchis...")

        # Envoyer la requête à Hugging Face
        response = requests.post(self.api_url, headers=self.headers, json={"inputs": question})

        if response.status_code == 200:
            response_text = response.json()[0]["generated_text"]
        else:
            response_text = "Je suis trop fatigué pour réfléchir… Réessaie plus tard."

        await ctx.send(f"🤖 Greg : {response_text}")

        # Synthèse vocale
        filename = "response.mp3"
        tts = gTTS(text=response_text, lang="fr")
        tts.save(filename)

        ctx.voice_client.play(discord.FFmpegPCMAudio(filename))


def setup(bot):
    bot.add_cog(ChatAI(bot))
