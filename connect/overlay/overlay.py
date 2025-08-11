"""
overlay.py
~~~~~~~~~~~

This module provides a simple always‑on‑top GUI overlay for controlling
Greg le Consanguin while you play games full‑screen.  It uses Tkinter
for the window and python‑socketio for real‑time updates from the
backend.  The overlay shows the current playlist and exposes buttons
to pause, resume, skip and stop the music.  You can also enqueue a
track by typing a URL or search query in the entry field and pressing
``Enter``.

To use the overlay, make sure your Flask/Socket.IO server is running
locally (``python main.py`` launches it on port 3000).  Then run:

    python -m overlay.overlay

When the overlay starts it will ask for your Discord guild ID and your
Discord user ID.  These are needed so that the overlay can control the
bot on the right server and attribute new tracks to the correct user.

Notes:
  * The overlay window is frameless, semi‑transparent and always
    stays on top of other windows.  You can move it by dragging it.
  * Because Tkinter runs on the main thread, the Socket.IO client
    operates in a background thread.  The queue is updated via
    thread‑safe Tkinter methods.
  * Network errors and API failures are logged to the console.  The
    overlay will not crash if the server is unavailable – it will
    simply retry the connection periodically.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import socketio
import tkinter as tk
from tkinter import messagebox, simpledialog


logger = logging.getLogger(__name__)


@dataclass
class PlaylistState:
    """Holds the current playlist and currently playing item."""

    queue: List[Dict[str, Any]]
    current: Optional[Dict[str, Any]]


class GregOverlay:
    """A minimal always‑on‑top overlay for controlling Greg.

    Attributes
    ----------
    server_url: str
        Base URL of the Flask/Socket.IO server (e.g. ``http://localhost:3000``).
    guild_id: str
        Discord guild ID to target when issuing control commands.
    user_id: str
        Discord user ID used when enqueuing new tracks.
    """

    def __init__(self, server_url: str = "http://localhost:3000") -> None:
        self.server_url = server_url.rstrip("/")
        self.guild_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.sio = socketio.Client()
        self.root = tk.Tk()
        # Configure the window: frameless, always on top, semi‑transparent
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.9)
        self.root.configure(bg="#222222")
        self.root.geometry("300x200+20+20")
        # Playlist listbox
        self.playlist_box = tk.Listbox(self.root, fg="white", bg="#222222", highlightthickness=0)
        self.playlist_box.pack(fill=tk.BOTH, expand=True, padx=5, pady=(5, 2))
        # Entry for adding new songs
        self.entry = tk.Entry(self.root, fg="white", bg="#333333", insertbackground="white")
        self.entry.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.entry.bind("<Return>", self._on_enter_pressed)
        # Control buttons
        btn_frame = tk.Frame(self.root, bg="#222222")
        btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        for label in ["Pause", "Resume", "Skip", "Stop"]:
            b = tk.Button(
                btn_frame,
                text=label,
                command=lambda name=label.lower(): self._handle_action(name),
                fg="white",
                bg="#444444",
                activebackground="#555555",
                relief=tk.FLAT,
                padx=4,
                pady=2,
            )
            b.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=1)
        # Dragging logic
        self._drag_data = {"x": 0, "y": 0}
        self.root.bind("<ButtonPress-1>", self._on_start_move)
        self.root.bind("<B1-Motion>", self._on_move)
        # Socket.IO event
        self.sio.on("playlist_update", self._on_playlist_update)
        # Start background thread for Socket.IO connection
        self._socket_thread = threading.Thread(target=self._run_socketio, daemon=True)
        self._socket_thread.start()
        # Ask for guild and user IDs
        self._prompt_for_ids()

    # ---- Socket.IO handling ----
    def _run_socketio(self) -> None:
        """Run the Socket.IO client in its own thread and reconnect on failures."""
        while True:
            try:
                logger.info("Connecting to Socket.IO server at %s", self.server_url)
                self.sio.connect(self.server_url)
                self.sio.wait()
            except Exception as exc:
                logger.error("Socket.IO connection failed: %s", exc)
                time.sleep(5)

    def _on_playlist_update(self, data: Dict[str, Any]) -> None:
        """Handle incoming playlist updates from the server."""
        logger.debug("Received playlist update: %s", data)
        state = PlaylistState(queue=data.get("queue", []), current=data.get("current"))
        # Tkinter updates must happen in the main thread
        self.root.after(0, self._update_playlist_ui, state)

    def _update_playlist_ui(self, state: PlaylistState) -> None:
        """Update the listbox with the current playlist."""
        self.playlist_box.delete(0, tk.END)
        for idx, item in enumerate(state.queue):
            title = item.get("title") or item.get("url")
            prefix = "▶ " if state.current and item == state.current else f"{idx + 1}. "
            self.playlist_box.insert(tk.END, f"{prefix}{title}")

    # ---- User interactions ----
    def _prompt_for_ids(self) -> None:
        """Prompt the user for guild_id and user_id using simple dialogs."""
        self.guild_id = simpledialog.askstring(
            "Guild ID", "Entrez l'ID du serveur Discord (guild_id) :", parent=self.root
        )
        if not self.guild_id:
            messagebox.showwarning("Guild ID manquant", "L'overlay nécessite un guild_id pour fonctionner.")
        self.user_id = simpledialog.askstring(
            "User ID", "Entrez votre ID utilisateur Discord (user_id) :", parent=self.root
        )

    def _on_start_move(self, event: tk.Event) -> None:
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_move(self, event: tk.Event) -> None:
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _on_enter_pressed(self, event: tk.Event) -> None:
        text = self.entry.get().strip()
        if not text or not self.guild_id or not self.user_id:
            return
        # Send a play request: treat the input as title and URL.  The backend
        # will fallback to extractor search if needed.
        payload = {
            "title": text,
            "url": text,
            "guild_id": self.guild_id,
            "user_id": self.user_id,
        }
        try:
            r = requests.post(f"{self.server_url}/api/play", json=payload, timeout=10)
            if r.status_code != 200:
                messagebox.showerror(
                    "Erreur", f"Échec de l'ajout : {r.status_code} {r.text}"
                )
        except Exception as exc:
            logger.error("Erreur lors de l'appel à /api/play: %s", exc)
            messagebox.showerror("Erreur", f"Impossible d'ajouter : {exc}")
        finally:
            self.entry.delete(0, tk.END)

    def _handle_action(self, action: str) -> None:
        if not self.guild_id:
            messagebox.showwarning("guild_id manquant", "Définissez d'abord un guild_id.")
            return
        endpoint = f"{self.server_url}/api/{action}"
        try:
            r = requests.post(endpoint, json={"guild_id": self.guild_id}, timeout=10)
            if r.status_code != 200:
                logger.warning("Action %s failed: %s", action, r.text)
        except Exception as exc:
            logger.error("Erreur lors de l'appel à %s: %s", endpoint, exc)

    def run(self) -> None:
        """Start the Tkinter main loop."""
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    overlay = GregOverlay()
    overlay.run()


if __name__ == "__main__":
    main()
