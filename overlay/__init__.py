"""
Overlay package for Greg le Consanguin.

This package contains a small GUI overlay that can sit on top of your game
window and allow you to control Greg without tabbing out.  The overlay
connects to the local Flask/SocketIO server and listens for playlist
updates.  It exposes simple controls such as pause, resume, skip and stop,
and displays the current queue.  You can also enqueue a new URL or search
query directly from the overlay.

The overlay is intended to be lightweight and unobtrusive.  It leverages
Tkinter, which ships with Python, so no additional GUI framework is
required.  SocketIO is used under the hood to stay in sync with the
server.  See ``overlay/overlay.py`` for the implementation.
"""
