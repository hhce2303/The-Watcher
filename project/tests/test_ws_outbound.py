"""Supervisor outbound — ClipRequestClient tests.

Structure
---------
Unit tests (no real network):
  - TestClipRequestClientConfig   — host list management, initial state
  - TestOutboundMessageFormat     — JSON payload shape, no Qt event loop needed
                                    (calls internal helpers via direct mock socket)

Integration tests (loopback WS server):
  - TestClipRequestClientIntegration  — real QWebSocketServer on 127.0.0.1:0
                                        verifies the client actually sends the
                                        correct wire message and the server receives it

Run with:  cd project && pytest tests/test_ws_outbound.py -v
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.ports.request_port import ClipRequest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_request(**kw) -> ClipRequest:
    defaults = dict(
        id=str(uuid.uuid4()),
        created_at="2026-06-17T10:00:00Z",
        supervisor_host="PC-SUP-01",
        operator="Operator-28",
        storage="Storage1",
        start_time="2026-06-17 09:00",
        end_time="2026-06-17 09:30",
        description="Incidente de prueba",
    )
    defaults.update(kw)
    return ClipRequest(**defaults)


def _wait_for(predicate, timeout_ms: int = 2000) -> bool:
    """Process Qt events until predicate() is True or timeout elapses."""
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(20)

    def _check():
        if predicate():
            loop.quit()

    poll.timeout.connect(_check)

    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    deadline.start(timeout_ms)

    poll.start()
    loop.exec()
    poll.stop()
    deadline.stop()

    return predicate()


# ── Unit: host list management ────────────────────────────────────────────────

class TestClipRequestClientConfig:
    def test_initial_hosts_stored(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient(["192.168.1.10", "192.168.1.11"], 9090)
        assert client._hosts == ["192.168.1.10", "192.168.1.11"]

    def test_set_hosts_replaces_list(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient(["old-host"], 9090)
        client.set_hosts(["new-host-a", "new-host-b"])
        assert client._hosts == ["new-host-a", "new-host-b"]

    def test_set_hosts_empty_list(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient(["h1"], 9090)
        client.set_hosts([])
        assert client._hosts == []

    def test_set_hosts_deduplication_not_enforced(self, qt_app):
        """set_hosts stores whatever is given — dedup is caller's responsibility."""
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        client.set_hosts(["h1", "h1"])
        assert len(client._hosts) == 2  # stored as-is

    def test_disconnect_all_clears_persistent(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        # Seed a fake persistent socket
        mock_sock = MagicMock()
        mock_sock.isValid.return_value = True
        client._persistent["fake-host"] = mock_sock

        client.disconnect_all()

        mock_sock.close.assert_called_once()
        assert client._persistent == {}


# ── Unit: message format (via payload inspection) ────────────────────────────

class TestOutboundMessageFormat:
    """Verify JSON shape without hitting the network.

    Strategy: patch QWebSocket so _send_to_host() believes the socket is
    connected; then capture the text sent via sendTextMessage().
    """

    def test_clip_request_payload_structure(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        sent_msgs: list[str] = []

        mock_sock = MagicMock()
        mock_sock.isValid.return_value = True
        mock_sock.sendTextMessage.side_effect = lambda m: sent_msgs.append(m)

        client = ClipRequestClient(["127.0.0.1"], 9090)
        client._persistent["127.0.0.1"] = mock_sock

        req = _make_request()
        client.send_request(req)

        assert len(sent_msgs) == 1
        data = json.loads(sent_msgs[0])
        assert data["type"] == "clip_request"
        assert "request" in data

    def test_payload_contains_all_required_fields(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        sent_msgs: list[str] = []
        mock_sock = MagicMock()
        mock_sock.isValid.return_value = True
        mock_sock.sendTextMessage.side_effect = lambda m: sent_msgs.append(m)

        client = ClipRequestClient(["127.0.0.1"], 9090)
        client._persistent["127.0.0.1"] = mock_sock

        req = _make_request()
        client.send_request(req)

        payload = json.loads(sent_msgs[0])["request"]
        for field in ("id", "created_at", "supervisor_host", "operator",
                      "storage", "start_time", "end_time", "description", "status"):
            assert field in payload, f"missing field: {field}"

    def test_payload_status_is_pending(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        sent_msgs: list[str] = []
        mock_sock = MagicMock()
        mock_sock.isValid.return_value = True
        mock_sock.sendTextMessage.side_effect = lambda m: sent_msgs.append(m)

        client = ClipRequestClient(["127.0.0.1"], 9090)
        client._persistent["127.0.0.1"] = mock_sock

        req = _make_request()
        client.send_request(req)

        payload = json.loads(sent_msgs[0])["request"]
        assert payload["status"] == "pending"

    def test_payload_id_matches_request(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        sent_msgs: list[str] = []
        mock_sock = MagicMock()
        mock_sock.isValid.return_value = True
        mock_sock.sendTextMessage.side_effect = lambda m: sent_msgs.append(m)

        req = _make_request(id="fixed-id-123")
        client = ClipRequestClient(["127.0.0.1"], 9090)
        client._persistent["127.0.0.1"] = mock_sock
        client.send_request(req)

        payload = json.loads(sent_msgs[0])["request"]
        assert payload["id"] == "fixed-id-123"

    def test_no_hosts_no_send(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        req = _make_request()
        # Must not raise, must not send anything
        client.send_request(req)
        assert client._persistent == {}

    def test_sends_to_multiple_hosts(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        msgs_by_host: dict[str, list[str]] = {}

        def make_mock(host: str):
            m = MagicMock()
            m.isValid.return_value = True
            msgs_by_host[host] = []
            m.sendTextMessage.side_effect = msgs_by_host[host].append
            return m

        client = ClipRequestClient(["host-a", "host-b"], 9090)
        client._persistent["host-a"] = make_mock("host-a")
        client._persistent["host-b"] = make_mock("host-b")

        req = _make_request()
        client.send_request(req)

        assert len(msgs_by_host["host-a"]) == 1
        assert len(msgs_by_host["host-b"]) == 1
        # Both hosts receive the same request id
        id_a = json.loads(msgs_by_host["host-a"][0])["request"]["id"]
        id_b = json.loads(msgs_by_host["host-b"][0])["request"]["id"]
        assert id_a == id_b == req.id


# ── Unit: status updates received from IT ────────────────────────────────────

class TestIncomingStatusUpdates:
    def test_ack_message_logged_silently(self, qt_app):
        """ack messages must not emit statusReceived."""
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        emitted: list[tuple] = []
        client.statusReceived.connect(lambda i, s: emitted.append((i, s)))

        client._on_message(json.dumps({"type": "ack", "id": "some-id"}))

        assert emitted == []

    def test_status_update_emits_signal(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        emitted: list[tuple] = []
        client.statusReceived.connect(lambda i, s: emitted.append((i, s)))

        client._on_message(json.dumps({"type": "status_update", "id": "req-1", "status": "processing"}))

        assert emitted == [("req-1", "processing")]

    def test_status_update_done(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        emitted: list[tuple] = []
        client.statusReceived.connect(lambda i, s: emitted.append((i, s)))

        client._on_message(json.dumps({"type": "status_update", "id": "req-2", "status": "done"}))

        assert emitted == [("req-2", "done")]

    def test_status_update_declined(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        emitted: list[tuple] = []
        client.statusReceived.connect(lambda i, s: emitted.append((i, s)))

        client._on_message(json.dumps({"type": "status_update", "id": "req-3", "status": "declined"}))

        assert emitted == [("req-3", "declined")]

    def test_malformed_json_does_not_raise(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        client._on_message("this is not json {{{")  # must not raise

    def test_unknown_message_type_ignored(self, qt_app):
        from app.adapters.ws.request_client import ClipRequestClient

        client = ClipRequestClient([], 9090)
        emitted: list[tuple] = []
        client.statusReceived.connect(lambda i, s: emitted.append((i, s)))

        client._on_message(json.dumps({"type": "unknown_type", "data": "x"}))

        assert emitted == []


# ── Integration: full loopback over 127.0.0.1 ────────────────────────────────

class TestClipRequestClientIntegration:
    """Start a bare QWebSocketServer on 127.0.0.1:0, have the client connect,
    and verify the wire message arrives intact."""

    def test_send_request_reaches_server(self, qt_app, tmp_path):
        from PySide6.QtNetwork import QHostAddress
        from PySide6.QtWebSockets import QWebSocketServer

        received: list[str] = []
        srv_clients: list = []

        srv = QWebSocketServer("test-echo", QWebSocketServer.SslMode.NonSecureMode)

        def _on_conn():
            while srv.hasPendingConnections():
                sock = srv.nextPendingConnection()
                srv_clients.append(sock)
                sock.textMessageReceived.connect(received.append)

        srv.newConnection.connect(_on_conn)
        ok = srv.listen(QHostAddress.SpecialAddress.LocalHost, 0)
        assert ok, "loopback server failed to listen"
        port = srv.serverPort()

        from app.adapters.ws.request_client import ClipRequestClient

        req = _make_request()
        client = ClipRequestClient(["127.0.0.1"], port)
        client.send_request(req)

        assert _wait_for(lambda: len(received) > 0), "server did not receive message within timeout"

        client.disconnect_all()
        srv.close()

        data = json.loads(received[0])
        assert data["type"] == "clip_request"
        assert data["request"]["id"] == req.id
        assert data["request"]["operator"] == req.operator
        assert data["request"]["supervisor_host"] == req.supervisor_host

    def test_sends_to_two_hosts(self, qt_app):
        """When two hosts are configured, the server on each should receive the request."""
        from PySide6.QtNetwork import QHostAddress
        from PySide6.QtWebSockets import QWebSocketServer

        received_a: list[str] = []
        received_b: list[str] = []

        def make_server(container: list[str]):
            s = QWebSocketServer("echo", QWebSocketServer.SslMode.NonSecureMode)
            clients: list = []

            def _conn():
                while s.hasPendingConnections():
                    sock = s.nextPendingConnection()
                    clients.append(sock)
                    sock.textMessageReceived.connect(container.append)

            s.newConnection.connect(_conn)
            s.listen(QHostAddress.SpecialAddress.LocalHost, 0)
            return s

        srv_a = make_server(received_a)
        srv_b = make_server(received_b)
        port_a, port_b = srv_a.serverPort(), srv_b.serverPort()

        from app.adapters.ws.request_client import ClipRequestClient

        # Two separate loopback addresses via different ports
        client_a = ClipRequestClient(["127.0.0.1"], port_a)
        client_b = ClipRequestClient(["127.0.0.1"], port_b)

        req = _make_request()
        client_a.send_request(req)
        client_b.send_request(req)

        assert _wait_for(lambda: len(received_a) > 0 and len(received_b) > 0)

        client_a.disconnect_all()
        client_b.disconnect_all()
        srv_a.close()
        srv_b.close()

        assert json.loads(received_a[0])["request"]["id"] == req.id
        assert json.loads(received_b[0])["request"]["id"] == req.id
