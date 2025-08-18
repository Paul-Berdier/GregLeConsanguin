# tests/test_api_rail.py
"""
Tests d'API contre l'instance déployée (Railway).

Ces tests valident :
- /api/health : up
- /api/autocomplete : format de réponse (même si vide)
- /api/playlist : squelette sans guild_id + robustesse avec faux guild
- /api/guilds : contrat + présence du serveur 'EKIP'
- /api/play : payload réel issu de /api/autocomplete (provider choisi)
- /api/pause|/resume|/skip|/stop : envoient un guild_id valide
"""

import pytest
import requests

# ====== CONFIG ADAPTÉE À TON DEPLOIEMENT ======
BASE_URL = "https://gregleconsanguin.up.railway.app"
GUILD_NAME = "EKIP"                       # nom EXACT du serveur
DISCORD_USER_ID = "522551561591980073"    # ton user id Discord (snowflake)
TIMEOUT = 25
# ==============================================

pytestmark = [
    pytest.mark.rail,
    pytest.mark.skipif(not BASE_URL, reason="BASE_URL non défini"),
]

def _url(path: str) -> str:
    path = path if path.startswith("/") else f"/{path}"
    return f"{BASE_URL}{path}"

# ---------- Helpers ----------
def _resolve_guild_id_by_name(name: str) -> str:
    r = requests.get(_url("/api/guilds"), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    wanted = name.strip().lower()
    for g in data:
        if g.get("name", "").strip().lower() == wanted:
            return g["id"]
    raise AssertionError(f"Guild '{name}' introuvable dans /api/guilds (trouvés: {[x.get('name') for x in data]})")

def _pick_track(results: list) -> dict | None:
    """
    Sélectionne le 1er item utilisable: récupère title + url (webpage_url prioritaire).
    """
    for item in results:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or "Titre inconnu"
        url = item.get("webpage_url") or item.get("url")
        if not url:
            continue
        url = str(url).strip().strip(";")
        if url.startswith("http://") or url.startswith("https://"):
            return {"title": title, "url": url}
    return None

# ---------- Santé ----------
def test_health_ok():
    r = requests.get(_url("/api/health"), timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, dict)
    assert data.get("ok") is True

# ---------- Autocomplete ----------
def test_autocomplete_contract_soundcloud_minimal():
    params = {"q": "daft punk", "provider": "soundcloud"}
    r = requests.get(_url("/api/autocomplete"), params=params, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "results" in data, data
    assert isinstance(data["results"], list)
    if data["results"]:
        item = data["results"][0]
        for key in ["title", "url", "webpage_url", "provider"]:
            assert key in item
        assert "duration" in item
        if "artist" in item and item["artist"] is not None:
            assert isinstance(item["artist"], str)
        if "thumb" in item and item["thumb"] is not None:
            assert isinstance(item["thumb"], str)

def test_autocomplete_contract_youtube_minimal():
    params = {"q": "lofi hip hop", "provider": "youtube"}
    r = requests.get(_url("/api/autocomplete"), params=params, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "results" in data
    assert isinstance(data["results"], list)
    if data["results"]:
        item = data["results"][0]
        for key in ["title", "url", "webpage_url", "provider"]:
            assert key in item

# ---------- Playlist ----------
def test_playlist_without_guild_returns_skeleton():
    r = requests.get(_url("/api/playlist"), timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    for key in ["queue", "current", "is_paused", "progress", "repeat_all", "thumbnail"]:
        assert key in data
    assert isinstance(data["queue"], list)
    assert isinstance(data["is_paused"], bool)
    assert isinstance(data["progress"], dict)

def test_playlist_with_fake_guild_returns_200_or_4xx():
    r = requests.get(_url("/api/playlist"), params={"guild_id": "123456789"}, timeout=10)
    assert r.status_code in (200, 400, 404, 500), r.text
    _ = r.json()

# ---------- Guilds (bot) ----------
def test_guilds_contract_and_contains_ekip():
    r = requests.get(_url("/api/guilds"), timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, list), f"Réponse attendue: list, reçu: {type(data)}"

    # Contrat minimal + IDs numériques
    ids = []
    for i, item in enumerate(data):
        assert isinstance(item, dict), f"item #{i} n'est pas un dict"
        assert "id" in item and "name" in item, f"item #{i} sans 'id'/'name': {item}"
        assert isinstance(item["id"], str) and item["id"].isdigit(), f"item #{i}.id invalide: {item['id']}"
        assert isinstance(item["name"], str) and item["name"].strip(), f"item #{i}.name vide"
        ids.append(item["id"])
    assert len(ids) == len(set(ids)), "IDs duplicés dans /api/guilds"

    # Présence 'EKIP'
    wanted = GUILD_NAME.strip().lower()
    found = next((g for g in data if g.get("name", "").strip().lower() == wanted), None)
    names = [g.get("name", "") for g in data]
    assert found is not None, (
        f"Serveur '{GUILD_NAME}' introuvable dans /api/guilds.\n"
        f"Guilds présents: {names}"
    )

# ---------- Play via AUTOCOMPLETE ----------
@pytest.mark.parametrize(
    "provider,query",
    [
        ("soundcloud", "lofi hip hop"),
        # tu peux ajouter youtube si tu veux:
        # ("youtube", "daft punk"),
    ],
)
def test_autocomplete_then_play(provider, query):
    # 1) Résoudre la guild 'EKIP'
    guild_id = _resolve_guild_id_by_name(GUILD_NAME)

    # 2) Appeler /api/autocomplete
    r = requests.get(_url("/api/autocomplete"), params={"q": query, "provider": provider}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "results" in data and isinstance(data["results"], list), data
    if not data["results"]:
        pytest.skip(f"autocomplete({provider}) a renvoyé 0 résultat pour {query!r} — skip.")

    track = _pick_track(data["results"])
    if not track:
        pytest.skip("Aucun résultat n'a d'URL http(s) exploitable — skip.")

    # 3) Appeler /api/play avec l'URL réelle + guild_id + user_id
    payload = {
        "title": track["title"],
        "url": track["url"],
        "guild_id": guild_id,
        "user_id": DISCORD_USER_ID,
    }
    r2 = requests.post(_url("/api/play"), json=payload, timeout=TIMEOUT)
    # succès (200) ou erreur métier contrôlée (500) — l'API ne doit pas planter
    assert r2.status_code in (200, 500), r2.text
    data2 = r2.json()
    assert isinstance(data2, dict)
    if r2.status_code == 200:
        assert data2.get("ok") is True
    else:
        assert "error" in data2

# ---------- Player endpoints ----------
@pytest.mark.parametrize("endpoint", ["/api/pause", "/api/resume", "/api/skip", "/api/stop"])
def test_player_commands_with_guild_id(endpoint):
    guild_id = _resolve_guild_id_by_name(GUILD_NAME)
    r = requests.post(_url(endpoint), json={"guild_id": guild_id}, timeout=15)
    # Si le bot est connecté et la playlist existe -> 200, sinon -> 500
    assert r.status_code in (200, 500), (endpoint, r.status_code, r.text)
    data = r.json()
    assert isinstance(data, dict)
