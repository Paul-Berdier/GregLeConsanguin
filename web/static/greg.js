// web/static/greg.js

// === Autocomplétion dynamique SoundCloud / YouTube ===
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

// === Contrôles AJAX sans reload (panel.html) ===
document.querySelectorAll(".controls button").forEach(btn => {
    btn.addEventListener("click", function(e) {
        e.preventDefault();
        const action = this.dataset.action;
        if (!action) return;
        fetch(`/api/${action}`, { method: "POST" });
    });
});

// === Socket.IO : Sync playlist & current ===
const socket = io();

function updatePlaylist(playlist, current) {
    // Affichage de la musique en cours
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
    // Affichage dynamique de la playlist (avec boutons cliquables)
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
    updatePlaylist(data.queue, data.current);
});

// === Envoi commande PLAY depuis le formulaire (panel.html) ===
const form = document.getElementById("play-form");
if (form && input && suggestions) {
    form.addEventListener("submit", function(e) {
        e.preventDefault();
        const val = input.value;
        if (!val.trim()) return;
        fetch("/api/play", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: val })
        }).then(() => {
            input.value = "";
            suggestions.style.display = "none";
            suggestions.innerHTML = "";
        });
    });
}

// === Sélection dynamique des salons vocaux ===
const guildSelect = document.getElementById("guild-select");
const channelSelect = document.getElementById("channel-select");
if (guildSelect && channelSelect) {
    guildSelect.addEventListener("change", function() {
        fetch(`/api/channels?guild_id=${guildSelect.value}`)
            .then(r => r.json())
            .then(chans => {
                channelSelect.innerHTML = "";
                chans.forEach(c => {
                    const opt = document.createElement("option");
                    opt.value = c.id;
                    opt.innerText = c.name;
                    channelSelect.appendChild(opt);
                });
            });
    });
}

// === Playlist cliquable (play/move) ===
function playlistClickHandler(e) {
    if (e.target.classList.contains("play-this")) {
        const li = e.target.closest("li");
        const index = li.dataset.index;
        fetch("/api/command/play_at", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ index })
        });
    }
    if (e.target.classList.contains("move-top")) {
        const li = e.target.closest("li");
        const index = li.dataset.index;
        fetch("/api/command/move_top", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ index })
        });
    }
}

const playlistUl = document.getElementById("playlist-ul");
if (playlistUl) {
    playlistUl.addEventListener("click", playlistClickHandler);
}

