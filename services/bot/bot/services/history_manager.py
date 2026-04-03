"""HistoryManager — historique des morceaux joués par guild.

Stocke les morceaux joués dans un fichier JSON par guild.
Chaque entrée a un compteur de lectures (play_count) et un timestamp.
Permet de construire un "top" des morceaux les plus joués et des suggestions.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("greg.history")

HISTORY_DIR = "history"
MAX_ENTRIES = 500  # Max entries per guild


class HistoryManager:
    """Gestion de l'historique des morceaux joués pour une guild."""

    def __init__(self, guild_id: int):
        self.guild_id = int(guild_id)
        self.lock = threading.Lock()
        self._entries: Dict[str, Dict[str, Any]] = {}  # keyed by url hash
        self._filepath = os.path.join(HISTORY_DIR, f"history_{self.guild_id}.json")
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._entries = data
                elif isinstance(data, list):
                    # Migrate from old list format
                    for item in data:
                        key = self._key(item.get("url", ""))
                        if key:
                            self._entries[key] = item
        except Exception as e:
            logger.warning("History load failed for guild %s: %s", self.guild_id, e)
            self._entries = {}

    def _save(self):
        try:
            os.makedirs(HISTORY_DIR, exist_ok=True)
            tmp = self._filepath + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=None)
            os.replace(tmp, self._filepath)
        except Exception as e:
            logger.error("History save failed for guild %s: %s", self.guild_id, e)

    @staticmethod
    def _key(url: str) -> str:
        if not url:
            return ""
        return hashlib.md5(url.encode()).hexdigest()[:12]

    def record_play(self, track: Dict[str, Any], played_by: Optional[str] = None):
        """Enregistre qu'un morceau a été joué."""
        url = track.get("url", "")
        if not url:
            return

        key = self._key(url)
        with self.lock:
            existing = self._entries.get(key)
            now = int(time.time())

            if existing:
                existing["play_count"] = existing.get("play_count", 0) + 1
                existing["last_played"] = now
                # Update metadata if better
                if track.get("title") and track["title"] != url:
                    existing["title"] = track["title"]
                if track.get("artist"):
                    existing["artist"] = track["artist"]
                if track.get("thumb"):
                    existing["thumb"] = track["thumb"]
                if played_by:
                    # Track last player and all players
                    existing["last_played_by"] = str(played_by)
                    players = existing.get("played_by", [])
                    if str(played_by) not in players:
                        players.append(str(played_by))
                    existing["played_by"] = players[-10:]  # Keep last 10
            else:
                self._entries[key] = {
                    "url": url,
                    "title": track.get("title", url),
                    "artist": track.get("artist", ""),
                    "thumb": track.get("thumb") or track.get("thumbnail", ""),
                    "duration": track.get("duration"),
                    "provider": track.get("provider", "youtube"),
                    "play_count": 1,
                    "first_played": now,
                    "last_played": now,
                    "last_played_by": str(played_by) if played_by else "",
                    "played_by": [str(played_by)] if played_by else [],
                }

            # Prune old entries if too many
            if len(self._entries) > MAX_ENTRIES:
                sorted_keys = sorted(
                    self._entries.keys(),
                    key=lambda k: self._entries[k].get("last_played", 0),
                )
                for old_key in sorted_keys[: len(self._entries) - MAX_ENTRIES]:
                    del self._entries[old_key]

            self._save()

    def get_top(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retourne les morceaux les plus joués."""
        with self.lock:
            entries = list(self._entries.values())
        entries.sort(key=lambda x: x.get("play_count", 0), reverse=True)
        return entries[:limit]

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retourne les morceaux les plus récemment joués."""
        with self.lock:
            entries = list(self._entries.values())
        entries.sort(key=lambda x: x.get("last_played", 0), reverse=True)
        return entries[:limit]

    def get_all(self) -> List[Dict[str, Any]]:
        """Retourne tout l'historique."""
        with self.lock:
            return list(self._entries.values())
