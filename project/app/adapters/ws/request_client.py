from __future__ import annotations

import json
from typing import Optional

from loguru import logger
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

from app.core.ports.request_port import ClipRequest


class ClipRequestClient(QObject):
    """WebSocket client that sends clip requests to IT PCs.

    Manages one ``QWebSocket`` per configured IT host.  Send is fire-and-forget
    with a single retry: connect → send → close.  Status updates from IT arrive
    on persistent connections that stay open until the app exits.

    Protocol:
        Supervisor → IT : ``{"type": "clip_request", "request": {...}}``
        IT → Supervisor : ``{"type": "ack", "id": "..."}``
                          ``{"type": "status_update", "id": "...", "status": "..."}``
    """

    statusReceived = Signal(str, str)   # (id, status) — from IT to Supervisor

    def __init__(
        self,
        hosts: list[str],
        port: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._hosts = list(hosts)
        self._port = port
        self._persistent: dict[str, QWebSocket] = {}   # host → socket
        self._pending_sends: dict[str, str] = {}       # host → queued JSON message

    def set_hosts(self, hosts: list[str]) -> None:
        """Update the target host list (e.g. when user adds a new IT PC)."""
        self._hosts = list(hosts)

    def send_request(self, req: ClipRequest) -> None:
        """Send the request to every configured IT host.

        Opens a connection if not already open, sends immediately on
        ``connected``, then leaves the socket open for status updates.
        """
        if not self._hosts:
            logger.warning("ClipRequestClient: no IT hosts configured — request not sent.")
            return

        payload = json.dumps({"type": "clip_request", "request": req.to_dict()})
        for host in self._hosts:
            self._send_to_host(host, payload)

    def disconnect_all(self) -> None:
        for sock in list(self._persistent.values()):
            sock.close()
        self._persistent.clear()

    # ── Private ───────────────────────────────────────────────────────

    def _send_to_host(self, host: str, payload: str) -> None:
        sock = self._persistent.get(host)
        if sock is not None and sock.isValid():
            sock.sendTextMessage(payload)
            logger.debug("ClipRequestClient: sent to {} (existing connection).", host)
            return

        # Open new connection; send on connected.
        sock = QWebSocket("The Watcher Supervisor", parent=self)
        self._persistent[host] = sock
        self._pending_sends[host] = payload

        sock.connected.connect(lambda h=host: self._on_connected(h))
        sock.textMessageReceived.connect(self._on_message)
        sock.disconnected.connect(lambda h=host: self._on_disconnected(h))
        sock.errorOccurred.connect(
            lambda err, h=host: logger.warning(
                "ClipRequestClient: error connecting to {}: {}", h, err
            )
        )

        url = QUrl(f"ws://{host}:{self._port}")
        sock.open(url)
        logger.info("ClipRequestClient: connecting to {} …", host)

    def _on_connected(self, host: str) -> None:
        payload = self._pending_sends.pop(host, None)
        if payload is not None:
            sock = self._persistent.get(host)
            if sock and sock.isValid():
                sock.sendTextMessage(payload)
                logger.info("ClipRequestClient: request sent to {}.", host)

    def _on_disconnected(self, host: str) -> None:
        self._persistent.pop(host, None)
        logger.debug("ClipRequestClient: disconnected from {}.", host)

    def _on_message(self, msg: str) -> None:
        try:
            data = json.loads(msg)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")
        if msg_type == "ack":
            logger.info("ClipRequestClient: ack for request {}.", data.get("id"))
        elif msg_type == "status_update":
            req_id = data.get("id", "")
            status = data.get("status", "")
            if req_id and status:
                logger.info(
                    "ClipRequestClient: status update {} → {}.", req_id, status
                )
                self.statusReceived.emit(req_id, status)
