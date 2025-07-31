// === GREG LE CONSANGUIN - JS Web Panel Dynamique ===

const input = document.getElementById("music-input");
const suggestions = document.getElementById("suggestions");
let debounce = null;
let currentGuildId = null;
let currentChannelId = null;

function dbg(...args) { console.log("[GREG.js]", ...args); }

// === Autocomplétion dynamique ===
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

// === Sélection dynamique des serveurs et salons textuels ===
const guildSelect = document.getElementById("guild-select");
const channelSelect = document.getElementById("channel-select");

if (guildSelect && channelSelect) {
    currentGuildId = guildSelect.value;
    dbg("Init currentGuildId:", currentGuildId);

    // Charger salons textuels au démarrage
    loadTextChannels(currentGuildId);

    guildSelect.addEventListener("change", function() {
        currentGuildId = guildSelect.value;
        dbg("Changement de serveur:", currentGuildId);
        loadTextChannels(currentGuildId);
    });

    channelSelect.addEventListener("change", function() {
        currentChannelId = channelSelect.value;
        dbg("Changement de salon textuel:", currentChannelId);
    });
}

function loadTextChannels(guildId) {
    fetch(`/api/text_channels?guild_id=${guildId}`)
        .then(r => r.json())
        .then(chans => {
            channelSelect.innerHTML = "";
            chans.forEach(c => {
                const opt = document.createElement("option");
                opt.value = c.id;
                opt.innerText = c.name;
                channelSelect.appendChild(opt);
            });
            if (channelSelect.options.length)
                currentChannelId = channelSelect.options[0].value;
            dbg("Salons textuels chargés:", chans, "currentChannelId:", currentChannelId);
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
            body: JSON.stringify({ guild_id: currentGuildId, channel_id: currentChannelId })
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
        if (!currentGuildId || !currentChannelId) {
            alert("Choisis un serveur ET un salon textuel !");
            return;
        }
        dbg("Formulaire play submit :", val, "guild:", currentGuildId, "channel:", currentChannelId);
        fetch("/api/play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: val, guild_id: currentGuildId, channel_id: currentChannelId })
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
