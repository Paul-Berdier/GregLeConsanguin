/* assets/js/player.js
   Greg le Consanguin — Web Player (pro)
   - Autocomplete riche (thumb + durée) via /api/v1/autocomplete
   - Clickable + navigation clavier (↑ ↓ Enter / Esc)
   - Anti-race (AbortController) + debounce
   - Ajout intelligent: URL => direct, texte => top suggestion si possible sinon raw
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

    // Autocomplete internal
    this.sug = {
      items: [],
      open: false,
      activeIndex: -1,
      abort: null,
      lastQuery: "",
    };

    // DOM refs
    this.$statusText = document.getElementById("statusText");
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

    this.$btnPrev = document.getElementById("btn-prev");
    this.$btnPlayPause = document.getElementById("btn-play-pause");
    this.$btnSkip = document.getElementById("btn-skip");
    this.$btnStop = document.getElementById("btn-stop");
    this.$btnRepeat = document.getElementById("btn-repeat");

    // user / guild
    this.$userName = document.getElementById("userName");
    this.$userAvatar = document.getElementById("userAvatar");
    this.$userStatus = document.getElementById("userStatus");
    this.$btnLogin = document.getElementById("btn-login-discord");
    this.$btnLogout = document.getElementById("btn-logout-discord");
    this.$guildSelect = document.getElementById("guildSelect");

    // spotify
    this.$spStatus = document.getElementById("spotifyStatus");
    this.$spLogin = document.getElementById("btn-spotify-login");
    this.$spLogout = document.getElementById("btn-spotify-logout");

    // nav (secondaires)
    this.$navSettings = document.getElementById("nav-settings");
    this.$navAbout = document.getElementById("nav-about");
    this.$panelSettings = document.getElementById("panel-settings");
    this.$panelAbout = document.getElementById("panel-about");

    // Small guard
    if (this.$suggestions) {
      // accessibility-ish
      this.$suggestions.setAttribute("role", "listbox");
      this.$suggestions.setAttribute("aria-label", "Suggestions");
    }
  }

  // -------------------------
  // Utils
  // -------------------------
  log(...args) {
    console.log("[GregWebPlayer]", ...args);
  }

  setStatus(text, ok = true) {
    if (!this.$statusText) return;
    this.$statusText.textContent = text;
    this.$statusText.className = ok
      ? "status-text status-text--ok"
      : "status-text status-text--err";
  }

  debounce(fn, delay = 220) {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), delay);
    };
  }

  isProbablyURL(v) {
    v = String(v || "").trim();
    return (
      /^https?:\/\//i.test(v) ||
      /^(?:www\.)?(youtube\.com|youtu\.be|soundcloud\.com|open\.spotify\.com)\//i.test(
        v
      )
    );
  }

  isSoundCloudCdn(u) {
    return /^https?:\/\/(?:cf|cf-hls|cf-hls-opus)-(?:opus-)?media\.sndcdn\.com/i.test(
      u || ""
    );
  }

  normalizePlayUrl(item) {
    // On veut un lien "page" (youtube watch, soundcloud page, spotify track...) pas un CDN stream
    const page =
      item?.webpage_url ||
      item?.permalink_url ||
      item?.page_url ||
      item?.url ||
      "";
    if (!page || this.isSoundCloudCdn(page)) return "";

    // Canonicalise YouTube (watch?v=) si c'est un youtu.be / shorts / v=
    try {
      const m = String(page).match(
        /(?:v=|youtu\.be\/|\/shorts\/)([A-Za-z0-9_-]{6,})/
      );
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
  // API helpers
  // -------------------------
  headers(extra = {}) {
    const h = { "Content-Type": "application/json" };
    if (this.guildId) h["X-Guild-ID"] = String(this.guildId);
    if (this.userId) h["X-User-ID"] = String(this.userId);
    return Object.assign(h, extra);
  }

  async apiGet(path, opts = {}) {
    const url = this.API_BASE + path;
    const r = await fetch(url, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      ...opts,
      headers: Object.assign({}, opts.headers || {}, this.headers()),
    });
    if (!r.ok) throw new Error(`GET ${path}: HTTP ${r.status}`);
    return await r.json();
  }

  async apiPost(path, body = {}, opts = {}) {
    const url = this.API_BASE + path;
    const r = await fetch(url, {
      method: "POST",
      credentials: "include",
      ...opts,
      headers: Object.assign({}, opts.headers || {}, this.headers()),
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`POST ${path}: HTTP ${r.status}`);
    return await r.json();
  }

  // -------------------------
  // INIT
  // -------------------------
  async init() {
    this.bindEvents();

    await this.refreshMe();
    await this.refreshGuilds();

    await this.refreshState(true);
    await this.refreshSpotify();

    // Poll state
    this.pollTimer = setInterval(() => this.refreshState(true), 3000);
    // Local progress tick
    setInterval(() => this.renderProgress(), 500);

    this.setStatus("Prêt ✅", true);
  }

  bindEvents() {
    // Submit (play)
    if (this.$searchForm) {
      this.$searchForm.addEventListener("submit", (ev) => {
        ev.preventDefault();
        this.onSubmitSearch().catch(() => {});
      });
    }

    // Input
    const debouncedAuto = this.debounce((q) => this.fetchAutocomplete(q), 220);

    if (this.$searchInput) {
      this.$searchInput.addEventListener("input", () => {
        const q = (this.$searchInput.value || "").trim();
        if (q.length < 2) {
          this.hideSuggestions();
          return;
        }
        debouncedAuto(q);
      });

      // Keyboard navigation for suggestions
      this.$searchInput.addEventListener("keydown", (e) => {
        if (!this.sug.open) {
          // If user presses ArrowDown while closed, open if we have items
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
          const prev = Math.max(0, (this.sug.activeIndex <= 0 ? 0 : this.sug.activeIndex - 1));
          this.setActiveSuggestion(prev);
          return;
        }

        if (e.key === "Enter") {
          // If a suggestion is selected, pick it
          if (this.sug.activeIndex >= 0 && this.sug.activeIndex < this.sug.items.length) {
            e.preventDefault();
            const it = this.sug.items[this.sug.activeIndex];
            this.pickSuggestion(it).catch(() => {});
          }
        }
      });

      // Click outside closes suggestions
      document.addEventListener("click", (e) => {
        const t = e.target;
        if (!t) return;
        const inside =
          (this.$suggestions && this.$suggestions.contains(t)) ||
          (this.$searchInput && this.$searchInput.contains(t));
        if (!inside) this.hideSuggestions();
      });
    }

    // Buttons
    this.$btnPlayPause?.addEventListener("click", () => this.togglePause());
    this.$btnSkip?.addEventListener("click", () => this.skip());
    this.$btnStop?.addEventListener("click", () => this.restart());
    this.$btnRepeat?.addEventListener("click", () => this.toggleRepeat());

    // Discord auth
    this.$btnLogin?.addEventListener("click", () => this.loginDiscord());
    this.$btnLogout?.addEventListener("click", () => this.logoutDiscord());

    // Guild select
    this.$guildSelect?.addEventListener("change", () => {
      this.guildId = this.$guildSelect.value || "";
      this.refreshState(true).catch(() => {});
    });

    // Spotify
    this.$spLogin?.addEventListener("click", () => this.loginSpotify());
    this.$spLogout?.addEventListener("click", () => this.logoutSpotify());

    // Secondary panels
    if (this.$navSettings && this.$panelSettings) {
      this.$navSettings.addEventListener("click", () => {
        this.$panelSettings.classList.toggle("hidden");
        this.$panelAbout?.classList.add("hidden");
      });
    }
    if (this.$navAbout && this.$panelAbout) {
      this.$navAbout.addEventListener("click", () => {
        this.$panelAbout.classList.toggle("hidden");
        this.$panelSettings?.classList.add("hidden");
      });
    }
  }

  // -------------------------
  // Search / Autocomplete
  // -------------------------
  async onSubmitSearch() {
    const q = (this.$searchInput?.value || "").trim();
    if (!q) return;

    // If suggestions are open + active, Enter picks it (already handled)
    // Here, normal submit: add top suggestion if possible (like overlay), else raw.
    await this.addTopOrRaw(q);
  }

  async fetchAutocomplete(q) {
    const query = String(q || "").trim();
    if (!query) {
      this.hideSuggestions();
      return;
    }

    // Cancel previous
    if (this.sug.abort) {
      try { this.sug.abort.abort(); } catch {}
      this.sug.abort = null;
    }
    const ctrl = new AbortController();
    this.sug.abort = ctrl;
    this.sug.lastQuery = query;

    try {
      const url = `${this.API_BASE}/autocomplete?q=${encodeURIComponent(query)}&limit=12`;
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

      // Normalize
      const items = arr
        .map((x) => {
          const urlPage = x?.webpage_url || x?.permalink_url || x?.url || "";
          const thumb =
            x?.thumb ||
            x?.thumbnail ||
            (Array.isArray(x?.thumbnails) &&
              (x.thumbnails.at(-1)?.url || x.thumbnails.at(-1))) ||
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

      // If query changed while awaiting, ignore
      if (this.sug.lastQuery !== query) return;

      this.sug.items = items;
      this.renderSuggestions(items);
    } catch (e) {
      if (e?.name === "AbortError") return;
      this.log("autocomplete error:", e);
      this.sug.items = [];
      this.hideSuggestions();
    } finally {
      // only clear abort if it's ours
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

    // Render max 10 (UX)
    const view = items.slice(0, 10);

    view.forEach((it, idx) => {
      const row = document.createElement("div");
      row.className = "suggestion-item rich";
      row.setAttribute("role", "option");
      row.setAttribute("tabindex", "-1");
      row.setAttribute("data-sug-idx", String(idx));

      // Thumb
      const thumb = document.createElement("div");
      thumb.className = "sug-thumb";
      if (it.thumb) {
        // safer than innerHTML: style background image only
        const safe = String(it.thumb).replace(/["\n\r]/g, "");
        thumb.style.backgroundImage = `url("${safe}")`;
      } else {
        // fallback icon (tu as assets/images/icon.png)
        // si tu exposes /static/assets/images/icon.png ou /assets/images/icon.png,
        // adapte au besoin; ici on tente /static/assets/images/icon.png
        thumb.style.backgroundImage = `url("/static/assets/images/icon.png")`;
      }

      // Main
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

      // Time
      const time = document.createElement("div");
      time.className = "sug-time";
      time.textContent = it.duration != null ? this.formatTime(it.duration) : "";

      const onPick = async () => {
        await this.pickSuggestion(it);
      };

      row.addEventListener("mouseenter", () => this.setActiveSuggestion(idx));
      row.addEventListener("click", () => onPick().catch(() => {}));
      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onPick().catch(() => {});
        }
      });

      row.appendChild(thumb);
      row.appendChild(main);
      row.appendChild(time);

      this.$suggestions.appendChild(row);
    });

    // default selection
    this.setActiveSuggestion(0);
  }

  async pickSuggestion(it) {
    const playUrl = this.normalizePlayUrl(it);
    if (!playUrl) {
      this.setStatus("Suggestion non jouable (lien CDN / invalide).", false);
      return;
    }

    // UX: set input to chosen title
    if (this.$searchInput) this.$searchInput.value = it.title || playUrl;

    // Enqueue as object (best)
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

    // URL direct
    if (this.isProbablyURL(q)) {
      await this.enqueueItem({ url: q, title: q });
      return;
    }

    // Try autocomplete top pick
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

    // Fallback raw (backend tentera aussi)
    await this.enqueueItem({ query: q });
    if (this.$searchInput) this.$searchInput.value = "";
    this.hideSuggestions();
  }

  async getSuggestionsOnce(q, limit = 8) {
    const query = String(q || "").trim();
    if (!query) return [];
    const url = `${this.API_BASE}/autocomplete?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(
      String(limit)
    )}`;
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
      // accepte {user:{...}} ou user direct
      const u = me?.user && me.user.id ? me.user : me;
      this.me = u && u.id ? u : null;
      this.userId = this.me ? this.me.id : null;
      this.renderMe();
    } catch (e) {
      this.log("refreshMe failed:", e);
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
      this.$userAvatar.textContent = String(u.username || "?")
        .slice(0, 1)
        .toUpperCase();

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

  // -------------------------
  // Guilds
  // -------------------------
  async refreshGuilds() {
    if (!this.$guildSelect) return;

    // Default option
    this.$guildSelect.innerHTML = `<option value="">(par défaut)</option>`;

    // If not logged in, nothing to fetch
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

      this.state.current = data.current || null;
      this.state.queue = data.queue || [];
      this.state.is_paused = !!data.is_paused;
      this.state.repeat = !!data.repeat;

      const elapsed = Number(data.elapsed || 0);
      const duration = Number(data.duration || (data.current && data.current.duration) || 0);

      this.progress.startedAt = Date.now() / 1000 - elapsed;
      this.progress.elapsed = elapsed;
      this.progress.duration = duration;

      if (!silent) this.setStatus("État mis à jour.", true);
      this.renderState();
    } catch (e) {
      this.log("refreshState error:", e);
      if (!silent) this.setStatus("Impossible de récupérer la playlist.", false);
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
      this.$queueCount.textContent = `${queue.length} titre${queue.length > 1 ? "s" : ""}`;
    }

    if (this.$queueList) {
      this.$queueList.innerHTML = "";
      queue.forEach((item, idx) => {
        const div = document.createElement("div");
        div.className = "queue-item";
        div.dataset.index = String(idx);

        const left = document.createElement("div");
        left.className = "queue-item-main";

        const title = document.createElement("div");
        title.className = "queue-item-title";
        title.textContent = item.title || item.query || "Sans titre";

        const meta = document.createElement("div");
        meta.className = "queue-item-meta";
        meta.textContent = item.artist || item.uploader || item.source || "";

        left.appendChild(title);
        left.appendChild(meta);

        const right = document.createElement("div");
        right.className = "queue-item-actions";

        const btnPlay = document.createElement("button");
        btnPlay.type = "button";
        btnPlay.className = "queue-item-btn";
        btnPlay.textContent = "▶";
        btnPlay.title = "Lire maintenant";
        btnPlay.addEventListener("click", () => this.playAt(idx));

        const btnDel = document.createElement("button");
        btnDel.type = "button";
        btnDel.className = "queue-item-btn";
        btnDel.textContent = "✕";
        btnDel.title = "Retirer";
        btnDel.addEventListener("click", () => this.removeAt(idx));

        right.appendChild(btnPlay);
        right.appendChild(btnDel);

        div.appendChild(left);
        div.appendChild(right);
        this.$queueList.appendChild(div);
      });
    }

    // Artwork
    const thumb = cur?.thumbnail || cur?.thumb || "";
    if (this.$artwork) {
      if (thumb) {
        const safe = String(thumb).replace(/["\n\r]/g, "");
        this.$artwork.style.backgroundImage = `url("${safe}")`;
        this.$artwork.textContent = "";
      } else {
        this.$artwork.style.backgroundImage = `url("/static/assets/images/icon.png")`;
        this.$artwork.textContent = "";
      }
    }

    // Play/Pause icon
    if (this.$btnPlayPause) {
      this.$btnPlayPause.textContent = this.state.is_paused ? "▶️" : "⏸";
    }
    // Repeat visual
    if (this.$btnRepeat) {
      this.$btnRepeat.classList.toggle("ctrl-btn--active", !!this.state.repeat);
    }
  }

  renderProgress() {
    const cur = this.state.current;
    if (!cur || !this.progress.duration) {
      if (this.$pf) this.$pf.style.width = "0%";
      if (this.$pCur) this.$pCur.textContent = "0:00";
      if (this.$pTot) this.$pTot.textContent = "0:00";
      return;
    }

    const now = Date.now() / 1000;
    let elapsed = this.state.is_paused
      ? this.progress.elapsed
      : Math.max(0, now - this.progress.startedAt);

    const duration = this.progress.duration;
    if (!Number.isFinite(elapsed) || elapsed < 0) elapsed = 0;

    const ratio = duration > 0 ? Math.min(1, elapsed / duration) : 0;
    if (this.$pf) this.$pf.style.width = `${ratio * 100}%`;

    if (this.$pCur) this.$pCur.textContent = this.formatTime(elapsed);
    if (this.$pTot) this.$pTot.textContent = this.formatTime(duration);
  }

  async enqueueItem(payload) {
    try {
      // Body: accept query/url/title/duration/thumb
      const body = Object.assign({}, payload || {});
      // Keep legacy compatibility (optional)
      if (this.guildId) body.guild_id = this.guildId;
      if (this.userId) body.user_id = this.userId;

      await this.apiPost("/queue/add", body);

      const label = body.title || body.query || body.url || "OK";
      this.setStatus(`Ajouté : ${label}`, true);

      if (this.$searchInput) this.$searchInput.value = "";
      await this.refreshState(true);
    } catch (e) {
      this.log("enqueueItem error:", e);
      this.setStatus("Impossible d’ajouter ce titre (vérifie: connecté + en vocal).", false);
    }
  }

  async playAt(idx) {
    try {
      await this.apiPost("/playlist/play_at", { index: idx });
      await this.refreshState(true);
    } catch (e) {
      this.log("playAt error:", e);
    }
  }

  async removeAt(idx) {
    try {
      await this.apiPost("/queue/remove", { index: idx });
      await this.refreshState(true);
    } catch (e) {
      this.log("removeAt error:", e);
    }
  }

  async togglePause() {
    try {
      await this.apiPost("/playlist/toggle_pause", {});
      await this.refreshState(true);
    } catch (e) {
      this.log("togglePause error:", e);
    }
  }

  async skip() {
    try {
      await this.apiPost("/queue/skip", {});
      await this.refreshState(true);
    } catch (e) {
      this.log("skip error:", e);
    }
  }

  async restart() {
    try {
      await this.apiPost("/playlist/restart", {});
      await this.refreshState(true);
    } catch (e) {
      this.log("restart error:", e);
    }
  }

  async toggleRepeat() {
    try {
      const res = await this.apiPost("/playlist/repeat", {});
      this.state.repeat = !!(res && res.repeat);
      await this.refreshState(true);
    } catch (e) {
      this.log("repeat error:", e);
    }
  }

  // -------------------------
  // Spotify
  // -------------------------
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
    } catch (e) {
      this.log("spotify status error:", e);
    }
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
    } catch (e) {
      this.log("spotify logout error:", e);
    }
  }
}

// Boot
document.addEventListener("DOMContentLoaded", () => {
  const app = new GregWebPlayer();
  app.init().catch((e) => console.error("Init GregWebPlayer failed:", e));
});
