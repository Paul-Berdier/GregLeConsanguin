# Greg Le Consanguin – Refactored Version

This repository contains a comprehensive refactor of the original *Greg le Consanguin* Discord and Web music bot.  The goal of this refactor is to
provide a modern, maintainable code base with an ergonomic web interface (inspired by
Spotify), improved playlist handling, robust YouTube and SoundCloud extraction,
and clear project structure.

## Project structure

```
greg_refonte/
├── bot/              # Discord bot and cogs
│   ├── __init__.py
│   ├── config.py     # Configuration (token, port, yt‑dlp cookies)
│   ├── playlist_manager.py  # Per‑guild playlist persistence
│   └── commands/     # Discord cogs
│       ├── __init__.py
│       ├── music.py  # Slash commands and web helpers
│       └── voice.py  # Join/leave/restart commands
├── extractors/       # Audio extractors for YouTube and SoundCloud
│   ├── __init__.py
│   ├── youtube.py    # Search/download/stream via yt‑dlp
│   └── soundcloud.py
├── web/              # Flask + SocketIO web panel
│   ├── __init__.py
│   ├── app.py        # API endpoints and SocketIO events
│   ├── static/
│   │   ├── assets/
│   │   │   └── greg.png  # Abstract avatar used in the UI
│   │   ├── greg.js  # Dynamic UI logic (autocomplete, controls)
│   │   └── style.css
│   └── templates/
│       ├── index.html
│       ├── select.html
│       └── panel.html
├── main.py           # Entry point to run the bot and web server
├── requirements.txt
└── README.md         # This file
```

## Key improvements

### Modern web interface

- The new panel (``/panel``) uses a dark theme and responsive layout inspired by
  Spotify.  Search suggestions appear in a drop‑down with arrow‑key navigation.
- A single **Pause/Resume** button toggles state and updates dynamically via
  Socket.IO.  Control buttons are more ergonomic and have tooltips.
- The playlist and current track update live without reloading the page.
- Autocomplete fetches results from SoundCloud via the internal search API
  and returns both a title and a URL.  The first result is used as a
  fallback if the user presses *Enter* without selecting a suggestion.

### Robust playlist handling

- Playlists are stored as JSON files on disk under ``data/playlists`` and
  loaded via :class:`playlist_manager.PlaylistManager`.  Each entry
  includes both the title and the URL, which allows pretty printing in
  Discord and on the web.
- All commands (including the ``/playlist`` slash command) reload the
  playlist from disk before reading it, ensuring that updates made from the
  web are reflected in Discord and vice versa.
- Web actions use ``asyncio.run_coroutine_threadsafe`` to post work onto the
  bot’s event loop, preventing ``Future attached to a different loop`` errors.

### Extractors updated for 2025

- The built‑in YouTube extractor uses the latest `yt‑dlp` options to bypass
  YouTube’s security changes and supports searching, streaming, and
  downloading audio with fallback to download.  Providing a cookie file via
  the ``YTDLP_COOKIES_FILE`` environment variable can improve extraction of
  age‑restricted or private tracks【800920760689218†L31-L77】.
- The SoundCloud extractor uses the `yt‑dlp` ``scsearch`` option and falls
  back to download if streaming is unavailable.  SoundCloud’s API is
  rate‑limited; adding your own client ID via the environment variable
  ``SOUNDCLOUD_CLIENT_ID`` may improve reliability【645914700203540†L30-L83】.
- The requirements specify a modern version of `yt‑dlp` (`2025.x.x` or later),
  which addresses YouTube 2025 breakages【860400024579143†L49-L52】.

### Clearer code and structure

- All cogs live under ``greg_refonte/bot/commands`` and import from a
  central ``playlist_manager``.  The code is fully type‑annotated and uses
  Python 3.12 features like pattern matching and union types.
- The web app is decoupled from the Discord bot.  It accesses the music
  cog via the bot instance and uses a simple ``emit`` callback to
  broadcast playlist changes over Socket.IO.
- Configuration is handled via environment variables; no secrets are
  committed in the repo.

## Running locally

1. **Install dependencies**
   ```sh
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Set your Discord bot token** (and optional YTDLP cookies) in the environment:
   ```sh
   export DISCORD_TOKEN=your_bot_token_here
   export YTDLP_COOKIES_FILE=path/to/cookies.txt  # optional
   export WEB_PORT=3000  # optional
   ```
3. **Run the bot**
   ```sh
   python -m greg_refonte.main
   ```

Navigate to `http://localhost:3000` to access the web panel.  The bot
will automatically connect to your Discord server(s) and respond to
slash commands once invited.

## Contributing

Feel free to fork this repository and submit issues or pull requests.
This refactor aims to be modular and straightforward to extend.  To
experiment with alternative extractors or UI frameworks, simply add
new modules under ``extractors`` or update the templates under
``web/templates``.