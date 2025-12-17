/* assets/static/player.js
   Greg le Consanguin — Web Player (TopNav + 3 colonnes)
   - API playlist compatible:
     { ok:true, state:{ current, queue, progress{elapsed,duration}, is_paused, repeat_all, guild_id, thumbnail } }
     + fallback anciens formats: { current, queue, elapsed, duration, is_paused, repeat }
   - Autocomplete: GET /api/v1/autocomplete?q=...&limit=...
   - Discord: /api/v1/me, /api/v1/guilds, /auth/login, /auth/logout
   - Player: /api/v1/playlist, /api/v1/queue/add, /api/v1/queue/remove, /api/v1/queue/skip, /api/v1/playlist/toggle_pause, /api/v1/playlist/restart, /api/v1/playlist/repeat, /api/v1/playlist/play_at
   - Spotify:
     - status/login/logout: /api/v1/spotify/status, /api/v1/spotify/login, /api/v1/spotify/logout
     - playlists (best effort):
       GET /api/v1/spotify/playlists
       GET /api/v1/spotify/playlists/<id>/tracks
       POST /api/v1/spotify/playlist/enqueue  (optionnel)
*/

"use strict";

class GregWebPlayer {
  constructor() {
    this.API_BASE = (window.GREG_API_BASE || "/api/v1").replace(/\/+$/, "");

    this.guildId = "";
    this.userId = null;
    this.me = null;

    this.state = {
      current: null,
      queue: [],
      is_paused: false,
      repeat: false,
    };

    this.progress = {
      startedAt: 0,
      elapsed: 0,
      duration: 0,
    };

    this.pollTimer = null;
    this.progressTimer = null;

    // Autocomplete internal
    this.sug = {
      items: [],
      open: false,
      activeIndex: -1,
      abort: null,
      lastQuery: "",
    };

    // Spotify
    this.spotify = {
      linked: false,
      playlists: [],
      playlistTracks: [],
      selectedPlaylistId: "",
    };

    // DOM
    this.$statusPill = document.getElementById("statusPill");
    this.$statusText = document.getElementById("statusText");

    this.$statConn = document.getElementById("statConn");
    this.$statGuild = document.getElementById("statGuild");
    this.$statQueue = document.getElementById("statQueue");

    this.$searchForm = document.getElementById("searchForm");
    this.$searchInput = document.getElementById("searchInput");
    this.$suggestions = document.getElementById("searchSuggestions");

    this.$queueList = document.getElementById("queueList");
    this.$queueCount = document.getElementById("queueCount");

    this.$artwork = document.getElementById("artwork");
    this.$title = document.getElementById("trackTitle");
    this.$artist = document.getElementById("trackArtist");
    this.$pf = document.getElementById("progressFill");
    this.$pCur = document.getElementById("progressCurrent");
    this.$pTot = document.getElementById("progressTotal");

    this.$btnPlayPause = document.getElementById("btn-play-pause");
    this.$btnSkip = document.getElementById("btn-skip");
    this.$btnStop = document.getElementById("btn-stop");
    this.$btnRepeat = document.getElementById("btn-repeat");
    this.$btnPrev = document.getElementById("btn-prev");

    // Discord
    this.$userName = document.getElementById("userName");
    this.$userAvatar = document.getElementById("userAvatar");
    this.$userStatus = document.getElementById("userStatus");
    this.$btnLogin = document.getElementById("btn-login-discord");
    this.$btnLogout = document.getElementById("btn-logout-discord");
    this.$guildSelect = document.getElementById("guildSelect");

    // Spotify UI
    this.$spotifyStatus = document.getElementById("spotifyStatus");
    this.$spLogin = document.getElementById("btn-spotify-login");
    this.$spLogout = document.getElementById("btn-spotify-logout");
    this.$spRefresh = document.getElementById("btn-refresh-spotify");
    this.$spHelp = document.getElementById("spotifyHelp");
    this.$spPlaylistSelect = document.getElementById("spotifyPlaylistSelect");
    this.$spTracks = document.getElementById("spotifyTracks");

    // A11y suggestions
    if (this.$suggestions) {
      this.$suggestions.setAttribute("role", "listbox");
      this.$suggestions.setAttribute("aria-label", "Suggestions");
    }

    // Restore persisted guild
    try {
      const saved = localStorage.getItem("greg.guildId") || "";
      if (saved && saved.trim()) this.guildId = saved.trim();
    } catch {}
  }

  // -------------------------
  // Utils
  // -------------------------
  log(...args) {
    console.log("[GregWebPlayer]", ...args);
  }

  setStatus(text, level = "info") {
    if (this.$statusText) this.$statusText.textContent = text;

    const pill = this.$statusPill;
    if (!pill) return;

    const lv = String(level || "info").toLowerCase();
    pill.textContent = lv.toUpperCase();

    // simple semantic color using inline style class-less
    pill.style.borderColor = "rgba(99,102,241,.28)";
    pill.style.background = "rgba(99,102,241,.18)";

    if (lv === "ok") {
      pill.style.borderColor = "rgba(16,185,129,.35)";
      pill.style.background = "rgba(16,185,129,.15)";
    } else if (lv === "err") {
      pill.style.borderColor = "rgba(239,68,68,.35)";
      pill.style.background = "rgba(239,68,68,.14)";
    } else if (lv === "warn") {
      pill.style.borderColor = "rgba(245,158,11,.35)";
      pill.style.background = "rgba(245,158,11,.14)";
    }
  }

