from __future__ import annotations

import json

from loguru import logger
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocket, QWebSocketServer

from app.core.ports.request_port import ClipRequest, RequestPort


class ClipRequestServer(QObject):
    """WebSocket server that receives clip requests from Supervisor PCs.

    Runs on the IT PC, bound to ``0.0.0.0:{port}``.  Lives in the Qt main
    thread — no extra thread needed.

    Protocol:
        Supervisor → IT : ``{"type": "clip_request", "request": {...}}``
        IT → Supervisor : ``{"type": "ack", "id": "..."}``
        IT → all clients: ``{"type": "status_update", "id": "...", "status": "..."}``
    """

    requestReceived = Signal(str)   # emits request id when a new request arrives

    def __init__(
        self,
        port: int,
        request_adapter: RequestPort,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._adapter = request_adapter
        self._port = port
        self._clients: list[QWebSocket] = []

        self._server = QWebSocketServer(
            "The Watcher IT",
            QWebSocketServer.SslMode.NonSecureMode,
            self,
        )

    def start(self) -> bool:
        ok = self._server.listen(QHostAddress.SpecialAddress.AnyIPv4, self._port)
        if ok:
            self._server.newConnection.connect(self._on_new_connection)
            logger.info("ClipRequestServer listening on port {}.", self._port)
        else:
            logger.error(
                "ClipRequestServer failed to bind on port {}: {}",
                self._port,
                self._server.errorString(),
            )
        return ok

    def stop(self) -> None:
        for client in list(self._clients):
            client.close()
        self._server.close()
        logger.info("ClipRequestServer stopped.")

    def send_status_update(self, req_id: str, status: str) -> None:
        """Broadcast a status update to all connected Supervisor clients."""
        msg = json.dumps({"type": "status_update", "id": req_id, "status": status})
        dead: list[QWebSocket] = []
        for client in self._clients:
            if client.isValid():
                client.sendTextMessage(msg)
            else:
                dead.append(client)
        for c in dead:
            self._clients.remove(c)

    # ── Private ───────────────────────────────────────────────────────

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            client: QWebSocket = self._server.nextPendingConnection()
            self._clients.append(client)
            client.textMessageReceived.connect(
                lambda msg, c=client: self._on_message(msg, c)
            )
            client.disconnected.connect(lambda c=client: self._on_disconnected(c))
            logger.info(
                "IT server: client connected from {}.",
                client.peerAddress().toString(),
            )

    def _on_disconnected(self, client: QWebSocket) -> None:
        if client in self._clients:
            self._clients.remove(client)
        logger.info("IT server: client disconnected.")

    def _on_message(self, msg: str, client: QWebSocket) -> None:
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            logger.warning("IT server: received invalid JSON — ignored.")
            return

        msg_type = data.get("type")

        if msg_type == "clip_request":
            raw = data.get("request", {})
            try:
                req = ClipRequest.from_dict(raw)
            except (KeyError, TypeError):
                logger.warning("IT server: malformed clip_request payload — ignored.")
                return

            self._adapter.save(req)
            logger.info(
                "IT server: request {} received — {} / {}",
                req.id, req.operator, req.start_time,
            )

            ack = json.dumps({"type": "ack", "id": req.id})
            client.sendTextMessage(ack)

            self.requestReceived.emit(req.id)
        else:
            logger.debug("IT server: unhandled message type '{}'.", msg_type)
