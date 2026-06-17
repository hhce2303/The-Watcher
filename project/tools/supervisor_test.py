"""
supervisor_test.py — The Watcher · Supervisor Request Simulator

Simulates a Supervisor PC sending a clip request to an IT PC over WebSocket.
Use this to verify network connectivity and end-to-end message flow before
deploying the full application.

Usage:
    python supervisor_test.py 192.168.101.164
    python supervisor_test.py 192.168.101.164 --port 9090
    python supervisor_test.py 192.168.101.164 --operator Operator-15 --wait 30

Build standalone .exe:
    pip install pyinstaller websockets
    pyinstaller --onefile --console --name supervisor_test supervisor_test.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone, timedelta

# ── Terminal colors (pure ANSI — no extra deps) ────────────────────────────

_IS_WIN = sys.platform == "win32"

if _IS_WIN:
    import ctypes
    import io
    # Enable ANSI escape codes on Windows 10+
    ctypes.windll.kernel32.SetConsoleMode(
        ctypes.windll.kernel32.GetStdHandle(-11), 7
    )
    # Force UTF-8 output so box/check characters render correctly
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

GREEN   = "\033[92m"
RED     = "\033[91m"
YELLOW  = "\033[93m"
CYAN    = "\033[96m"
WHITE   = "\033[97m"
DIM     = "\033[2m"
BOLD    = "\033[1m"
RESET   = "\033[0m"


def _ok(msg: str)    -> None: print(f"  {GREEN}✔{RESET}  {msg}")
def _err(msg: str)   -> None: print(f"  {RED}✗{RESET}  {msg}")
def _info(msg: str)  -> None: print(f"  {CYAN}→{RESET}  {msg}")
def _warn(msg: str)  -> None: print(f"  {YELLOW}!{RESET}  {msg}")
def _dim(msg: str)   -> None: print(f"     {DIM}{msg}{RESET}")
def _sep()           -> None: print(f"  {DIM}{'─' * 52}{RESET}")


def _banner() -> None:
    print()
    print(f"  {BOLD}{WHITE}THE WATCHER  ·  Supervisor Request Simulator{RESET}")
    _sep()


def _build_request(operator: str, storage: str) -> dict:
    now     = datetime.now(timezone.utc)
    start   = now - timedelta(hours=1)
    end     = now - timedelta(minutes=30)

    return {
        "id":              str(uuid.uuid4()),
        "created_at":      now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "supervisor_host": "SUPERVISOR-TEST",
        "operator":        operator,
        "storage":         storage,
        "start_time":      start.strftime("%Y-%m-%d %H:%M"),
        "end_time":        end.strftime("%Y-%m-%d %H:%M"),
        "description":     "Test de conectividad — simulador Supervisor",
        "status":          "pending",
    }


async def run(host: str, port: int, operator: str, storage: str, wait_seconds: int) -> int:
    """Returns 0 on success, 1 on failure."""

    try:
        import websockets  # noqa: PLC0415
    except ImportError:
        _err("websockets no está instalado.")
        _dim("Ejecuta:  pip install websockets")
        return 1

    url = f"ws://{host}:{port}"
    req = _build_request(operator, storage)

    print()
    _info(f"Host IT   : {BOLD}{host}{RESET}")
    _info(f"Puerto    : {port}")
    _info(f"Operador  : {operator}  ({storage})")
    _sep()

    # ── Conexión ──────────────────────────────────────────────────────────
    _info(f"Conectando a {url} ...")
    try:
        ws = await asyncio.wait_for(
            websockets.connect(url, open_timeout=5),
            timeout=6,
        )
    except (ConnectionRefusedError, OSError) as exc:
        _err(f"Conexión rechazada — {exc}")
        _dim("Verifica que la app esté corriendo en el PC IT y que el puerto esté abierto en el firewall.")
        return 1
    except asyncio.TimeoutError:
        _err("Timeout al conectar (6s)")
        _dim("El host no respondió. Comprueba la IP y que el puerto 9090 esté accesible.")
        return 1
    except Exception as exc:
        _err(f"Error inesperado al conectar: {exc}")
        return 1

    _ok("Conectado")

    try:
        # ── Envío ─────────────────────────────────────────────────────────
        payload = json.dumps({"type": "clip_request", "request": req})
        _info("Enviando solicitud de clip ...")
        _dim(f"ID          : {req['id']}")
        _dim(f"Operador    : {req['operator']}")
        _dim(f"Almacén     : {req['storage']}")
        _dim(f"Inicio      : {req['start_time']}")
        _dim(f"Fin         : {req['end_time']}")
        _dim(f"Descripción : {req['description']}")

        await ws.send(payload)

        # ── Esperar ACK ───────────────────────────────────────────────────
        _sep()
        _info("Esperando ACK del servidor IT ...")
        try:
            raw_ack = await asyncio.wait_for(ws.recv(), timeout=8)
        except asyncio.TimeoutError:
            _err("Timeout esperando ACK (8s) — el servidor recibió el mensaje pero no respondió.")
            return 1

        try:
            ack = json.loads(raw_ack)
        except json.JSONDecodeError:
            _err(f"ACK no es JSON válido: {raw_ack!r}")
            return 1

        if ack.get("type") != "ack":
            _err(f"Respuesta inesperada (esperado 'ack'): {ack}")
            return 1

        if ack.get("id") != req["id"]:
            _warn(f"ACK con ID diferente: {ack.get('id')!r}  (esperado: {req['id']!r})")
        else:
            _ok(f"ACK recibido  (ID: {ack['id'][:8]}...)")

        # ── Esperar actualizaciones de estado ─────────────────────────────
        if wait_seconds > 0:
            _sep()
            _info(f"Esperando actualizaciones de estado ({wait_seconds}s) ...")
            _dim("Acepta o declina la solicitud en el PC IT para ver la actualización aquí.")

            deadline = asyncio.get_event_loop().time() + wait_seconds
            received_updates: list[str] = []

            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 1.0))
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if msg.get("type") == "status_update":
                        status = msg.get("status", "?")
                        received_updates.append(status)
                        if status in ("done", "declined"):
                            _ok(f"Estado final recibido: {BOLD}{status.upper()}{RESET}")
                            break
                        else:
                            _info(f"Estado actualizado: {BOLD}{status}{RESET}")
                    else:
                        _dim(f"Mensaje: {msg.get('type','?')}")

                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    _warn("Conexión cerrada por el servidor.")
                    break

            if not received_updates:
                _warn("Sin actualizaciones de estado recibidas durante la espera.")
                _dim("La solicitud llegó al IT (ACK confirmado). El IT no ha procesado aún.")
        else:
            _dim("(--wait 0: sin espera de actualizaciones de estado)")

        return 0

    finally:
        await ws.close()

    return 0  # unreachable


# ── Resultado final ────────────────────────────────────────────────────────

def _print_result(success: bool) -> None:
    _sep()
    if success:
        print(f"\n  {GREEN}{BOLD}RESULTADO: ✔ EXITOSO{RESET}")
        print(f"  {DIM}La solicitud llegó al PC IT y fue confirmada con ACK.{RESET}")
    else:
        print(f"\n  {RED}{BOLD}RESULTADO: ✗ FALLIDO{RESET}")
        print(f"  {DIM}Revisa los mensajes anteriores para diagnosticar el problema.{RESET}")
    print()


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="The Watcher — Supervisor Request Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  supervisor_test.exe 192.168.101.164
  supervisor_test.exe 192.168.101.164 --port 9090 --wait 60
  supervisor_test.exe PC-IT-01 --operator Operator-15 --storage Storage2
        """,
    )
    parser.add_argument("host",                              help="IP o hostname del PC IT")
    parser.add_argument("--port",     type=int, default=9090, help="Puerto WebSocket (default: 9090)")
    parser.add_argument("--operator", default="Operator-28",  help="Nombre del operador (default: Operator-28)")
    parser.add_argument("--storage",  default="Storage1",     help="Almacén (default: Storage1)")
    parser.add_argument("--wait",     type=int, default=30,   help="Segundos esperando actualizaciones de estado (default: 30, 0 para no esperar)")

    args = parser.parse_args()

    _banner()

    try:
        rc = asyncio.run(run(
            host=args.host,
            port=args.port,
            operator=args.operator,
            storage=args.storage,
            wait_seconds=args.wait,
        ))
    except KeyboardInterrupt:
        print()
        _warn("Interrumpido por el usuario.")
        rc = 1

    _print_result(rc == 0)
    if _IS_WIN:
        input("  Presiona Enter para cerrar...\n")
    sys.exit(rc)


if __name__ == "__main__":
    main()