  setMiniStats() {
    if (this.$statConn) this.$statConn.textContent = this.me?.id ? "OK" : "—";
    if (this.$statGuild) this.$statGuild.textContent = this.guildId ? "OK" : "—";
    if (this.$statQueue) this.$statQueue.textContent = String((this.state.queue || []).length);
  }

  debounce(fn, delay = 220) {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), delay);
    };
  }

  pickIconUrl() {
    return "/static/icon.png";
  }

  isProbablyURL(v) {
    v = String(v || "").trim();
    return (
      /^https?:\/\//i.test(v) ||
      /^(?:www\.)?(youtube\.com|youtu\.be|soundcloud\.com|open\.spotify\.com)\//i.test(v)
    );
  }

  isSoundCloudCdn(u) {
    return /^https?:\/\/(?:cf|cf-hls|cf-hls-opus)-(?:opus-)?media\.sndcdn\.com/i.test(u || "");
  }

  normalizePlayUrl(item) {
    const page =
      item?.webpage_url ||
      item?.permalink_url ||
      item?.page_url ||
      item?.url ||
      "";

    if (!page || this.isSoundCloudCdn(page)) return "";

    // Canonicalise YouTube -> watch?v=
    try {
      const m = String(page).match(/(?:v=|youtu\.be\/|\/shorts\/)([A-Za-z0-9_-]{6,})/);
      return m ? `https://www.youtube.com/watch?v=${m[1]}` : page;
    } catch {
      return page;
    }
  }

  formatTime(sec) {
    sec = Math.max(0, Math.floor(Number(sec || 0)));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  // -------------------------
  // HTTP
  // -------------------------
  headers(extra = {}) {
    const h = { "Content-Type": "application/json" };
    if (this.guildId) h["X-Guild-ID"] = String(this.guildId);
    if (this.userId) h["X-User-ID"] = String(this.userId);
    return Object.assign(h, extra);
  }

  async fetchWithTimeout(url, opts = {}, timeoutMs = 12000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal });
    } finally {
      clearTimeout(t);
    }
  }

  async apiGet(path, opts = {}) {
    const url = this.API_BASE + path;
    const r = await this.fetchWithTimeout(
      url,
      {
        method: "GET",
        credentials: "include",
        cache: "no-store",
        ...opts,
        headers: Object.assign({}, opts.headers || {}, this.headers()),
      },
      12000
    );
    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      throw new Error(`GET ${path}: HTTP ${r.status} ${txt ? `- ${txt.slice(0,120)}` : ""}`);
    }
    return await r.json();
  }

  async apiPost(path, body = {}, opts = {}) {
    const url = this.API_BASE + path;
    const r = await this.fetchWithTimeout(
      url,
      {
        method: "POST",
        credentials: "include",
        ...opts,
        headers: Object.assign({}, opts.headers || {}, this.headers()),
        body: JSON.stringify(body || {}),
      },
      12000
    );
    if (!r.ok) {
      const txt = await r.text().catch(() => "");
      throw new Error(`POST ${path}: HTTP ${r.status} ${txt ? `- ${txt.slice(0,120)}` : ""}`);
    }
    return await r.json();
  }

  // -------------------------
  // Playlist parsing
  // -------------------------
  unwrapPlaylistResponse(data) {
    if (!data || typeof data !== "object") return null;
    if (data.state && typeof data.state === "object") return data.state;
    if ("current" in data || "queue" in data || "progress" in data) return data;
    return null;
  }

  sameTrack(a, b) {
    if (!a || !b) return false;
    const au = String(a.url || a.webpage_url || "").trim();
    const bu = String(b.url || b.webpage_url || "").trim();
    if (au && bu && au === bu) return true;

    const at = String(a.title || "").trim();
    const bt = String(b.title || "").trim();
    return at && bt && at === bt;
  }

  applyStateFromBackend(raw) {
    const st = this.unwrapPlaylistResponse(raw);
    if (!st) return false;

    // capture guild_id if not set
    if (!this.guildId && st.guild_id) {
      this.guildId = String(st.guild_id);
      try { localStorage.setItem("greg.guildId", this.guildId); } catch {}
      if (this.$guildSelect) this.$guildSelect.value = this.guildId;
    }

    const current = st.current || null;
    let queue = Array.isArray(st.queue) ? st.queue.slice() : [];

    // remove duplicated current at top of queue
    if (current && queue.length && this.sameTrack(queue[0], current)) {
      queue = queue.slice(1);
    }

    const isPaused = !!(st.is_paused ?? st.paused ?? false);
    const repeat = !!(st.repeat_all ?? st.repeat ?? false);

    const elapsed = Number(st?.progress?.elapsed ?? st.elapsed ?? 0);
    const duration = Number(st?.progress?.duration ?? st.duration ?? (current && current.duration) ?? 0);

    const thumb =
      st.thumbnail ||
      (current && (current.thumb || current.thumbnail)) ||
      "";

    this.state.current = current ? Object.assign({}, current, { thumbnail: thumb }) : null;
    this.state.queue = queue;
    this.state.is_paused = isPaused;
    this.state.repeat = repeat;

    this.progress.elapsed = Number.isFinite(elapsed) ? elapsed : 0;
    this.progress.duration = Number.isFinite(duration) ? duration : 0;
    this.progress.startedAt = Date.now() / 1000 - this.progress.elapsed;

    return true;
  }

  // -------------------------
  // INIT
  // -------------------------
  async init() {
    this.bindEvents();

    await this.refreshMe();
    await this.refreshGuilds();
    this.autoSelectGuildIfPossible();

    await this.refreshState(false);
    await this.refreshSpotify();

    this.pollTimer = setInterval(() => this.refreshState(true), 3000);
    this.progressTimer = setInterval(() => this.renderProgress(), 500);

    this.setMiniStats();
    this.setStatus("Prêt ✅", "ok");
  }

  autoSelectGuildIfPossible() {
    if (this.guildId) return;
    if (!this.$guildSelect) return;

    const opts = Array.from(this.$guildSelect.querySelectorAll("option"));
    const firstGuild = opts.find((o) => o.value && o.value.trim());
    if (firstGuild) {
      this.guildId = firstGuild.value.trim();
      this.$guildSelect.value = this.guildId;
      try { localStorage.setItem("greg.guildId", this.guildId); } catch {}
    }
  }

  // -------------------------
  // Events
  // -------------------------
  bindEvents() {
    // Search submit
    this.$searchForm?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this.onSubmitSearch().catch(() => {});
    });

    // Autocomplete
    const debouncedAuto = this.debounce((q) => this.fetchAutocomplete(q), 220);

    this.$searchInput?.addEventListener("input", () => {
      const q = (this.$searchInput.value || "").trim();
      if (q.length < 2) {
        this.hideSuggestions();
        return;
      }
      debouncedAuto(q);
    });

    this.$searchInput?.addEventListener("keydown", (e) => {
      if (!this.sug.open) {
        if (e.key === "ArrowDown" && this.sug.items.length) {
          e.preventDefault();
          this.openSuggestions();
          this.setActiveSuggestion(0);
        }
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        this.hideSuggestions();
        return;
      }

      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(this.sug.items.length - 1, (this.sug.activeIndex < 0 ? 0 : this.sug.activeIndex + 1));
        this.setActiveSuggestion(next);
        return;
      }

      if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = Math.max(0, (this.sug.activeIndex <= 0 ? 0 : this.sug.activeIndex - 1));
        this.setActiveSuggestion(prev);
        return;
      }

      if (e.key === "Enter") {
        if (this.sug.activeIndex >= 0 && this.sug.activeIndex < this.sug.items.length) {
          e.preventDefault();
          const it = this.sug.items[this.sug.activeIndex];
          this.pickSuggestion(it).catch(() => {});
        }
      }
    });

    document.addEventListener("click", (e) => {
      const t = e.target;
      if (!t) return;
      const inside =
        (this.$suggestions && this.$suggestions.contains(t)) ||
        (this.$searchInput && this.$searchInput.contains(t));
      if (!inside) this.hideSuggestions();
    });

    // Controls
    this.$btnPlayPause?.addEventListener("click", () => this.togglePause());
    this.$btnSkip?.addEventListener("click", () => this.skip());
    this.$btnStop?.addEventListener("click", () => this.restart());
    this.$btnRepeat?.addEventListener("click", () => this.toggleRepeat());

    // Discord
    this.$btnLogin?.addEventListener("click", () => this.loginDiscord());
    this.$btnLogout?.addEventListener("click", () => this.logoutDiscord());

    // Guild select
    this.$guildSelect?.addEventListener("change", () => {
      this.guildId = this.$guildSelect.value || "";
      try { localStorage.setItem("greg.guildId", this.guildId); } catch {}
      this.refreshState(false).catch(() => {});
      this.setMiniStats();
    });

    // Spotify
    this.$spLogin?.addEventListener("click", () => this.loginSpotify());
    this.$spLogout?.addEventListener("click", () => this.logoutSpotify());
    this.$spRefresh?.addEventListener("click", () => this.refreshSpotifyPlaylists(true));

    this.$spPlaylistSelect?.addEventListener("change", () => {
      const pid = this.$spPlaylistSelect.value || "";
      this.spotify.selectedPlaylistId = pid;
      this.refreshSpotifyPlaylistTracks(pid).catch(() => {});
    });
  }

  // -------------------------
  // Search / Autocomplete
  // -------------------------
  async onSubmitSearch() {
    const q = (this.$searchInput?.value || "").trim();
    if (!q) return;
    await this.addTopOrRaw(q);
  }

  async fetchAutocomplete(q) {
    const query = String(q || "").trim();
    if (!query) {
      this.hideSuggestions();
      return;
    }

    if (this.sug.abort) {
      try { this.sug.abort.abort(); } catch {}
      this.sug.abort = null;
    }
    const ctrl = new AbortController();
    this.sug.abort = ctrl;
    this.sug.lastQuery = query;

    try {
      const url = `${this.API_BASE}/autocomplete?q=${encodeURIComponent(query)}&limit=10`;
      const r = await fetch(url, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
        headers: this.headers(),
        signal: ctrl.signal,
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);

      const data = await r.json().catch(() => ({}));
      const arr = Array.isArray(data?.results)
        ? data.results
        : Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data)
        ? data
        : [];

      if (this.sug.lastQuery !== query) return;

      const items = arr
        .map((x) => {
          const urlPage = x?.webpage_url || x?.permalink_url || x?.url || "";
          const thumb =
            x?.thumb ||
            x?.thumbnail ||
            (Array.isArray(x?.thumbnails) && (x.thumbnails.at(-1)?.url || x.thumbnails.at(-1))) ||
            "";
          const duration = Number.isFinite(+x?.duration)
            ? +x.duration
            : Number.isFinite(+x?.duration_seconds)
            ? +x.duration_seconds
            : null;

          return {
            title: (x?.title || x?.track || x?.name || urlPage || "Untitled").trim(),
            artist: (x?.artist || x?.uploader || x?.author || x?.channel || "").trim(),
            duration,
            thumb: String(thumb || ""),
            url: String(x?.url || urlPage || ""),
            webpage_url: String(urlPage || x?.url || ""),
            source: x?.source || x?.provider || "",
          };
        })
        .filter((it) => !!(it.webpage_url || it.url));

      this.sug.items = items;
      this.renderSuggestions(items);
    } catch (e) {
      if (e?.name === "AbortError") return;
      this.log("autocomplete error:", e);
      this.sug.items = [];
      this.hideSuggestions();
    } finally {
      if (this.sug.abort === ctrl) this.sug.abort = null;
    }
  }

  openSuggestions() {
    if (!this.$suggestions) return;
    this.sug.open = true;
    this.$suggestions.classList.add("search-suggestions--open");
  }

  hideSuggestions() {
    if (!this.$suggestions) return;
    this.sug.open = false;
    this.sug.activeIndex = -1;
    this.$suggestions.innerHTML = "";
    this.$suggestions.classList.remove("search-suggestions--open");
  }

  setActiveSuggestion(i) {
    const idx = Number(i);
    if (!Number.isFinite(idx)) return;
    this.sug.activeIndex = idx;

    if (!this.$suggestions) return;
    const rows = Array.from(this.$suggestions.querySelectorAll("[data-sug-idx]"));
    rows.forEach((el) => el.classList.remove("is-active"));
    const active = rows.find((el) => Number(el.getAttribute("data-sug-idx")) === idx);
    if (active) {
      active.classList.add("is-active");
      try { active.scrollIntoView({ block: "nearest" }); } catch {}
    }
  }

  renderSuggestions(items) {
    if (!this.$suggestions) return;

    this.$suggestions.innerHTML = "";
    if (!Array.isArray(items) || items.length === 0) {
      this.hideSuggestions();
      return;
    }

    this.openSuggestions();

    items.slice(0, 10).forEach((it, idx) => {
      const row = document.createElement("div");
      row.className = "suggestion-item";
      row.setAttribute("role", "option");
      row.setAttribute("tabindex", "-1");
      row.setAttribute("data-sug-idx", String(idx));

      const thumb = document.createElement("div");
      thumb.className = "sug-thumb";
      if (it.thumb) {
        const safe = String(it.thumb).replace(/["\n\r]/g, "");
        thumb.style.backgroundImage = `url("${safe}")`;
      } else {
        thumb.style.backgroundImage = `url("${this.pickIconUrl()}")`;
      }

      const main = document.createElement("div");
      main.className = "sug-main";

      const title = document.createElement("div");
      title.className = "sug-title";
      title.textContent = it.title || "Untitled";
      title.title = it.title || "";

      const artist = document.createElement("div");
      artist.className = "sug-artist";
      artist.textContent = it.artist || "";

      main.appendChild(title);
      main.appendChild(artist);

      const time = document.createElement("div");
      time.className = "sug-time";
      time.textContent = it.duration != null ? this.formatTime(it.duration) : "";

      const onPick = async () => { await this.pickSuggestion(it); };

      row.addEventListener("mouseenter", () => this.setActiveSuggestion(idx));
      row.addEventListener("click", () => onPick().catch(() => {}));

      row.appendChild(thumb);
      row.appendChild(main);
      row.appendChild(time);

      this.$suggestions.appendChild(row);
    });

    this.setActiveSuggestion(0);
  }

  async pickSuggestion(it) {
    const playUrl = this.normalizePlayUrl(it);
    if (!playUrl) {
      this.setStatus("Suggestion non jouable (lien CDN / invalide).", "warn");
      return;
    }
    if (this.$searchInput) this.$searchInput.value = it.title || playUrl;

    await this.enqueueItem({
      url: playUrl,
      title: it.title || playUrl,
      duration: it.duration ?? undefined,
      thumb: it.thumb || undefined,
      artist: it.artist || undefined,
      source: it.source || undefined,
    });

    this.hideSuggestions();
  }

  async addTopOrRaw(query) {
    const q = String(query || "").trim();
    if (!q) return;

    if (this.isProbablyURL(q)) {
      await this.enqueueItem({ url: q, title: q });
      return;
    }

    // try top suggestion
    try {
      const items = await this.getSuggestionsOnce(q, 8);
      if (items && items.length) {
        const pick = items.find((x) => !!this.normalizePlayUrl(x)) || items[0];
        const playUrl = this.normalizePlayUrl(pick);
        if (playUrl) {
          await this.enqueueItem({
            url: playUrl,
            title: pick.title || q,
            duration: pick.duration ?? undefined,
            thumb: pick.thumb || undefined,
            artist: pick.artist || undefined,
            source: pick.source || undefined,
          });
          if (this.$searchInput) this.$searchInput.value = "";
          this.hideSuggestions();
          return;
        }
      }
    } catch {}

    // fallback raw
    await this.enqueueItem({ query: q });
    if (this.$searchInput) this.$searchInput.value = "";
    this.hideSuggestions();
  }

  async getSuggestionsOnce(q, limit = 8) {
    const query = String(q || "").trim();
    if (!query) return [];
    const url = `${this.API_BASE}/autocomplete?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(String(limit))}`;
    const r = await fetch(url, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: this.headers(),
    });
    if (!r.ok) return [];
    const data = await r.json().catch(() => ({}));
    const arr = Array.isArray(data?.results)
      ? data.results
      : Array.isArray(data?.items)
      ? data.items
      : Array.isArray(data)
      ? data
      : [];
    return arr.map((x) => ({
      title: x?.title || "",
      artist: x?.artist || x?.uploader || "",
      duration: Number.isFinite(+x?.duration) ? +x.duration : null,
      thumb: x?.thumb || x?.thumbnail || "",
      url: x?.url || "",
      webpage_url: x?.webpage_url || x?.url || "",
      source: x?.source || x?.provider || "",
    }));
  }

  // -------------------------
  // Discord Auth
  // -------------------------
  async refreshMe() {
    try {
      const me = await this.apiGet("/me");
      const u = me?.user && me.user.id ? me.user : me;
      this.me = u && u.id ? u : null;
      this.userId = this.me ? this.me.id : null;
      this.renderMe();
      this.setMiniStats();
    } catch (e) {
      this.log("refreshMe failed:", e);
      this.me = null;
      this.userId = null;
      this.renderMe();
      this.setMiniStats();
    }
  }

  renderMe() {
    const u = this.me;

    if (this.$userName) this.$userName.textContent = u ? (u.global_name || u.username || String(u.id)) : "Non connecté";
    if (this.$userStatus) this.$userStatus.textContent = u ? "Connecté" : "Discord";

    if (this.$userAvatar) {
      const letter = u ? String(u.username || "U").slice(0, 1).toUpperCase() : "?";
      this.$userAvatar.textContent = letter;
    }

    this.$btnLogin?.classList.toggle("hidden", !!u);
    this.$btnLogout?.classList.toggle("hidden", !u);
  }

  async loginDiscord() {
    try {
      const w = window.open("/auth/login", "greg_login", "width=520,height=780");
      if (!w) alert("Popup bloquée : autorise l’ouverture de fenêtre pour te connecter.");
    } catch {}

    this.setStatus("Connexion Discord…", "info");

    const t0 = Date.now();
    const loop = async () => {
      await this.refreshMe();
      if (this.me) {
        this.setStatus("Connecté à Discord ✅", "ok");
        await this.refreshGuilds();
        this.autoSelectGuildIfPossible();
        await this.refreshState(true);
      } else if (Date.now() - t0 < 120000) {
        setTimeout(loop, 1500);
      } else {
        this.setStatus("Connexion Discord expirée.", "warn");
      }
    };
    loop();
  }

  async logoutDiscord() {
    try {
      await fetch("/auth/logout", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
    } catch {}
    this.me = null;
    this.userId = null;
    this.renderMe();
    this.setMiniStats();
    this.setStatus("Déconnecté.", "info");
  }

  // -------------------------
  // Guilds
  // -------------------------
  async refreshGuilds() {
    if (!this.$guildSelect) return;

    this.$guildSelect.innerHTML = `<option value="">(par défaut)</option>`;

    if (!this.me?.id) return;

    try {
      const data = await this.apiGet("/guilds");
      const guilds = Array.isArray(data?.guilds) ? data.guilds : [];
      guilds.forEach((g) => {
        const opt = document.createElement("option");
        opt.value = String(g.id || "");
        opt.textContent = g.name || String(g.id || "Serveur");
        this.$guildSelect.appendChild(opt);
      });

      if (this.guildId) this.$guildSelect.value = this.guildId;
    } catch (e) {
      this.log("refreshGuilds failed:", e);
    }
  }

  // -------------------------
  // Playlist / Queue
  // -------------------------
  async refreshState(silent = false) {
    try {
      const data = await this.apiGet("/playlist");
      const ok = this.applyStateFromBackend(data);
      if (!ok) throw new Error("Bad playlist payload");

      this.renderState();
      this.setMiniStats();
      if (!silent) this.setStatus("État mis à jour.", "ok");
    } catch (e) {
      this.log("refreshState error:", e);

      if (!silent) {
        const msg = String(e?.message || e || "");
        if (/HTTP 400/.test(msg) && !this.guildId) {
          this.setStatus("Sélectionne un serveur (guild) pour charger la playlist.", "warn");
        } else {
          this.setStatus("Impossible de récupérer la playlist.", "err");
        }
      }
    }
  }

  renderState() {
    const cur = this.state.current;
    const queue = this.state.queue || [];

    if (this.$title) this.$title.textContent = cur ? (cur.title || "Sans titre") : "Rien en cours";

    if (this.$artist) {
      const artist = cur?.artist || cur?.uploader || cur?.author || cur?.channel || "";
      this.$artist.textContent = cur ? (artist || "Artiste inconnu") : "Greg dort encore";
    }

    if (this.$queueCount) {
      const n = queue.length;
      this.$queueCount.textContent = `${n} titre${n > 1 ? "s" : ""}`;
    }

    // Artwork
    const thumb = cur?.thumbnail || cur?.thumb || cur?.image || "";
    if (this.$artwork) {
      if (thumb) {
        const safe = String(thumb).replace(/["\n\r]/g, "");
        this.$artwork.style.backgroundImage = `url("${safe}")`;
        this.$artwork.textContent = "";
      } else {
        this.$artwork.style.backgroundImage = `url("${this.pickIconUrl()}")`;
        this.$artwork.textContent = "🎵";
      }
    }

    // Play/pause UI
    if (this.$btnPlayPause) this.$btnPlayPause.textContent = this.state.is_paused ? "▶️" : "⏸";
    if (this.$btnRepeat) this.$btnRepeat.classList.toggle("ctrl-btn--active", !!this.state.repeat);

    // Queue list
    if (this.$queueList) {
      this.$queueList.innerHTML = "";
      queue.forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "queue-item";

        const th = document.createElement("div");
        th.className = "queue-thumb";
        const t = item.thumb || item.thumbnail || "";
        if (t) {
          const safe = String(t).replace(/["\n\r]/g, "");
          th.style.backgroundImage = `url("${safe}")`;
          th.textContent = "";
        } else {
          th.style.backgroundImage = `url("${this.pickIconUrl()}")`;
          th.textContent = "🎵";
        }

        const info = document.createElement("div");
        info.className = "queue-info";

        const title = document.createElement("div");
        title.className = "queue-track";
        title.textContent = item.title || item.query || "Sans titre";

        const artist = document.createElement("div");
        artist.className = "queue-artist";
        artist.textContent = item.artist || item.uploader || item.author || item.source || "";

        info.appendChild(title);
        info.appendChild(artist);

        const actions = document.createElement("div");
        actions.className = "queue-actions";

        const meta = document.createElement("div");
        meta.className = "queue-meta";
        meta.textContent = item.duration ? this.formatTime(item.duration) : "";

        const btnPlay = document.createElement("button");
        btnPlay.className = "queue-btn";
        btnPlay.type = "button";
        btnPlay.title = "Lire maintenant";
        btnPlay.textContent = "▶";
        btnPlay.addEventListener("click", () => this.playAt(idx));

        const btnDel = document.createElement("button");
        btnDel.className = "queue-btn";
        btnDel.type = "button";
        btnDel.title = "Retirer";
        btnDel.textContent = "✕";
        btnDel.addEventListener("click", () => this.removeAt(idx));

        actions.appendChild(meta);
        actions.appendChild(btnPlay);
        actions.appendChild(btnDel);

        row.appendChild(th);
        row.appendChild(info);
        row.appendChild(actions);

        this.$queueList.appendChild(row);
      });
    }

    this.renderProgress();
  }

  renderProgress() {
    const cur = this.state.current;

    const duration = Number(this.progress.duration || 0);
    if (!cur || !duration || !Number.isFinite(duration) || duration <= 0) {
      if (this.$pf) this.$pf.style.width = "0%";
      if (this.$pCur) this.$pCur.textContent = this.formatTime(this.progress.elapsed || 0);
      if (this.$pTot) this.$pTot.textContent = "0:00";
      return;
    }

    const now = Date.now() / 1000;
    let elapsed = this.state.is_paused
      ? Number(this.progress.elapsed || 0)
      : Math.max(0, now - Number(this.progress.startedAt || now));

    if (!Number.isFinite(elapsed) || elapsed < 0) elapsed = 0;
    if (elapsed > duration) elapsed = duration;

    const ratio = duration > 0 ? Math.min(1, elapsed / duration) : 0;
    if (this.$pf) this.$pf.style.width = `${ratio * 100}%`;

    if (this.$pCur) this.$pCur.textContent = this.formatTime(elapsed);
    if (this.$pTot) this.$pTot.textContent = this.formatTime(duration);
  }

  // -------------------------
  // Actions
  // -------------------------
  async ensureGuildSelected() {
    if (this.guildId) return true;
    this.autoSelectGuildIfPossible();
    if (this.guildId) return true;
    this.setStatus("Choisis un serveur (guild) avant d’agir.", "warn");
    return false;
  }

  async enqueueItem(payload) {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;

      const body = Object.assign({}, payload || {});
      body.guild_id = this.guildId;
      if (this.userId) body.user_id = this.userId;

      await this.apiPost("/queue/add", body);

      const label = body.title || body.query || body.url || "OK";
      this.setStatus(`Ajouté : ${label}`, "ok");

      if (this.$searchInput) this.$searchInput.value = "";
      await this.refreshState(true);
    } catch (e) {
      this.log("enqueueItem error:", e);
      this.setStatus("Impossible d’ajouter (connecté ? en vocal ? serveur ?).", "err");
    }
  }

  async playAt(idx) {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;
      await this.apiPost("/playlist/play_at", { index: idx });
      await this.refreshState(true);
    } catch (e) {
      this.log("playAt error:", e);
      this.setStatus("play_at a échoué.", "err");
    }
  }

  async removeAt(idx) {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;
      await this.apiPost("/queue/remove", { index: idx });
      await this.refreshState(true);
    } catch (e) {
      this.log("removeAt error:", e);
      this.setStatus("remove a échoué.", "err");
    }
  }

  async togglePause() {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;

      await this.apiPost("/playlist/toggle_pause", {});
      await this.refreshState(true);
    } catch (e) {
      // fallback pause/resume if exists
      try {
        if (this.state.is_paused) await this.apiPost("/playlist/resume", {});
        else await this.apiPost("/playlist/pause", {});
        await this.refreshState(true);
      } catch (e2) {
        this.log("togglePause error:", e, e2);
        this.setStatus("pause/resume a échoué.", "err");
      }
    }
  }

  async skip() {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;
      await this.apiPost("/queue/skip", {});
      await this.refreshState(true);
    } catch (e) {
      this.log("skip error:", e);
      this.setStatus("skip a échoué.", "err");
    }
  }

  async restart() {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;
      await this.apiPost("/playlist/restart", {});
      await this.refreshState(true);
    } catch (e) {
      // fallback stop if exists
      try {
        await this.apiPost("/queue/stop", {});
        await this.refreshState(true);
      } catch (e2) {
        this.log("restart/stop error:", e, e2);
        this.setStatus("stop a échoué.", "err");
      }
    }
  }

  async toggleRepeat() {
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;

      const res = await this.apiPost("/playlist/repeat", {});
      const st = this.unwrapPlaylistResponse(res) || res;
      this.state.repeat = !!(st.repeat_all ?? st.repeat ?? res?.repeat);
      await this.refreshState(true);
    } catch (e) {
      this.log("repeat error:", e);
      this.setStatus("repeat a échoué.", "err");
    }
  }

  // -------------------------
  // Spotify
  // -------------------------
  async refreshSpotify() {
    try {
      const st = await this.apiGet("/spotify/status");
      const linked = !!st?.linked;
      this.spotify.linked = linked;

      if (this.$spotifyStatus) {
        this.$spotifyStatus.textContent = linked
          ? `Spotify lié (${st?.profile?.display_name || st?.profile?.id || "?"})`
          : "Spotify non lié";
      }

      if (this.$spLogin && this.$spLogout) {
        this.$spLogin.classList.toggle("hidden", linked);
        this.$spLogout.classList.toggle("hidden", !linked);
      }

      // playlists
      await this.refreshSpotifyPlaylists(false);
    } catch (e) {
      this.log("spotify status error:", e);
      if (this.$spotifyStatus) this.$spotifyStatus.textContent = "Spotify indisponible";
      this.disableSpotifyPlaylists("Spotify indisponible (status KO).");
    }
  }

  async loginSpotify() {
    try {
      const w = window.open(`${this.API_BASE}/spotify/login`, "spotify_login", "width=520,height=780");
      if (!w) alert("Popup bloquée : autorise l’ouverture de fenêtre pour Spotify.");
    } catch {}

    this.setStatus("Connexion Spotify…", "info");

    const t0 = Date.now();
    const loop = async () => {
      await this.refreshSpotify();
      if (this.spotify.linked) this.setStatus("Spotify lié ✅", "ok");
      else if (Date.now() - t0 < 60000) setTimeout(loop, 1500);
      else this.setStatus("Connexion Spotify expirée.", "warn");
    };
    loop();
  }

  async logoutSpotify() {
    try {
      await this.apiPost("/spotify/logout", {});
      await this.refreshSpotify();
      this.setStatus("Spotify dé-lié.", "info");
    } catch (e) {
      this.log("spotify logout error:", e);
      this.setStatus("Dé-liaison Spotify impossible.", "err");
    }
  }

  disableSpotifyPlaylists(reason) {
    if (this.$spHelp) this.$spHelp.textContent = reason || "Playlists non disponibles.";
    if (this.$spPlaylistSelect) {
      this.$spPlaylistSelect.disabled = true;
      this.$spPlaylistSelect.innerHTML = `<option value="">(Non disponible)</option>`;
    }
    if (this.$spTracks) this.$spTracks.innerHTML = "";
  }

  async refreshSpotifyPlaylists(showStatus) {
    if (!this.spotify.linked) {
      this.disableSpotifyPlaylists("Liaison Spotify requise.");
      return;
    }

    try {
      // Best effort endpoint:
      // Expected shapes:
      // {playlists:[{id,name,tracks_total,images:[{url}]}]} OR direct array
      const res = await this.apiGet("/spotify/playlists");
      const list = Array.isArray(res?.playlists) ? res.playlists : Array.isArray(res) ? res : [];

      this.spotify.playlists = list;

      if (!list.length) {
        this.disableSpotifyPlaylists("Aucune playlist trouvée (ou endpoint non implémenté).");
        return;
      }

      // Enable select
      if (this.$spPlaylistSelect) {
        this.$spPlaylistSelect.disabled = false;
        this.$spPlaylistSelect.innerHTML = `<option value="">(Choisir…)</option>`;

        list.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = String(p.id || "");
          opt.textContent = `${p.name || p.id}${p.tracks_total != null ? ` • ${p.tracks_total}` : ""}`;
          this.$spPlaylistSelect.appendChild(opt);
        });

        // keep selection
        if (this.spotify.selectedPlaylistId) {
          this.$spPlaylistSelect.value = this.spotify.selectedPlaylistId;
        }
      }

      if (this.$spHelp) this.$spHelp.textContent = "Sélectionne une playlist pour voir ses titres.";

      if (showStatus) this.setStatus("Playlists Spotify rafraîchies.", "ok");

      // Auto-load first if nothing selected
      if (!this.spotify.selectedPlaylistId && list[0]?.id) {
        this.spotify.selectedPlaylistId = String(list[0].id);
        if (this.$spPlaylistSelect) this.$spPlaylistSelect.value = this.spotify.selectedPlaylistId;
        await this.refreshSpotifyPlaylistTracks(this.spotify.selectedPlaylistId);
      }
    } catch (e) {
      this.log("spotify playlists error:", e);
      this.disableSpotifyPlaylists("Endpoint playlists absent côté backend.");
    }
  }

  async refreshSpotifyPlaylistTracks(playlistId) {
    const pid = String(playlistId || "").trim();
    if (!pid) {
      if (this.$spTracks) this.$spTracks.innerHTML = "";
      return;
    }

    if (!this.spotify.linked) {
      this.disableSpotifyPlaylists("Liaison Spotify requise.");
      return;
    }

    try {
      // Best effort endpoint:
      // {tracks:[{id,name,artists:[{name}],duration_ms,external_url}]} OR direct array
      const res = await this.apiGet(`/spotify/playlists/${encodeURIComponent(pid)}/tracks`);
      const tracks = Array.isArray(res?.tracks) ? res.tracks : Array.isArray(res) ? res : [];

      this.spotify.playlistTracks = tracks;
      this.renderSpotifyTracks(tracks);
    } catch (e) {
      this.log("spotify tracks error:", e);
      if (this.$spTracks) this.$spTracks.innerHTML = "";
      if (this.$spHelp) this.$spHelp.textContent = "Endpoint tracks absent côté backend.";
    }
  }

  renderSpotifyTracks(tracks) {
    if (!this.$spTracks) return;
    this.$spTracks.innerHTML = "";

    if (!Array.isArray(tracks) || !tracks.length) {
      const empty = document.createElement("div");
      empty.className = "muted small";
      empty.textContent = "Aucun titre (ou lecture non autorisée).";
      this.$spTracks.appendChild(empty);
      return;
    }

    // Render max 50 (UX)
    tracks.slice(0, 50).forEach((t) => {
      const row = document.createElement("div");
      row.className = "sp-track";

      const main = document.createElement("div");
      main.className = "sp-track-main";

      const title = document.createElement("div");
      title.className = "sp-track-title";
      title.textContent = t.name || t.title || "Sans titre";

      const artist = document.createElement("div");
      artist.className = "sp-track-artist";
      const artists = Array.isArray(t.artists) ? t.artists.map((a) => a?.name).filter(Boolean).join(", ") : (t.artist || "");
      artist.textContent = artists || "";

      main.appendChild(title);
      main.appendChild(artist);

      const btn = document.createElement("button");
      btn.className = "sp-track-btn";
      btn.type = "button";
      btn.title = "Ajouter à la queue";
      btn.textContent = "+";
      btn.addEventListener("click", () => this.enqueueSpotifyTrack(t).catch(() => {}));

      row.appendChild(main);
      row.appendChild(btn);
      this.$spTracks.appendChild(row);
    });
  }

  async enqueueSpotifyTrack(track) {
    // Option A: backend fournit direct url spotify track => on l’enqueue comme url
    const url =
      track?.external_url ||
      track?.external_urls?.spotify ||
      track?.url ||
      "";

    if (url && /open\.spotify\.com\/track\//i.test(String(url))) {
      await this.enqueueItem({ url, title: track?.name || url });
      return;
    }

    // Option B: backend a un endpoint dédié
    try {
      const ok = await this.ensureGuildSelected();
      if (!ok) return;

      await this.apiPost("/spotify/playlist/enqueue", {
        guild_id: this.guildId,
        track_id: track?.id,
      });

      this.setStatus("Titre Spotify ajouté ✅", "ok");
      await this.refreshState(true);
    } catch (e) {
      this.log("enqueueSpotifyTrack error:", e);
      this.setStatus("Impossible d’ajouter ce titre Spotify (endpoint manquant).", "warn");
    }
  }
}

// Boot
document.addEventListener("DOMContentLoaded", () => {
  const app = new GregWebPlayer();
  app.init().catch((e) => console.error("Init GregWebPlayer failed:", e));
});
