/* assets/static/player.js
   Greg le Consanguin — Web Player (pro, robuste)
   - Support API:
     • { ok:true, state:{ current, queue, progress:{elapsed,duration}, is_paused, repeat_all, guild_id, thumbnail } }
     • fallback anciens formats: { current, queue, elapsed, duration, is_paused, repeat }
   - Rendu: current + queue + progress (même si duration = null)
   - Anti-400: guild auto + persist localStorage
   - UI: autocomplete + queue actions + discord/spotify status
*/

"use strict";

class GregWebPlayer {
  constructor() {
    this.API_BASE = String(window.GREG_API_BASE || "/api/v1").replace(/\/+$/, "");
    this.STATIC_BASE = String(window.GREG_STATIC_BASE || "/static").replace(/\/+$/, "");

    // persisted selections
    this.guildId = this._lsGet("greg.guildId", "");
    this.userId = null;
    this.me = null;

    this.state = {
      current: null,
      queue: [],
      is_paused: false,
      repeat: false,
    };

    this.progress = {
      startedAt: 0, // epoch seconds
      elapsed: 0,
      duration: 0,
    };

    this.pollTimer = null;
    this.progressTimer = null;

    // Autocomplete
    this.sug = {
      items: [],
      open: false,
      activeIndex: -1,
      abort: null,
      lastQuery: "",
    };

    // DOM refs (robustes: on tente plusieurs IDs)
    this.$statusMessage = this._q("#statusMessage");
    this.$statusText = this._q("#statusText", "#statusBar");

    this.$searchForm = this._q("#searchForm", "#addForm");
    this.$searchInput = this._q("#searchInput", "#addInput");
    this.$suggestions = this._q("#searchSuggestions");

    this.$queueList = this._q("#queueList");
    this.$queueCount = this._q("#queueCount");

    this.$artwork = this._q("#artwork");
    this.$title = this._q("#trackTitle");
    this.$artist = this._q("#trackArtist");

    this.$pf = this._q("#progressFill");
    this.$pCur = this._q("#progressCurrent");
    this.$pTot = this._q("#progressTotal");

    // Controls
    this.$btnPrev = this._q("#btn-prev", "#prevBtn");
    this.$btnPlayPause = this._q("#btn-play-pause", "#playPauseBtn");
    this.$btnSkip = this._q("#btn-skip", "#skipBtn");
    this.$btnStop = this._q("#btn-stop", "#restartBtn");
    this.$btnRepeat = this._q("#btn-repeat", "#repeatBtn");

    // user / guild
    this.$userName = this._q("#userName");
    this.$userAvatar = this._q("#userAvatar");
    this.$userStatus = this._q("#userStatus");
    this.$btnLogin = this._q("#btn-login-discord");
    this.$btnLogout = this._q("#btn-logout-discord");
    this.$guildSelect = this._q("#guildSelect");

    // spotify
    this.$spStatus = this._q("#spotifyStatus");
    this.$spLogin = this._q("#btn-spotify-login");
    this.$spLogout = this._q("#btn-spotify-logout");

    // A11y suggestions
    if (this.$suggestions) {
      this.$suggestions.setAttribute("role", "listbox");
      this.$suggestions.setAttribute("aria-label", "Suggestions");
    }

    // sanity check
    this._debugDomSanity();
  }

  // ---------------------------------------------------------------------------
  // DOM helpers
  // ---------------------------------------------------------------------------
  _q(...selectors) {
    for (const s of selectors) {
      const el = document.querySelector(s);
      if (el) return el;
    }
    return null;
  }

  _debugDomSanity() {
    const required = [
      ["statusText", this.$statusText],
      ["trackTitle", this.$title],
      ["queueList", this.$queueList],
    ];
    const missing = required.filter(([, el]) => !el).map(([name]) => name);
    if (missing.length) console.warn("[GregWebPlayer] DOM missing:", missing.join(", "));
  }

  // ---------------------------------------------------------------------------
  // LocalStorage
  // ---------------------------------------------------------------------------
  _lsGet(key, def = "") {
    try {
      const v = localStorage.getItem(key);
      return v == null ? def : String(v);
    } catch {
      return def;
    }
  }
  _lsSet(key, val) {
    try { localStorage.setItem(key, String(val ?? "")); } catch {}
  }

