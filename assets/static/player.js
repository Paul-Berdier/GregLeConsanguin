/* Greg le Consanguin — Web Player (pro, streamlined) — v2026-02-12
   PATCH (2026-02-12 / progress fix):
   - Progress bar no longer depends only on ticker loop: renderNowPlaying sets initial progress.
   - Persist playback snapshot in localStorage and restore after F5 to avoid hard reset to 0.
   - Periodic lightweight resync while playing (every ~5s) to converge to server truth.

   Scope (as requested):
   - Spotify: link/unlink + load playlists + create playlist + delete playlist + play tracks from playlist
   - No Spotify search / no add-to-playlist / no remove-from-playlist / no “add current/queue”
   - YouTube: autocomplete + add to queue
   - Player: queue + controls + optional /voice/join best-effort
   - API_BASE auto: if page is not served from Railway, defaults to Railway origin unless overridden

   Usage:
   - Override API base (optional):
     window.GREG_API_BASE = "https://gregleconsanguin.up.railway.app/api/v1"
   - Enable debug:
     window.GREG_DEBUG = 1  OR localStorage.setItem("greg.webplayer.debug","1")
*/

(() => {
  "use strict";

  // =============================
  // Config
  // =============================
  const STATIC_BASE = window.GREG_STATIC_BASE || "/static";

  const DEFAULT_RAILWAY = "https://gregleconsanguin.up.railway.app/api/v1";
  const RAW_API_BASE = window.GREG_API_BASE || "/api/v1";
  const API_BASE = (() => {
    const b = String(RAW_API_BASE).trim();
    if (!b) return DEFAULT_RAILWAY;

    if (/^https?:\/\//i.test(b)) return b.replace(/\/+$/, "");
    if (String(location.hostname).includes("railway.app")) return b.replace(/\/+$/, "");
    if (b === "/api/v1") return DEFAULT_RAILWAY;

    return b.replace(/\/+$/, "");
  })();

  const API_ORIGIN = (() => {
    try {
      if (/^https?:\/\//i.test(API_BASE)) return new URL(API_BASE).origin;
      return ""; // same-origin
    } catch {
      return "";
    }
  })();

  const LS_KEY_GUILD = "greg.webplayer.guild_id";
  const LS_KEY_SPOTIFY_LAST_PLAYLIST = "greg.spotify.last_playlist_id";
  const LS_KEY_DEBUG = "greg.webplayer.debug";

  // PATCH: persist playback snapshot for progress restore
  const LS_KEY_PROGRESS_PREFIX = "greg.webplayer.progress."; // + guild_id

  const DEBUG = (() => {
    const flag = (window.GREG_DEBUG ?? localStorage.getItem(LS_KEY_DEBUG) ?? "")
      .toString()
      .trim();
    return flag === "1" || flag.toLowerCase() === "true";
  })();

  function dlog(...args) {
    if (DEBUG) console.log("[GregWebPlayer]", ...args);
  }

  // =============================
  // DOM helpers
  // =============================
  const $ = (sel) => document.querySelector(sel);

  const el = {
    // auth
    userAvatar: $("#userAvatar"),
    userName: $("#userName"),
    userStatus: $("#userStatus"),
    btnLoginDiscord: $("#btn-login-discord"),
    btnLogoutDiscord: $("#btn-logout-discord"),
    guildSelect: $("#guildSelect"),

    // search (YouTube)
    searchForm: $("#searchForm"),
    searchInput: $("#searchInput"),
    searchSuggestions: $("#searchSuggestions"),

    // now playing
    artwork: $("#artwork"),
    trackTitle: $("#trackTitle"),
    trackArtist: $("#trackArtist"),
    progressFill: $("#progressFill"),
    progressCurrent: $("#progressCurrent"),
    progressTotal: $("#progressTotal"),
    playPauseUse: $("#playPauseUse"),

    // controls
    btnStop: $("#btn-stop"),
    btnPrev: $("#btn-prev"),
    btnPlayPause: $("#btn-play-pause"),
    btnSkip: $("#btn-skip"),
    btnRepeat: $("#btn-repeat"),

    // queue
    queueCount: $("#queueCount"),
    queueList: $("#queueList"),

    // spotify (minimal)
    spotifyStatus: $("#spotifyStatus"),
    btnSpotifyLogin: $("#btn-spotify-login"),
    btnSpotifyLogout: $("#btn-spotify-logout"),
    btnSpotifyLoadPlaylists: $("#btn-spotify-load-playlists"),

    spotifyPanel: $("#spotifyPanel"),
    spotifyMe: $("#spotifyMe"),
    spotifyPlaylistsWrap: $("#spotifyPlaylistsWrap"),
    spotifyPlaylists: $("#spotifyPlaylists"),
    spotifyTracksWrap: $("#spotifyTracksWrap"),
    spotifyTracks: $("#spotifyTracks"),

    btnSpotifyCreatePlaylist: $("#btn-spotify-create-playlist"),
    spotifyCreateName: $("#spotifyCreateName"),
    spotifyCreatePublic: $("#spotifyCreatePublic"),

    // status bar
    statusMessage: $("#statusMessage"),
    statusText: $("#statusText"),
  };

  // =============================
  // Utils
  // =============================
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatTime(seconds) {
    if (seconds == null || !isFinite(seconds)) return "--:--";
    const s = Math.max(0, Math.floor(Number(seconds)));
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  function toSeconds(v) {
    if (v == null) return null;
    if (typeof v === "number" && isFinite(v)) {
      if (v > 10000) return Math.floor(v / 1000); // ms
      return Math.floor(v);
    }
    const s = String(v).trim();
    if (!s) return null;
    if (/^\d+(\.\d+)?$/.test(s)) {
      const n = Number(s);
      if (!isFinite(n)) return null;
      if (n > 10000) return Math.floor(n / 1000);
      return Math.floor(n);
    }
    const parts = s.split(":").map((x) => Number(x));
    if (parts.some((x) => !isFinite(x))) return null;
    if (parts.length === 2) return parts[0] * 60 + parts[1];
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return null;
  }

  function clamp(n, a, b) {
    n = Number(n);
    if (!isFinite(n)) return a;
    return Math.min(Math.max(n, a), b);
  }

  function setStatus(text, kind = "info") {
    if (!el.statusText) return;
    el.statusText.textContent = text;

    if (el.statusMessage)
      el.statusMessage.classList.remove("status-message--ok", "status-message--err");
    el.statusText.classList.remove("status-text--ok", "status-text--err");

    if (kind === "ok") {
      if (el.statusMessage) el.statusMessage.classList.add("status-message--ok");
      el.statusText.classList.add("status-text--ok");
    } else if (kind === "err") {
      if (el.statusMessage) el.statusMessage.classList.add("status-message--err");
      el.statusText.classList.add("status-text--err");
    }
  }

  function setRepeatActive(active) {
    if (!el.btnRepeat) return;
    el.btnRepeat.classList.toggle("control-btn--active", !!active);
  }

  function updatePlayPauseIcon(paused) {
    const href = paused ? "#icon-play" : "#icon-pause";
    if (el.playPauseUse) el.playPauseUse.setAttribute("href", href);
  }

  // =============================
  // Progress persistence (PATCH)
  // =============================
  function progressKeyForGuild(guildId) {
    const gid = String(guildId || "").trim();
    return `${LS_KEY_PROGRESS_PREFIX}${gid || "noguild"}`;
  }

  function snapshotFromState() {
    const c = state.playlist.current;
    if (!c) return null;
    return {
      v: 1,
      at: Date.now(),
      track: {
        url: c.url || "",
        title: c.title || "",
        artist: c.artist || "",
        provider: c.provider || "",
      },
      pos: Number(state.playlist.position || 0),
      dur: Number(state.playlist.duration || c.duration || 0),
      paused: !!state.playlist.paused,
      guildId: String(state.guildId || ""),
    };
  }

  function saveProgressSnapshot() {
    try {
      if (!state.guildId) return;
      const snap = snapshotFromState();
      if (!snap) return;
      localStorage.setItem(progressKeyForGuild(state.guildId), JSON.stringify(snap));
    } catch {}
  }

  function tryRestoreProgressSnapshot() {
    try {
      if (!state.guildId) return false;
      const raw = localStorage.getItem(progressKeyForGuild(state.guildId));
      if (!raw) return false;
      const snap = JSON.parse(raw);
      if (!snap || typeof snap !== "object" || !snap.track) return false;

      const age = Date.now() - Number(snap.at || 0);
      if (!isFinite(age) || age < 0 || age > 2 * 60 * 60 * 1000) return false; // max 2h

      const c = state.playlist.current;
      if (!c) return false;

      const sameTrack =
        (snap.track.url && c.url && String(snap.track.url) === String(c.url)) ||
        (
          String(snap.track.title || "").toLowerCase() === String(c.title || "").toLowerCase() &&
          String(snap.track.artist || "").toLowerCase() === String(c.artist || "").toLowerCase()
        );

      if (!sameTrack) return false;

      // If server gave us a good position (>0), don't override.
      // Only restore when backend is 0-ish.
      const serverPos = Number(state.playlist.position || 0);
      if (serverPos > 1) return false;

      const basePos = Number(snap.pos || 0);
      const dur = Number(snap.dur || 0) || Number(state.playlist.duration || c.duration || 0);

      // If not paused at snapshot time, advance by elapsed
      const wasPaused = !!snap.paused;
      const elapsed = wasPaused ? 0 : age / 1000;

      const seededPos = dur > 0 ? clamp(basePos + elapsed, 0, dur) : Math.max(0, basePos + elapsed);

      state.playlist.position = seededPos;
      if (!state.playlist.duration && dur) state.playlist.duration = dur;

      state.tick.basePos = seededPos;
      state.tick.baseAt = Date.now();
      state.tick.duration = state.playlist.duration || dur || 0;

      dlog("Progress restored from snapshot", { seededPos, dur, ageMs: age });
      return true;
    } catch (e) {
      dlog("restore snapshot failed", e);
      return false;
    }
  }

  // =============================
  // Discord avatar helpers
  // =============================
  function discordDefaultAvatarIndex(userId) {
    try {
      const id = BigInt(String(userId || "0"));
      const idx = Number((id >> 22n) % 6n);
      return Number.isFinite(idx) ? idx : 0;
    } catch {
      return 0;
    }
  }

  function discordAvatarUrl(me, size = 96) {
    if (!me || !me.id) return null;
    if (me.avatar_url && typeof me.avatar_url === "string" && me.avatar_url.startsWith("http")) {
      return me.avatar_url;
    }
    if (me.avatar) {
      return `https://cdn.discordapp.com/avatars/${me.id}/${me.avatar}.png?size=${size}`;
    }
    const idx = discordDefaultAvatarIndex(me.id);
    return `https://cdn.discordapp.com/embed/avatars/${idx}.png`;
  }

  // =============================
  // API Client
  // =============================
  class GregAPI {
    constructor(base) {
      this.base = base;
      this.routes = {
        // users / auth
        users_me: { method: "GET", path: "/users/me" },
        auth_login: { method: "GET", path: "/auth/login" },
        auth_logout: { method: "POST", path: "/auth/logout" },

        // guilds
        guilds: { method: "GET", path: "/guilds" },

        // search (YouTube)
        search_autocomplete: { method: "GET", path: "/search/autocomplete" },
        autocomplete_compat: { method: "GET", path: "/autocomplete" },

        // playlist + queue
        playlist_state: { method: "GET", path: "/playlist" },
        queue_add: { method: "POST", path: "/queue/add" },
        queue_remove: { method: "POST", path: "/queue/remove" },
        queue_skip: { method: "POST", path: "/queue/skip" },
        queue_stop: { method: "POST", path: "/queue/stop" },
        playlist_play_at: { method: "POST", path: "/playlist/play_at" },
        playlist_toggle_pause: { method: "POST", path: "/playlist/toggle_pause" },
        playlist_repeat: { method: "POST", path: "/playlist/repeat" },
        playlist_restart: { method: "POST", path: "/playlist/restart" },

        // voice (optional)
        voice_join: { method: "POST", path: "/voice/join" },

        // spotify (ONLY what you keep)
        spotify_login: { method: "GET", path: "/spotify/login" },
        spotify_status: { method: "GET", path: "/spotify/status" },
        spotify_me: { method: "GET", path: "/spotify/me" },
        spotify_playlists: { method: "GET", path: "/spotify/playlists" },
        spotify_playlist_tracks: { method: "GET", path: "/spotify/playlist_tracks" },
        spotify_playlist_create: { method: "POST", path: "/spotify/playlist_create" },
        spotify_playlist_delete: { method: "POST", path: "/spotify/playlist_delete" },
        spotify_quickplay: { method: "POST", path: "/spotify/quickplay" },
        spotify_logout: { method: "POST", path: "/spotify/logout" },
      };
    }

    url(path) {
      return `${this.base}${path}`;
    }

    async request(method, path, { query, json, allowText = false } = {}) {
      const url = new URL(this.url(path), location.href);

      if (query && typeof query === "object") {
        for (const [k, v] of Object.entries(query)) {
          if (v === undefined || v === null || v === "") continue;
          url.searchParams.set(k, String(v));
        }
      }

      const opts = { method, credentials: "include", headers: {} };
      if (json !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(json);
      }

      const res = await fetch(url.toString(), opts);
      const ct = (res.headers.get("content-type") || "").toLowerCase();

      let payload = null;
      if (ct.includes("application/json")) payload = await res.json().catch(() => null);
      else payload = allowText ? await res.text().catch(() => null) : await res.text().catch(() => null);

      if (res.ok && payload && typeof payload === "object" && payload.ok === false) {
        const msg = payload.error || payload.message || "Request failed";
        const err = new Error(msg);
        err.status = res.status;
        err.payload = payload;
        throw err;
      }

      if (!res.ok) {
        const msg =
          (payload && typeof payload === "object" && (payload.error || payload.message)) ||
          (typeof payload === "string" && payload.slice(0, 200)) ||
          `HTTP ${res.status}`;
        const err = new Error(msg);
        err.status = res.status;
        err.payload = payload;
        throw err;
      }

      return payload;
    }

    get(path, query) {
      return this.request("GET", path, { query });
    }

    post(path, json, query) {
      return this.request("POST", path, { json, query });
    }
  }

  const api = new GregAPI(API_BASE);
  window.GregAPI = api;

  // =============================
  // App state
  // =============================
  const state = {
    me: null,
    guilds: [],
    guildId: "",

    socket: null,
    socketReady: false,
    socketId: null,

    playlist: {
      current: null,
      queue: [],
      paused: true,
      repeat: false,
      position: 0,
      duration: 0,
    },

    tick: { running: false, basePos: 0, baseAt: 0, duration: 0 },

    // YouTube suggestions
    suggestions: [],
    sugOpen: false,
    sugIndex: -1,
    sugAbort: null,

    // Spotify minimal
    spotifyLinked: false,
    spotifyProfile: null,
    spotifyPlaylists: [],
    spotifyCurrentPlaylistId: "",
    spotifyTracks: [],

    // voice join throttling
    voiceJoinLastAt: 0,

    // PATCH: resync throttle
    resync: { lastAt: 0 },
  };

  // =============================
  // Socket.IO
  // =============================
  function initSocket() {
    if (typeof window.io !== "function") {
      setStatus("Socket.IO client absent — fallback polling", "err");
      return null;
    }

    const socket = window.io(API_ORIGIN || undefined, {
      path: "/socket.io",
      transports: ["websocket", "polling"],
      withCredentials: true,
      reconnection: true,
      reconnectionAttempts: 999,
      reconnectionDelay: 400,
      reconnectionDelayMax: 2500,
      timeout: 8000,
    });

    socket.on("connect", () => {
      state.socketReady = true;
      state.socketId = socket.id;
      setStatus(`Socket connecté (${socket.id})`, "ok");
      dlog("socket connect", socket.id);

      try {
        socket.emit("overlay_register", {
          kind: "web_player",
          page: "player",
          guild_id: state.guildId ? String(state.guildId) : undefined,
          user_id: state.me?.id ? String(state.me.id) : undefined,
          t: Date.now(),
        });
      } catch (e) {
        dlog("overlay_register failed", e);
      }

      if (state.guildId) {
        try {
          socket.emit("overlay_subscribe_guild", { guild_id: String(state.guildId) });
        } catch (e) {
          dlog("overlay_subscribe_guild failed", e);
        }
      }
    });

    socket.on("disconnect", (reason) => {
      state.socketReady = false;
      setStatus(`Socket déconnecté (${reason}) — polling actif`, "err");
      dlog("socket disconnect", reason);
    });

    socket.on("playlist_update", (payload) => {
      dlog("playlist_update", payload);
      applyPlaylistPayload(payload);
      renderAll();
    });

    socket.on("spotify:linked", async (payload) => {
      dlog("spotify:linked", payload);
      state.spotifyLinked = true;
      state.spotifyProfile = payload?.profile || payload?.data?.profile || null;
      renderSpotify();
      setStatus("Spotify lié ✅", "ok");

      await refreshSpotifyPlaylists().catch(() => {});
      renderAll();
    });

    setInterval(() => {
      if (!state.socketReady) return;
      try {
        socket.emit("overlay_ping", { t: Date.now(), sid: state.socketId || undefined });
      } catch {}
    }, 25000);

    return socket;
  }

  function socketResubscribeGuild(oldGid, newGid) {
    if (!state.socket || !state.socketReady) return;
    try {
      if (oldGid) state.socket.emit("overlay_unsubscribe_guild", { guild_id: String(oldGid) });
      if (newGid) state.socket.emit("overlay_subscribe_guild", { guild_id: String(newGid) });
    } catch {}
  }

  // =============================
  // Payload normalization
  // =============================
  function normalizeMePayload(payload) {
    if (!payload) return null;
    if (typeof payload === "object" && payload.ok === true && payload.user && typeof payload.user === "object") {
      return payload.user;
    }
    if (typeof payload === "object" && payload.id) return payload;
    if (typeof payload === "object" && payload.user && payload.user.id) return payload.user;
    return null;
  }

  function normalizeGuildsPayload(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) return payload;
    if (payload.guilds && Array.isArray(payload.guilds)) return payload.guilds;
    if (payload.data && Array.isArray(payload.data.guilds)) return payload.data.guilds;
    return [];
  }

  function normalizeItem(it) {
    if (!it || typeof it !== "object") return null;
    const title = it.title || it.name || it.track_title || it.track || "";
    const url = it.url || it.webpage_url || it.href || it.link || "";
    const artist = it.artist || it.uploader || it.author || it.channel || it.by || "";

    // PATCH: accept more duration shapes
    const duration =
      toSeconds(
        it.duration ??
          it.duration_s ??
          it.duration_sec ??
          it.duration_ms ??
          it.length ??
          it.length_s ??
          it.length_ms
      ) ?? null;

    const thumb = it.thumb || it.thumbnail || it.image || it.artwork || it.cover || null;
    const provider = it.provider || it.source || it.platform || null;

    return {
      title: String(title || ""),
      url: String(url || ""),
      artist: String(artist || ""),
      duration,
      thumb,
      provider,
      raw: it,
    };
  }

  // PATCH: extra position/duration keys for robustness
  function pickPositionSeconds(p) {
    return (
      toSeconds(p.position ?? p.pos ?? p.progress ?? p.current_time ?? p.currentTime ?? p.elapsed ?? 0) ??
      toSeconds(p.position_ms ?? p.elapsed_ms ?? p.current_time_ms ?? 0) ??
      0
    );
  }

  function pickDurationSeconds(p, current) {
    return (
      toSeconds(p.duration ?? p.total ?? p.length ?? p.total_time ?? p.totalTime ?? (current?.duration ?? 0)) ??
      toSeconds(p.duration_ms ?? p.total_ms ?? p.length_ms ?? 0) ??
      (current?.duration ?? 0) ??
      0
    );
  }

  function applyPlaylistPayload(payload) {
  // payload peut être:
  // - { ok:true, state:{...} } via REST
  // - { state:{...} } via WS broadcast
  // - { only_elapsed:true, progress:{...} } via ticker WS
  const p = payload?.state || payload?.pm || payload?.data || payload || {};

  const isOnlyElapsed = !!(p.only_elapsed || payload?.only_elapsed);

  // ---- Pause / repeat (supporte tes clés back) ----
  const paused = !!(p.paused ?? p.is_paused ?? p.pause ?? false);
  const repeat = !!(p.repeat ?? p.repeat_mode ?? p.loop ?? p.repeat_all ?? false);

  // ---- Progress : le BACK renvoie progress:{elapsed,duration} ----
  const pr = (p.progress && typeof p.progress === "object") ? p.progress : null;

  const position =
    toSeconds(
      pr?.elapsed ??
      pr?.position ??
      p.position ??
      p.pos ??
      p.current_time ??
      0
    ) ?? 0;

  const duration =
    toSeconds(
      pr?.duration ??
      p.duration ??
      p.total ??
      p.length ??
      0
    ) ?? 0;

  // ---- Si c'est un patch "only_elapsed", on ne touche PAS au current/queue ----
  if (isOnlyElapsed) {
    // garde current/queue tels quels
    state.playlist.paused = paused || !state.playlist.current;
    state.playlist.repeat = repeat;

    state.playlist.position = position || 0;
    // si duration est fourni par ticker, on le met à jour
    if (duration) state.playlist.duration = duration;

    // recalage ticker local
    state.tick.basePos = state.playlist.position;
    state.tick.baseAt = Date.now();
    state.tick.duration = state.playlist.duration || duration || 0;

    setRepeatActive(state.playlist.repeat);
    updatePlayPauseIcon(state.playlist.paused);
    return;
  }

  // ---- Update complet ----
  const current = normalizeItem(p.current || p.now_playing || p.playing || null);

  const queueRaw = Array.isArray(p.queue)
    ? p.queue
    : Array.isArray(p.items)
    ? p.items
    : Array.isArray(p.list)
    ? p.list
    : [];

  const queue = queueRaw.map(normalizeItem).filter(Boolean);

  // si le back n'a pas mis duration au top-level, fallback sur current.duration
  const durFinal = duration || (current?.duration ?? 0);

  state.playlist.current = current;
  state.playlist.queue = queue;
  state.playlist.paused = paused || !current;
  state.playlist.repeat = repeat;

  state.playlist.position = position || 0;
  state.playlist.duration = durFinal || 0;

  state.tick.basePos = state.playlist.position;
  state.tick.baseAt = Date.now();
  state.tick.duration = state.playlist.duration;

  setRepeatActive(state.playlist.repeat);
  updatePlayPauseIcon(state.playlist.paused);
}

  // =============================
  // Rendering
  // =============================
  function renderAuth() {
    const me = state.me;

    if (!me) {
      if (el.userAvatar) {
        el.userAvatar.classList.remove("avatar--img");
        el.userAvatar.style.backgroundImage = "";
        el.userAvatar.textContent = "?";
      }
      if (el.userName) el.userName.textContent = "Non connecté";
      if (el.userStatus) el.userStatus.textContent = "Discord";
      if (el.btnLoginDiscord) el.btnLoginDiscord.classList.remove("hidden");
      if (el.btnLogoutDiscord) el.btnLogoutDiscord.classList.add("hidden");
      return;
    }

    const name = me.global_name || me.display_name || me.username || me.name || `User ${me.id}`;
    if (el.userName) el.userName.textContent = name;
    if (el.userStatus) el.userStatus.textContent = "Connecté";
    if (el.btnLoginDiscord) el.btnLoginDiscord.classList.add("hidden");
    if (el.btnLogoutDiscord) el.btnLogoutDiscord.classList.remove("hidden");

    const url = discordAvatarUrl(me, 128);
    if (el.userAvatar) {
      if (url) {
        el.userAvatar.style.backgroundImage = `url("${url}")`;
        el.userAvatar.style.backgroundSize = "contain";
        el.userAvatar.style.backgroundPosition = "center";
        el.userAvatar.style.backgroundRepeat = "no-repeat";
        el.userAvatar.classList.add("avatar--img");
        el.userAvatar.textContent = "";
      } else {
        const letter = (name || "?").trim().slice(0, 1).toUpperCase();
        el.userAvatar.classList.remove("avatar--img");
        el.userAvatar.style.backgroundImage = "";
        el.userAvatar.textContent = letter || "?";
      }
    }
  }

  function renderGuilds() {
    const sel = el.guildSelect;
    if (!sel) return;

    const current = state.guildId ? String(state.guildId) : "";
    const guilds = Array.isArray(state.guilds) ? state.guilds : [];

    const keep0 = sel.querySelector("option[value='']")
      ? sel.querySelector("option[value='']").outerHTML
      : "<option value=''>— Choisir un serveur —</option>";

    sel.innerHTML = keep0;

    for (const g of guilds) {
      const opt = document.createElement("option");
      opt.value = String(g.id);
      opt.textContent = g.name || String(g.id);
      sel.appendChild(opt);
    }

    sel.value = current;
  }

  // PATCH: renderNowPlaying always sets initial progress immediately (no “missing” gauge)
  function renderNowPlaying() {
    const c = state.playlist.current;

    if (!c) {
      if (el.trackTitle) el.trackTitle.textContent = "Rien en cours";
      if (el.trackArtist) el.trackArtist.textContent = "—";
      if (el.artwork) el.artwork.style.backgroundImage = "";
      if (el.progressFill) el.progressFill.style.width = "0%";
      if (el.progressCurrent) el.progressCurrent.textContent = "0:00";
      if (el.progressTotal) el.progressTotal.textContent = "--:--";
      updatePlayPauseIcon(true);
      return;
    }

    if (el.trackTitle) el.trackTitle.textContent = c.title || "Titre inconnu";
    if (el.trackArtist) el.trackArtist.textContent = c.artist || "—";
    if (el.artwork) el.artwork.style.backgroundImage = c.thumb ? `url("${c.thumb}")` : "";

    const dur = state.playlist.duration || c.duration || 0;
    const pos = state.playlist.position || 0;

    if (el.progressCurrent) el.progressCurrent.textContent = formatTime(pos);
    if (el.progressTotal) el.progressTotal.textContent = formatTime(dur);

    const pct = dur > 0 ? (clamp(pos, 0, dur) / dur) * 100 : 0;
    if (el.progressFill) el.progressFill.style.width = `${clamp(pct, 0, 100)}%`;

    updatePlayPauseIcon(state.playlist.paused);
    setRepeatActive(state.playlist.repeat);
  }

  function renderQueue() {
    const q = state.playlist.queue || [];
    if (el.queueCount) el.queueCount.textContent = `${q.length} titre${q.length > 1 ? "s" : ""}`;
    if (!el.queueList) return;

    if (!q.length) {
      el.queueList.innerHTML = `<div class="queue-empty">File d’attente vide</div>`;
      return;
    }

    const html = q
      .map((it, idx) => {
        const title = escapeHtml(it.title || "Titre inconnu");
        const sub = escapeHtml(
          [it.artist || "", it.duration != null ? formatTime(it.duration) : ""].filter(Boolean).join(" • ")
        );
        const thumbStyle = it.thumb ? `style="background-image:url('${escapeHtml(it.thumb)}')"` : "";
        return `
          <div class="queue-item" data-idx="${idx}">
            <div class="queue-thumb" ${thumbStyle}></div>
            <div class="queue-main">
              <div class="queue-title">${title}</div>
              <div class="queue-sub">${sub || "&nbsp;"}</div>
            </div>
            <div class="queue-actions">
              <button class="queue-btn danger" data-action="remove" title="Retirer">
                <svg class="icon" viewBox="0 0 24 24"><use href="#icon-trash"></use></svg>
              </button>
            </div>
          </div>
        `;
      })
      .join("");

    el.queueList.innerHTML = html;

    for (const row of el.queueList.querySelectorAll(".queue-item")) {
      const idx = Number(row.getAttribute("data-idx"));
      row.addEventListener("click", async (ev) => {
        const btn = ev.target.closest("button");
        if (btn) return;
        await safeAction(() => api_playlist_play_at(idx), `Lecture: item #${idx}`, true);
        await bestEffortVoiceJoin("play_at");
      });

      const rm = row.querySelector("button[data-action='remove']");
      if (rm) {
        rm.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          await safeAction(() => api_queue_remove(idx), `Retiré: item #${idx}`, true);
        });
      }
    }
  }

  // -------- Spotify UI (minimal) --------
  function renderSpotify() {
    if (!el.spotifyStatus || !el.btnSpotifyLogin || !el.btnSpotifyLogout) return;

    const hasPanel = !!el.spotifyPanel;

    const hidePanel = () => {
      if (hasPanel) el.spotifyPanel.classList.add("hidden");
      if (el.spotifyPlaylistsWrap) el.spotifyPlaylistsWrap.classList.add("hidden");
      if (el.spotifyTracksWrap) el.spotifyTracksWrap.classList.add("hidden");
      if (el.spotifyPlaylists) el.spotifyPlaylists.innerHTML = "";
      if (el.spotifyTracks) el.spotifyTracks.innerHTML = "";
    };

    const showPanel = () => {
      if (hasPanel) el.spotifyPanel.classList.remove("hidden");
      if (el.spotifyPlaylistsWrap) el.spotifyPlaylistsWrap.classList.remove("hidden");
      if (el.spotifyTracksWrap) el.spotifyTracksWrap.classList.remove("hidden");
    };

    // Not logged to Discord
    if (!state.me) {
      el.spotifyStatus.textContent = "Connecte-toi à Discord pour lier Spotify";
      el.btnSpotifyLogin.disabled = true;
      el.btnSpotifyLogout.disabled = true;

      el.btnSpotifyLogout.classList.add("hidden");
      el.btnSpotifyLogin.classList.remove("hidden");

      if (el.spotifyMe) el.spotifyMe.textContent = "";
      if (el.btnSpotifyLoadPlaylists) el.btnSpotifyLoadPlaylists.classList.add("hidden");

      hidePanel();
      return;
    }

    // Logged to Discord
    el.btnSpotifyLogin.disabled = false;
    el.btnSpotifyLogout.disabled = false;

    // Spotify not linked
    if (!state.spotifyLinked) {
      el.spotifyStatus.textContent = "Spotify non lié";

      el.btnSpotifyLogout.classList.add("hidden");
      el.btnSpotifyLogin.classList.remove("hidden");

      if (el.spotifyMe) el.spotifyMe.textContent = "";
      if (el.btnSpotifyLoadPlaylists) el.btnSpotifyLoadPlaylists.classList.add("hidden");

      hidePanel();
      return;
    }

    // Spotify linked
    const prof = state.spotifyProfile || null;
    const name = prof?.display_name || prof?.id || "Spotify lié";

    el.spotifyStatus.textContent = `Spotify lié : ${name}`;
    if (el.spotifyMe) el.spotifyMe.textContent = prof?.id ? `@${prof.id}` : "";

    el.btnSpotifyLogin.classList.add("hidden");
    el.btnSpotifyLogout.classList.remove("hidden");

    if (el.btnSpotifyLoadPlaylists) el.btnSpotifyLoadPlaylists.classList.remove("hidden");

    showPanel();
  }

  function renderSpotifyPlaylists() {
    if (!el.spotifyPlaylists) return;

    const pls = Array.isArray(state.spotifyPlaylists) ? state.spotifyPlaylists : [];
    if (!pls.length) {
      el.spotifyPlaylists.innerHTML = `<div class="queue-empty">Aucune playlist chargée</div>`;
      return;
    }

    el.spotifyPlaylists.innerHTML = pls
      .map((p) => {
        const name = escapeHtml(p.name || "Playlist");
        const id = escapeHtml(p.id || "");

        const owner =
          (typeof p.owner === "string" ? p.owner : p.owner?.display_name || p.owner?.id || "") || "";

        const tracks = String(p.tracks?.total ?? p.tracks_total ?? p.tracksCount ?? p.tracksTotal ?? "");
        const img = p.images?.[0]?.url || p.image || p.cover || "";
        const thumbStyle = img ? `style="background-image:url('${escapeHtml(img)}')"` : "";

        const active =
          state.spotifyCurrentPlaylistId && String(p.id) === String(state.spotifyCurrentPlaylistId)
            ? " is-active"
            : "";

        return `
          <div class="queue-item${active}" data-spotify-pl="${id}">
            <div class="queue-thumb" ${thumbStyle}></div>
            <div class="queue-main">
              <div class="queue-title">${name}</div>
              <div class="queue-sub">${escapeHtml([owner, tracks ? `${tracks} tracks` : ""].filter(Boolean).join(" • "))}</div>
            </div>
            <div class="queue-actions">
              <button class="queue-btn danger" data-action="delete-playlist" title="Supprimer (unfollow)">
                <svg class="icon" viewBox="0 0 24 24"><use href="#icon-trash"></use></svg>
              </button>
            </div>
          </div>
        `;
      })
      .join("");

    for (const row of el.spotifyPlaylists.querySelectorAll(".queue-item[data-spotify-pl]")) {
      row.addEventListener("click", async (ev) => {
        const btn = ev.target.closest("button");
        if (btn) return;

        const pid = row.getAttribute("data-spotify-pl") || "";
        if (!pid) return;

        state.spotifyCurrentPlaylistId = pid;
        localStorage.setItem(LS_KEY_SPOTIFY_LAST_PLAYLIST, pid);
        renderSpotifyPlaylists();

        await safeAction(() => api_spotify_playlist_tracks(pid), "Titres chargés ✅", false);
      });

      const btnDel = row.querySelector("button[data-action='delete-playlist']");
      if (btnDel) {
        btnDel.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();

          const pid = row.getAttribute("data-spotify-pl") || "";
          if (!pid) return;

          const pl = (state.spotifyPlaylists || []).find((x) => String(x.id) === String(pid));
          const plName = pl?.name || pid;

          const ok = window.confirm(`Supprimer / unfollow la playlist "${plName}" ?`);
          if (!ok) return;

          await safeAction(() => api_spotify_playlist_delete(pid), "Playlist supprimée ✅", false);

          if (String(state.spotifyCurrentPlaylistId || "") === String(pid)) {
            state.spotifyCurrentPlaylistId = "";
            localStorage.removeItem(LS_KEY_SPOTIFY_LAST_PLAYLIST);
            state.spotifyTracks = [];
            renderSpotifyTracks();
          }

          await refreshSpotifyPlaylists().catch(() => {});
          renderSpotifyPlaylists();
        });
      }
    }
  }

  function renderSpotifyTracks() {
    if (!el.spotifyTracks) return;

    const rows = Array.isArray(state.spotifyTracks) ? state.spotifyTracks : [];
    if (!rows.length) {
      el.spotifyTracks.innerHTML = `<div class="queue-empty">Aucun titre chargé</div>`;
      return;
    }

    el.spotifyTracks.innerHTML = rows
      .map((t, idx) => {
        const name = escapeHtml(t.name || t.title || "Track");
        const artist = escapeHtml(
          Array.isArray(t.artists)
            ? t.artists.map((a) => a.name).filter(Boolean).join(", ")
            : t.artists || t.artist || ""
        );
        const img = t.album?.images?.[0]?.url || t.image || "";
        const thumbStyle = img ? `style="background-image:url('${escapeHtml(img)}')"` : "";
        return `
          <div class="queue-item" data-idx="${idx}">
            <div class="queue-thumb" ${thumbStyle}></div>
            <div class="queue-main">
              <div class="queue-title">${name}</div>
              <div class="queue-sub">${artist || "&nbsp;"}</div>
            </div>
            <div class="queue-actions">
              <button class="queue-btn" data-action="play" title="Lire">
                <svg class="icon" viewBox="0 0 24 24"><use href="#icon-play"></use></svg>
              </button>
            </div>
          </div>
        `;
      })
      .join("");

    for (const row of el.spotifyTracks.querySelectorAll(".queue-item")) {
      const btnPlay = row.querySelector("button[data-action='play']");
      if (!btnPlay) continue;

      btnPlay.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();

        const idx = Number(row.getAttribute("data-idx"));
        const t = state.spotifyTracks[idx];
        if (!t) return setStatus("Track introuvable.", "err");
        if (!state.guildId) return setStatus("Choisis un serveur Discord.", "err");

        const artistsStr =
          Array.isArray(t.artists) ? t.artists.map((a) => a.name).filter(Boolean).join(", ") : t.artists || t.artist || "";

        const tr = {
          name: t.name || t.title || "",
          artists: artistsStr,
          duration_ms: t.duration_ms ?? null,
          image: t.image || t.album?.images?.[0]?.url || null,
          uri: t.uri || null,
        };

        await safeAction(() => api_spotify_quickplay(tr), "Lecture Spotify ✅", true);
        await bestEffortVoiceJoin("spotify_quickplay");
      });
    }
  }

  function renderAll() {
    renderAuth();
    renderGuilds();
    renderNowPlaying();
    renderQueue();

    renderSpotify();
    renderSpotifyPlaylists();
    renderSpotifyTracks();
  }

  // =============================
  // Progress ticker
  // =============================
  function startProgressLoop() {
    if (state.tick.running) return;
    state.tick.running = true;

    setInterval(async () => {
      const c = state.playlist.current;
      if (!c) return;

      const dur = state.playlist.duration || c.duration || 0;
      const basePos = state.tick.basePos || 0;
      const elapsed = (Date.now() - (state.tick.baseAt || Date.now())) / 1000;
      const paused = !!state.playlist.paused;

      const pos = paused ? basePos : basePos + elapsed;
      const clamped = dur > 0 ? Math.min(Math.max(pos, 0), dur) : Math.max(pos, 0);

      // Always update UI even if duration is unknown (dur=0)
      if (el.progressCurrent) el.progressCurrent.textContent = formatTime(clamped);
      if (el.progressTotal) el.progressTotal.textContent = dur > 0 ? formatTime(dur) : "--:--";

      const pct = dur > 0 ? (clamped / dur) * 100 : 0;
      if (el.progressFill) el.progressFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;

      // PATCH: periodically persist & resync (avoid drift + fix reset after F5)
      if (state.guildId && c) saveProgressSnapshot();

      const now = Date.now();
      const shouldResync =
        !paused &&
        state.me &&
        state.guildId &&
        (now - (state.resync.lastAt || 0) > 5000); // ~5s

      if (shouldResync) {
        state.resync.lastAt = now;
        // If server was slow after reload, or our base was restored, converge to true server pos
        try {
          await refreshPlaylist();
          // After refresh, renderNowPlaying will set bar deterministically
          renderNowPlaying();
        } catch {}
      }
    }, 250);
  }

  // =============================
  // Suggestions (YouTube)
  // =============================
  function closeSuggestions() {
    state.sugOpen = false;
    state.sugIndex = -1;
    if (el.searchSuggestions) {
      el.searchSuggestions.classList.remove("search-suggestions--open");
      el.searchSuggestions.innerHTML = "";
    }
  }

  function openSuggestions() {
    state.sugOpen = true;
    if (el.searchSuggestions) el.searchSuggestions.classList.add("search-suggestions--open");
  }

  function renderSuggestions(list) {
    if (!el.searchSuggestions) return;

    if (!Array.isArray(list) || !list.length) {
      closeSuggestions();
      return;
    }

    state.suggestions = list;
    if (state.sugIndex >= list.length) state.sugIndex = -1;

    const html = list
      .map((it, i) => {
        const title = escapeHtml(it.title || it.name || "Titre");
        const artist = escapeHtml(it.artist || it.channel || it.uploader || "");
        const dur = toSeconds(it.duration) ?? null;
        const time = dur != null ? formatTime(dur) : "";
        const thumb = it.thumb || it.thumbnail || null;
        const active = i === state.sugIndex ? " is-active" : "";
        const thumbStyle = thumb ? `style="background-image:url('${escapeHtml(thumb)}')"` : "";
        return `
          <div class="suggestion-item rich${active}" data-idx="${i}">
            <div class="sug-thumb" ${thumbStyle}></div>
            <div class="sug-main">
              <div class="sug-title">${title}</div>
              <div class="sug-artist">${artist || "&nbsp;"}</div>
            </div>
            <div class="sug-time">${escapeHtml(time)}</div>
          </div>
        `;
      })
      .join("");

    el.searchSuggestions.innerHTML = html;
    openSuggestions();

    for (const row of el.searchSuggestions.querySelectorAll(".suggestion-item")) {
      row.addEventListener("mousedown", (ev) => ev.preventDefault());
      row.addEventListener("click", async () => {
        const idx = Number(row.getAttribute("data-idx"));
        const pick = state.suggestions[idx];
        closeSuggestions();
        await addFromSuggestion(pick);
      });
    }
  }

  async function fetchSuggestions(q) {
    if (state.sugAbort) {
      try {
        state.sugAbort.abort();
      } catch {}
    }
    state.sugAbort = new AbortController();

    const endpoints = [api.routes.search_autocomplete.path, api.routes.autocomplete_compat.path];

    for (const p of endpoints) {
      const url = new URL(`${API_BASE}${p}`, location.href);
      url.searchParams.set("q", q);
      url.searchParams.set("limit", "8");

      const res = await fetch(url.toString(), {
        method: "GET",
        credentials: "include",
        signal: state.sugAbort.signal,
      });

      if (!res.ok) {
        if (res.status === 404) continue;
        return [];
      }

      const data = await res.json().catch(() => null);
      const rows = Array.isArray(data?.results) ? data.results : Array.isArray(data) ? data : [];
      return rows;
    }

    return [];
  }

  function debounce(fn, ms) {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }

  const onSearchInput = debounce(async () => {
    const q = (el.searchInput?.value || "").trim();
    if (q.length < 2) {
      closeSuggestions();
      return;
    }
    try {
      const rows = await fetchSuggestions(q);
      renderSuggestions(rows);
    } catch (e) {
      dlog("fetchSuggestions error", e);
    }
  }, 160);

  async function addFromSuggestion(sug) {
    const url = (sug?.webpage_url || sug?.url || "").trim();
    const title = (sug?.title || sug?.name || "").trim();
    const artist = (sug?.artist || sug?.uploader || sug?.channel || "").trim();
    const duration = sug?.duration ?? null;
    const thumb = sug?.thumb || sug?.thumbnail || null;

    if (!state.me) return setStatus("Connecte-toi à Discord d'abord.", "err");
    if (!state.guildId) return setStatus("Choisis un serveur.", "err");

    await safeAction(
      () =>
        api_queue_add({
          query: url || title,
          url: url || undefined,
          webpage_url: url || undefined,
          title: title || undefined,
          artist: artist || undefined,
          duration: duration ?? undefined,
          thumb: thumb || undefined,
          thumbnail: thumb || undefined,
          source: sug?.source || sug?.provider || "yt",
          provider: sug?.provider || sug?.source || undefined,
        }),
      "Ajouté à la file ✅",
      true
    );

    await bestEffortVoiceJoin("add_from_suggestion");

    if (el.searchInput) el.searchInput.value = "";
  }

  // =============================
  // API actions (playlist / queue)
  // =============================
  function basePayload(extra = {}) {
    const out = { ...extra };
    if (state.guildId) out.guild_id = String(state.guildId);
    if (state.me?.id) out.user_id = String(state.me.id);
    return out;
  }

  async function api_playlist_state() {
    return api.get(api.routes.playlist_state.path, state.guildId ? { guild_id: state.guildId } : undefined);
  }

  async function api_queue_add(itemOrQuery) {
    let payload =
      typeof itemOrQuery === "string" ? basePayload({ query: itemOrQuery }) : basePayload(itemOrQuery || {});

    const url = String(payload.url || payload.webpage_url || "").trim();
    const title = String(payload.title || "").trim();

    if (!payload.query) payload.query = url || title || "";
    if (payload.url && !payload.webpage_url) payload.webpage_url = payload.url;
    if (payload.thumb && !payload.thumbnail) payload.thumbnail = payload.thumb;
    if (payload.thumbnail && !payload.thumb) payload.thumb = payload.thumbnail;
    if (payload.duration == null) delete payload.duration;

    const queryStr = String(payload.query || "").trim();
    const urlStr = String(payload.url || payload.webpage_url || "").trim();
    if (!queryStr && !urlStr) throw new Error("Ajout impossible: query/url vide.");

    dlog("queue_add payload", payload);

    try {
      return await api.post(api.routes.queue_add.path, payload);
    } catch (e) {
      const st = Number(e?.status || 0);
      if (![400, 415, 422, 500].includes(st)) throw e;

      const qs = {};
      for (const [k, v] of Object.entries(payload)) {
        if (v === undefined || v === null || v === "") continue;
        qs[k] = String(v);
      }
      dlog("queue_add retry querystring", qs);

      return api.post(api.routes.queue_add.path, {}, qs);
    }
  }

  async function api_queue_remove(index) {
    return api.post(api.routes.queue_remove.path, basePayload({ index: Number(index) }));
  }
  async function api_queue_skip() {
    return api.post(api.routes.queue_skip.path, basePayload({}));
  }
  async function api_queue_stop() {
    return api.post(api.routes.queue_stop.path, basePayload({}));
  }
  async function api_playlist_toggle_pause() {
    return api.post(api.routes.playlist_toggle_pause.path, basePayload({}));
  }
  async function api_playlist_restart() {
    return api.post(api.routes.playlist_restart.path, basePayload({}));
  }
  async function api_playlist_repeat() {
    return api.post(api.routes.playlist_repeat.path, basePayload({}));
  }
  async function api_playlist_play_at(index) {
    return api.post(api.routes.playlist_play_at.path, basePayload({ index: Number(index) }));
  }

  // Optional voice join
  async function bestEffortVoiceJoin(reason) {
    const now = Date.now();
    if (now - state.voiceJoinLastAt < 8000) return;
    state.voiceJoinLastAt = now;

    if (!state.me || !state.guildId) return;

    try {
      await api.post(api.routes.voice_join.path, basePayload({ reason: String(reason || "") }));
      dlog("voice_join ok");
    } catch (e) {
      if (Number(e?.status || 0) !== 404) dlog("voice_join failed", e?.message || e);
    }
  }

  // =============================
  // Spotify actions (minimal)
  // =============================
  async function api_spotify_status() {
    return api.get(api.routes.spotify_status.path);
  }
  async function api_spotify_logout() {
    return api.post(api.routes.spotify_logout.path, {});
  }
  async function api_spotify_me() {
    return api.get(api.routes.spotify_me.path);
  }
  async function api_spotify_playlists() {
    return api.get(api.routes.spotify_playlists.path);
  }
  async function api_spotify_playlist_tracks(playlistId) {
    const data = await api.get(api.routes.spotify_playlist_tracks.path, { playlist_id: playlistId });

    const items =
      (Array.isArray(data?.tracks) && data.tracks) ||
      (Array.isArray(data?.items) && data.items) ||
      (Array.isArray(data?.tracks?.items) && data.tracks.items) ||
      (Array.isArray(data?.data?.items) && data.data.items) ||
      (Array.isArray(data) && data) ||
      [];

    const tracks = items.map((x) => x?.track || x).filter(Boolean);

    state.spotifyTracks = tracks;
    renderSpotifyTracks();
    return data;
  }

  async function api_spotify_playlist_create(name, isPublic) {
    return api.post(api.routes.spotify_playlist_create.path, { name, public: !!isPublic });
  }

  async function api_spotify_playlist_delete(playlistId) {
    if (!playlistId) throw new Error("missing playlist_id");
    return api.post(api.routes.spotify_playlist_delete.path, { playlist_id: String(playlistId) });
  }

  async function api_spotify_quickplay(trackObj) {
    if (!state.guildId) throw new Error("missing guild_id");

    const track = trackObj && typeof trackObj === "object" ? trackObj : {};

    // IMPORTANT: include user_id like other endpoints
    const payload = basePayload({ track });

    const res = await api.post(api.routes.spotify_quickplay.path, payload);

    await sleep(250);
    await refreshPlaylist();
    renderAll();
    return res;
  }

  function openPopup(url, name = "greg_oauth", w = 520, h = 720) {
    const y = Math.round(window.top.outerHeight / 2 + window.top.screenY - h / 2);
    const x = Math.round(window.top.outerWidth / 2 + window.top.screenX - w / 2);
    return window.open(
      url,
      name,
      `toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=${w},height=${h},top=${y},left=${x},noopener=yes`
    );
  }

  function spotifyLogin() {
    if (!state.me) return setStatus("Connecte-toi à Discord avant Spotify.", "err");

    const sid = state.socketId || "";
    const url = `${API_BASE}${api.routes.spotify_login.path}?sid=${encodeURIComponent(sid)}`;
    const popup = openPopup(url, "spotify_link");

    if (!popup) return setStatus("Popup bloquée — autorise les popups puis réessaie.", "err");

    setStatus("Ouverture Spotify…", "ok");

    (async () => {
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline) {
        await sleep(1500);
        await refreshSpotify();
        renderSpotify();
        if (state.spotifyLinked) {
          await refreshSpotifyPlaylists().catch(() => {});
          break;
        }
        if (popup.closed) await sleep(1200);
      }
    })().catch(() => {});
  }

  // =============================
  // Refresh: Auth / Guilds / Spotify / Playlist
  // =============================
  async function refreshMe() {
    try {
      const raw = await api.get(api.routes.users_me.path);
      state.me = normalizeMePayload(raw);
      return state.me;
    } catch {
      state.me = null;
      return null;
    }
  }

  async function refreshGuilds() {
    if (!state.me) {
      state.guilds = [];
      return [];
    }
    try {
      const data = await api.get(api.routes.guilds.path);
      state.guilds = normalizeGuildsPayload(data);
      return state.guilds;
    } catch {
      state.guilds = [];
      return [];
    }
  }

  async function refreshSpotify() {
    if (!state.me) {
      state.spotifyLinked = false;
      state.spotifyProfile = null;
      return;
    }

    try {
      const st = await api_spotify_status();

      if (st && typeof st === "object" && "linked" in st) state.spotifyLinked = !!st.linked;
      else state.spotifyLinked = !!st?.ok;

      state.spotifyProfile = st?.profile || st?.me || st?.data?.profile || st?.data?.me || null;

      if (state.spotifyLinked && !state.spotifyProfile) {
        try {
          const me = await api_spotify_me();
          state.spotifyProfile = me?.profile || me?.me || me?.data?.profile || me?.data?.me || me || null;
        } catch {}
      }
    } catch {
      state.spotifyLinked = false;
      state.spotifyProfile = null;
    }
  }

  async function refreshSpotifyPlaylists() {
    if (!state.spotifyLinked) {
      state.spotifyPlaylists = [];
      state.spotifyTracks = [];
      renderSpotifyPlaylists();
      renderSpotifyTracks();
      return;
    }

    try {
      const data = await api_spotify_playlists();

      const items =
        (Array.isArray(data?.items) && data.items) ||
        (Array.isArray(data?.playlists) && data.playlists) ||
        (Array.isArray(data?.data?.items) && data.data.items) ||
        (Array.isArray(data?.data?.playlists) && data.data.playlists) ||
        (Array.isArray(data) && data) ||
        [];

      state.spotifyPlaylists = items;

      const saved = localStorage.getItem(LS_KEY_SPOTIFY_LAST_PLAYLIST) || "";
      if (!state.spotifyCurrentPlaylistId) state.spotifyCurrentPlaylistId = saved;
      if (!state.spotifyCurrentPlaylistId && items.length) state.spotifyCurrentPlaylistId = items[0]?.id || "";

      renderSpotifyPlaylists();

      if (state.spotifyCurrentPlaylistId) {
        await api_spotify_playlist_tracks(state.spotifyCurrentPlaylistId).catch(() => {});
      } else {
        state.spotifyTracks = [];
        renderSpotifyTracks();
      }
    } catch (e) {
      setStatus(e?.message || "Spotify playlists error", "err");
      state.spotifyPlaylists = [];
      state.spotifyTracks = [];
      renderSpotifyPlaylists();
      renderSpotifyTracks();
    }
  }

  async function refreshPlaylist() {
    if (!state.me || !state.guildId) {
      applyPlaylistPayload({ current: null, queue: [], paused: true, repeat: false, position: 0, duration: 0 });
      return;
    }
    try {
      const data = await api_playlist_state();
      applyPlaylistPayload(data);
    } catch (e) {
      setStatus(String(e?.message || e), "err");
    }
  }

  async function refreshAll() {
    await refreshMe();
    await refreshGuilds();

    const saved = localStorage.getItem(LS_KEY_GUILD) || "";
    if (!state.guildId) {
      if (saved) state.guildId = saved;
      else if (state.guilds?.length) state.guildId = String(state.guilds[0].id);
      else state.guildId = "";
    }

    await refreshSpotify();
    if (state.spotifyLinked) {
      await refreshSpotifyPlaylists().catch(() => {});
    } else {
      state.spotifyPlaylists = [];
      state.spotifyTracks = [];
    }

    await refreshPlaylist();

    // PATCH: after initial refresh, if server still gives 0, try restore snapshot once more
    if (state.playlist.current && state.playlist.position <= 1) {
      tryRestoreProgressSnapshot();
    }

    renderAll();
  }

  // =============================
  // Safe action helper
  // =============================
  async function safeAction(fn, okText, refreshAfter = false) {
    try {
      const res = await fn();
      if (okText) setStatus(okText, "ok");
      if (refreshAfter) await refreshPlaylist();
      renderAll();
      return res;
    } catch (e) {
      const msg = e?.payload?.error || e?.payload?.message || e?.message || String(e);
      setStatus(msg, "err");
      throw e;
    }
  }

  // =============================
  // Polling fallback
  // =============================
  function startPolling() {
    setInterval(async () => {
      if (state.socketReady) return;
      await refreshMe();
      await refreshSpotify();
      await refreshPlaylist();
      renderAll();
    }, 2000);

    setInterval(async () => {
      if (!state.me || !state.spotifyLinked) return;
      await refreshSpotify();
      renderSpotify();
    }, 5000);
  }

  // =============================
  // Events binding
  // =============================
  function bindUI() {
    // YouTube search/autocomplete
    if (el.searchInput) el.searchInput.addEventListener("input", onSearchInput);

    if (el.searchInput) {
      el.searchInput.addEventListener("keydown", async (ev) => {
        if (!state.sugOpen) return;

        if (ev.key === "ArrowDown") {
          ev.preventDefault();
          state.sugIndex = Math.min(state.suggestions.length - 1, state.sugIndex + 1);
          renderSuggestions(state.suggestions);
        } else if (ev.key === "ArrowUp") {
          ev.preventDefault();
          state.sugIndex = Math.max(-1, state.sugIndex - 1);
          renderSuggestions(state.suggestions);
        } else if (ev.key === "Enter") {
          if (state.sugIndex >= 0 && state.suggestions[state.sugIndex]) {
            ev.preventDefault();
            const pick = state.suggestions[state.sugIndex];
            closeSuggestions();
            await addFromSuggestion(pick);
          }
        } else if (ev.key === "Escape") {
          closeSuggestions();
        }
      });

      el.searchInput.addEventListener("blur", () => setTimeout(() => closeSuggestions(), 120));
    }

    if (el.searchForm) {
      el.searchForm.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const q = (el.searchInput?.value || "").trim();
        if (!q) return;

        if (state.sugOpen && state.sugIndex >= 0 && state.suggestions[state.sugIndex]) {
          const pick = state.suggestions[state.sugIndex];
          closeSuggestions();
          await addFromSuggestion(pick);
          return;
        }

        closeSuggestions();
        await safeAction(() => api_queue_add(q), "Ajouté à la file ✅", true);
        await bestEffortVoiceJoin("search_submit");
        if (el.searchInput) el.searchInput.value = "";
      });
    }

    // Discord auth
    if (el.btnLoginDiscord) {
      el.btnLoginDiscord.addEventListener("click", () => {
        const url = `${API_BASE}${api.routes.auth_login.path}`;
        window.location.href = url;
      });
    }

    if (el.btnLogoutDiscord) {
      el.btnLogoutDiscord.addEventListener("click", async () => {
        await safeAction(() => api.post(api.routes.auth_logout.path, {}), "Déconnecté ✅", false);
        state.me = null;
        state.guilds = [];
        state.guildId = "";
        state.spotifyLinked = false;
        state.spotifyProfile = null;
        state.spotifyPlaylists = [];
        state.spotifyTracks = [];
        await refreshAll();
      });
    }

    // Guild select
    if (el.guildSelect) {
      el.guildSelect.addEventListener("change", async () => {
        const oldGid = state.guildId;
        const newGid = el.guildSelect.value || "";
        state.guildId = newGid;

        if (newGid) localStorage.setItem(LS_KEY_GUILD, newGid);
        else localStorage.removeItem(LS_KEY_GUILD);

        socketResubscribeGuild(oldGid, newGid);
        await refreshPlaylist();
        renderAll();
      });
    }

    // Player controls
    if (el.btnStop) el.btnStop.addEventListener("click", async () => safeAction(() => api_queue_stop(), "Stop ✅", true));
    if (el.btnSkip) el.btnSkip.addEventListener("click", async () => safeAction(() => api_queue_skip(), "Skip ✅", true));
    if (el.btnPlayPause)
      el.btnPlayPause.addEventListener("click", async () => safeAction(() => api_playlist_toggle_pause(), "Toggle ✅", true));
    if (el.btnPrev) el.btnPrev.addEventListener("click", async () => safeAction(() => api_playlist_restart(), "Restart ✅", true));
    if (el.btnRepeat) el.btnRepeat.addEventListener("click", async () => safeAction(() => api_playlist_repeat(), "Repeat toggle ✅", true));

    // Spotify link/unlink/load/create
    if (el.btnSpotifyLogin) el.btnSpotifyLogin.addEventListener("click", () => spotifyLogin());

    if (el.btnSpotifyLogout) {
      el.btnSpotifyLogout.addEventListener("click", async () => {
        await safeAction(() => api_spotify_logout(), "Spotify délié ✅", false);
        state.spotifyLinked = false;
        state.spotifyProfile = null;
        state.spotifyPlaylists = [];
        state.spotifyTracks = [];
        state.spotifyCurrentPlaylistId = "";
        localStorage.removeItem(LS_KEY_SPOTIFY_LAST_PLAYLIST);
        renderAll();
      });
    }

    if (el.btnSpotifyLoadPlaylists) {
      el.btnSpotifyLoadPlaylists.addEventListener("click", async () => {
        if (!state.spotifyLinked) return setStatus("Spotify non lié.", "err");
        await safeAction(() => refreshSpotifyPlaylists(), "Playlists chargées ✅", false);
      });
    }

    if (el.btnSpotifyCreatePlaylist) {
      el.btnSpotifyCreatePlaylist.addEventListener("click", async () => {
        if (!state.spotifyLinked) return setStatus("Spotify non lié.", "err");
        const name = (el.spotifyCreateName?.value || "").trim() || "Greg Playlist";
        const isPublic = !!el.spotifyCreatePublic?.checked;

        const data = await safeAction(() => api_spotify_playlist_create(name, isPublic), "Playlist créée ✅", false);

        await refreshSpotifyPlaylists();

        const createdId = data?.id || data?.playlist_id || data?.playlist?.id || data?.data?.id || "";
        if (createdId) {
          state.spotifyCurrentPlaylistId = String(createdId);
          localStorage.setItem(LS_KEY_SPOTIFY_LAST_PLAYLIST, String(createdId));
          renderSpotifyPlaylists();
          await api_spotify_playlist_tracks(createdId).catch(() => {});
        }
      });
    }

    // After OAuth popup, refresh
    window.addEventListener("focus", async () => {
      try {
        await refreshMe();
        await refreshSpotify();
        if (state.spotifyLinked) await refreshSpotifyPlaylists().catch(() => {});
        renderAll();
      } catch {}
    });

    // close suggestions on outside click
    document.addEventListener("click", (ev) => {
      if (!state.sugOpen) return;
      const target = ev.target;
      const inside =
        (el.searchSuggestions && el.searchSuggestions.contains(target)) ||
        (el.searchInput && el.searchInput.contains(target));
      if (!inside) closeSuggestions();
    });
  }

  // =============================
  // Boot
  // =============================
  async function boot() {
    setStatus("Initialisation…", "ok");

    const saved = localStorage.getItem(LS_KEY_GUILD) || "";
    if (saved) state.guildId = saved;

    state.socket = initSocket();
    bindUI();

    await refreshAll();

    if (state.socket && state.socketReady && state.guildId) {
      try {
        state.socket.emit("overlay_subscribe_guild", { guild_id: String(state.guildId) });
      } catch {}
    }

    startProgressLoop();
    startPolling();

    setStatus("Prêt ✅", "ok");
  }

  boot().catch((e) => {
    setStatus(`Boot error: ${e?.message || e}`, "err");
  });
})();
