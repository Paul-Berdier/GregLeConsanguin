/* Greg le Consanguin — Web Player (pro)
   - API routes: auth/users/guilds/search/playlist/admin + Spotify full
   - Socket.IO: welcome / overlay_registered / overlay_pong / overlay_joined / overlay_left / playlist_update + spotify:linked
   - Fallback: polling if sockets not available
   - Robust: /users/me supports {ok:true,user:{...}} OR direct user object
   - Robust: search supports /search/autocomplete (preferred) with fallback /autocomplete
*/

(() => {
  "use strict";

  // =============================
  // Config
  // =============================
  const STATIC_BASE = window.GREG_STATIC_BASE || "/static";
  const API_BASE = (window.GREG_API_BASE || "/api/v1").replace(/\/$/, "");
  const API_ORIGIN = API_BASE.replace(/\/api\/v1$/, ""); // http://host:port (or "" if same-origin)
  const LS_KEY_GUILD = "greg.webplayer.guild_id";

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

    // search
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

  function setStatus(text, kind = "info") {
    if (!el.statusText) return;
    el.statusText.textContent = text;

    if (el.statusMessage) el.statusMessage.classList.remove("status-message--ok", "status-message--err");
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

  // Discord avatar helpers
  function discordDefaultAvatarIndex(userId) {
    try {
      // Discord uses (user_id >> 22) % 6 for default? Historically % 5.
      // Embed endpoint supports 0..5. We’ll do % 6 to be safe, fallback to % 5.
      const id = BigInt(String(userId || "0"));
      const idx = Number((id >> 22n) % 6n);
      return Number.isFinite(idx) ? idx : 0;
    } catch (_) {
      return 0;
    }
  }

  function discordAvatarUrl(me, size = 96) {
    if (!me || !me.id) return null;
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
        auth_device_start: { method: "POST", path: "/auth/device/start" },
        auth_device_poll: { method: "GET", path: "/auth/device/poll" },

        // guilds
        guilds: { method: "GET", path: "/guilds" },

        // search (preferred)
        search_autocomplete: { method: "GET", path: "/search/autocomplete" },

        // playlist + queue
        playlist_state: { method: "GET", path: "/playlist" },
        queue_add: { method: "POST", path: "/queue/add" },
        queue_remove: { method: "POST", path: "/queue/remove" },
        queue_move: { method: "POST", path: "/queue/move" },
        queue_skip: { method: "POST", path: "/queue/skip" },
        queue_stop: { method: "POST", path: "/queue/stop" },
        queue_next: { method: "POST", path: "/queue/next" },

        playlist_play: { method: "POST", path: "/playlist/play" },
        playlist_play_at: { method: "POST", path: "/playlist/play_at" },
        playlist_toggle_pause: { method: "POST", path: "/playlist/toggle_pause" },
        playlist_repeat: { method: "POST", path: "/playlist/repeat" },
        playlist_restart: { method: "POST", path: "/playlist/restart" },

        // admin
        admin_overlays_online: { method: "GET", path: "/overlays_online" },
        admin_jumpscare: { method: "POST", path: "/jumpscare" },

        // spotify (FULL)
        spotify_login: { method: "GET", path: "/spotify/login" },
        spotify_callback: { method: "GET", path: "/spotify/callback" }, // not called from JS
        spotify_status: { method: "GET", path: "/spotify/status" },
        spotify_me: { method: "GET", path: "/spotify/me" },
        spotify_playlists: { method: "GET", path: "/spotify/playlists" },
        spotify_playlist_tracks: { method: "GET", path: "/spotify/playlist_tracks" },
        spotify_search_tracks: { method: "GET", path: "/spotify/search_tracks" },

        spotify_playlist_create: { method: "POST", path: "/spotify/playlist_create" },
        spotify_playlist_add_track: { method: "POST", path: "/spotify/playlist_add_track" },
        spotify_playlist_add_by_query: { method: "POST", path: "/spotify/playlist_add_by_query" },
        spotify_add_current_to_playlist: { method: "POST", path: "/spotify/add_current_to_playlist" },
        spotify_add_queue_to_playlist: { method: "POST", path: "/spotify/add_queue_to_playlist" },
        spotify_quickplay: { method: "POST", path: "/spotify/quickplay" },
        spotify_logout: { method: "POST", path: "/spotify/logout" },
        spotify_playlist_delete: { method: "POST", path: "/spotify/playlist_delete" },
        spotify_playlist_remove_tracks: { method: "POST", path: "/spotify/playlist_remove_tracks" },
        spotify_playlist_clear: { method: "POST", path: "/spotify/playlist_clear" },
      };
    }

    url(path) {
      return `${this.base}${path}`;
    }

    async request(method, path, { query, json } = {}) {
      const url = new URL(this.url(path), location.href);
      if (query) {
        for (const [k, v] of Object.entries(query)) {
          if (v === undefined || v === null || v === "") continue;
          url.searchParams.set(k, String(v));
        }
      }

      const opts = {
        method,
        credentials: "include",
        headers: {},
      };

      if (json !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(json);
      }

      const res = await fetch(url.toString(), opts);
      const ct = (res.headers.get("content-type") || "").toLowerCase();

      let payload = null;
      if (ct.includes("application/json")) payload = await res.json().catch(() => null);
      else payload = await res.text().catch(() => null);

      if (!res.ok) {
        const msg =
          (payload && typeof payload === "object" && payload.error) ||
          (payload && typeof payload === "object" && payload.message) ||
          (typeof payload === "string" && payload.slice(0, 200)) ||
          `HTTP ${res.status}`;
        const err = new Error(msg);
        err.status = res.status;
        err.payload = payload;
        throw err;
      }
      return payload;
    }

    async get(path, query) {
      return this.request("GET", path, { query });
    }
    async post(path, json, query) {
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
    guildId: null,

    socket: null,
    socketReady: false,
    socketId: null,

    playlist: {
      current: null,
      queue: [],
      paused: false,
      repeat: false,
      position: 0,
      duration: 0,
    },

    tick: {
      running: false,
      basePos: 0,
      baseAt: 0,
      duration: 0,
      paused: true,
    },

    suggestions: [],
    sugOpen: false,
    sugIndex: -1,
    sugAbort: null,

    spotifyLinked: false,
    spotifyProfile: null,
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

      try {
        socket.emit("overlay_register", {
          kind: "web_player",
          page: "player",
          guild_id: state.guildId ? Number(state.guildId) : undefined,
          user_id: state.me?.id ? Number(state.me.id) : undefined,
        });
      } catch (_) {}

      if (state.guildId) {
        socket.emit("overlay_subscribe_guild", { guild_id: Number(state.guildId) });
      }
    });

    socket.on("disconnect", (reason) => {
      state.socketReady = false;
      setStatus(`Socket déconnecté (${reason}) — polling actif`, "err");
    });

    socket.on("playlist_update", (payload) => {
      applyPlaylistPayload(payload);
      renderAll();
    });

    socket.on("spotify:linked", (payload) => {
      state.spotifyLinked = true;
      state.spotifyProfile = payload?.profile || null;
      renderSpotify();
      setStatus("Spotify lié ✅", "ok");
    });

    setInterval(() => {
      if (!state.socketReady) return;
      try {
        socket.emit("overlay_ping", { t: Date.now() });
      } catch (_) {}
    }, 25000);

    return socket;
  }

  function socketResubscribeGuild(oldGid, newGid) {
    if (!state.socket || !state.socketReady) return;
    try {
      if (oldGid) state.socket.emit("overlay_unsubscribe_guild", { guild_id: Number(oldGid) });
      if (newGid) state.socket.emit("overlay_subscribe_guild", { guild_id: Number(newGid) });
    } catch (_) {}
  }

  // =============================
  // Payload normalization
  // =============================
  function normalizeItem(it) {
    if (!it || typeof it !== "object") return null;
    return {
      title: it.title || it.name || it.track_title || "",
      url: it.url || it.webpage_url || it.href || "",
      artist: it.artist || it.uploader || it.author || it.channel || "",
      duration: toSeconds(it.duration ?? it.duration_s ?? it.duration_sec ?? it.duration_ms) ?? null,
      thumb: it.thumb || it.thumbnail || it.image || null,
      provider: it.provider || it.source || it.platform || null,
    };
  }

  function applyPlaylistPayload(payload) {
    const p = payload?.state || payload?.pm || payload || {};
    const current = normalizeItem(p.current || p.now_playing || null);
    const queueRaw = Array.isArray(p.queue) ? p.queue : Array.isArray(p.items) ? p.items : [];
    const queue = queueRaw.map(normalizeItem).filter(Boolean);

    const paused = !!(p.paused ?? p.is_paused ?? p.pause ?? false);
    const repeat = !!(p.repeat ?? p.repeat_mode ?? p.loop ?? false);

    const position = toSeconds(p.position ?? p.pos ?? p.progress ?? 0) ?? 0;
    const duration =
      toSeconds(p.duration ?? p.total ?? p.length ?? (current?.duration ?? 0)) ??
      (current?.duration ?? 0);

    state.playlist.current = current;
    state.playlist.queue = queue;
    state.playlist.paused = paused;
    state.playlist.repeat = repeat;
    state.playlist.position = position;
    state.playlist.duration = duration;

    state.tick.basePos = position || 0;
    state.tick.baseAt = Date.now();
    state.tick.duration = duration || 0;
    state.tick.paused = paused || !current;

    setRepeatActive(repeat);
    updatePlayPauseIcon(paused);
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

    const name =
      me.global_name ||
      me.display_name ||
      me.username ||
      me.name ||
      `User ${me.id}`;

    if (el.userName) el.userName.textContent = name;
    if (el.userStatus) el.userStatus.textContent = "Connecté";
    if (el.btnLoginDiscord) el.btnLoginDiscord.classList.add("hidden");
    if (el.btnLogoutDiscord) el.btnLogoutDiscord.classList.remove("hidden");

    // Avatar
    const url = discordAvatarUrl(me, 128);
    if (el.userAvatar) {
      if (url) {
        el.userAvatar.style.backgroundImage = `url("${url}")`;
        el.userAvatar.classList.add("avatar--img");
        el.userAvatar.textContent = ""; // on cache la lettre
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
      : "<option value=''></option>";
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

    if (el.artwork) {
      if (c.thumb) el.artwork.style.backgroundImage = `url("${c.thumb}")`;
      else el.artwork.style.backgroundImage = "";
    }

    const dur = state.playlist.duration || c.duration || 0;
    if (el.progressTotal) el.progressTotal.textContent = formatTime(dur);
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

  function renderSpotify() {
    if (!el.spotifyStatus || !el.btnSpotifyLogin || !el.btnSpotifyLogout) return;

    if (!state.me) {
      el.spotifyStatus.textContent = "Connecte-toi à Discord pour lier Spotify";
      el.btnSpotifyLogin.disabled = true;
      el.btnSpotifyLogout.disabled = true;
      el.btnSpotifyLogout.classList.add("hidden");
      el.btnSpotifyLogin.classList.remove("hidden");
      return;
    }

    el.btnSpotifyLogin.disabled = false;
    el.btnSpotifyLogout.disabled = false;

    if (!state.spotifyLinked) {
      el.spotifyStatus.textContent = "Spotify non lié";
      el.btnSpotifyLogout.classList.add("hidden");
      el.btnSpotifyLogin.classList.remove("hidden");
      return;
    }

    const prof = state.spotifyProfile;
    const name = prof?.display_name || prof?.id || "Spotify lié";
    el.spotifyStatus.textContent = `Spotify lié : ${name}`;
    el.btnSpotifyLogin.classList.add("hidden");
    el.btnSpotifyLogout.classList.remove("hidden");
  }

  function renderAll() {
    renderAuth();
    renderGuilds();
    renderNowPlaying();
    renderQueue();
    renderSpotify();
  }

  // =============================
  // Progress ticker
  // =============================
  function startProgressLoop() {
    if (state.tick.running) return;
    state.tick.running = true;

    setInterval(() => {
      const c = state.playlist.current;
      if (!c) return;

      const dur = state.playlist.duration || c.duration || 0;
      const basePos = state.tick.basePos || 0;
      const elapsed = (Date.now() - (state.tick.baseAt || Date.now())) / 1000;
      const paused = state.playlist.paused;

      const pos = paused ? basePos : basePos + elapsed;
      const clamped = dur > 0 ? Math.min(Math.max(pos, 0), dur) : Math.max(pos, 0);

      if (el.progressCurrent) el.progressCurrent.textContent = formatTime(clamped);
      if (el.progressTotal) el.progressTotal.textContent = formatTime(dur);

      const pct = dur > 0 ? (clamped / dur) * 100 : 0;
      if (el.progressFill) el.progressFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    }, 250);
  }

  // =============================
  // Search suggestions
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
      try { state.sugAbort.abort(); } catch (_) {}
    }
    state.sugAbort = new AbortController();

    // Prefer /search/autocomplete, fallback /autocomplete
    const endpoints = [
      `${API_BASE}${api.routes.search_autocomplete.path}`,
      `${API_BASE}/autocomplete`,
    ];

    for (const ep of endpoints) {
      const url = new URL(ep, location.href);
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
      return Array.isArray(data?.results) ? data.results : [];
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
    } catch (_) {}
  }, 160);

  async function addFromSuggestion(sug) {
    const url = sug?.webpage_url || sug?.url || "";
    const title = sug?.title || sug?.name || "";
    const artist = sug?.artist || sug?.uploader || sug?.channel || "";
    const duration = sug?.duration ?? null;
    const thumb = sug?.thumb || sug?.thumbnail || null;

    if (!state.me) {
      setStatus("Connecte-toi à Discord d'abord.", "err");
      return;
    }
    if (!state.guildId) {
      setStatus("Choisis un serveur.", "err");
      return;
    }

    await safeAction(
      () =>
        api_queue_add({
          url,
          title,
          artist,
          duration,
          thumb,
          provider: sug?.provider || sug?.source || undefined,
        }),
      "Ajouté à la file ✅",
      true
    );

    if (el.searchInput) el.searchInput.value = "";
  }

  // =============================
  // API actions (playlist / queue)
  // =============================
  function basePayload(extra = {}) {
    const out = { ...extra };
    if (state.guildId) out.guild_id = Number(state.guildId);
    if (state.me?.id) out.user_id = Number(state.me.id);
    return out;
  }

  async function api_playlist_state() {
    return api.get(api.routes.playlist_state.path, state.guildId ? { guild_id: state.guildId } : undefined);
  }

  async function api_queue_add(itemOrQuery) {
    const payload =
      typeof itemOrQuery === "string"
        ? basePayload({ query: itemOrQuery })
        : basePayload(itemOrQuery || {});
    return api.post(api.routes.queue_add.path, payload);
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

  // =============================
  // Spotify actions
  // =============================
  async function api_spotify_status() {
    return api.get(api.routes.spotify_status.path);
  }

  async function api_spotify_logout() {
    return api.post(api.routes.spotify_logout.path, {});
  }

  function openPopup(url, name = "greg_oauth", w = 520, h = 720) {
    const y = window.top.outerHeight / 2 + window.top.screenY - h / 2;
    const x = window.top.outerWidth / 2 + window.top.screenX - w / 2;
    const win = window.open(
      url,
      name,
      `toolbar=no,location=no,status=no,menubar=no,scrollbars=yes,resizable=yes,width=${w},height=${h},top=${y},left=${x}`
    );
    return win;
  }

  function spotifyLogin() {
    if (!state.me) {
      setStatus("Connecte-toi à Discord avant Spotify.", "err");
      return;
    }

    const sid = state.socketId || "";
    const url = `${API_BASE}${api.routes.spotify_login.path}?sid=${encodeURIComponent(sid)}`;
    const popup = openPopup(url, "spotify_link");

    if (!popup) {
      setStatus("Popup bloquée — autorise les popups puis réessaie.", "err");
      return;
    }

    setStatus("Ouverture Spotify…", "ok");

    // ✅ Polling 60s (ton snippet, intégré proprement)
    (async () => {
      const deadline = Date.now() + 60000;
      while (Date.now() < deadline) {
        await sleep(1500);
        await refreshSpotify();
        renderSpotify();
        if (state.spotifyLinked) break;
      }
    })().catch(() => {});
  }

  // =============================
  // Auth / Guilds / Refresh
  // =============================
  function normalizeMePayload(payload) {
    if (!payload) return null;
    // case 1: { ok:true, user:{...} }
    if (typeof payload === "object" && payload.ok === true && payload.user && typeof payload.user === "object") {
      return payload.user;
    }
    // case 2: direct user object {id, username, ...}
    if (typeof payload === "object" && payload.id) return payload;
    return null;
  }

  async function refreshMe() {
    try {
      const raw = await api.get(api.routes.users_me.path);
      state.me = normalizeMePayload(raw);
      return state.me;
    } catch (_) {
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
      const rows = Array.isArray(data?.guilds) ? data.guilds : Array.isArray(data) ? data : [];
      state.guilds = rows;
      return rows;
    } catch (_) {
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
      state.spotifyLinked = !!st?.linked;
      state.spotifyProfile = st?.profile || null;
    } catch (_) {
      state.spotifyLinked = false;
      state.spotifyProfile = null;
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
      setStatus(String(e.message || e), "err");
    }
  }

  async function refreshAll() {
    await refreshMe();
    await refreshGuilds();

    const saved = localStorage.getItem(LS_KEY_GUILD);
    if (!state.guildId) {
      if (saved) state.guildId = saved;
      else if (state.guilds?.length) state.guildId = String(state.guilds[0].id);
      else state.guildId = "";
    }

    await refreshSpotify();
    await refreshPlaylist();
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
  // Events binding
  // =============================
  function bindUI() {
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

      el.searchInput.addEventListener("blur", () => {
        setTimeout(() => closeSuggestions(), 120);
      });
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
        if (el.searchInput) el.searchInput.value = "";
      });
    }

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
        await refreshAll();
      });
    }

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

    if (el.btnStop) el.btnStop.addEventListener("click", async () => safeAction(() => api_queue_stop(), "Stop ✅", true));
    if (el.btnSkip) el.btnSkip.addEventListener("click", async () => safeAction(() => api_queue_skip(), "Skip ✅", true));
    if (el.btnPlayPause) el.btnPlayPause.addEventListener("click", async () => safeAction(() => api_playlist_toggle_pause(), "Toggle ✅", true));
    if (el.btnPrev) el.btnPrev.addEventListener("click", async () => safeAction(() => api_playlist_restart(), "Restart ✅", true));
    if (el.btnRepeat) el.btnRepeat.addEventListener("click", async () => safeAction(() => api_playlist_repeat(), "Repeat toggle ✅", true));

    if (el.btnSpotifyLogin) el.btnSpotifyLogin.addEventListener("click", () => spotifyLogin());

    if (el.btnSpotifyLogout) {
      el.btnSpotifyLogout.addEventListener("click", async () => {
        await safeAction(() => api_spotify_logout(), "Spotify délié ✅", false);
        state.spotifyLinked = false;
        state.spotifyProfile = null;
        renderSpotify();
      });
    }

    // ✅ Très fiable: dès que l’utilisateur revient sur l’onglet après OAuth
    window.addEventListener("focus", async () => {
      try {
        await refreshMe();
        await refreshSpotify();
        renderAll();
      } catch (_) {}
    });
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
  }

  // =============================
  // Boot
  // =============================
  async function boot() {
    setStatus("Initialisation…", "ok");

    state.socket = initSocket();
    bindUI();
    await refreshAll();

    startProgressLoop();
    startPolling();

    setStatus("Prêt ✅", "ok");
  }

  boot().catch((e) => {
    setStatus(`Boot error: ${e?.message || e}`, "err");
  });
})();
