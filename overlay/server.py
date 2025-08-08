# overlay/server.py
import os
import asyncio
import json
from aiohttp import web, WSMsgType

class OverlayServer:
    def __init__(self):
        self.clients = set()
        self.app = web.Application()
        self.app.add_routes([
            web.get("/", self.handle_overlay),
            web.get("/ws", self.handle_ws),
            web.static("/static", os.path.join(os.path.dirname(__file__), "static"))
        ])
        self.runner = None

    async def handle_overlay(self, request):
        """Retourne la page overlay HTML."""
        with open(os.path.join(os.path.dirname(__file__), "overlay.html"), "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")

    async def handle_ws(self, request):
        """WebSocket pour mise à jour en temps réel."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.clients.add(ws)
        print("[Overlay] Client connecté.")

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    # Ici, on pourrait intégrer l’appel direct aux commandes bot
                    print(f"[Overlay] Commande reçue : {data}")
                except Exception as e:
                    print(f"[Overlay] Erreur WS : {e}")
            elif msg.type == WSMsgType.ERROR:
                print(f"[Overlay] Erreur WS : {ws.exception()}")

        self.clients.remove(ws)
        print("[Overlay] Client déconnecté.")
        return ws

    async def broadcast(self, event, payload):
        """Envoie un message JSON à tous les clients."""
        data = json.dumps({"event": event, "data": payload})
        for ws in list(self.clients):
            await ws.send_str(data)

    async def start(self, host="0.0.0.0", port=8080):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        print(f"[Overlay] Serveur démarré sur http://{host}:{port}")
        await site.start()

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
