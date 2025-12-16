// assets/js/player.js
// Web player simple pour Greg le Consanguin
// Parle à l'API Flask sur /api/v1, réutilisable avec l'overlay.

class GregWebPlayer {
    constructor() {
        this.API_BASE = window.GREG_API_BASE || "/api/v1";

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

        // DOM refs
        this.$statusText   = document.getElementById("statusText");
        this.$searchForm   = document.getElementById("searchForm");
        this.$searchInput  = document.getElementById("searchInput");
        this.$suggestions  = document.getElementById("searchSuggestions");
        this.$queueList    = document.getElementById("queueList");
        this.$queueCount   = document.getElementById("queueCount");

        this.$artwork      = document.getElementById("artwork");
        this.$title        = document.getElementById("trackTitle");
        this.$artist       = document.getElementById("trackArtist");
        this.$pf           = document.getElementById("progressFill");
        this.$pCur         = document.getElementById("progressCurrent");
        this.$pTot         = document.getElementById("progressTotal");

        this.$btnPrev      = document.getElementById("btn-prev");
        this.$btnPlayPause = document.getElementById("btn-play-pause");
        this.$btnSkip      = document.getElementById("btn-skip");
        this.$btnStop      = document.getElementById("btn-stop");
        this.$btnRepeat    = document.getElementById("btn-repeat");

        // user / guild
        this.$userName     = document.getElementById("userName");
        this.$userAvatar   = document.getElementById("userAvatar");
        this.$userStatus   = document.getElementById("userStatus");
        this.$btnLogin     = document.getElementById("btn-login-discord");
        this.$btnLogout    = document.getElementById("btn-logout-discord");
        this.$guildSelect  = document.getElementById("guildSelect");

        // spotify
        this.$spStatus     = document.getElementById("spotifyStatus");
        this.$spLogin      = document.getElementById("btn-spotify-login");
        this.$spLogout     = document.getElementById("btn-spotify-logout");

        // nav (secondaires)
        this.$navSettings  = document.getElementById("nav-settings");
        this.$navAbout     = document.getElementById("nav-about");
        this.$panelSettings = document.getElementById("panel-settings");
        this.$panelAbout    = document.getElementById("panel-about");
    }

    log(...args) {
        console.log("[GregWebPlayer]", ...args);
    }

    setStatus(text, ok = true) {
        if (!this.$statusText) return;
        this.$statusText.textContent = text;
        this.$statusText.className = ok ? "status-text status-text--ok"
                                        : "status-text status-text--err";
    }

    // ============ INIT =========================================
    async init() {
        this.bindEvents();
        await this.refreshMe();
        await this.refreshGuilds();
        await this.refreshState();
        await this.refreshSpotify();

        // petit polling d’état pour avoir le temps qui avance
        this.pollTimer = setInterval(() => this.refreshState(true), 3000);
        // tick local pour la barre de progression
        setInterval(() => this.renderProgress(), 500);
    }

