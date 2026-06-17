"""IT inbound — ClipRequestServer tests.

Structure
---------
Unit tests (no real network):
  - TestServerMessageHandler      — call _on_message() directly with mock socket
                                    covers: valid payload, malformed JSON,
                                    unknown type, missing fields
  - TestServerStatusBroadcast     — send_status_update() reaches all clients

Integration tests (loopback WS client):
  - TestClipRequestServerIntegration — real start() + connect from client
                                       verifies server saves request, sends ack,
                                       and emits requestReceived signal

Run with:  cd project && pytest tests/test_ws_inbound.py -v
"""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, call

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


def _make_server(tmp_path: Path, port: int = 0):
    from app.adapters.ws.request_server import ClipRequestServer
    from app.adapters.filesystem.request_adapter import JsonRequestAdapter

    adapter = JsonRequestAdapter(path=tmp_path)
    server = ClipRequestServer(port=port, request_adapter=adapter)
    return server, adapter


# ── Unit: _on_message handler ────────────────────────────────────────────────

class TestServerMessageHandler:
    def test_valid_clip_request_saves_to_adapter(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()
        req = _make_request()

        server._on_message(json.dumps({"type": "clip_request", "request": req.to_dict()}), mock_client)

        saved = adapter.load_all()
        assert len(saved) == 1
        assert saved[0].id == req.id

    def test_valid_clip_request_sends_ack(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)
        mock_client = MagicMock()
        req = _make_request()

        server._on_message(json.dumps({"type": "clip_request", "request": req.to_dict()}), mock_client)

        mock_client.sendTextMessage.assert_called_once()
        ack = json.loads(mock_client.sendTextMessage.call_args[0][0])
        assert ack["type"] == "ack"
        assert ack["id"] == req.id

    def test_valid_clip_request_emits_signal(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)
        mock_client = MagicMock()
        req = _make_request()

        received_ids: list[str] = []
        server.requestReceived.connect(received_ids.append)

        server._on_message(json.dumps({"type": "clip_request", "request": req.to_dict()}), mock_client)

        assert received_ids == [req.id]

    def test_malformed_json_no_crash_no_save(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        server._on_message("this is not valid json {{{", mock_client)

        assert adapter.load_all() == []
        mock_client.sendTextMessage.assert_not_called()

    def test_unknown_message_type_ignored(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        server._on_message(json.dumps({"type": "heartbeat", "ts": 1234}), mock_client)

        assert adapter.load_all() == []
        mock_client.sendTextMessage.assert_not_called()

    def test_missing_required_field_no_save(self, qt_app, tmp_path):
        """A clip_request payload missing 'operator' must not persist."""
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        bad_payload = {
            "type": "clip_request",
            "request": {
                "id": str(uuid.uuid4()),
                "created_at": "2026-06-17T10:00:00Z",
                # missing operator, start_time, end_time
            },
        }
        server._on_message(json.dumps(bad_payload), mock_client)

        assert adapter.load_all() == []

    def test_empty_request_dict_no_save(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        server._on_message(json.dumps({"type": "clip_request", "request": {}}), mock_client)

        assert adapter.load_all() == []

    def test_two_requests_both_saved(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        req1 = _make_request()
        req2 = _make_request()

        server._on_message(json.dumps({"type": "clip_request", "request": req1.to_dict()}), mock_client)
        server._on_message(json.dumps({"type": "clip_request", "request": req2.to_dict()}), mock_client)

        saved_ids = {r.id for r in adapter.load_all()}
        assert saved_ids == {req1.id, req2.id}

    def test_request_status_stored_as_pending(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        req = _make_request()
        server._on_message(json.dumps({"type": "clip_request", "request": req.to_dict()}), mock_client)

        saved = adapter.load_all()
        assert saved[0].status == "pending"

    def test_all_fields_persisted_correctly(self, qt_app, tmp_path):
        server, adapter = _make_server(tmp_path)
        mock_client = MagicMock()

        req = _make_request(
            operator="Operator-07",
            storage="StorageB",
            start_time="2026-06-17 08:00",
            end_time="2026-06-17 08:45",
            description="Revisión urgente",
        )
        server._on_message(json.dumps({"type": "clip_request", "request": req.to_dict()}), mock_client)

        saved = adapter.load_all()[0]
        assert saved.operator == "Operator-07"
        assert saved.storage == "StorageB"
        assert saved.start_time == "2026-06-17 08:00"
        assert saved.end_time == "2026-06-17 08:45"
        assert saved.description == "Revisión urgente"


# ── Unit: status broadcast ────────────────────────────────────────────────────

class TestServerStatusBroadcast:
    def test_broadcast_reaches_all_connected_clients(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)

        client_a = MagicMock()
        client_a.isValid.return_value = True
        client_b = MagicMock()
        client_b.isValid.return_value = True
        server._clients = [client_a, client_b]

        server.send_status_update("req-1", "processing")

        expected = json.dumps({"type": "status_update", "id": "req-1", "status": "processing"})
        client_a.sendTextMessage.assert_called_once_with(expected)
        client_b.sendTextMessage.assert_called_once_with(expected)

    def test_broadcast_skips_invalid_clients(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)

        valid_client = MagicMock()
        valid_client.isValid.return_value = True
        dead_client = MagicMock()
        dead_client.isValid.return_value = False
        server._clients = [valid_client, dead_client]

        server.send_status_update("req-2", "done")

        valid_client.sendTextMessage.assert_called_once()
        dead_client.sendTextMessage.assert_not_called()

    def test_broadcast_no_clients_no_crash(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)
        server._clients = []
        server.send_status_update("req-3", "done")  # must not raise

    def test_broadcast_removes_dead_clients_from_list(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)

        dead_client = MagicMock()
        dead_client.isValid.return_value = False
        server._clients = [dead_client]

        server.send_status_update("req-4", "done")

        assert server._clients == []

    def test_broadcast_message_format(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)

        msgs: list[str] = []
        client = MagicMock()
        client.isValid.return_value = True
        client.sendTextMessage.side_effect = msgs.append
        server._clients = [client]

        server.send_status_update("req-42", "declined")

        assert len(msgs) == 1
        data = json.loads(msgs[0])
        assert data["type"] == "status_update"
        assert data["id"] == "req-42"
        assert data["status"] == "declined"


# ── Unit: full status lifecycle ───────────────────────────────────────────────

class TestStatusLifecycle:
    """Verify all valid terminal statuses can be persisted and broadcast."""

    @pytest.mark.parametrize("final_status", ["processing", "done", "declined"])
    def test_update_status_persists(self, qt_app, tmp_path, final_status):
        from app.adapters.filesystem.request_adapter import JsonRequestAdapter

        adapter = JsonRequestAdapter(path=tmp_path)
        req = _make_request()
        adapter.save(req)

        adapter.update_status(req.id, final_status)

        updated = adapter.load_all()[0]
        assert updated.status == final_status

    def test_declined_broadcast_format(self, qt_app, tmp_path):
        server, _ = _make_server(tmp_path)

        msgs: list[str] = []
        client = MagicMock()
        client.isValid.return_value = True
        client.sendTextMessage.side_effect = msgs.append
        server._clients = [client]

        server.send_status_update("req-5", "declined")

        data = json.loads(msgs[0])
        assert data["status"] == "declined"


# ── Integration: full loopback ────────────────────────────────────────────────

class TestClipRequestServerIntegration:
    """Start the real server on port 0; connect a raw QWebSocket client;
    send a clip_request; verify save + ack + signal."""

    def test_server_receives_and_acks(self, qt_app, tmp_path):
        from PySide6.QtCore import QUrl
        from PySide6.QtNetwork import QHostAddress
        from PySide6.QtWebSockets import QWebSocket

        server, adapter = _make_server(tmp_path, port=0)
        ok = server.start()
        assert ok, "server failed to start"
        port = server._server.serverPort()

        req = _make_request()
        payload = json.dumps({"type": "clip_request", "request": req.to_dict()})

        acks: list[str] = []
        ws = QWebSocket()
        ws.textMessageReceived.connect(acks.append)
        ws.open(QUrl(f"ws://127.0.0.1:{port}"))

        connected = _wait_for(lambda: ws.isValid(), timeout_ms=2000)
        assert connected, "client did not connect within timeout"

        ws.sendTextMessage(payload)

        assert _wait_for(lambda: len(acks) > 0), "no ack received within timeout"

        ws.close()
        server.stop()

        # Ack content
        ack = json.loads(acks[0])
        assert ack["type"] == "ack"
        assert ack["id"] == req.id

        # Persisted
        saved = adapter.load_all()
        assert len(saved) == 1
        assert saved[0].id == req.id
        assert saved[0].status == "pending"

    def test_server_emits_requestReceived_signal(self, qt_app, tmp_path):
        from PySide6.QtCore import QUrl
        from PySide6.QtWebSockets import QWebSocket

        server, _ = _make_server(tmp_path, port=0)
        server.start()
        port = server._server.serverPort()

        received_ids: list[str] = []
        server.requestReceived.connect(received_ids.append)

        req = _make_request()
        ws = QWebSocket()
        ws.open(QUrl(f"ws://127.0.0.1:{port}"))

        _wait_for(lambda: ws.isValid())
        ws.sendTextMessage(json.dumps({"type": "clip_request", "request": req.to_dict()}))

        assert _wait_for(lambda: len(received_ids) > 0)

        ws.close()
        server.stop()

        assert received_ids == [req.id]

    def test_server_ignores_malformed_over_wire(self, qt_app, tmp_path):
        """Sending garbage over the wire must not crash the server."""
        from PySide6.QtCore import QUrl
        from PySide6.QtWebSockets import QWebSocket

        server, adapter = _make_server(tmp_path, port=0)
        server.start()
        port = server._server.serverPort()

        ws = QWebSocket()
        ws.open(QUrl(f"ws://127.0.0.1:{port}"))
        _wait_for(lambda: ws.isValid())

        ws.sendTextMessage("not json {{{{")
        # Give a brief window for the server to process the message
        _wait_for(lambda: False, timeout_ms=200)

        ws.close()
        server.stop()

        assert adapter.load_all() == []

    def test_full_round_trip_with_status_update(self, qt_app, tmp_path):
        """Client sends request → IT server saves it → broadcasts status update
        back to all connected Supervisor clients."""
        from PySide6.QtCore import QUrl
        from PySide6.QtWebSockets import QWebSocket

        server, adapter = _make_server(tmp_path, port=0)
        server.start()
        port = server._server.serverPort()

        supervisor_msgs: list[str] = []
        ws = QWebSocket()
        ws.textMessageReceived.connect(supervisor_msgs.append)
        ws.open(QUrl(f"ws://127.0.0.1:{port}"))
        _wait_for(lambda: ws.isValid())

        req = _make_request()
        ws.sendTextMessage(json.dumps({"type": "clip_request", "request": req.to_dict()}))

        # Wait for ack
        assert _wait_for(lambda: len(supervisor_msgs) > 0), "no ack from server"

        # IT now marks request as processing
        server.send_status_update(req.id, "processing")
        adapter.update_status(req.id, "processing")

        assert _wait_for(lambda: len(supervisor_msgs) >= 2), "no status update from server"

        # IT marks done
        server.send_status_update(req.id, "done")
        adapter.update_status(req.id, "done")

        assert _wait_for(lambda: len(supervisor_msgs) >= 3), "no 'done' update from server"

        ws.close()
        server.stop()

        # Check all messages in order: ack → processing → done
        ack = json.loads(supervisor_msgs[0])
        assert ack["type"] == "ack"

        processing_msg = json.loads(supervisor_msgs[1])
        assert processing_msg["type"] == "status_update"
        assert processing_msg["status"] == "processing"

        done_msg = json.loads(supervisor_msgs[2])
        assert done_msg["type"] == "status_update"
        assert done_msg["status"] == "done"

        # Final persisted status
        final = adapter.load_all()[0]
        assert final.status == "done"
