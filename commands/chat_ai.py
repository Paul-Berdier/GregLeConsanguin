from discord.ext import commands
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import config
import os
from gtts import gTTS

class ChatAI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.model_name = "mistralai/Mistral-7B-Instruct-v0.1"
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_name, torch_dtype=torch.float16)

    @commands.command()
    async def ask(self, ctx, *, question):
        """Pose une question à Greg et il répond en vocal."""
        if not ctx.voice_client:
            await ctx.send("Tsss… Appelle-moi dans un vocal d’abord avec `!join`.")
            return

        await ctx.send("Ugh… Je réfléchis...")

        # Générer une réponse
        inputs = self.tokenizer(question, return_tensors="pt")
        outputs = self.model.generate(**inputs, max_length=200)
        response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

        await ctx.send(f"🤖 Greg : {response}")

        # Synthèse vocale
        filename = "response.mp3"
        tts = gTTS(text=response, lang="fr")
        tts.save(filename)

        ctx.voice_client.play(discord.FFmpegPCMAudio(filename))

def setup(bot):
    bot.add_cog(ChatAI(bot))