  // ---------------------------------------------------------------------------
  // Utils
  // ---------------------------------------------------------------------------
  setStatus(text, ok = true) {
    if (this.$statusText) this.$statusText.textContent = String(text || "");
    if (this.$statusText) {
      this.$statusText.classList.toggle("status-text--ok", !!ok);
      this.$statusText.classList.toggle("status-text--err", !ok);
    }
    if (this.$statusMessage) {
      this.$statusMessage.classList.toggle("status-message--ok", !!ok);
      this.$statusMessage.classList.toggle("status-message--err", !ok);
    }
  }

  debounce(fn, delay = 220) {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), delay);
    };
  }

  pickIconUrl() {
    return `${this.STATIC_BASE}/icon.png`;
  }

  formatTime(sec) {
    sec = Math.max(0, Math.floor(Number(sec || 0)));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  isProbablyURL(v) {
    v = String(v || "").trim();
    return /^https?:\/\//i.test(v) ||
      /^(?:www\.)?(youtube\.com|youtu\.be|soundcloud\.com|open\.spotify\.com)\//i.test(v);
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

    // Canonicalise YouTube
    try {
      const m = String(page).match(/(?:v=|youtu\.be\/|\/shorts\/)([A-Za-z0-9_-]{6,})/);
      return m ? `https://www.youtube.com/watch?v=${m[1]}` : page;
    } catch {
      return page;
    }
  }

  // ---------------------------------------------------------------------------
  // HTTP helpers
  // ---------------------------------------------------------------------------
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

    let payload = null;
    try { payload = await r.json(); } catch { payload = null; }

    if (!r.ok) {
      const e = new Error(`GET ${path}: HTTP ${r.status}`);
      e.status = r.status;
      e.payload = payload;
      throw e;
    }
    return payload;
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

    let payload = null;
    try { payload = await r.json(); } catch { payload = null; }

    if (!r.ok) {
      const e = new Error(`POST ${path}: HTTP ${r.status}`);
      e.status = r.status;
      e.payload = payload;
      throw e;
    }
    return payload;
  }

  // ---------------------------------------------------------------------------
  // Normalisation API -> état UI
  // ---------------------------------------------------------------------------
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

    // Auto-capture guild_id si pas déjà fixé
    if (!this.guildId && st.guild_id) {
      this.guildId = String(st.guild_id);
      this._lsSet("greg.guildId", this.guildId);
      if (this.$guildSelect) this.$guildSelect.value = this.guildId;
    }

    const current = st.current || null;
    let queue = Array.isArray(st.queue) ? st.queue.slice() : [];

    // queue affichée = "à venir" (on retire le current si doublon)
    if (current && queue.length && this.sameTrack(queue[0], current)) {
      queue = queue.slice(1);
    }

    const isPaused = !!(st.is_paused ?? st.paused ?? false);
    const repeat = !!(st.repeat_all ?? st.repeat ?? false);

    // progress
    const elapsed = Number(st?.progress?.elapsed ?? st.elapsed ?? 0);
    const duration = Number(st?.progress?.duration ?? st.duration ?? (current?.duration ?? 0));

    // thumb
    const thumb =
      st.thumbnail ||
      current?.thumb ||
      current?.thumbnail ||
      "";

    this.state.current = current ? Object.assign({}, current, { thumbnail: thumb }) : null;
    this.state.queue = queue;
    this.state.is_paused = isPaused;
    this.state.repeat = repeat;

    // Baseline progress
    this.progress.elapsed = Number.isFinite(elapsed) ? elapsed : 0;
    this.progress.duration = Number.isFinite(duration) ? duration : 0;
    this.progress.startedAt = Date.now() / 1000 - this.progress.elapsed;

    return true;
  }

  // ---------------------------------------------------------------------------
  // INIT
  // ---------------------------------------------------------------------------
  async init() {
    this.bindEvents();

    await this.refreshMe();
    await this.refreshGuilds();

    this.autoSelectGuildIfPossible();

    await this.refreshState(false);
    await this.refreshSpotify();

    this.pollTimer = setInterval(() => this.refreshState(true), 2000);
    this.progressTimer = setInterval(() => this.renderProgress(), 500);

    this.setStatus("Prêt ✅", true);
  }

  autoSelectGuildIfPossible() {
    if (this.guildId) return;
    if (!this.$guildSelect) return;
    const opts = Array.from(this.$guildSelect.querySelectorAll("option"));
    const firstGuild = opts.find((o) => o.value && o.value.trim());
    if (firstGuild) {
      this.guildId = firstGuild.value.trim();
      this.$guildSelect.value = this.guildId;
      this._lsSet("greg.guildId", this.guildId);
    }
  }

  // ---------------------------------------------------------------------------
  // UI bindings
  // ---------------------------------------------------------------------------
  bindEvents() {
    // Submit (add/play)
    if (this.$searchForm) {
      this.$searchForm.addEventListener("submit", (ev) => {
        ev.preventDefault();
        this.onSubmitSearch().catch(() => {});
      });
    }

    // Autocomplete
    const debouncedAuto = this.debounce((q) => this.fetchAutocomplete(q), 220);

    if (this.$searchInput) {
      this.$searchInput.addEventListener("input", () => {
        const q = (this.$searchInput.value || "").trim();
        if (!this.$suggestions) return;
        if (q.length < 2) {
          this.hideSuggestions();
          return;
        }
        debouncedAuto(q);
      });

      this.$searchInput.addEventListener("keydown", (e) => {
        if (!this.$suggestions) return;

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
          const next = Math.min(
            this.sug.items.length - 1,
            (this.sug.activeIndex < 0 ? 0 : this.sug.activeIndex + 1)
          );
          this.setActiveSuggestion(next);
          return;
        }

        if (e.key === "ArrowUp") {
          e.preventDefault();
          const prev = Math.max(
            0,
            (this.sug.activeIndex <= 0 ? 0 : this.sug.activeIndex - 1)
          );
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
        if (!this.$suggestions) return;
        const t = e.target;
        if (!t) return;
        const inside =
          (this.$suggestions && this.$suggestions.contains(t)) ||
          (this.$searchInput && this.$searchInput.contains(t));
        if (!inside) this.hideSuggestions();
      });
    }

    // Controls
    this.$btnPlayPause?.addEventListener("click", () => this.togglePause());
    this.$btnSkip?.addEventListener("click", () => this.skip());
    this.$btnStop?.addEventListener("click", () => this.restart());
    this.$btnRepeat?.addEventListener("click", () => this.toggleRepeat());
    this.$btnPrev?.addEventListener("click", () => this.restart()); // fallback

    // Discord auth
    this.$btnLogin?.addEventListener("click", () => this.loginDiscord());
    this.$btnLogout?.addEventListener("click", () => this.logoutDiscord());

    // Guild select
    this.$guildSelect?.addEventListener("change", () => {
      this.guildId = this.$guildSelect.value || "";
      this._lsSet("greg.guildId", this.guildId);
      this.refreshState(false).catch(() => {});
    });

    // Spotify
    this.$spLogin?.addEventListener("click", () => this.loginSpotify());
    this.$spLogout?.addEventListener("click", () => this.logoutSpotify());
  }

  // ---------------------------------------------------------------------------
  // Search / Autocomplete
  // ---------------------------------------------------------------------------
  async onSubmitSearch() {
    const q = (this.$searchInput?.value || "").trim();
    if (!q) return;
    await this.addTopOrRaw(q);
  }

  async fetchAutocomplete(q) {
    if (!this.$suggestions) return;

    const query = String(q || "").trim();
    if (!query) {
      this.hideSuggestions();
      return;
    }

    // cancel previous
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
          const duration = Number.isFinite(+x?.duration) ? +x.duration : null;

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
    if (!this.$suggestions) return;
    const idx = Number(i);
    if (!Number.isFinite(idx)) return;

    this.sug.activeIndex = idx;
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
      row.className = "suggestion-item rich";
      row.setAttribute("role", "option");
      row.setAttribute("tabindex", "-1");
      row.setAttribute("data-sug-idx", String(idx));

      const thumb = document.createElement("div");
      thumb.className = "sug-thumb";
      const src = it.thumb ? String(it.thumb).replace(/["\n\r]/g, "") : this.pickIconUrl();
      thumb.style.backgroundImage = `url("${src}")`;

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

      row.addEventListener("mouseenter", () => this.setActiveSuggestion(idx));
      row.addEventListener("click", () => this.pickSuggestion(it).catch(() => {}));

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
      this.setStatus("Suggestion non jouable (lien invalide).", false);
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
      if (this.$searchInput) this.$searchInput.value = "";
      this.hideSuggestions();
      return;
    }

    // sans suggestions UI, on envoie directement
    if (!this.$suggestions) {
      await this.enqueueItem({ query: q });
      if (this.$searchInput) this.$searchInput.value = "";
      return;
    }

    // tente top suggestion
    try {
      const items = await this.getSuggestionsOnce(q, 6);
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

  async getSuggestionsOnce(q, limit = 6) {
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

  // ---------------------------------------------------------------------------
  // Discord Auth
  // ---------------------------------------------------------------------------
  async refreshMe() {
    try {
      const me = await this.apiGet("/me");
      const u = me?.user && me.user.id ? me.user : me;
      this.me = u && u.id ? u : null;
      this.userId = this.me ? this.me.id : null;
      this.renderMe();
    } catch {
      this.me = null;
      this.userId = null;
      this.renderMe();
    }
  }

  renderMe() {
    if (!this.$userName || !this.$userAvatar || !this.$userStatus) return;
    const u = this.me;

    if (u && u.id) {
      this.$userName.textContent = u.global_name || u.username || String(u.id);
      this.$userStatus.textContent = "Connecté";
      this.$userAvatar.textContent = String(u.username || "?").slice(0, 1).toUpperCase();

      this.$btnLogin?.classList.add("hidden");
      this.$btnLogout?.classList.remove("hidden");
    } else {
      this.$userName.textContent = "Non connecté";
      this.$userStatus.textContent = "Discord";
      this.$userAvatar.textContent = "?";

      this.$btnLogin?.classList.remove("hidden");
      this.$btnLogout?.classList.add("hidden");
    }
  }

  async loginDiscord() {
    try {
      const w = window.open("/auth/login", "greg_login", "width=520,height=780");
      if (!w) alert("Popup bloquée : autorise l’ouverture de fenêtre pour te connecter.");
    } catch {}
    this.setStatus("Connexion Discord…", true);

    const t0 = Date.now();
    const loop = async () => {
      await this.refreshMe();
      if (this.me) {
        this.setStatus("Connecté à Discord ✅", true);
        await this.refreshGuilds();
        this.autoSelectGuildIfPossible();
        await this.refreshState(true);
      } else if (Date.now() - t0 < 120000) {
        setTimeout(loop, 1500);
      } else {
        this.setStatus("Connexion Discord expirée.", false);
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
    this.setStatus("Déconnecté.", true);
  }

  // ---------------------------------------------------------------------------
  // Guilds
  // ---------------------------------------------------------------------------
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
    } catch {
      // silence
    }
  }

  // ---------------------------------------------------------------------------
  // Playlist / Queue
  // ---------------------------------------------------------------------------
  async refreshState(silent = false) {
    try {
      const data = await this.apiGet("/playlist");
      const ok = this.applyStateFromBackend(data);
      if (!ok) throw new Error("Bad playlist payload");

      this.renderState();
      if (!silent) this.setStatus("État mis à jour ✅", true);
    } catch (e) {
      const status = e?.status;
      const detail = e?.payload?.error || e?.payload?.message || "";

      if (!silent) {
        if (status === 400 && !this.guildId) {
          this.setStatus("Choisis un serveur (guild) pour charger la playlist.", false);
        } else {
          this.setStatus(`Playlist KO${status ? ` (HTTP ${status})` : ""}${detail ? `: ${detail}` : ""}`, false);
        }
      }
    }
  }

  _setUseIcon(btn, iconId) {
    if (!btn) return;
    const use = btn.querySelector("use");
    if (use) use.setAttribute("href", iconId);
  }

  renderState() {
    const cur = this.state.current;
    const queue = this.state.queue || [];

    // Current title/artist
    if (this.$title) this.$title.textContent = cur ? (cur.title || "Sans titre") : "Rien en cours";
    if (this.$artist) {
      const a = cur?.artist || cur?.uploader || cur?.author || cur?.channel || "";
      this.$artist.textContent = cur ? (a || "Artiste inconnu") : "—";
    }

    // Queue count
    if (this.$queueCount) {
      this.$queueCount.textContent = `${queue.length} titre${queue.length > 1 ? "s" : ""}`;
    }

    // Queue list
    if (this.$queueList) {
      this.$queueList.innerHTML = "";

      if (!queue.length) {
        const empty = document.createElement("div");
        empty.className = "queue-empty";
        empty.textContent = "Aucun titre en attente.";
        this.$queueList.appendChild(empty);
      } else {
        queue.forEach((item, idx) => {
          const div = document.createElement("div");
          div.className = "queue-item";
          div.dataset.index = String(idx);

          const thumb = document.createElement("div");
          thumb.className = "queue-thumb";
          const img = String(item.thumb || item.thumbnail || item.image || "").replace(/["\n\r]/g, "");
          thumb.style.backgroundImage = `url("${img || this.pickIconUrl()}")`;

          const main = document.createElement("div");
          main.className = "queue-main";

          const t = document.createElement("div");
          t.className = "queue-title";
          t.textContent = item.title || item.query || "Sans titre";

          const sub = document.createElement("div");
          sub.className = "queue-sub";
          sub.textContent = item.artist || item.uploader || item.author || item.source || "";

          main.appendChild(t);
          main.appendChild(sub);

          const actions = document.createElement("div");
          actions.className = "queue-actions";

          const btnPlay = document.createElement("button");
          btnPlay.type = "button";
          btnPlay.className = "queue-btn";
          btnPlay.title = "Lire maintenant";
          btnPlay.setAttribute("aria-label", "Lire maintenant");
          btnPlay.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><use href="#icon-play"></use></svg>`;
          btnPlay.addEventListener("click", () => this.playAt(idx));

          const btnDel = document.createElement("button");
          btnDel.type = "button";
          btnDel.className = "queue-btn danger";
          btnDel.title = "Retirer";
          btnDel.setAttribute("aria-label", "Retirer");
          btnDel.innerHTML = `<svg class="icon" viewBox="0 0 24 24"><use href="#icon-trash"></use></svg>`;
          btnDel.addEventListener("click", () => this.removeAt(idx));

          actions.appendChild(btnPlay);
          actions.appendChild(btnDel);

          div.appendChild(thumb);
          div.appendChild(main);
          div.appendChild(actions);

          this.$queueList.appendChild(div);
        });
      }
    }

    // Artwork
    const thumb = cur?.thumbnail || cur?.thumb || cur?.image || "";
    if (this.$artwork) {
      const src = thumb ? String(thumb).replace(/["\n\r]/g, "") : this.pickIconUrl();
      this.$artwork.style.backgroundImage = `url("${src}")`;
      this.$artwork.textContent = "";
    }

    // Play/Pause icon
    if (this.$btnPlayPause) {
      this._setUseIcon(this.$btnPlayPause, this.state.is_paused ? "#icon-play" : "#icon-pause");
      this.$btnPlayPause.setAttribute("aria-pressed", String(!this.state.is_paused));
    }

    // Repeat visual
    if (this.$btnRepeat) {
      this.$btnRepeat.classList.toggle("control-btn--active", !!this.state.repeat);
      this.$btnRepeat.setAttribute("aria-pressed", String(!!this.state.repeat));
    }

    // Progress now
    this.renderProgress();
  }

  renderProgress() {
    const cur = this.state.current;
    const duration = Number(this.progress.duration || 0);

    const now = Date.now() / 1000;
    let elapsed = this.state.is_paused
      ? Number(this.progress.elapsed || 0)
      : Math.max(0, now - Number(this.progress.startedAt || now));

    if (!Number.isFinite(elapsed) || elapsed < 0) elapsed = 0;

    if (this.$pCur) this.$pCur.textContent = this.formatTime(elapsed);

    if (!cur || !duration || !Number.isFinite(duration) || duration <= 0) {
      if (this.$pf) this.$pf.style.width = "0%";
      if (this.$pTot) this.$pTot.textContent = "--:--";
      return;
    }

    if (elapsed > duration) elapsed = duration;

    const ratio = Math.min(1, elapsed / duration);
    if (this.$pf) this.$pf.style.width = `${ratio * 100}%`;
    if (this.$pTot) this.$pTot.textContent = this.formatTime(duration);
  }

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------
  async enqueueItem(payload) {
    try {
      if (!this.guildId) this.autoSelectGuildIfPossible();
      if (!this.guildId) {
        this.setStatus("Choisis un serveur (guild) avant d’ajouter un titre.", false);
        return;
      }

      const body = Object.assign({}, payload || {});
      body.guild_id = this.guildId;
      if (this.userId) body.user_id = this.userId;

      await this.apiPost("/queue/add", body);

      const label = body.title || body.query || body.url || "OK";
      this.setStatus(`Ajouté : ${label}`, true);

      await this.refreshState(true);
    } catch {
      this.setStatus("Impossible d’ajouter (connecté ? en vocal ? serveur sélectionné ?).", false);
    }
  }

  async playAt(idx) {
    try {
      await this.apiPost("/playlist/play_at", { index: idx, guild_id: this.guildId || undefined });
      await this.refreshState(true);
    } catch {}
  }

  async removeAt(idx) {
    try {
      await this.apiPost("/queue/remove", { index: idx, guild_id: this.guildId || undefined });
      await this.refreshState(true);
    } catch {}
  }

  async togglePause() {
    try {
      await this.apiPost("/playlist/toggle_pause", { guild_id: this.guildId || undefined });
      await this.refreshState(true);
    } catch {
      try {
        if (this.state.is_paused) await this.apiPost("/playlist/resume", { guild_id: this.guildId || undefined });
        else await this.apiPost("/playlist/pause", { guild_id: this.guildId || undefined });
        await this.refreshState(true);
      } catch {}
    }
  }

  async skip() {
    try {
      await this.apiPost("/queue/skip", { guild_id: this.guildId || undefined });
      await this.refreshState(true);
    } catch {}
  }

  async restart() {
    try {
      await this.apiPost("/playlist/restart", { guild_id: this.guildId || undefined });
      await this.refreshState(true);
    } catch {
      try {
        await this.apiPost("/queue/stop", { guild_id: this.guildId || undefined });
        await this.refreshState(true);
      } catch {}
    }
  }

  async toggleRepeat() {
    try {
      const res = await this.apiPost("/playlist/repeat", { guild_id: this.guildId || undefined });
      const st = this.unwrapPlaylistResponse(res) || res;
      this.state.repeat = !!(st?.repeat_all ?? st?.repeat ?? res?.repeat);
      await this.refreshState(true);
    } catch {}
  }

  // ---------------------------------------------------------------------------
  // Spotify
  // ---------------------------------------------------------------------------
  async refreshSpotify() {
    try {
      const st = await this.apiGet("/spotify/status");
      const linked = !!st?.linked;

      if (this.$spStatus) {
        this.$spStatus.textContent = linked
          ? `Spotify lié (${st?.profile?.display_name || st?.profile?.id || "?"})`
          : "Spotify non lié";
      }
      if (this.$spLogin && this.$spLogout) {
        this.$spLogin.classList.toggle("hidden", linked);
        this.$spLogout.classList.toggle("hidden", !linked);
      }
    } catch {}
  }

  async loginSpotify() {
    try {
      const w = window.open(`${this.API_BASE}/spotify/login`, "spotify_login", "width=520,height=780");
      if (!w) alert("Popup bloquée : autorise l’ouverture de fenêtre pour Spotify.");
    } catch {}
    this.setStatus("Connexion Spotify…", true);

    const t0 = Date.now();
    const loop = async () => {
      await this.refreshSpotify();
      const ok = this.$spStatus && /lié/i.test(this.$spStatus.textContent || "");
      if (ok) this.setStatus("Spotify lié ✅", true);
      else if (Date.now() - t0 < 60000) setTimeout(loop, 1500);
      else this.setStatus("Connexion Spotify expirée.", false);
    };
    loop();
  }

  async logoutSpotify() {
    try {
      await this.apiPost("/spotify/logout", {});
      await this.refreshSpotify();
      this.setStatus("Spotify dé-lié.", true);
    } catch {}
  }
}

// Boot (works even if this script is injected after DOMContentLoaded)
(() => {
  const boot = () => {
    const app = new GregWebPlayer();
    app.init().catch((e) => console.error("Init GregWebPlayer failed:", e));
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
