/* /static/player.js
 * Greg le Consanguin — Web Player (pro)
 * - Compatible avec ton HTML (IDs) + tes routes Flask /api/v1
 * - Robuste aux payloads {state:{...}} vs {...}
 * - Polling + ticker local pour la progression
 */

(() => {
  "use strict";

  // -----------------------------
  // Utils
  // -----------------------------
  const $id = (id) => document.getElementById(id);

  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const isObj = (x) => x && typeof x === "object" && !Array.isArray(x);
  const asStr = (x, d = "") => (x == null ? d : String(x));
  const asNum = (x, d = 0) => {
    const n = Number(x);
    return Number.isFinite(n) ? n : d;
  };

  const safeBgUrl = (u) => {
    const s = asStr(u, "").trim();
    if (!s) return "";
    // évite de casser le CSS url("..")
    return s.replace(/["\\)\n\r]/g, (m) =>
      ({ '"': "%22", "\\": "%5C", ")": "%29", "\n": "", "\r": "" }[m] || "")
    );
  };

  const formatTime = (sec) => {
    sec = Math.max(0, Math.floor(asNum(sec, 0)));
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const debounce = (fn, ms) => {
    let t = null;
    return (...args) => {
      if (t) clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  };

  // -----------------------------
  // Player
  // -----------------------------
  class GregWebPlayer {
    constructor() {
      this.API_BASE = (window.GREG_API_BASE || "/api/v1").replace(/\/+$/, "");

      // auth / guild
      this.me = null;
      this.userId = "";
      this.guildId = "";

      // state
      this.state = {
        current: null,
        queue: [],
        is_paused: false,
        repeat_all: false,
      };

      // progress tracker (ticker local)
      this.progress = {
        trackKey: "",
        duration: 0,
        baselineElapsed: 0,
        t0ms: Date.now(),
        paused: true,
      };

      // timers
      this.pollTimer = null;
      this.tickTimer = null;

      // autocomplete cache
      this._autoReqId = 0;

      // dom
      this.el = {};
    }

    // -----------------------------
    // DOM / status
    // -----------------------------
    cacheDom() {
      this.el.statusText = $id("statusText");

      this.el.searchForm = $id("searchForm");
      this.el.searchInput = $id("searchInput");
      this.el.suggestions = $id("searchSuggestions");

      this.el.queueList = $id("queueList");
      this.el.queueCount = $id("queueCount");

      this.el.artwork = $id("artwork");
      this.el.title = $id("trackTitle");
      this.el.artist = $id("trackArtist");

      this.el.pFill = $id("progressFill");
      this.el.pCur = $id("progressCurrent");
      this.el.pTot = $id("progressTotal");

      this.el.btnPrev = $id("btn-prev");
      this.el.btnPlayPause = $id("btn-play-pause");
      this.el.btnSkip = $id("btn-skip");
      this.el.btnStop = $id("btn-stop");
      this.el.btnRepeat = $id("btn-repeat");

      this.el.userName = $id("userName");
      this.el.userAvatar = $id("userAvatar");
      this.el.userStatus = $id("userStatus");
      this.el.btnLogin = $id("btn-login-discord");
      this.el.btnLogout = $id("btn-logout-discord");

      this.el.guildSelect = $id("guildSelect");

      this.el.spStatus = $id("spotifyStatus");
      this.el.spLogin = $id("btn-spotify-login");
      this.el.spLogout = $id("btn-spotify-logout");

      this.el.navSettings = $id("nav-settings");
      this.el.navAbout = $id("nav-about");
      this.el.panelSettings = $id("panel-settings");
      this.el.panelAbout = $id("panel-about");

      // close suggestions on outside click
      document.addEventListener("click", (ev) => {
        if (!this.el.suggestions) return;
        const within =
          (this.el.searchInput && this.el.searchInput.contains(ev.target)) ||
          this.el.suggestions.contains(ev.target);
        if (!within) this.renderSuggestions([]);
      });
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") this.renderSuggestions([]);
      });
    }

    setStatus(text, ok = true) {
      if (!this.el.statusText) return;
      this.el.statusText.textContent = text;
      // optionnel: si tu ajoutes du CSS plus tard
      this.el.statusText.dataset.ok = ok ? "1" : "0";
    }

    // -----------------------------
    // Fetch helpers (robustes)
    // -----------------------------
    headers(extra = {}) {
      const h = { "Content-Type": "application/json" };
      if (this.guildId) h["X-Guild-ID"] = String(this.guildId);
      if (this.userId) h["X-User-ID"] = String(this.userId);
      return Object.assign(h, extra);
    }

    async fetchJson(url, options = {}) {
      const controller = new AbortController();
      const timeoutMs = asNum(options.timeoutMs, 12000);
      const t = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const r = await fetch(url, {
          credentials: "include",
          cache: "no-store",
          ...options,
          signal: controller.signal,
        });

        const ct = (r.headers.get("content-type") || "").toLowerCase();
        const isJson = ct.includes("application/json");
        const payload = isJson ? await r.json().catch(() => null) : await r.text().catch(() => "");

        if (!r.ok) {
          const msg =
            (isObj(payload) && (payload.error || payload.message)) ||
            (typeof payload === "string" && payload.slice(0, 220)) ||
            `${r.status} ${r.statusText}`;
          const err = new Error(msg);
          err.status = r.status;
          err.payload = payload;
          throw err;
        }
        return payload;
      } finally {
        clearTimeout(t);
      }
    }

    apiUrl(path) {
      return `${this.API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
    }

    async apiGet(path) {
      return this.fetchJson(this.apiUrl(path), {
        method: "GET",
        headers: this.headers(),
      });
    }

    async apiPost(path, body = {}) {
      return this.fetchJson(this.apiUrl(path), {
        method: "POST",
        headers: this.headers(),
        body: JSON.stringify(body || {}),
      });
    }

    // -----------------------------
    // Boot
    // -----------------------------
    async init() {
      this.cacheDom();
      this.bindEvents();

      // restore guild
      try {
        const saved = localStorage.getItem("greg_guild") || "";
        if (saved) this.guildId = saved;
      } catch {}

      // initial load
      await this.refreshMe();
      await this.refreshGuilds(); // va aussi sélectionner une guilde si besoin
      await this.refreshState(true);
      await this.refreshSpotify();

      // poll + ticker local
      this.pollTimer = setInterval(() => this.refreshState(true), 3000);
      this.tickTimer = setInterval(() => this.renderProgressOnly(), 400);

      this.setStatus(this.me ? "Connecté ✅" : "Connecte-toi à Discord pour contrôler Greg.", !!this.me);
    }

    bindEvents() {
      // search submit
      this.el.searchForm?.addEventListener("submit", (ev) => {
        ev.preventDefault();
        const q = (this.el.searchInput?.value || "").trim();
        if (!q) return;
        this.enqueueQuery(q);
      });

      // autocomplete input
      const debouncedAuto = debounce(() => {
        const q = (this.el.searchInput?.value || "").trim();
        if (q.length < 3) return this.renderSuggestions([]);
        this.fetchAutocomplete(q);
      }, 150);

      this.el.searchInput?.addEventListener("input", debouncedAuto);

      // controls
      this.el.btnPlayPause?.addEventListener("click", () => this.togglePause());
      this.el.btnSkip?.addEventListener("click", () => this.skip());
      this.el.btnStop?.addEventListener("click", () => this.stop());
      this.el.btnPrev?.addEventListener("click", () => this.restart());
      this.el.btnRepeat?.addEventListener("click", () => this.toggleRepeat());

      // auth
      this.el.btnLogin?.addEventListener("click", () => this.loginDiscordPopup());
      this.el.btnLogout?.addEventListener("click", () => this.logoutDiscord());

      // guild select
      this.el.guildSelect?.addEventListener("change", async () => {
        this.guildId = this.el.guildSelect.value || "";
        try {
          localStorage.setItem("greg_guild", this.guildId);
        } catch {}
        await this.refreshState(false);
      });

      // spotify
      this.el.spLogin?.addEventListener("click", () => this.loginSpotifyPopup());
      this.el.spLogout?.addEventListener("click", () => this.logoutSpotify());

      // panels
      this.el.navSettings?.addEventListener("click", () => {
        this.el.panelSettings?.classList.toggle("hidden");
        this.el.panelAbout?.classList.add("hidden");
      });
      this.el.navAbout?.addEventListener("click", () => {
        this.el.panelAbout?.classList.toggle("hidden");
        this.el.panelSettings?.classList.add("hidden");
      });

      // cleanup
      window.addEventListener("beforeunload", () => {
        try {
          if (this.pollTimer) clearInterval(this.pollTimer);
          if (this.tickTimer) clearInterval(this.tickTimer);
        } catch {}
      });
    }

    // -----------------------------
    // Auth (Discord)
    // -----------------------------
    async refreshMe() {
      try {
        // /api/v1/me (retourne l'user brut ou {})
        const raw = await this.apiGet("/me");
        const u = isObj(raw) && raw.id ? raw : null;
        this.me = u;
        this.userId = u?.id ? String(u.id) : "";
        this.renderMe();
        return u;
      } catch {
        this.me = null;
        this.userId = "";
        this.renderMe();
        return null;
      }
    }

    renderMe() {
      const u = this.me;

      if (this.el.userName) this.el.userName.textContent = u ? (u.global_name || u.username || u.id) : "Non connecté";
      if (this.el.userStatus) this.el.userStatus.textContent = u ? "Connecté" : "Discord";
      if (this.el.userAvatar) this.el.userAvatar.textContent = u ? String(u.username || u.global_name || "?").slice(0, 1).toUpperCase() : "?";

      this.el.btnLogin?.classList.toggle("hidden", !!u);
      this.el.btnLogout?.classList.toggle("hidden", !u);
    }

    async loginDiscordPopup() {
      try {
        const w = window.open("/auth/login", "greg_login", "width=480,height=720");
        if (!w) alert("Popup bloquée. Autorise les popups pour te connecter.");
      } catch {}

      this.setStatus("Connexion Discord en cours…", true);

      const t0 = Date.now();
      const loop = async () => {
        await this.refreshMe();
        if (this.me) {
          this.setStatus("Connecté à Discord ✅", true);
          await this.refreshGuilds();
          await this.refreshState(true);
          return;
        }
        if (Date.now() - t0 < 120000) return setTimeout(loop, 1200);
        this.setStatus("Connexion Discord expirée.", false);
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
      this.userId = "";
      this.renderMe();
      this.setStatus("Déconnecté.", true);
      // guilds list becomes unavailable
      await this.refreshGuilds();
      await this.refreshState(true);
    }

    // -----------------------------
    // Guilds
    // -----------------------------
    async refreshGuilds() {
      if (!this.el.guildSelect) return;

      // default option always present
      const setOptions = (guilds) => {
        const sel = this.el.guildSelect;
        sel.innerHTML = "";
        const opt0 = document.createElement("option");
        opt0.value = "";
        opt0.textContent = "(par défaut)";
        sel.appendChild(opt0);

        for (const g of guilds) {
          const opt = document.createElement("option");
          opt.value = String(g.id || "");
          opt.textContent = g.name ? `${g.name}` : String(g.id || "Guild");
          sel.appendChild(opt);
        }

        // restore selection if exists
        if (this.guildId) sel.value = String(this.guildId);
      };

      // If not logged in => keep only default
      if (!this.me) {
        setOptions([]);
        return;
      }

      try {
        const raw = await this.apiGet("/guilds");
        const guilds = Array.isArray(raw) ? raw : Array.isArray(raw?.guilds) ? raw.guilds : [];
        setOptions(guilds);

        // if no selected guild, pick first available
        if (!this.guildId && guilds.length) {
          this.guildId = String(guilds[0].id || "");
          this.el.guildSelect.value = this.guildId;
          try {
            localStorage.setItem("greg_guild", this.guildId);
          } catch {}
        }
      } catch (e) {
        // 401/403 => not logged in
        setOptions([]);
      }
    }

    // -----------------------------
    // Playlist / state
    // -----------------------------
    unwrapStatePayload(raw) {
      // accepte:
      // - { ok:true, state:{...} }
      // - { current, queue, ... }
      // - { ok:true, ...direct... }
      if (!isObj(raw)) return {};
      if (isObj(raw.state)) return raw.state;
      return raw;
    }

    makeTrackKey(cur) {
      if (!cur) return "";
      const url = cur.webpage_url || cur.url || "";
      const t = cur.title || "";
      const d = cur.duration || cur._duration || "";
      return `${t}::${url}::${d}`;
    }

    pickDuration(cur, data) {
      // donne une durée stable, même si le backend change de champs
      const a = asNum(data?.duration, 0);
      const b = asNum(data?.progress?.duration, 0);
      const c = asNum(cur?.duration, 0);
      const d = asNum(cur?._duration, 0);
      return a || b || c || d || 0;
    }

    rebaseProgressFromPayload(data) {
      const cur = data?.current || null;
      const paused = !!data?.is_paused;

      const repeat_all =
        typeof data?.repeat_all === "boolean"
          ? !!data.repeat_all
          : typeof data?.repeat === "boolean"
          ? !!data.repeat
          : !!this.state.repeat_all;

      this.state.repeat_all = repeat_all;

      if (!cur) {
        this.progress.trackKey = "";
        this.progress.duration = 0;
        this.progress.baselineElapsed = 0;
        this.progress.t0ms = Date.now();
        this.progress.paused = true;
        return;
      }

      const newKey = this.makeTrackKey(cur);
      const same = newKey && newKey === this.progress.trackKey;

      const elapsed =
        (data?.progress && typeof data.progress.elapsed === "number" ? data.progress.elapsed : null) ??
        (typeof data?.elapsed === "number" ? data.elapsed : null);

      const dur = this.pickDuration(cur, data);

      if (!same) {
        this.progress.trackKey = newKey;
        this.progress.duration = dur || 0;
        this.progress.baselineElapsed = elapsed != null ? asNum(elapsed, 0) : 0;
        this.progress.t0ms = Date.now();
        this.progress.paused = paused;
      } else {
        // même track => update sans perdre la durée connue
        if (dur && dur > 0) this.progress.duration = dur;
        if (elapsed != null) {
          this.progress.baselineElapsed = asNum(elapsed, this.progress.baselineElapsed);
          this.progress.t0ms = Date.now();
        }
        this.progress.paused = paused;
      }
    }

    computedElapsed() {
      if (this.progress.paused) return this.progress.baselineElapsed;
      const dt = (Date.now() - this.progress.t0ms) / 1000;
      return Math.max(0, this.progress.baselineElapsed + dt);
    }

    async refreshState(silent = false) {
      if (!this.me) {
        // rendu "offline" propre
        this.state.current = null;
        this.state.queue = [];
        this.state.is_paused = false;
        this.state.repeat_all = false;
        this.rebaseProgressFromPayload({ current: null, is_paused: true });
        this.renderState();
        this.renderProgressOnly();
        return;
      }

      try {
        const raw = await this.apiGet("/playlist");
        const data = this.unwrapStatePayload(raw);

        this.state.current = data.current || null;
        this.state.queue = Array.isArray(data.queue) ? data.queue : [];
        this.state.is_paused = !!data.is_paused;

        // progress rebase
        this.rebaseProgressFromPayload(data);

        if (!silent) this.setStatus("État mis à jour.", true);
        this.renderState();
        this.renderProgressOnly();
      } catch (e) {
        if (!silent) {
          const msg = e?.status === 401 ? "Connecte-toi à Discord." : "Impossible de récupérer la playlist.";
          this.setStatus(msg, false);
        }
      }
    }

    renderState() {
      const cur = this.state.current;
      const queue = this.state.queue || [];

      // title/artist
      if (this.el.title) this.el.title.textContent = cur ? asStr(cur.title, "Sans titre") : "Rien en cours";

      if (this.el.artist) {
        const artist = cur?.artist || cur?.uploader || cur?.author || cur?.channel || cur?.provider || "";
        this.el.artist.textContent = cur ? (artist || "Artiste inconnu") : "Greg dort encore";
      }

      // artwork thumb
      if (this.el.artwork) {
        const thumb = cur?.thumbnail || cur?.thumb || "";
        if (thumb) {
          const s = safeBgUrl(thumb);
          this.el.artwork.style.backgroundImage = `url("${s}")`;
          this.el.artwork.textContent = "";
        } else {
          this.el.artwork.style.backgroundImage = "";
          this.el.artwork.textContent = "🎵";
        }
      }

      // queue count
      if (this.el.queueCount) {
        this.el.queueCount.textContent = `${queue.length} titre${queue.length > 1 ? "s" : ""}`;
      }

      // controls visuals
      if (this.el.btnPlayPause) this.el.btnPlayPause.textContent = this.state.is_paused ? "▶️" : "⏸";
      if (this.el.btnRepeat) {
        // petit feedback visuel sans dépendre du CSS
        this.el.btnRepeat.style.opacity = this.state.repeat_all ? "1" : "0.7";
        this.el.btnRepeat.title = this.state.repeat_all ? "Répétition activée" : "Répétition désactivée";
      }

      // enable/disable (si pas de guild sélectionnée, backend peut refuser sur certains cas)
      const hasGuild = !!this.guildId;
      const hasCurrent = !!cur;
      const canControl = !!this.me && (hasGuild || true); // backend accepte parfois default guild côté serveur

      if (this.el.btnPlayPause) this.el.btnPlayPause.disabled = !canControl || !hasCurrent;
      if (this.el.btnSkip) this.el.btnSkip.disabled = !canControl;
      if (this.el.btnStop) this.el.btnStop.disabled = !canControl;
      if (this.el.btnPrev) this.el.btnPrev.disabled = !canControl || !hasCurrent;
      if (this.el.btnRepeat) this.el.btnRepeat.disabled = !canControl;

      // queue list
      this.renderQueue(queue);
    }

    renderQueue(queue) {
      if (!this.el.queueList) return;
      this.el.queueList.innerHTML = "";

      if (!queue.length) {
        const empty = document.createElement("div");
        empty.className = "queue-empty";
        empty.style.padding = "16px";
        empty.style.color = "rgba(148,163,184,.9)";
        empty.textContent = "Aucun titre dans la file.";
        this.el.queueList.appendChild(empty);
        return;
      }

      queue.forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "queue-item";

        const thumb = document.createElement("div");
        thumb.className = "queue-thumb";
        const th = item.thumbnail || item.thumb || "";
        if (th) {
          thumb.style.backgroundImage = `url("${safeBgUrl(th)}")`;
          thumb.textContent = "";
        } else {
          thumb.style.backgroundImage = "";
          thumb.textContent = "🎵";
        }

        const info = document.createElement("div");
        info.className = "queue-info";

        const t = document.createElement("div");
        t.className = "queue-track";
        t.textContent = asStr(item.title || item.query || item.url, "Sans titre");

        const a = document.createElement("div");
        a.className = "queue-artist";
        a.textContent = asStr(item.artist || item.uploader || item.author || item.provider || item.source, "");

        info.appendChild(t);
        info.appendChild(a);

        const dur = document.createElement("div");
        dur.className = "queue-duration";
        const seconds = asNum(item.duration, 0);
        dur.textContent = seconds ? formatTime(seconds) : "";

        const actions = document.createElement("div");
        actions.className = "queue-actions";

        const btnPlay = document.createElement("button");
        btnPlay.type = "button";
        btnPlay.className = "qa-btn";
        btnPlay.title = "Lire maintenant";
        btnPlay.textContent = "▶";
        btnPlay.addEventListener("click", () => this.playAt(idx));

        const btnDel = document.createElement("button");
        btnDel.type = "button";
        btnDel.className = "qa-btn qa-del";
        btnDel.title = "Supprimer";
        btnDel.textContent = "🗑";
        btnDel.addEventListener("click", () => this.removeAt(idx));

        actions.appendChild(btnPlay);
        actions.appendChild(btnDel);

        row.appendChild(thumb);
        row.appendChild(info);
        row.appendChild(dur);
        row.appendChild(actions);

        this.el.queueList.appendChild(row);
      });
    }

    renderProgressOnly() {
      const cur = this.state.current;
      const duration = asNum(this.progress.duration, 0);

      if (!cur || !duration) {
        if (this.el.pFill) this.el.pFill.style.width = "0%";
        if (this.el.pCur) this.el.pCur.textContent = "0:00";
        if (this.el.pTot) this.el.pTot.textContent = "0:00";
        return;
      }

      const elapsed = clamp(this.computedElapsed(), 0, duration);
      const ratio = duration > 0 ? elapsed / duration : 0;

      if (this.el.pFill) this.el.pFill.style.width = `${Math.round(ratio * 1000) / 10}%`;
      if (this.el.pCur) this.el.pCur.textContent = formatTime(elapsed);
      if (this.el.pTot) this.el.pTot.textContent = formatTime(duration);
    }

    // -----------------------------
    // Queue actions
    // -----------------------------
    async enqueueQuery(query) {
      if (!this.me) return this.setStatus("Connecte-toi à Discord d’abord.", false);

      try {
        // /queue/add accepte query/url/title + récupère gid depuis header X-Guild-ID
        await this.apiPost("/queue/add", { query });
        this.setStatus(`Ajouté: ${query}`, true);

        if (this.el.searchInput) this.el.searchInput.value = "";
        this.renderSuggestions([]);

        // refresh immédiat
        await this.refreshState(true);
      } catch (e) {
        const msg =
          e?.status === 400 ? "Requête invalide (titre/lien manquant)." :
          e?.status === 401 ? "Session expirée, reconnecte-toi." :
          e?.status === 403 ? "Action bloquée par les règles de priorité." :
          "Impossible d’ajouter ce titre.";
        this.setStatus(msg, false);
      }
    }

    async playAt(index) {
      try {
        await this.apiPost("/playlist/play_at", { index });
        await this.refreshState(true);
        this.setStatus("Lecture lancée.", true);
      } catch (e) {
        this.setStatus("Impossible de lancer ce titre.", false);
      }
    }

    async removeAt(index) {
      try {
        await this.apiPost("/queue/remove", { index });
        await this.refreshState(true);
        this.setStatus("Supprimé de la file.", true);
      } catch (e) {
        this.setStatus("Impossible de supprimer.", false);
      }
    }

    async togglePause() {
      try {
        const res = await this.apiPost("/playlist/toggle_pause", {});
        // certains backends renvoient paused, d'autres is_paused
        if (typeof res?.paused === "boolean") this.state.is_paused = !!res.paused;
        await this.refreshState(true);
      } catch (e) {
        this.setStatus("Impossible de pause/reprendre.", false);
      }
    }

    async skip() {
      try {
        await this.apiPost("/queue/skip", {});
        await this.refreshState(true);
        this.setStatus("Titre suivant ⏭", true);
      } catch (e) {
        this.setStatus("Impossible de skip.", false);
      }
    }

    async stop() {
      try {
        await this.apiPost("/queue/stop", {});
        await this.refreshState(true);
        this.setStatus("Stop ⏹", true);
      } catch (e) {
        this.setStatus("Impossible de stop.", false);
      }
    }

    async restart() {
      try {
        await this.apiPost("/playlist/restart", {});
        await this.refreshState(true);
        this.setStatus("Redémarrage ⏮", true);
      } catch (e) {
        this.setStatus("Impossible de redémarrer.", false);
      }
    }

    async toggleRepeat() {
      try {
        const res = await this.apiPost("/playlist/repeat", {});
        const next =
          typeof res?.repeat_all === "boolean"
            ? !!res.repeat_all
            : typeof res?.repeat === "boolean"
            ? !!res.repeat
            : this.state.repeat_all;

        this.state.repeat_all = next;
        this.renderState();
        this.setStatus(next ? "Répétition activée 🔁" : "Répétition désactivée", true);
      } catch (e) {
        this.setStatus("Impossible de changer la répétition.", false);
      }
    }

    // -----------------------------
    // Autocomplete
    // -----------------------------
    async fetchAutocomplete(q) {
      const reqId = ++this._autoReqId;
      try {
        const url = this.apiUrl(`/autocomplete?q=${encodeURIComponent(q)}&limit=12`);
        const data = await this.fetchJson(url, {
          method: "GET",
          headers: this.headers(),
          timeoutMs: 9000,
        });

        if (reqId !== this._autoReqId) return; // stale response

        // backend: { ok:true, results:[...] } (ou items)
        const items = Array.isArray(data?.results)
          ? data.results
          : Array.isArray(data?.items)
          ? data.items
          : Array.isArray(data)
          ? data
          : [];

        this.renderSuggestions(items);
      } catch {
        if (reqId !== this._autoReqId) return;
        this.renderSuggestions([]);
      }
    }

    renderSuggestions(items) {
      if (!this.el.suggestions) return;

      this.el.suggestions.innerHTML = "";
      const arr = Array.isArray(items) ? items : [];

      if (!arr.length) {
        this.el.suggestions.classList.remove("search-suggestions--open");
        return;
      }
      this.el.suggestions.classList.add("search-suggestions--open");

      arr.slice(0, 12).forEach((it) => {
        const div = document.createElement("div");
        div.className = "suggestion-item";
        const label = it.title || it.query || it.label || it.url || "Résultat";
        div.textContent = asStr(label, "Résultat");

        div.addEventListener("click", () => {
          const q = it.url || it.query || it.title || "";
          if (this.el.searchInput) this.el.searchInput.value = q;
          if (q) this.enqueueQuery(q);
        });

        this.el.suggestions.appendChild(div);
      });
    }

    // -----------------------------
    // Spotify
    // -----------------------------
    async refreshSpotify() {
      try {
        const st = await this.apiGet("/spotify/status");
        const linked = !!st?.linked;
        const who = st?.profile?.display_name || st?.profile?.id || "?";

        if (this.el.spStatus) {
          this.el.spStatus.textContent = linked ? `Spotify lié (${who})` : "Spotify non lié";
        }
        this.el.spLogin?.classList.toggle("hidden", linked);
        this.el.spLogout?.classList.toggle("hidden", !linked);
      } catch {
        // si pas connecté, le endpoint peut 401 → on affiche neutre
        if (this.el.spStatus) this.el.spStatus.textContent = "Spotify non lié";
        this.el.spLogin?.classList.remove("hidden");
        this.el.spLogout?.classList.add("hidden");
      }
    }

    async loginSpotifyPopup() {
      if (!this.me) return this.setStatus("Connecte-toi à Discord d’abord.", false);

      try {
        const w = window.open(this.apiUrl("/spotify/login"), "spotify_login", "width=480,height=720");
        if (!w) alert("Popup Spotify bloquée. Autorise les popups.");
      } catch {}

      this.setStatus("Connexion Spotify en cours…", true);

      const t0 = Date.now();
      const loop = async () => {
        await this.refreshSpotify();
        const linked = this.el.spStatus?.textContent?.includes("lié");
        if (linked) return this.setStatus("Spotify lié ✅", true);
        if (Date.now() - t0 < 60000) return setTimeout(loop, 1200);
        this.setStatus("Connexion Spotify expirée.", false);
      };
      loop();
    }

    async logoutSpotify() {
      try {
        await this.apiPost("/spotify/logout", {});
        await this.refreshSpotify();
        this.setStatus("Spotify dé-lié.", true);
      } catch {
        this.setStatus("Impossible de dé-lier Spotify.", false);
      }
    }
  }

  // Boot
  document.addEventListener("DOMContentLoaded", () => {
    const app = new GregWebPlayer();
    app.init().catch((e) => {
      console.error("GregWebPlayer init failed:", e);
    });
    // debug (optionnel)
    window.__gregPlayer = app;
  });
})();
