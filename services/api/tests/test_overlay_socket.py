"""Socket.IO à jeton porteur (spec 2026-11-25 §3.5) : `auth.token` du paquet CONNECT, refus NOT_AUTHENTICATED ou
STORAGE_UNAVAILABLE, revérification du jeton à l'abonnement, et révocation qui déconnecte les sockets du jeton."""
from __future__ import annotations

import threading

import api.services.overlay_tokens as ot
import pytest
import redis
from api import socketio
from api.services.redis_listener import CHANNEL_BOT_STATUS, _handle_message
from api.websocket import events
from flask_socketio import ConnectionRefusedError
from overlay_fakes import overlay_redis, issue_token  # noqa: F401
from test_socketio import FakeBot, fake_bot, _events  # noqa: F401


def sock(app, tok, flask_client=None):
    return socketio.test_client(app, auth={"token": tok}, flask_test_client=flask_client)


def test_valid_token_connects_and_joins_its_guild(app, fake_bot, issue_token):
    c = sock(app, issue_token(uid=4242)); assert c.is_connected(); c.get_received()
    c.emit("join_guild", {"guild_id": "42"}); got = c.get_received()
    assert _events(got, "joined") and _events(got, "playlist_update")
    assert fake_bot.calls[-1]["user_id"] == 4242


def test_invalid_token_is_refused_even_with_a_cookie(app, login, overlay_redis):
    assert not sock(app, "greg_ow_nope").is_connected()
    assert not sock(app, "greg_ow_nope", login(app.test_client())).is_connected()
    assert not socketio.test_client(app, auth={"token": 5}).is_connected()


def test_refusal_message_is_not_authenticated(app, overlay_redis):
    with app.test_request_context("/"), pytest.raises(ConnectionRefusedError) as e:
        events.on_connect({"token": "greg_ow_nope"})
    assert e.value.error_args == {"message": "NOT_AUTHENTICATED"}


def test_redis_down_at_connect_is_storage_unavailable(app, overlay_redis, issue_token):   # Review Focus 1
    tok = issue_token(); overlay_redis.fail = redis.ConnectionError("down")
    with app.test_request_context("/"), pytest.raises(ConnectionRefusedError) as e:
        events.on_connect({"token": tok})
    assert e.value.error_args == {"message": "STORAGE_UNAVAILABLE"}


def test_token_socket_receives_bot_status(app, issue_token):
    c = sock(app, issue_token()); c.get_received()
    _handle_message(socketio, CHANNEL_BOT_STATUS, {"status": "ready", "guilds": []})
    assert _events(c.get_received(), "bot_status")


def test_revocation_disconnects_exactly_that_tokens_sockets(app, client, issue_token):
    a, b = issue_token(), issue_token()
    a1, a2, b1 = sock(app, a), sock(app, a), sock(app, b)
    r = client.post("/api/v1/overlay/tokens/revoke", json={"id": ot.resolve(a).tid}, headers={"Authorization": f"Bearer {a}"})
    assert r.status_code == 200
    assert (a1.is_connected(), a2.is_connected(), b1.is_connected()) == (False, False, True)


def test_logout_disconnects(app, client, issue_token):
    t = issue_token(); c = sock(app, t)
    client.post("/api/v1/overlay/logout", json={}, headers={"Authorization": f"Bearer {t}"})
    assert not c.is_connected()


def test_revoked_token_cannot_join_on_an_open_socket(app, fake_bot, issue_token):
    t = issue_token(); c = sock(app, t); c.get_received(); rec = ot.resolve(t)
    ot.revoke(rec.uid, rec.tid)                                    # sans déconnexion : la revérification joue
    c.emit("join_guild", {"guild_id": "42"}); got = c.get_received()
    assert not _events(got, "playlist_update") and fake_bot.calls == []
    assert _events(got, "guild_join_error")[0]["args"][0]["error"] == "NOT_AUTHENTICATED"


def test_redis_down_on_join_is_redis_unavailable_never_not_authenticated(app, fake_bot, overlay_redis, issue_token,
                                                                        monkeypatch):   # Review Focus 1
    c = sock(app, issue_token()); c.get_received()
    joined = []; monkeypatch.setattr(events, "join_room", lambda room, *a, **k: joined.append(room))
    overlay_redis.fail = redis.ConnectionError("down")             # l'appli effacerait son jeton sur NOT_AUTHENTICATED
    c.emit("join_guild", {"guild_id": "42"}); got = c.get_received()
    [err] = [e["args"][0] for e in _events(got, "guild_join_error")]
    assert (err["error"], err["retry"]) == ("REDIS_UNAVAILABLE", True) and err["guild_id"] == "42"
    assert joined == [] and fake_bot.calls == [] and not _events(got, "playlist_update") and not _events(got, "joined")
    assert c.is_connected()


def test_disconnect_forgets_the_sid(app, issue_token):
    t = issue_token(); tid = ot.resolve(t).tid; c = sock(app, t)
    assert events._TOKEN_SIDS.get(tid); c.disconnect()
    assert not events._TOKEN_SIDS.get(tid) and tid not in events._SID_TOKEN.values()   # le registre est partagé entre tests


def test_disconnect_token_disconnects_outside_the_lock(app, issue_token):
    t = issue_token(); tid = ot.resolve(t).tid; c1, c2 = sock(app, t), sock(app, t)
    out = []; th = threading.Thread(target=lambda: out.append(events.disconnect_token(tid)), daemon=True)
    th.start(); th.join(5)
    assert not th.is_alive() and out == [2]          # on_disconnect → forget_sid sur ce même fil : pas d'interblocage
    assert (c1.is_connected(), c2.is_connected()) == (False, False)
    assert tid not in events._TOKEN_SIDS and tid not in events._SID_TOKEN.values()
    events.forget_sid("sid-inconnu")                 # entrée absente : sans erreur
    assert events.disconnect_token(tid) == 0


def test_auth_without_token_keeps_the_cookie_path(app, login, fake_bot, session_uid):
    c = socketio.test_client(app, auth={}, flask_test_client=login(app.test_client())); c.get_received()
    c.emit("join_guild", {"guild_id": "42"})
    assert _events(c.get_received(), "joined") and fake_bot.calls[-1]["user_id"] == session_uid
