const input = document.getElementById("music-input");
const suggestions = document.getElementById("suggestions");
let debounce = null;

input.addEventListener("input", function () {
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

suggestions.addEventListener("click", function (e) {
    if (e.target.classList.contains("suggestion-item")) {
        input.value = e.target.getAttribute("data-title");
        suggestions.style.display = "none";
        suggestions.innerHTML = "";
    }
});

input.addEventListener("blur", function () {
    setTimeout(() => { suggestions.style.display = "none"; }, 200);
});
input.addEventListener("focus", function () {
    if (suggestions.innerHTML) suggestions.style.display = "block";
});

// Contrôles (Pause / Skip / Stop)
document.querySelectorAll(".controls button").forEach(btn => {
    btn.addEventListener("click", function (e) {
        e.preventDefault();
        const action = this.closest("form").action;
        fetch(action, { method: "POST" });
    });
});

// Playlist live avec Socket.IO
const socket = io();

function updatePlaylist(playlist, current) {
    const currentDiv = document.querySelector(".current-song");
    if (currentDiv) {
        if (current) {
            currentDiv.innerHTML = `<h2>🎧 En lecture :</h2>
                <p><a href="${current}" target="_blank" style="color:#ffe066;">${current}</a></p>`;
            document.querySelector('.greg-face').classList.add('playing');
        } else {
            currentDiv.innerHTML = "";
            document.querySelector('.greg-face').classList.remove('playing');
        }
    }

    const playlistDiv = document.querySelector(".playlist ul");
    if (playlistDiv) {
        playlistDiv.innerHTML = playlist.length
            ? playlist.map((song, i) =>
                `<li>${i + 1}. <a href="${song}" target="_blank">${song}</a></li>`
            ).join('')
            : `<p><em>La playlist est vide. Comme votre goût musical sans doute...</em></p>`;
    }
}

socket.on("playlist_update", function (data) {
    updatePlaylist(data.queue, data.current);
});

// Envoi du formulaire principal
document.getElementById("play-form").addEventListener("submit", function (e) {
    e.preventDefault();
    const val = input.value.trim();
    const button = document.getElementById("play-button");
    if (!val) return;

    button.disabled = true;
    button.innerText = "⏳ Greg s'exécute...";

    fetch("/api/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: val })
    }).then(() => {
        input.value = "";
        suggestions.style.display = "none";
        suggestions.innerHTML = "";
        setTimeout(() => {
            button.disabled = false;
            button.innerText = "🎵 JOUER";
        }, 1000);
    }).catch(() => {
        button.disabled = false;
        button.innerText = "🎵 JOUER";
    });
});
