/* Greg le Consanguin — Web Player (pro, streamlined) — v2026-02-13
   - Refactor: architecture propre + actions robustes + messages status niveau
   - FIX: Spotify remove track payload (track_uris) + variable bug
   - PERF: progress ticker via requestAnimationFrame + render ciblé
   - UX: verrouillage boutons pendant action, statuts riches, raccourcis clavier, confirmations intelligentes

   Backend routes used:
   - Discord/Auth:
     GET  /users/me
     GET  /auth/login
     POST /auth/logout
     GET  /guilds
   - Player:
     GET  /playlist?guild_id=...
     POST /queue/add
     POST /queue/remove
     POST /queue/skip
     POST /queue/stop
     POST /playlist/play_at
     POST /playlist/toggle_pause
     POST /playlist/repeat
     POST /playlist/restart
     POST /voice/join (optional)
   - Spotify:
     GET  /spotify/login?sid=...
     GET  /spotify/status
     GET  /spotify/me
     GET  /spotify/playlists
     GET  /spotify/playlist_tracks?playlist_id=...
     POST /spotify/playlist_create
     POST /spotify/playlist_remove_tracks     {playlist_id, track_uris:[...]}
     POST /spotify/playlist_delete            {playlist_id}
     POST /spotify/quickplay                  {guild_id, user_id, track:{...}}
     POST /spotify/logout
     POST /spotify/add_current_to_playlist    {playlist_id, guild_id}
     POST /spotify/add_queue_to_playlist      {playlist_id, guild_id, max_items}

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

  const LS = {
    GUILD: "greg.webplayer.guild_id",
    SPOTIFY_LAST_PLAYLIST: "greg.spotify.last_playlist_id",
    DEBUG: "greg.webplayer.debug",
    PROGRESS_PREFIX: "greg.webplayer.progress.", // + guild_id
  };

  const DEBUG = (() => {
    const flag = (window.GREG_DEBUG ?? localStorage.getItem(LS.DEBUG) ?? "").toString().trim();
    return flag === "1" || flag.toLowerCase() === "true";
  })();

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

  const RESYNC_MS = 5000;               // converge server truth while playing
  const POLL_FALLBACK_MS = 2000;        // when socket disconnected
  const SPOTIFY_POLL_MS = 5000;         // spotify status refresh
  const VOICE_JOIN_COOLDOWN_MS = 8000;  // throttle join
  const PROGRESS_SNAPSHOT_MAX_AGE_MS = 2 * 60 * 60 * 1000; // 2h

  function dlog(...args) {
    if (DEBUG) console.log("[GregWebPlayer]", ...args);
  }

  // =============================
  // DOM
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

    // spotify
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

    // add-to-playlist toolbar
    spotifyTargetName: $("#spotifyTargetName"),
    btnSpotifyAddCurrent: $("#btn-spotify-add-current"),
    btnSpotifyAddQueue: $("#btn-spotify-add-queue"),

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

  function clamp(n, a, b) {
    n = Number(n);
    if (!isFinite(n)) return a;
    return Math.min(Math.max(n, a), b);
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
      if (v > 10000) return Math.floor(v / 1000);
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

  // =============================
  // Status system (pro)
  // =============================
  const Status = (() => {
    let lastText = "";
    let lastKind = "info";
    let toastTimer = null;

    function set(text, kind = "info", { sticky = false } = {}) {
      if (!el.statusText) return;

      // prevent noisy duplicates
      const key = `${kind}::${text}`;
      if (key === `${lastKind}::${lastText}`) return;
      lastText = text;
      lastKind = kind;

      el.statusText.textContent = text;

      if (el.statusMessage) {
        el.statusMessage.classList.remove("status-message--ok", "status-message--err", "status-message--warn");
      }
      el.statusText.classList.remove("status-text--ok", "status-text--err", "status-text--warn");

      if (kind === "ok") {
        if (el.statusMessage) el.statusMessage.classList.add("status-message--ok");
        el.statusText.classList.add("status-text--ok");
      } else if (kind === "err") {
        if (el.statusMessage) el.statusMessage.classList.add("status-message--err");
        el.statusText.classList.add("status-text--err");
      } else if (kind === "warn") {
        if (el.statusMessage) el.statusMessage.classList.add("status-message--warn");
        el.statusText.classList.add("status-text--warn");
      }

      // auto clear (except sticky)
      if (toastTimer) clearTimeout(toastTimer);
      if (!sticky) {
        toastTimer = setTimeout(() => {
          // keep lastText? or clear lightly
          // optional: el.statusText.textContent = "";
        }, 4500);
      }
    }

    return { set };
  })();

  // =============================
  // UI helpers
  // =============================
  function setRepeatActive(active) {
    if (!el.btnRepeat) return;
    el.btnRepeat.classList.toggle("control-btn--active", !!active);
  }

  function updatePlayPauseIcon(paused) {
    const href = paused ? "#icon-play" : "#icon-pause";
    if (el.playPauseUse) el.playPauseUse.setAttribute("href", href);
  }

  function setBusy(node, busy) {
    if (!node) return;
    node.disabled = !!busy;
    node.classList.toggle("is-busy", !!busy);
  }

  function setBtnLoading(btn, loading, labelWhenLoading) {
    if (!btn) return;
    btn.classList.toggle("btn-loading", !!loading);
    btn.disabled = !!loading;

    // optionnel: change le texte pendant chargement
    if (labelWhenLoading) {
      if (loading) {
        btn.dataset._oldLabel = btn.textContent;
        btn.textContent = labelWhenLoading;
      } else if (btn.dataset._oldLabel) {
        btn.textContent = btn.dataset._oldLabel;
        delete btn.dataset._oldLabel;
      }
    }
  }

  // mini wrapper pratique
  async function withBtnLoading(btn, label, fn) {
    setBtnLoading(btn, true, label);
    try {
      return await fn();
    } finally {
      setBtnLoading(btn, false);
    }
  }

  async function withPanelLoading(panelEl, fn) {
    if (panelEl) panelEl.classList.add("is-loading");
    try {
      return await fn();
    } finally {
      if (panelEl) panelEl.classList.remove("is-loading");
    }
  }

  // Global action lock to avoid double-click spam
  const ActionLock = (() => {
    const locks = new Map();
    function isLocked(key) { return locks.get(key) === true; }
    function lock(key) { locks.set(key, true); }
    function unlock(key) { locks.delete(key); }
    return { isLocked, lock, unlock };
  })();

  function setSearchLoading(loading) {
    if (el.searchForm) el.searchForm.classList.toggle("is-loading", !!loading);
    if (el.searchInput) el.searchInput.disabled = !!loading;

    // si tu as un bouton submit dans le form
    const btn = el.searchForm?.querySelector("button[type='submit']");
    if (btn) setBtnLoading(btn, !!loading, "Ajout…");
  }

  async function withSearchLoading(fn) {
    setSearchLoading(true);
    try {
      return await fn();
    } finally {
      setSearchLoading(false);
    }
  }

  // =============================
  // Progress persistence
  // =============================
  function progressKeyForGuild(guildId) {
    const gid = String(guildId || "").trim();
    return `${LS.PROGRESS_PREFIX}${gid || "noguild"}`;
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
      if (!isFinite(age) || age < 0 || age > PROGRESS_SNAPSHOT_MAX_AGE_MS) return false;

      const c = state.playlist.current;
      if (!c) return false;

      const sameTrack =
        (snap.track.url && c.url && String(snap.track.url) === String(c.url)) ||
        (
          String(snap.track.title || "").toLowerCase() === String(c.title || "").toLowerCase() &&
          String(snap.track.artist || "").toLowerCase() === String(c.artist || "").toLowerCase()
        );

      if (!sameTrack) return false;

      // if server already gives reliable position, don’t override
      const serverPos = Number(state.playlist.position || 0);
      if (serverPos > 1) return false;

      const basePos = Number(snap.pos || 0);
      const dur = Number(snap.dur || 0) || Number(state.playlist.duration || c.duration || 0);

      const wasPaused = !!snap.paused;
      const elapsed = wasPaused ? 0 : age / 1000;

      const seededPos = dur > 0 ? clamp(basePos + elapsed, 0, dur) : Math.max(0, basePos + elapsed);

      state.playlist.position = seededPos;
      if (!state.playlist.duration && dur) state.playlist.duration = dur;

      state.tick.basePos = seededPos;
      state.tick.baseAt = performance.now();
      state.tick.duration = state.playlist.duration || dur || 0;

      dlog("Progress restored snapshot", { seededPos, dur, ageMs: age });
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
  // API client
  // =============================
  class GregAPI {
    constructor(base) {
      this.base = base;
      this.routes = {
        users_me: { method: "GET", path: "/users/me" },
        auth_login: { method: "GET", path: "/auth/login" },
        auth_logout: { method: "POST", path: "/auth/logout" },

        guilds: { method: "GET", path: "/guilds" },

        search_autocomplete: { method: "GET", path: "/search/autocomplete" },
        autocomplete_compat: { method: "GET", path: "/autocomplete" },

        playlist_state: { method: "GET", path: "/playlist" },
        queue_add: { method: "POST", path: "/queue/add" },
        queue_remove: { method: "POST", path: "/queue/remove" },
        queue_skip: { method: "POST", path: "/queue/skip" },
        queue_stop: { method: "POST", path: "/queue/stop" },
        playlist_play_at: { method: "POST", path: "/playlist/play_at" },
        playlist_toggle_pause: { method: "POST", path: "/playlist/toggle_pause" },
        playlist_repeat: { method: "POST", path: "/playlist/repeat" },
        playlist_restart: { method: "POST", path: "/playlist/restart" },

        voice_join: { method: "POST", path: "/voice/join" },

        spotify_login: { method: "GET", path: "/spotify/login" },
        spotify_status: { method: "GET", path: "/spotify/status" },
        spotify_me: { method: "GET", path: "/spotify/me" },
        spotify_playlists: { method: "GET", path: "/spotify/playlists" },
        spotify_playlist_tracks: { method: "GET", path: "/spotify/playlist_tracks" },
        spotify_playlist_create: { method: "POST", path: "/spotify/playlist_create" },
        spotify_track_delete: { method: "POST", path: "/spotify/playlist_remove_tracks" },
        spotify_playlist_delete: { method: "POST", path: "/spotify/playlist_delete" },
        spotify_quickplay: { method: "POST", path: "/spotify/quickplay" },
        spotify_logout: { method: "POST", path: "/spotify/logout" },

        spotify_add_current_to_playlist: { method: "POST", path: "/spotify/add_current_to_playlist" },
        spotify_add_queue_to_playlist: { method: "POST", path: "/spotify/add_queue_to_playlist" },
      };
    }

    url(path) { return `${this.base}${path}`; }

    async request(method, path, { query, json } = {}) {
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
      else payload = await res.text().catch(() => null);

      if (res.ok && payload && typeof payload === "object" && payload.ok === false) {
        throw Object.assign(new Error(payload.error || payload.message || "Request failed"), {
          status: res.status,
          payload,
        });
      }

      if (!res.ok) {
        const msg =
          (payload && typeof payload === "object" && (payload.error || payload.message)) ||
          (typeof payload === "string" && payload.slice(0, 200)) ||
          `HTTP ${res.status}`;
        throw Object.assign(new Error(msg), { status: res.status, payload });
      }

      return payload;
    }

    get(path, query) { return this.request("GET", path, { query }); }
    post(path, json, query) { return this.request("POST", path, { json, query }); }
  }

  const api = new GregAPI(API_BASE);
  window.GregAPI = api;

  // =============================
  // State
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

    tick: {
      running: false,
      basePos: 0,
      baseAt: 0,     // performance.now()
      duration: 0,
      rafId: null,
    },

    suggestions: [],
    sugOpen: false,
    sugIndex: -1,
    sugAbort: null,

    spotifyLinked: false,
    spotifyProfile: null,
    spotifyPlaylists: [],
    spotifyCurrentPlaylistId: "",
    spotifyTracks: [],

    voiceJoinLastAt: 0,
    resync: { lastAt: 0 },

    // Render diff cache
    renderCache: {
      nowKey: "",
      queueKey: "",
      spotifyPlaylistsKey: "",
      spotifyTracksKey: "",
      authKey: "",
      guildKey: "",
      spotifyKey: "",
    },
  };

  // =============================
  // Normalization
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

  function applyPlaylistPayload(payload) {
    const root = (payload && typeof payload === "object" ? payload : {}) || {};
    const p =
      (root.state && typeof root.state === "object" ? root.state : null) ||
      (root.pm && typeof root.pm === "object" ? root.pm : null) ||
      (root.data && typeof root.data === "object" ? root.data : null) ||
      root;

    const isTick = !!p.only_elapsed;

    const pickFirst = (...vals) => {
      for (const v of vals) if (v !== undefined && v !== null) return v;
      return undefined;
    };

    const toBool = (v) => {
      if (typeof v === "boolean") return v;
      if (typeof v === "number") return v !== 0;
      if (typeof v === "string") {
        const s = v.trim().toLowerCase();
        if (["1", "true", "yes", "on"].includes(s)) return true;
        if (["0", "false", "no", "off"].includes(s)) return false;
      }
      return !!v;
    };

    const normalizeMaybeItem = (it) => {
      const n = normalizeItem(it);
      return n && (n.title || n.url) ? n : null;
    };

    let current = state.playlist.current;
    if (!isTick) current = normalizeMaybeItem(p.current || p.now_playing || p.playing || null);
    else if (p.current || p.now_playing || p.playing) {
      const maybe = normalizeMaybeItem(p.current || p.now_playing || p.playing);
      if (maybe) current = maybe;
    }

    let queue = state.playlist.queue || [];
    if (!isTick) {
      const queueRaw = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : Array.isArray(p.list) ? p.list : [];
      queue = queueRaw.map(normalizeItem).filter(Boolean);
    } else {
      const queueMaybe = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : Array.isArray(p.list) ? p.list : null;
      if (queueMaybe) queue = queueMaybe.map(normalizeItem).filter(Boolean);
    }

    const paused = toBool(pickFirst(p.is_paused, p.paused, p.isPaused, p.pause, false));
    const repeat = toBool(pickFirst(p.repeat_all, p.repeat, p.repeat_mode, p.loop, false));

    const elapsed = toSeconds(
      pickFirst(p.progress?.elapsed, p.progress?.position, p.elapsed, p.position, p.pos, p.current_time, 0)
    ) ?? 0;

    const duration = toSeconds(
      pickFirst(p.progress?.duration, p.duration, p.total, p.length, current?.duration, 0)
    ) ?? 0;

    state.playlist.current = current;
    state.playlist.queue = queue;
    state.playlist.paused = paused || !current;
    state.playlist.repeat = repeat;

    state.playlist.position = Math.max(0, elapsed || 0);
    state.playlist.duration = Math.max(0, duration || 0);

    // seed ticker base
    state.tick.basePos = state.playlist.position;
    state.tick.baseAt = performance.now();
    state.tick.duration = state.playlist.duration;

    setRepeatActive(state.playlist.repeat);
    updatePlayPauseIcon(state.playlist.paused);
  }

  // =============================
  // Spotify target helpers
  // =============================
  function getSpotifyTargetPlaylist() {
    const pid = String(state.spotifyCurrentPlaylistId || "").trim();
    if (!pid) return null;
    const pls = Array.isArray(state.spotifyPlaylists) ? state.spotifyPlaylists : [];
    const found = pls.find((p) => String(p.id || "") === pid) || null;
    return found || { id: pid, name: "Playlist" };
  }

  function updateSpotifyToolbarState() {
    const target = getSpotifyTargetPlaylist();
    const hasTarget = !!target?.id;
    const can = !!(state.me && state.spotifyLinked && state.guildId && hasTarget);

    if (el.spotifyTargetName) el.spotifyTargetName.textContent = target?.name || "—";
    if (el.btnSpotifyAddCurrent) el.btnSpotifyAddCurrent.disabled = !can;
    if (el.btnSpotifyAddQueue) el.btnSpotifyAddQueue.disabled = !can;
  }

  // =============================
  // Rendering (diff-based)
  // =============================
  function renderAuth() {
    const me = state.me;
    const key = me ? `${me.id}|${me.username || ""}|${me.global_name || ""}|${me.avatar || ""}` : "nologin";
    if (key === state.renderCache.authKey) return;
    state.renderCache.authKey = key;

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
    const key = `${current}|${guilds.map((g) => g.id).join(",")}`;
    if (key === state.renderCache.guildKey) return;
    state.renderCache.guildKey = key;

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

  function renderNowPlaying() {
    const c = state.playlist.current;
    const dur = state.playlist.duration || c?.duration || 0;
    const key = c ? `${c.url}|${c.title}|${c.artist}|${dur}|${!!state.playlist.paused}|${!!state.playlist.repeat}` : "none";
    if (key === state.renderCache.nowKey) return;
    state.renderCache.nowKey = key;

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

    // initialize progress immediately
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
    const key = q.map((x) => `${x.url}|${x.title}`).join("||");
    if (key === state.renderCache.queueKey) {
      if (el.queueCount) el.queueCount.textContent = `${q.length} titre${q.length > 1 ? "s" : ""}`;
      return;
    }
    state.renderCache.queueKey = key;

    if (el.queueCount) el.queueCount.textContent = `${q.length} titre${q.length > 1 ? "s" : ""}`;
    if (!el.queueList) return;

    if (!q.length) {
      el.queueList.innerHTML = `<div class="queue-empty">File d’attente vide</div>`;
      return;
    }

    const html = q.map((it, idx) => {
      const title = escapeHtml(it.title || "Titre inconnu");
      const sub = escapeHtml([it.artist || "", it.duration != null ? formatTime(it.duration) : ""].filter(Boolean).join(" • "));
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
    }).join("");

    el.queueList.innerHTML = html;

    for (const row of el.queueList.querySelectorAll(".queue-item")) {
      const idx = Number(row.getAttribute("data-idx"));

      row.addEventListener("click", async (ev) => {
        const btn = ev.target.closest("button");
        if (btn) return;
        await safeAction(`play_at_${idx}`, () => api_playlist_play_at(idx), `Lecture: #${idx + 1}`, true);
        await bestEffortVoiceJoin("play_at");
      });

      const rm = row.querySelector("button[data-action='remove']");
      if (rm) {
        rm.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          await safeAction(`queue_remove_${idx}`, () => api_queue_remove(idx), `Retiré: #${idx + 1}`, true);
        });
      }
    }
  }

  function renderSpotify() {
    if (!el.spotifyStatus || !el.btnSpotifyLogin || !el.btnSpotifyLogout) return;

    const key = `${!!state.me}|${!!state.spotifyLinked}|${state.spotifyProfile?.id || ""}`;
    if (key === state.renderCache.spotifyKey) {
      updateSpotifyToolbarState();
      return;
    }
    state.renderCache.spotifyKey = key;

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

    if (!state.me) {
      el.spotifyStatus.textContent = "Connecte-toi à Discord pour lier Spotify";
      el.btnSpotifyLogin.disabled = true;
      el.btnSpotifyLogout.disabled = true;
      el.btnSpotifyLogout.classList.add("hidden");
      el.btnSpotifyLogin.classList.remove("hidden");
      if (el.spotifyMe) el.spotifyMe.textContent = "";
      if (el.btnSpotifyLoadPlaylists) el.btnSpotifyLoadPlaylists.classList.add("hidden");
      hidePanel();
      updateSpotifyToolbarState();
      return;
    }

    el.btnSpotifyLogin.disabled = false;
    el.btnSpotifyLogout.disabled = false;

    if (!state.spotifyLinked) {
      el.spotifyStatus.textContent = "Spotify non lié";
      el.btnSpotifyLogout.classList.add("hidden");
      el.btnSpotifyLogin.classList.remove("hidden");
      if (el.spotifyMe) el.spotifyMe.textContent = "";
      if (el.btnSpotifyLoadPlaylists) el.btnSpotifyLoadPlaylists.classList.add("hidden");
      hidePanel();
      updateSpotifyToolbarState();
      return;
    }

    const prof = state.spotifyProfile || null;
    const name = prof?.display_name || prof?.id || "Spotify lié";

    el.spotifyStatus.textContent = `Spotify lié : ${name}`;
    if (el.spotifyMe) el.spotifyMe.textContent = prof?.id ? `@${prof.id}` : "";

    el.btnSpotifyLogin.classList.add("hidden");
    el.btnSpotifyLogout.classList.remove("hidden");
    if (el.btnSpotifyLoadPlaylists) el.btnSpotifyLoadPlaylists.classList.remove("hidden");

    showPanel();
    updateSpotifyToolbarState();
  }

  function renderSpotifyPlaylists() {
    if (!el.spotifyPlaylists) return;
    const pls = Array.isArray(state.spotifyPlaylists) ? state.spotifyPlaylists : [];
    const key = `${state.spotifyCurrentPlaylistId}|${pls.map((p) => p.id).join(",")}`;
    if (key === state.renderCache.spotifyPlaylistsKey) {
      updateSpotifyToolbarState();
      return;
    }
    state.renderCache.spotifyPlaylistsKey = key;

    if (!pls.length) {
      el.spotifyPlaylists.innerHTML = `<div class="queue-empty">Aucune playlist chargée</div>`;
      updateSpotifyToolbarState();
      return;
    }

    el.spotifyPlaylists.innerHTML = pls.map((p) => {
      const name = escapeHtml(p.name || "Playlist");
      const id = escapeHtml(p.id || "");
      const owner = (typeof p.owner === "string" ? p.owner : p.owner?.display_name || p.owner?.id || "") || "";
      const tracks = String(p.tracks?.total ?? p.tracks_total ?? p.tracksCount ?? p.tracksTotal ?? "");
      const img = p.images?.[0]?.url || p.image || p.cover || "";
      const thumbStyle = img ? `style="background-image:url('${escapeHtml(img)}')"` : "";
      const active = state.spotifyCurrentPlaylistId && String(p.id) === String(state.spotifyCurrentPlaylistId)
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
            <button class="queue-btn danger" data-action="delete-playlist" title="Supprimer / unfollow">
              <svg class="icon" viewBox="0 0 24 24"><use href="#icon-trash"></use></svg>
            </button>
          </div>
        </div>
      `;
    }).join("");

    for (const row of el.spotifyPlaylists.querySelectorAll(".queue-item[data-spotify-pl]")) {
      row.addEventListener("click", async (ev) => {
        const btn = ev.target.closest("button");
        if (btn) return;

        const pid = row.getAttribute("data-spotify-pl") || "";
        if (!pid) return;

        state.spotifyCurrentPlaylistId = pid;
        localStorage.setItem(LS.SPOTIFY_LAST_PLAYLIST, pid);

        renderSpotifyPlaylists();
        updateSpotifyToolbarState();

        await safeAction(`spotify_tracks_${pid}`, () => api_spotify_playlist_tracks(pid), "Titres Spotify chargés ✅", false);
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

          await withPanelLoading(el.spotifyTracksWrap, async () => {
            await safeAction(
              `spotify_tracks_${pid}`,
              () => api_spotify_playlist_tracks(pid),
              "Titres Spotify chargés ✅",
              false
            );
          });

          if (String(state.spotifyCurrentPlaylistId || "") === String(pid)) {
            state.spotifyCurrentPlaylistId = "";
            localStorage.removeItem(LS.SPOTIFY_LAST_PLAYLIST);
            state.spotifyTracks = [];
            renderSpotifyTracks();
            updateSpotifyToolbarState();
          }

          await refreshSpotifyPlaylists().catch(() => {});
          renderSpotifyPlaylists();
          updateSpotifyToolbarState();
        });
      }
    }

    updateSpotifyToolbarState();
  }

  function renderSpotifyTracks() {
    if (!el.spotifyTracks) return;

    const rows = Array.isArray(state.spotifyTracks) ? state.spotifyTracks : [];
    const pid = String(state.spotifyCurrentPlaylistId || "").trim();
    const key = `${pid}|${rows.map((t) => (t.uri || t.id || t.name || "")).join(",")}`;
    if (key === state.renderCache.spotifyTracksKey) return;
    state.renderCache.spotifyTracksKey = key;

    if (!rows.length) {
      el.spotifyTracks.innerHTML = `<div class="queue-empty">Aucun titre chargé</div>`;
      return;
    }

    el.spotifyTracks.innerHTML = rows.map((t, idx) => {
      const name = escapeHtml(t.name || t.title || "Track");
      const artist = escapeHtml(
        Array.isArray(t.artists)
          ? t.artists.map((a) => a?.name).filter(Boolean).join(", ")
          : t.artists || t.artist || ""
      );
      const img = t.album?.images?.[0]?.url || t.image || "";
      const thumbStyle = img ? `style="background-image:url('${escapeHtml(img)}')"` : "";

      const uri = String(t.uri || "").trim();
      const id = String(t.id || "").trim();

      return `
        <div class="queue-item" data-idx="${idx}" data-uri="${escapeHtml(uri)}" data-id="${escapeHtml(id)}">
          <div class="queue-thumb" ${thumbStyle}></div>
          <div class="queue-main">
            <div class="queue-title">${name}</div>
            <div class="queue-sub">${artist || "&nbsp;"}</div>
          </div>
          <div class="queue-actions">
            <button class="queue-btn" data-action="play" title="Lire">
              <svg class="icon" viewBox="0 0 24 24"><use href="#icon-play"></use></svg>
            </button>
            <button class="queue-btn danger" data-action="delete-track" title="Retirer de la playlist">
              <svg class="icon" viewBox="0 0 24 24"><use href="#icon-trash"></use></svg>
            </button>
          </div>
        </div>
      `;
    }).join("");

    for (const row of el.spotifyTracks.querySelectorAll(".queue-item")) {
      const idx = Number(row.getAttribute("data-idx"));
      const track = rows[idx];

      const btnPlay = row.querySelector("button[data-action='play']");
      if (btnPlay) {
        btnPlay.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();

          if (!track) return Status.set("Track introuvable.", "err");
          if (!state.guildId) return Status.set("Choisis un serveur Discord.", "warn");

          const artistsStr = Array.isArray(track.artists)
            ? track.artists.map((a) => a?.name).filter(Boolean).join(", ")
            : track.artists || track.artist || "";

          const tr = {
            name: track.name || track.title || "",
            artists: artistsStr,
            duration_ms: track.duration_ms ?? null,
            image: track.image || track.album?.images?.[0]?.url || null,
            uri: track.uri || null,
          };

          await safeAction(`spotify_quickplay_${idx}`, () => api_spotify_quickplay(tr), "Lecture Spotify ✅", true);
          await bestEffortVoiceJoin("spotify_quickplay");
        });
      }

      const btnDel = row.querySelector("button[data-action='delete-track']");
      if (btnDel) {
        btnDel.addEventListener("click", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();

          if (!pid) return Status.set("Choisis une playlist Spotify (colonne Playlists).", "warn");
          if (!state.spotifyLinked) return Status.set("Spotify non lié.", "warn");

          const uri = String(track?.uri || row.getAttribute("data-uri") || "").trim();
          const id = String(track?.id || row.getAttribute("data-id") || "").trim();
          const normUri = uri || (id ? `spotify:track:${id}` : "");

          if (!normUri) return Status.set("Impossible: uri/id manquant pour ce track.", "err");

          const title = track?.name || track?.title || "ce titre";
          const ok = window.confirm(`Retirer "${title}" de la playlist ?`);
          if (!ok) return;

          // Optimistic UI
          const prev = Array.isArray(state.spotifyTracks) ? state.spotifyTracks : [];
          state.spotifyTracks = prev.filter((_, i) => i !== idx);
          renderSpotifyTracks();

          try {
            await withPanelLoading(el.spotifyTracksWrap, async () => {
              await safeAction(
                `spotify_delete_track_${idx}`,
                () => api_spotify_track_delete(pid, [normUri]),
                "Titre retiré ✅",
                false
              );
            });
          } catch (e) {
            // rollback
            state.spotifyTracks = prev;
            renderSpotifyTracks();
            throw e;
          }

          // server resync
          await api_spotify_playlist_tracks(pid).catch(() => {});
        });
      }
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
    updateSpotifyToolbarState();
  }

  // =============================
  // Progress ticker (requestAnimationFrame)
  // =============================
  function computeLivePosition() {
    const c = state.playlist.current;
    if (!c) return { pos: 0, dur: 0, pct: 0 };

    const dur = state.playlist.duration || c.duration || 0;
    const basePos = state.tick.basePos || 0;
    const paused = !!state.playlist.paused;

    const now = performance.now();
    const elapsed = paused ? 0 : (now - (state.tick.baseAt || now)) / 1000;
    const pos = paused ? basePos : basePos + elapsed;
    const clamped = dur > 0 ? clamp(pos, 0, dur) : Math.max(0, pos);
    const pct = dur > 0 ? (clamped / dur) * 100 : 0;

    return { pos: clamped, dur, pct: clamp(pct, 0, 100) };
  }

  function tickProgress() {
    const c = state.playlist.current;
    if (c) {
      const { pos, dur, pct } = computeLivePosition();

      if (el.progressCurrent) el.progressCurrent.textContent = formatTime(pos);
      if (el.progressTotal) el.progressTotal.textContent = dur > 0 ? formatTime(dur) : "--:--";
      if (el.progressFill) el.progressFill.style.width = `${pct}%`;

      // Persist snapshot sometimes (not every frame)
      if (state.guildId) {
        // cheap throttle using modulo time
        if ((Date.now() % 1000) < 40) saveProgressSnapshot();
      }

      // periodic resync while playing
      const now = Date.now();
      const shouldResync = !state.playlist.paused && state.me && state.guildId && (now - (state.resync.lastAt || 0) > RESYNC_MS);
      if (shouldResync) {
        state.resync.lastAt = now;
        refreshPlaylist().then(() => {
          // don’t full render if unchanged; nowPlaying diff handles it
          renderNowPlaying();
          renderQueue();
        }).catch(() => {});
      }
    }

    state.tick.rafId = requestAnimationFrame(tickProgress);
  }

  function startProgressLoop() {
    if (state.tick.running) return;
    state.tick.running = true;
    state.tick.baseAt = performance.now();
    state.tick.rafId = requestAnimationFrame(tickProgress);
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

    const html = list.map((it, i) => {
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
    }).join("");

    el.searchSuggestions.innerHTML = html;
    openSuggestions();

    for (const row of el.searchSuggestions.querySelectorAll(".suggestion-item")) {
      row.addEventListener("mousedown", (ev) => ev.preventDefault());
      row.addEventListener("click", async () => {
        const idx = Number(row.getAttribute("data-idx"));
        const pick = state.suggestions[idx];
        closeSuggestions();
        await withSearchLoading(() => addFromSuggestion(pick));
      });
    }
  }

  async function fetchSuggestions(q) {
    if (state.sugAbort) { try { state.sugAbort.abort(); } catch {} }
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
    if (q.length < 2) { closeSuggestions(); return; }
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

    if (!state.me) return Status.set("Connecte-toi à Discord d'abord.", "warn");
    if (!state.guildId) return Status.set("Choisis un serveur.", "warn");

    await safeAction(
      "queue_add_suggestion",
      () => api_queue_add({
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
  // API actions
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
    let payload = typeof itemOrQuery === "string"
      ? basePayload({ query: itemOrQuery })
      : basePayload(itemOrQuery || {});

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

    // Retry strategy: body JSON first, then querystring fallback for older backends
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
  async function api_queue_skip() { return api.post(api.routes.queue_skip.path, basePayload({})); }
  async function api_queue_stop() { return api.post(api.routes.queue_stop.path, basePayload({})); }
  async function api_playlist_toggle_pause() { return api.post(api.routes.playlist_toggle_pause.path, basePayload({})); }
  async function api_playlist_restart() { return api.post(api.routes.playlist_restart.path, basePayload({})); }
  async function api_playlist_repeat() { return api.post(api.routes.playlist_repeat.path, basePayload({})); }
  async function api_playlist_play_at(index) { return api.post(api.routes.playlist_play_at.path, basePayload({ index: Number(index) })); }

  async function bestEffortVoiceJoin(reason) {
    const now = Date.now();
    if (now - state.voiceJoinLastAt < VOICE_JOIN_COOLDOWN_MS) return;
    state.voiceJoinLastAt = now;
    if (!state.me || !state.guildId) return;

    try {
      await api.post(api.routes.voice_join.path, basePayload({ reason: String(reason || "") }));
      dlog("voice_join ok");
    } catch (e) {
      if (Number(e?.status || 0) !== 404) dlog("voice_join failed", e?.message || e);
    }
  }

  // Spotify API
  async function api_spotify_status() { return api.get(api.routes.spotify_status.path); }
  async function api_spotify_logout() { return api.post(api.routes.spotify_logout.path, {}); }
  async function api_spotify_me() { return api.get(api.routes.spotify_me.path); }
  async function api_spotify_playlists() { return api.get(api.routes.spotify_playlists.path); }

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

  // ✅ FIXED: correct payload for backend
  async function api_spotify_track_delete(playlistId, trackUris) {
    if (!playlistId) throw new Error("missing playlist_id");
    const uris = Array.isArray(trackUris) ? trackUris.map(String).filter(Boolean) : [String(trackUris || "")].filter(Boolean);
    if (!uris.length) throw new Error("missing track_uris");
    return api.post(api.routes.spotify_track_delete.path, { playlist_id: String(playlistId), track_uris: uris });
  }

  async function api_spotify_quickplay(trackObj) {
    if (!state.guildId) throw new Error("missing guild_id");
    const track = trackObj && typeof trackObj === "object" ? trackObj : {};
    const payload = basePayload({ track });

    const res = await api.post(api.routes.spotify_quickplay.path, payload);
    await sleep(250);
    await refreshPlaylist();
    renderAll();
    return res;
  }

  async function api_spotify_add_current_to_playlist(playlistId) {
    if (!state.guildId) throw new Error("Choisis un serveur Discord.");
    if (!playlistId) throw new Error("Choisis une playlist Spotify.");
    return api.post(api.routes.spotify_add_current_to_playlist.path, {
      playlist_id: String(playlistId),
      guild_id: String(state.guildId),
    });
  }

  async function api_spotify_add_queue_to_playlist(playlistId, maxItems = 20) {
    if (!state.guildId) throw new Error("Choisis un serveur Discord.");
    if (!playlistId) throw new Error("Choisis une playlist Spotify.");
    return api.post(api.routes.spotify_add_queue_to_playlist.path, {
      playlist_id: String(playlistId),
      guild_id: String(state.guildId),
      max_items: Number(maxItems) || 20,
    });
  }

  // =============================
  // Socket.IO
  // =============================
  function initSocket() {
    if (typeof window.io !== "function") {
      Status.set("Socket.IO absent — mode polling", "warn");
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
      Status.set(`Socket connecté ✅`, "ok");
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
        try { socket.emit("overlay_subscribe_guild", { guild_id: String(state.guildId) }); } catch {}
      }
    });

    socket.on("disconnect", (reason) => {
      state.socketReady = false;
      Status.set(`Socket déconnecté — polling actif`, "warn");
      dlog("socket disconnect", reason);
    });

    socket.on("playlist_update", (payload) => {
      applyPlaylistPayload(payload);
      const p = payload?.state || payload?.data || payload || {};
      if (p.only_elapsed) return;
      renderAll();
    });

    socket.on("spotify:linked", async (payload) => {
      dlog("spotify:linked", payload);
      state.spotifyLinked = true;
      state.spotifyProfile = payload?.profile || payload?.data?.profile || null;
      renderSpotify();
      Status.set("Spotify lié ✅", "ok");
      await refreshSpotifyPlaylists().catch(() => {});
      renderAll();
    });

    setInterval(() => {
      if (!state.socketReady) return;
      try { socket.emit("overlay_ping", { t: Date.now(), sid: state.socketId || undefined }); } catch {}
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
  // Refresh logic
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
      updateSpotifyToolbarState();
      return;
    }

    const data = await api_spotify_playlists();

    const items =
      (Array.isArray(data?.items) && data.items) ||
      (Array.isArray(data?.playlists) && data.playlists) ||
      (Array.isArray(data?.data?.items) && data.data.items) ||
      (Array.isArray(data?.data?.playlists) && data.data.playlists) ||
      (Array.isArray(data) && data) ||
      [];

    state.spotifyPlaylists = items;

    const saved = localStorage.getItem(LS.SPOTIFY_LAST_PLAYLIST) || "";
    if (!state.spotifyCurrentPlaylistId) state.spotifyCurrentPlaylistId = saved;
    if (!state.spotifyCurrentPlaylistId && items.length) state.spotifyCurrentPlaylistId = items[0]?.id || "";

    renderSpotifyPlaylists();
    updateSpotifyToolbarState();

    if (state.spotifyCurrentPlaylistId) {
      await api_spotify_playlist_tracks(state.spotifyCurrentPlaylistId).catch(() => {});
    } else {
      state.spotifyTracks = [];
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
      Status.set(String(e?.message || e), "err");
    }
  }

  async function refreshAll() {
    await refreshMe();
    await refreshGuilds();

    const saved = localStorage.getItem(LS.GUILD) || "";
    if (!state.guildId) {
      if (saved) state.guildId = saved;
      else if (state.guilds?.length) state.guildId = String(state.guilds[0].id);
      else state.guildId = "";
    }

    await refreshSpotify();
    if (state.spotifyLinked) await refreshSpotifyPlaylists().catch(() => {});
    else {
      state.spotifyPlaylists = [];
      state.spotifyTracks = [];
    }

    await refreshPlaylist();

    // restore progress if server pos unreliable
    if (state.playlist.current && state.playlist.position <= 1) {
      tryRestoreProgressSnapshot();
    }

    renderAll();
  }

  // =============================
  // Safe action helper (locked, consistent status)
  // =============================
  async function safeAction(lockKey, fn, okText, refreshAfter = false) {
    if (ActionLock.isLocked(lockKey)) return;
    ActionLock.lock(lockKey);

    try {
      Status.set("Action en cours…", "info");
      const res = await fn();
      if (okText) Status.set(okText, "ok");
      if (refreshAfter) await refreshPlaylist();
      renderAll();
      return res;
    } catch (e) {
      const msg = e?.payload?.error || e?.payload?.message || e?.message || String(e);
      Status.set(msg, "err", { sticky: false });
      throw e;
    } finally {
      ActionLock.unlock(lockKey);
    }
  }

  // =============================
  // OAuth popups
  // =============================
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
    if (!state.me) return Status.set("Connecte-toi à Discord avant Spotify.", "warn");

    const sid = state.socketId || "";
    const url = `${API_BASE}${api.routes.spotify_login.path}?sid=${encodeURIComponent(sid)}`;
    const popup = openPopup(url, "spotify_link");

    if (!popup) return Status.set("Popup bloquée — autorise les popups puis réessaie.", "warn");

    Status.set("Ouverture Spotify…", "info");

    (async () => {
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline) {
        await sleep(1500);
        await refreshSpotify();
        renderSpotify();
        if (state.spotifyLinked) {
          Status.set("Spotify connecté ✅", "ok");
          await refreshSpotifyPlaylists().catch(() => {});
          break;
        }
        if (popup.closed) await sleep(1200);
      }
    })().catch(() => {});
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
    }, POLL_FALLBACK_MS);

    setInterval(async () => {
      if (!state.me || !state.spotifyLinked) return;
      await refreshSpotify();
      renderSpotify();
      updateSpotifyToolbarState();
    }, SPOTIFY_POLL_MS);
  }

   async function reloadSpotifyTracksForTarget(targetId) {
     if (typeof withPanelLoading === "function") {
       return withPanelLoading(el.spotifyTracksWrap, async () => {
         await api_spotify_playlist_tracks(targetId).catch(() => {});
       });
     }
     return api_spotify_playlist_tracks(targetId).catch(() => {});
   }

  // =============================
  // Events binding (+ keyboard shortcuts)
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
            await withSearchLoading(() => addFromSuggestion(pick));
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

        await withSearchLoading(async () => {
          // si suggestion sélectionnée, on l’utilise
          if (state.sugOpen && state.sugIndex >= 0 && state.suggestions[state.sugIndex]) {
            const pick = state.suggestions[state.sugIndex];
            closeSuggestions();
            await addFromSuggestion(pick); // addFromSuggestion fait déjà safeAction
          } else {
            closeSuggestions();
            await safeAction("queue_add_text", () => api_queue_add(q), "Ajouté à la file ✅", true);
            await bestEffortVoiceJoin("search_submit");
          }

          if (el.searchInput) el.searchInput.value = "";
        });
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
        await safeAction("auth_logout", () => api.post(api.routes.auth_logout.path, {}), "Déconnecté ✅", false);
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

        if (newGid) localStorage.setItem(LS.GUILD, newGid);
        else localStorage.removeItem(LS.GUILD);

        socketResubscribeGuild(oldGid, newGid);
        await refreshPlaylist();
        renderAll();
      });
    }

    // Player controls
    if (el.btnStop) el.btnStop.addEventListener("click", async () => safeAction("stop", () => api_queue_stop(), "Stop ✅", true));
    if (el.btnSkip) el.btnSkip.addEventListener("click", async () => safeAction("skip", () => api_queue_skip(), "Skip ✅", true));
    if (el.btnPlayPause) el.btnPlayPause.addEventListener("click", async () => safeAction("toggle_pause", () => api_playlist_toggle_pause(), "Lecture/Pause ✅", true));
    if (el.btnPrev) el.btnPrev.addEventListener("click", async () => safeAction("restart", () => api_playlist_restart(), "Restart ✅", true));
    if (el.btnRepeat) el.btnRepeat.addEventListener("click", async () => safeAction("repeat", () => api_playlist_repeat(), "Repeat togglé ✅", true));

    // Spotify link/unlink/load/create
    if (el.btnSpotifyLogin) el.btnSpotifyLogin.addEventListener("click", () => spotifyLogin());

    if (el.btnSpotifyLogout) {
      el.btnSpotifyLogout.addEventListener("click", async () => {
        await safeAction("spotify_logout", () => api_spotify_logout(), "Spotify délié ✅", false);
        state.spotifyLinked = false;
        state.spotifyProfile = null;
        state.spotifyPlaylists = [];
        state.spotifyTracks = [];
        state.spotifyCurrentPlaylistId = "";
        localStorage.removeItem(LS.SPOTIFY_LAST_PLAYLIST);
        renderAll();
      });
    }

    if (el.btnSpotifyLoadPlaylists) {
      el.btnSpotifyLoadPlaylists.addEventListener("click", async () => {
        if (!state.spotifyLinked) return Status.set("Spotify non lié.", "warn");

        await withBtnLoading(el.btnSpotifyLoadPlaylists, "Chargement…", async () => {
          await safeAction(
            "spotify_load_playlists",
            () => refreshSpotifyPlaylists(),
            "Playlists chargées ✅",
            false
          );
        });
      });
    }

    // Spotify create playlist
    if (el.btnSpotifyCreatePlaylist) {
      el.btnSpotifyCreatePlaylist.addEventListener("click", async () => {
        if (!state.spotifyLinked) return Status.set("Spotify non lié.", "warn");

        const name = (el.spotifyCreateName?.value || "").trim() || "Greg Playlist";
        const isPublic = !!el.spotifyCreatePublic?.checked;

        // Spinner + lock + status ok/err via safeAction
        const data = await withBtnLoading(el.btnSpotifyCreatePlaylist, "Création…", async () => {
          return safeAction(
            "spotify_create_playlist",
            () => api_spotify_playlist_create(name, isPublic),
            "Playlist créée ✅",
            false
          );
        });

        // Refresh playlists after creation
        await refreshSpotifyPlaylists().catch(() => {});

        // Try to focus/select the newly created playlist (id may be in different places)
        const createdId =
          data?.id ||
          data?.playlist_id ||
          data?.playlist?.id ||
          data?.data?.id ||
          "";

        if (!createdId) return;

        state.spotifyCurrentPlaylistId = String(createdId);
        localStorage.setItem(LS.SPOTIFY_LAST_PLAYLIST, String(createdId));

        renderSpotifyPlaylists();
        updateSpotifyToolbarState();

        // Load tracks for the newly created playlist
        await reloadSpotifyTracksForTarget(createdId).catch(() => {});
      });
    }

    // add current
    if (el.btnSpotifyAddCurrent) {
      el.btnSpotifyAddCurrent.addEventListener("click", async () => {
        const target = getSpotifyTargetPlaylist();
        if (!target?.id) return Status.set("Choisis une playlist (colonne Playlists).", "warn");
        if (!state.guildId) return Status.set("Choisis un serveur Discord.", "warn");

        await withBtnLoading(el.btnSpotifyAddCurrent, "Ajout…", async () => {
          await safeAction(
            "spotify_add_current",
            () => api_spotify_add_current_to_playlist(target.id),
            "Titre ajouté à la playlist ✅",
            false
          );
        });

        await reloadSpotifyTracksForTarget(target.id).catch(() => {});
      });
    }

    // add queue
    if (el.btnSpotifyAddQueue) {
      el.btnSpotifyAddQueue.addEventListener("click", async () => {
        const target = getSpotifyTargetPlaylist();
        if (!target?.id) return Status.set("Choisis une playlist (colonne Playlists).", "warn");
        if (!state.guildId) return Status.set("Choisis un serveur Discord.", "warn");

        const qlen = (state.playlist.queue || []).length;
        if (!qlen) return Status.set("File d’attente vide.", "warn");

        const maxItems = 20;
        const n = Math.min(qlen, maxItems);
        const ok = window.confirm(`Ajouter ${n} titre${n > 1 ? "s" : ""} de la file à "${target.name}" ?`);
        if (!ok) return;

        await withBtnLoading(el.btnSpotifyAddQueue, "Ajout…", async () => {
          const res = await safeAction(
            "spotify_add_queue",
            () => api_spotify_add_queue_to_playlist(target.id, maxItems),
            "File ajoutée ✅",
            false
          );
          dlog("add_queue_to_playlist result", res);
        });

        await reloadSpotifyTracksForTarget(target.id).catch(() => {});
      });
    }

    // Refresh after returning focus
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

    // ✅ Keyboard shortcuts (comfort)
    // Space: play/pause (if not typing in input)
    // N: skip, P: restart, R: repeat
    document.addEventListener("keydown", async (ev) => {
      const tag = (ev.target?.tagName || "").toLowerCase();
      const inInput = tag === "input" || tag === "textarea" || ev.target?.isContentEditable;

      if (inInput) return;

      if (ev.code === "Space") {
        ev.preventDefault();
        await safeAction("kbd_pause", () => api_playlist_toggle_pause(), "Lecture/Pause ✅", true);
      } else if (ev.key?.toLowerCase() === "n") {
        await safeAction("kbd_skip", () => api_queue_skip(), "Skip ✅", true);
      } else if (ev.key?.toLowerCase() === "p") {
        await safeAction("kbd_restart", () => api_playlist_restart(), "Restart ✅", true);
      } else if (ev.key?.toLowerCase() === "r") {
        await safeAction("kbd_repeat", () => api_playlist_repeat(), "Repeat togglé ✅", true);
      }
    });
  }

  // =============================
  // Boot
  // =============================
  async function boot() {
    Status.set("Initialisation…", "info", { sticky: true });

    const saved = localStorage.getItem(LS.GUILD) || "";
    if (saved) state.guildId = saved;

    state.socket = initSocket();
    bindUI();

    await refreshAll();

    if (state.socket && state.socketReady && state.guildId) {
      try { state.socket.emit("overlay_subscribe_guild", { guild_id: String(state.guildId) }); } catch {}
    }

    startProgressLoop();
    startPolling();

    Status.set("Prêt ✅", "ok");
  }

  boot().catch((e) => {
    Status.set(`Boot error: ${e?.message || e}`, "err", { sticky: true });
  });
})();
