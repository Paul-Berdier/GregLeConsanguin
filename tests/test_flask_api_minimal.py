# tests/test_flask_api_minimal.py
import importlib
import requests

class Recorder:
    def __init__(self): self.calls=[]
    def post(self, url, json=None):
        self.calls.append(("POST", url, json))
        class R: status_code=204
        return R()

def test_play_route_emits_webhook(monkeypatch):
    m = importlib.import_module("main")
    rec = Recorder()
    monkeypatch.setattr(requests, "post", rec.post)  # <- patch global
    client = m.app.test_client()
    r = client.post("/play", data={"url":"https://youtu.be/xyz"})
    assert r.status_code in (301,302)
    assert rec.calls and rec.calls[0][2]["content"].startswith("/play ")

def test_controls_routes(monkeypatch):
    m = importlib.import_module("main")
    rec = Recorder()
    monkeypatch.setattr(requests, "post", rec.post)
    client = m.app.test_client()
    for path, cmd in [("/pause","/pause"), ("/skip","/skip"), ("/stop","/stop")]:
        r = client.post(path, data={})
        assert r.status_code in (301,302)
    assert {c[2]["content"] for c in rec.calls} >= {"/pause","/skip","/stop"}