    bindEvents() {
        if (this.$searchForm) {
            this.$searchForm.addEventListener("submit", (ev) => {
                ev.preventDefault();
                const q = (this.$searchInput?.value || "").trim();
                if (q) this.enqueueQuery(q);
            });
        }

        if (this.$searchInput) {
            this.$searchInput.addEventListener("input", () => {
                const q = this.$searchInput.value.trim();
                if (q.length < 3) {
                    this.renderSuggestions([]);
                } else {
                    this.fetchAutocomplete(q);
                }
            });
        }

        if (this.$btnPlayPause) {
            this.$btnPlayPause.addEventListener("click", () => this.togglePause());
        }
        if (this.$btnSkip) {
            this.$btnSkip.addEventListener("click", () => this.skip());
        }
        if (this.$btnStop) {
            this.$btnStop.addEventListener("click", () => this.restart());
        }
        if (this.$btnRepeat) {
            this.$btnRepeat.addEventListener("click", () => this.toggleRepeat());
        }

        if (this.$btnLogin) {
            this.$btnLogin.addEventListener("click", () => this.loginDiscord());
        }
        if (this.$btnLogout) {
            this.$btnLogout.addEventListener("click", () => this.logoutDiscord());
        }

        if (this.$guildSelect) {
            this.$guildSelect.addEventListener("change", () => {
                this.guildId = this.$guildSelect.value || "";
                this.refreshState();
            });
        }

        if (this.$spLogin) {
            this.$spLogin.addEventListener("click", () => this.loginSpotify());
        }
        if (this.$spLogout) {
            this.$spLogout.addEventListener("click", () => this.logoutSpotify());
        }

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

    // ============ API helpers =================================
    headers(extra = {}) {
        const h = { "Content-Type": "application/json" };
        if (this.guildId) h["X-Guild-ID"] = this.guildId;
        if (this.userId)  h["X-User-ID"] = String(this.userId);
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

    // ============ Auth Discord =================================
    async refreshMe() {
        try {
            const me = await this.apiGet("/me");
            this.me = me && me.id ? me : null;
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
        const u = this.me;
        if (!this.$userName || !this.$userAvatar || !this.$userStatus) return;
        if (u && u.id) {
            this.$userName.textContent = u.global_name || u.username || u.id;
            this.$userStatus.textContent = "Connecté";
            this.$userAvatar.textContent = (u.username || "?").slice(0, 1).toUpperCase();

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
        // version simple : on ouvre /auth/login dans une nouvelle fenêtre
        try {
            const w = window.open("/auth/login", "greg_login", "width=480,height=720");
            if (!w) {
                alert("Impossible d’ouvrir la fenêtre de connexion. Vérifie ton bloqueur de popup.");
            }
        } catch {}
        this.setStatus("Connexion Discord en cours…", true);

        // on poll /me quelques secondes pour voir si ça a marché
        const t0 = Date.now();
        const tryMe = async () => {
            await this.refreshMe();
            if (this.me) {
                this.setStatus("Connecté à Discord ✅", true);
            } else if (Date.now() - t0 < 120000) {
                setTimeout(tryMe, 2000);
            } else {
                this.setStatus("Connexion Discord expirée.", false);
            }
        };
        tryMe();
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
        this.setStatus("Déconnecté de Discord.", true);
    }

    // ============ Guilds ======================================
    async refreshGuilds() {
        // Si tu as une route dédiée genre /api/v1/guilds, tu peux la consommer ici.
        // Pour l’instant on laisse un sélecteur trivial basé sur DEFAULT_GUILD_ID côté serveur.
        if (!this.$guildSelect) return;
        // Pas de route -> pas de liste. La valeur vide = guild par défaut côté backend.
        this.$guildSelect.innerHTML = `<option value="">(par défaut)</option>`;
    }

    // ============ Playlist / queue =============================
    async refreshState(silent = false) {
        try {
            const data = await this.apiGet("/playlist");
            // format attendu aligné sur ce qu’utilisent déjà tes routes overlay
            this.state.current   = data.current || null;
            this.state.queue     = data.queue || [];
            this.state.is_paused = !!data.is_paused;
            this.state.repeat    = !!data.repeat;

            const elapsed = Number(data.elapsed || 0);
            const duration = Number(data.duration || (data.current && data.current.duration) || 0);
            this.progress.startedAt = Date.now() / 1000 - elapsed;
            this.progress.elapsed   = elapsed;
            this.progress.duration  = duration;

            if (!silent) this.setStatus("État mis à jour.", true);
            this.renderState();
        } catch (e) {
            this.log("refreshState error:", e);
            if (!silent) this.setStatus("Impossible de récupérer la playlist.", false);
        }
    }

    renderState() {
        const cur   = this.state.current;
        const queue = this.state.queue || [];

        if (this.$title) {
            this.$title.textContent = cur ? (cur.title || "Sans titre") : "Rien en cours";
        }
        if (this.$artist) {
            const artist =
                cur?.artist ||
                cur?.uploader ||
                cur?.author ||
                cur?.channel ||
                "";
            this.$artist.textContent = cur ? artist || "Artiste inconnu" : "Greg dort encore";
        }

        if (this.$queueCount) {
            this.$queueCount.textContent = `${queue.length} titre${queue.length > 1 ? "s" : ""}`;
        }

        if (this.$queueList) {
            this.$queueList.innerHTML = "";
            queue.forEach((item, idx) => {
                const div = document.createElement("div");
                div.className = "queue-item";

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
                btnPlay.addEventListener("click", () => this.playAt(idx));

                const btnDel = document.createElement("button");
                btnDel.type = "button";
                btnDel.className = "queue-item-btn";
                btnDel.textContent = "✕";
                btnDel.addEventListener("click", () => this.removeAt(idx));

                right.appendChild(btnPlay);
                right.appendChild(btnDel);

                div.appendChild(left);
                div.appendChild(right);

                this.$queueList.appendChild(div);
            });
        }

        // artwork
        const thumb = cur?.thumbnail || cur?.thumb || "";
        if (this.$artwork) {
            if (thumb) {
                const safe = String(thumb).replace(/["\\)\n\r]/g, m => ({
                    '"': "%22",
                    "\\": "%5C",
                    ")": "%29",
                    "\n": "",
                    "\r": "",
                }[m]));
                this.$artwork.style.backgroundImage = `url("${safe}")`;
                this.$artwork.textContent = "";
            } else {
                this.$artwork.style.backgroundImage = "";
                this.$artwork.textContent = "🎵";
            }
        }

        // bouton play/pause
        if (this.$btnPlayPause) {
            this.$btnPlayPause.textContent = this.state.is_paused ? "▶️" : "⏸";
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

    formatTime(sec) {
        sec = Math.max(0, Math.floor(sec || 0));
        const m = Math.floor(sec / 60);
        const s = sec % 60;
        return `${m}:${s.toString().padStart(2, "0")}`;
    }

    // ============ Queue actions ================================
    async enqueueQuery(query) {
        try {
            await this.apiPost("/queue/add", {
                query,
                guild_id: this.guildId || undefined,
                user_id: this.userId || undefined,
            });
            this.setStatus(`Ajouté à la file: ${query}`, true);
            this.$searchInput && (this.$searchInput.value = "");
            this.renderSuggestions([]);
            await this.refreshState();
        } catch (e) {
            this.log("enqueueQuery error:", e);
            this.setStatus("Impossible d’ajouter ce titre.", false);
        }
    }

    async playAt(idx) {
        try {
            await this.apiPost("/playlist/play_at", { index: idx });
            await this.refreshState();
        } catch (e) {
            this.log("playAt error:", e);
        }
    }

    async removeAt(idx) {
        try {
            await this.apiPost("/queue/remove", { index: idx });
            await this.refreshState();
        } catch (e) {
            this.log("removeAt error:", e);
        }
    }

    async togglePause() {
        try {
            await this.apiPost("/playlist/toggle_pause", {});
            await this.refreshState();
        } catch (e) {
            this.log("togglePause error:", e);
        }
    }

    async skip() {
        try {
            await this.apiPost("/queue/skip", {});
            await this.refreshState();
        } catch (e) {
            this.log("skip error:", e);
        }
    }

    async restart() {
        try {
            await this.apiPost("/playlist/restart", {});
            await this.refreshState();
        } catch (e) {
            this.log("restart error:", e);
        }
    }

    async toggleRepeat() {
        try {
            const res = await this.apiPost("/playlist/repeat", {});
            this.state.repeat = !!(res && res.repeat);
        } catch (e) {
            this.log("repeat error:", e);
        }
    }

    // ============ Autocomplete recherche =======================
    async fetchAutocomplete(q) {
        try {
            const url = `${this.API_BASE}/autocomplete?q=${encodeURIComponent(q)}&limit=12`;
            const r = await fetch(url, {
                method: "GET",
                credentials: "include",
                cache: "no-store",
                headers: this.headers(),
            });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            const items = Array.isArray(data?.items) ? data.items : [];
            this.renderSuggestions(items);
        } catch (e) {
            this.log("autocomplete error:", e);
            this.renderSuggestions([]);
        }
    }

    renderSuggestions(items) {
        if (!this.$suggestions) return;
        this.$suggestions.innerHTML = "";
        if (!items || !items.length) {
            this.$suggestions.classList.remove("search-suggestions--open");
            return;
        }
        this.$suggestions.classList.add("search-suggestions--open");

        items.forEach((it) => {
            const div = document.createElement("div");
            div.className = "suggestion-item";
            div.textContent = it.title || it.query || it.label || "Résultat";
            div.addEventListener("click", () => {
                const q = it.query || it.url || it.title;
                if (this.$searchInput) this.$searchInput.value = q;
                this.enqueueQuery(q);
            });
            this.$suggestions.appendChild(div);
        });
    }

    // ============ Spotify ======================================
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
            const w = window.open(`${this.API_BASE}/spotify/login`, "spotify_login", "width=480,height=720");
            if (!w) {
                alert("Impossible d’ouvrir la fenêtre Spotify.");
            }
        } catch {}
        this.setStatus("Connexion Spotify en cours…", true);

        const t0 = Date.now();
        const loop = async () => {
            await this.refreshSpotify();
            // si lié, on arrête
            if (this.$spStatus && this.$spStatus.textContent.includes("lié")) {
                this.setStatus("Spotify lié ✅", true);
            } else if (Date.now() - t0 < 60000) {
                setTimeout(loop, 2000);
            } else {
                this.setStatus("Connexion Spotify expirée.", false);
            }
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
    app.init().catch((e) => {
        console.error("Init GregWebPlayer failed:", e);
    });
});
