FROM python:3.12-slim
WORKDIR /app
COPY packages/shared/ /shared/
RUN pip install /shared/
COPY services/voice-ai/ .
RUN pip install -r requirements.txt 2>/dev/null || true
CMD ["python", "-m", "voice_ai.main"]
