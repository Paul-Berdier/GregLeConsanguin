# tests/test_soundcloud_integration.py
import os
import pytest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "extractors" / "soundcloud.py"
spec = importlib.util.spec_from_file_location("soundcloud", str(MODULE_PATH))
soundcloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soundcloud)


@pytest.mark.skipif(
    not os.getenv("SOUNDCLOUD_CLIENT_ID"),
    reason="Pas de SOUNDCLOUD_CLIENT_ID -> on skip l'intégration."
)
def test_resolve_and_pick_progressive_real_world():
    # 👉 Remplace par une vraie URL publique SoundCloud que tu connais
    url = "https://soundcloud.com/officialdjpanda/panda-mix"
    cids = soundcloud._sc_client_ids()
    assert cids, "SOUNDCLOUD_CLIENT_ID doit être défini"

    tr = soundcloud._sc_resolve_track(url, cids[0])
    assert tr and tr.get("title"), "resolve doit retourner un dict de track"

    stream_url, title, duration = soundcloud._sc_pick_progressive_stream(tr, cids[0])
    assert stream_url and stream_url.startswith("http"), "Doit retourner une URL de stream signée"
    assert isinstance(title, str)
    assert (duration is None) or isinstance(duration, int)
