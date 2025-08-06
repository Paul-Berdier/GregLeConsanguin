function dbg(...args) { console.log("[GREG.js]", ...args); }

let chosenSuggestion = null, currentSuggestions = [];
let suggestionsIndex = -1;

const input = document.getElementById("music-input");
const suggestions = document.getElementById("suggestions");
const playForm = document.getElementById('play-form');
const playBtn = document.getElementById('play-btn');
const playlistUl = document.getElementById('playlist-ul');
const playError = document.getElementById('play-error');
const currentSongDiv = document.getElementById('current-song');

const currentUserId = window.USER_ID;
const currentGuildId = window.GUILD_ID;
const currentChannelId = window.CHANNEL_ID;

// --- Autocomplete Avancé ---
let debounce = null;
if (input && suggestions) {
    input.addEventListener("input", function() {
        const val = this.value;
        chosenSuggestion = null;
        suggestionsIndex = -1;
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
                    currentSuggestions = data.results || [];
                    if (!currentSuggestions.length) {
                        suggestions.style.display = "none";
                        suggestions.innerHTML = "";
                        return;
                    }
                    suggestions.innerHTML = currentSuggestions.map(
                        (item, i) =>
                        `<div class="suggestion-item" data-index="${i}" data-title="${item.title.replace(/"/g, '&quot;')}" data-url="${item.url}">
                            <span class="suggestion-title">${item.title}</span>
                            <a href="${item.url}" target="_blank" class="suggestion-link">🔗</a>
                        </div>`
                    ).join('');
                    suggestions.style.display = "block";
                });
        }, 200);
    });

    suggestions.addEventListener("mousedown", function(e) {
        if (e.target.closest(".suggestion-item")) {
            const elem = e.target.closest(".suggestion-item");
            const idx = parseInt(elem.getAttribute("data-index"));
            const sug = currentSuggestions[idx];
            input.value = sug.title;
            chosenSuggestion = {title: sug.title, url: sug.url};
            suggestions.style.display = "none";
            suggestions.innerHTML = "";
        }
    });

    input.addEventListener("keydown", function(e) {
        if (!currentSuggestions.length) return;
        if (["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) e.preventDefault();
        if (e.key === "ArrowDown") {
            suggestionsIndex = (suggestionsIndex + 1) % currentSuggestions.length;
            highlightSuggestion();
        } else if (e.key === "ArrowUp") {
            suggestionsIndex = (suggestionsIndex - 1 + currentSuggestions.length) % currentSuggestions.length;
            highlightSuggestion();
        } else if (e.key === "Enter" && suggestionsIndex >= 0) {
            const sug = currentSuggestions[suggestionsIndex];
            input.value = sug.title;
            chosenSuggestion = {title: sug.title, url: sug.url};
            suggestions.style.display = "none";
            suggestions.innerHTML = "";
            suggestionsIndex = -1;
        }
    });

    function highlightSuggestion() {
        const items = suggestions.querySelectorAll(".suggestion-item");
        items.forEach((el, i) => el.classList.toggle("highlight", i === suggestionsIndex));
        if (items[suggestionsIndex]) items[suggestionsIndex].scrollIntoView({block: 'nearest'});
    }

    input.addEventListener("blur", function() {
        setTimeout(() => { suggestions.style.display = "none"; }, 180);
    });

    input.addEventListener("focus", function() {
        if (suggestions.innerHTML) suggestions.style.display = "block";
    });
}

// --- Submit Play (anti-spam, reset bouton) ---
let isPlayingRequest = false;

playForm.addEventListener('submit', async function(e) {
    e.preventDefault();
    if (isPlayingRequest) return;
    const value = input.value.trim();
    if (!value) return;

    playError.style.display = "none";
    playBtn.disabled = true;
    isPlayingRequest = true;

    // Utilise la suggestion choisie, sinon fallback brut
    let item = chosenSuggestion || {title: value, url: value};
    chosenSuggestion = null;

    addTrackToPlaylist(item);

    try {
        const payload = {
            title: item.title,
            url: item.url,
            guild_id: currentGuildId,
            user_id: currentUserId
        };
        const res = await fetch("/api/play", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload)
        });
        const resp = await res.json();
        if (!res.ok) throw resp.error || "Erreur API";
    } catch (err) {
        playError.style.display = "";
        playError.innerText = "Erreur : " + (err || "Impossible d’ajouter ce son");
    }

    input.value = "";
    playBtn.disabled = false;
    isPlayingRequest = false;
});

// Ajoute un morceau à la playlist affichée (optimiste)
function addTrackToPlaylist(item) {
    const li = document.createElement("li");
    li.innerHTML = `<a href="${item.url}" target="_blank">${item.title}</a>`;
    playlistUl.appendChild(li);
}

// Mets à jour la playlist depuis le serveur (via socket)
function updatePlaylist(tracks) {
    playlistUl.innerHTML = "";
    if (!tracks || tracks.length === 0) {
        playlistUl.innerHTML = `<p><em>La playlist est vide. Comme votre inspiration.</em></p>`;
        return;
    }
    for (const item of tracks) {
        addTrackToPlaylist(item);
    }
}

// Mets à jour le morceau en cours
function updateCurrent(current) {
    if (current) {
        currentSongDiv.innerHTML = `🎧 En lecture : <a href="${current.url}" target="_blank">${current.title}</a>`;
        document.querySelector('.greg-face')?.classList.add('playing');
    } else {
        currentSongDiv.innerHTML = "";
        document.querySelector('.greg-face')?.classList.remove('playing');
    }
}

const pauseResumeBtn = document.getElementById("pause-resume-btn");
let isPaused = false; // état local du player (a synchroniser si besoin avec le bot !)

pauseResumeBtn.addEventListener("click", function(e) {
    e.preventDefault();
    if (!currentGuildId) return alert("Choisis un serveur !");
    pauseResumeBtn.disabled = true;

    const action = isPaused ? "resume" : "pause";
    fetch(`/api/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            guild_id: currentGuildId,
            user_id: currentUserId
        })
    }).finally(() => setTimeout(() => { pauseResumeBtn.disabled = false; }, 500));

    // Switch local
    isPaused = !isPaused;
    updatePauseResumeBtn();
});

function updatePauseResumeBtn() {
    if (isPaused) {
        pauseResumeBtn.setAttribute("data-action", "resume");
        pauseResumeBtn.title = "Reprendre";
        pauseResumeBtn.innerHTML = "<span>▶️</span>";
    } else {
        pauseResumeBtn.setAttribute("data-action", "pause");
        pauseResumeBtn.title = "Pause";
        pauseResumeBtn.innerHTML = "<span>⏸️</span>";
    }
}



// == Socket.IO ==
const socket = io();
socket.on("playlist_update", function(data) {
    updatePlaylist(data.queue || []);
    updateCurrent(data.current);
    isPaused = !!data.is_paused; // <-- à condition que ton backend l'envoie !
    updatePauseResumeBtn();
});

// --- Contrôles AJAX musicaux, ergonomiques ---
document.querySelectorAll(".controls button").forEach(btn => {
    btn.addEventListener("click", function(e) {
        e.preventDefault();
        const action = this.dataset.action;
        if (!action) return;
        if (!currentGuildId) return alert("Choisis un serveur !");
        btn.disabled = true;
        fetch(`/api/${action}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                guild_id: currentGuildId,
                user_id: currentUserId
            })
        }).finally(() => setTimeout(() => { btn.disabled = false; }, 500));
    });
});
