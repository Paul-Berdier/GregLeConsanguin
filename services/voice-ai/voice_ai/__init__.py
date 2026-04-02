"""Greg le Consanguin — Voice AI service (futur).

Ce service gérera la conversation vocale avec Greg :
1. STT (Speech-to-Text) — Whisper / Deepgram
2. LLM (Language Model) — Claude API avec system prompt Greg
3. TTS (Text-to-Speech) — ElevenLabs / Coqui / Bark

Architecture :
  Discord Audio Stream → STT → LLM → TTS → Discord Audio Playback
"""
