"""Greg le Consanguin — Bot entry point.

Slim entry point: instancie le bot, connecte Redis, lance.
Plus de threading Flask, plus de PlayerAPIBridge.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from greg_shared.config import settings

# ── Logging ──
LOG_LEVEL = settings.log_level.upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("greg.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("greg.bot")


def main():
    if not settings.discord_token:
        logger.critical("DISCORD_TOKEN manquant !")
        sys.exit(1)
    if not settings.discord_app_id:
        logger.critical("DISCORD_CLIENT_ID manquant !")
        sys.exit(1)

    logger.info("=== DÉMARRAGE GREG LE CONSANGUIN v2 ===")

    from bot.greg_bot import GregBot

    bot = GregBot()

    try:
        bot.run(settings.discord_token)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur.")
    except Exception as e:
        logger.exception("Erreur fatale: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
