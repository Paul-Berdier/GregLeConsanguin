// === Submit avec désactivation temporaire et effacement ===
document.getElementById("play-form").addEventListener("submit", function(e) {
    e.preventDefault();
    const val = input.value.trim();
    const button = document.getElementById("play-button");
    if (!val) return;

    button.disabled = true;
    button.innerText = "⏳ Greg s'exécute...";

    fetch("/api/play", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url: val})
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
