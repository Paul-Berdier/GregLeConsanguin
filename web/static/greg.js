// === GREG LE CONSANGUIN - JS Web Panel Dynamique ===

function dbg(...args) { console.log("[GREG.js]", ...args); }

// === Récupère l'ID Discord de l'utilisateur connecté, injecté dans la page HTML ===
let currentUserId = null;
if (window.USER_ID) {
    currentUserId = window.USER_ID;
    dbg("User Discord connecté (USER_ID):", currentUserId);
} else {
    dbg("⚠️ USER_ID non défini dans la page HTML !");
}

// === Récupère guild_id et channel_id depuis l'URL sur le panel ===
function getUrlParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}
let currentGuildId = getUrlParam("guild_id");
let currentChannelId = getUrlParam("channel_id");
dbg("Init via URL params:", currentGuildId, currentChannelId);



// === Autocomplétion dynamique ===
const input = document.getElementById("music-input");
const suggestions = document.getElementById("suggestions");
let debounce = null;

if (input && suggestions) {
    input.addEventListener("input", function() {
        const val = this.value;
        if (debounce) clearTimeout(debounce);
        if (!val.trim() || val.startsWith("http")) {
            suggestions.style.display = "none";
            suggestions.innerHTML = "";
            return;
        }
        debounce = setTimeout(() => {
            fetch(`/autocomplete?q=${encodeURIComponent(val)}`)
                .then(res => res.json())
                .then(data => {
                    if (!data.results.length) {
                        suggestions.style.display = "none";
                        suggestions.innerHTML = "";
                        return;
                    }
                    suggestions.innerHTML = data.results.map(
                        item => `<div class="suggestion-item" data-title="${item.title.replace(/"/g, '&quot;')}" data-url="${item.url}">${item.title}</div>`
                    ).join('');
                    suggestions.style.display = "block";
                });
        }, 300);
    });

    suggestions.addEventListener("click", function(e) {
        if (e.target.classList.contains("suggestion-item")) {
            input.value = e.target.getAttribute("data-title");
            suggestions.style.display = "none";
            suggestions.innerHTML = "";
        }
    });

    input.addEventListener("blur", function() {
        setTimeout(() => { suggestions.style.display = "none"; }, 200);
    });

    input.addEventListener("focus", function() {
        if (suggestions.innerHTML) suggestions.style.display = "block";
    });
}

// === Contrôles AJAX (Play, Pause, etc.) ===
document.querySelectorAll(".controls button").forEach(btn => {
    btn.addEventListener("click", function(e) {
        e.preventDefault();
        const action = this.dataset.action;
        if (!action) return;
        if (!currentGuildId || !currentChannelId) return alert("Choisis un serveur et un salon textuel !");
        dbg("Action bouton:", action, "Sur serveur:", currentGuildId, "Salon:", currentChannelId);
        fetch(`/api/${action}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                guild_id: currentGuildId,
                channel_id: currentChannelId,
                user_id: currentUserId // <-- Ajoute le user_id partout pour plus de robustesse si besoin plus tard
            })
        });
    });
});

// === Socket.IO : Sync playlist & current ===
const socket = io();

function updatePlaylist(playlist, current) {
    const currentDiv = document.querySelector(".current-song");
    if (currentDiv) {
        if (current) {
            currentDiv.innerHTML = `<h2>🎧 En lecture :</h2>
                <p><a href="${current}" target="_blank" style="color:#ffe066;">${current}</a></p>`;
            document.querySelector('.greg-face')?.classList.add('playing');
        } else {
            currentDiv.innerHTML = "";
            document.querySelector('.greg-face')?.classList.remove('playing');
        }
    }
    // Affichage dynamique de la playlist
    const playlistDiv = document.getElementById("playlist-ul");
    if (playlistDiv) {
        playlistDiv.innerHTML = playlist.length
            ? playlist.map((song, i) =>
                `<li data-index="${i}">
                    <a href="${song}" target="_blank">${song}</a>
                    <button class="play-this" title="Jouer ce morceau">▶️</button>
                    <button class="move-top" title="Passer en tête">⏫</button>
                </li>`
              ).join('')
            : `<p><em>La playlist est vide. Comme votre goût musical sans doute...</em></p>`;
    }
}

socket.on("playlist_update", function(data) {
    dbg("Playlist MAJ via SocketIO", data);
    updatePlaylist(data.queue, data.current);
});

// === Envoi commande PLAY depuis le formulaire ===
const form = document.getElementById("play-form");
if (form && input && suggestions) {
    form.addEventListener("submit", function(e) {
        e.preventDefault();
        const val = input.value;
        if (!val.trim()) return;
        if (!currentGuildId || !currentChannelId || !currentUserId) {
            alert("Choisis un serveur ET un salon textuel, et connecte-toi avec ton compte Discord !");
            return;
        }
        dbg("Formulaire play submit :", val, "guild:", currentGuildId, "channel:", currentChannelId, "user_id:", currentUserId);
        fetch("/api/play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                url: val,
                guild_id: currentGuildId,
                channel_id: currentChannelId,
                user_id: currentUserId   // <= CRUCIAL pour que le bot te trouve
            })
        }).then(() => {
            input.value = "";
            suggestions.style.display = "none";
            suggestions.innerHTML = "";
        });
    });
}

// === Playlist cliquable (play/move) ===
function playlistClickHandler(e) {
    if (!currentGuildId) return alert("Choisis un serveur !");
    const li = e.target.closest("li");
    if (!li) return;
    const index = li.dataset.index;
    if (e.target.classList.contains("play-this")) {
        dbg("Demande play_at index", index, "guild:", currentGuildId);
        fetch("/api/command/play_at", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ index, guild_id: currentGuildId })
        });
    }
    if (e.target.classList.contains("move-top")) {
        dbg("Demande move_top index", index, "guild:", currentGuildId);
        fetch("/api/command/move_top", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ index, guild_id: currentGuildId })
        });
    }
}

const playlistUl = document.getElementById("playlist-ul");
if (playlistUl) {
    playlistUl.addEventListener("click", playlistClickHandler);
}
