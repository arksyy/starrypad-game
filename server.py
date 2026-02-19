#!/usr/bin/env python3
"""
StarryPad Simon Says – Python backend (MIDI + game logic) with web UI over WebSocket.
Run: python server.py
Then open http://localhost:8765 in a browser.
"""

import asyncio
import json
import random
import threading
import time
from pathlib import Path
from queue import Empty, Queue

try:
    import mido
except ImportError:
    print("Missing dependency: run  pip install mido python-rtmidi")
    exit(1)

try:
    from aiohttp import web
except ImportError:
    print("Missing dependency: run  pip install aiohttp")
    exit(1)

NOTE_MIN, NOTE_MAX = 31, 46
PLAYABLE_NOTES = list(range(NOTE_MIN, NOTE_MAX + 1))
DEBOUNCE_S = 0.35
WEB_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent
LEADERBOARD_FILE = STATIC_DIR / "leaderboard.json"
TOP_N = 5


# ── Leaderboard persistence ──────────────────────────────────────────

def load_leaderboard() -> list[dict]:
    if LEADERBOARD_FILE.exists():
        try:
            data = json.loads(LEADERBOARD_FILE.read_text())
            if isinstance(data, list):
                return sorted(data, key=lambda e: e.get("score", 0), reverse=True)[:TOP_N]
        except (json.JSONDecodeError, OSError):
            pass
    return []


def save_leaderboard(board: list[dict]):
    LEADERBOARD_FILE.write_text(json.dumps(board, indent=2))


def is_top_score(score: int) -> bool:
    board = load_leaderboard()
    if len(board) < TOP_N:
        return score > 0
    return score > board[-1].get("score", 0)


def add_score(name: str, score: int) -> list[dict]:
    board = load_leaderboard()
    board.append({"name": name, "score": score})
    board = sorted(board, key=lambda e: e["score"], reverse=True)[:TOP_N]
    save_leaderboard(board)
    return board


# ── MIDI helpers ──────────────────────────────────────────────────────

def note_to_pad_index(note: int) -> int | None:
    if NOTE_MIN <= note <= NOTE_MAX:
        return note - NOTE_MIN
    return None


def find_starrypad_ports():
    in_names = mido.get_input_names()
    out_names = mido.get_output_names()
    key = "starry"
    in_name = next((n for n in in_names if key in n.lower()), None)
    out_name = next((n for n in out_names if key in n.lower()), None)
    return in_name, out_name


# ── Game thread ───────────────────────────────────────────────────────

def game_thread(game_events: Queue, ui_to_game: Queue):
    inport = None
    outport = None

    sequence: list[int] = []
    score = 0
    phase = "idle"  # idle | playing | input | gameover
    expected_index = 0
    last_note = None
    last_note_time = 0.0
    stop_requested = False
    midi_ok = False

    def emit(ev):
        game_events.put(ev)

    def drain_commands() -> str | None:
        cmd = None
        while True:
            try:
                cmd = ui_to_game.get_nowait()
            except Empty:
                break
        return cmd

    def try_connect_midi() -> bool:
        nonlocal inport, outport, midi_ok
        if midi_ok:
            return True
        try:
            in_name, out_name = find_starrypad_ports()
            if not in_name:
                return False
            inport = mido.open_input(in_name)
            outport = mido.open_output(out_name) if out_name else None
            midi_ok = True
            print(f"StarryPad connected: {in_name}")
            return True
        except Exception as e:
            print(f"MIDI connect failed: {e}")
            return False

    def light_pad(note: int, duration_s: float = 0.45):
        idx = note_to_pad_index(note)
        if idx is not None:
            emit({"type": "light", "pad": idx})
        if outport:
            try:
                outport.send(mido.Message("note_on", note=note, velocity=127))
            except Exception:
                pass
        time.sleep(duration_s)
        if outport:
            try:
                outport.send(mido.Message("note_off", note=note))
                outport.send(mido.Message("note_on", note=note, velocity=0))
            except Exception:
                pass
        if idx is not None:
            emit({"type": "unlight", "pad": idx})
        time.sleep(0.25)

    def go_idle():
        nonlocal phase, sequence, score, stop_requested
        phase = "idle"
        sequence = []
        score = 0
        stop_requested = False
        emit({"type": "phase", "phase": "idle"})
        emit({"type": "score", "score": 0})
        emit({"type": "leaderboard", "board": load_leaderboard()})

    def start_round():
        nonlocal sequence, score, phase, expected_index, stop_requested
        sequence.append(random.choice(PLAYABLE_NOTES))
        score = len(sequence) - 1
        phase = "playing"
        expected_index = 0
        emit({"type": "score", "score": score})
        emit({"type": "phase", "phase": "playing"})
        for note in sequence:
            cmd = drain_commands()
            if cmd == "stop":
                stop_requested = True
                go_idle()
                return
            light_pad(note)
        cmd = drain_commands()
        if cmd == "stop":
            go_idle()
            return
        phase = "input"
        expected_index = 0
        emit({"type": "phase", "phase": "input"})

    def game_over():
        nonlocal phase
        final_score = score
        phase = "gameover"
        emit({"type": "phase", "phase": "gameover"})
        top = is_top_score(final_score)
        emit({"type": "gameover", "score": final_score, "is_top5": top})

    # Try to connect on startup
    try_connect_midi()
    go_idle()

    try:
        while True:
            cmd = drain_commands()

            if cmd == "stop" and phase not in ("idle",):
                go_idle()
                continue

            if cmd == "start" and phase in ("idle", "gameover"):
                if not midi_ok:
                    try_connect_midi()
                if not midi_ok:
                    emit({"type": "error", "text": "No StarryPad found. Connect it and try again."})
                    go_idle()
                    continue
                stop_requested = False
                sequence = []
                score = 0
                start_round()
                if phase == "idle":
                    continue

            if phase in ("idle", "gameover"):
                time.sleep(0.05)
                continue

            if not inport:
                time.sleep(0.05)
                continue

            for msg in inport.iter_pending():
                if msg.type != "note_on" or msg.velocity == 0:
                    continue
                note = msg.note
                idx = note_to_pad_index(note)
                if idx is None:
                    continue

                if phase != "input":
                    continue

                now = time.time()
                if last_note == note and (now - last_note_time) < DEBOUNCE_S:
                    continue
                last_note = note
                last_note_time = now

                if outport:
                    try:
                        outport.send(mido.Message("note_on", note=note, velocity=127))
                    except Exception:
                        pass
                time.sleep(0.15)
                if outport:
                    try:
                        outport.send(mido.Message("note_off", note=note))
                        outport.send(mido.Message("note_on", note=note, velocity=0))
                    except Exception:
                        pass

                if note != sequence[expected_index]:
                    emit({"type": "wrong", "pad": idx})
                    game_over()
                    continue

                emit({"type": "correct", "pad": idx})
                expected_index += 1
                if expected_index >= len(sequence):
                    time.sleep(0.8)
                    start_round()
                    if phase == "idle":
                        break
            time.sleep(0.05)
    except Exception as e:
        emit({"type": "error", "text": f"Error: {e}"})
    finally:
        if inport:
            inport.close()
        if outport:
            outport.close()


# ── Web server ────────────────────────────────────────────────────────

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app["clients"].add(ws)

    # Send current leaderboard on connect
    board = load_leaderboard()
    await ws.send_str(json.dumps({"type": "leaderboard", "board": board}))

    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            cmd = data.get("type")
            if cmd == "start":
                request.app["ui_to_game"].put("start")
            elif cmd == "stop":
                request.app["ui_to_game"].put("stop")
            elif cmd == "submit_name":
                name = str(data.get("name", "")).strip()[:20]
                score = data.get("score", 0)
                if name and isinstance(score, int) and score > 0:
                    board = add_score(name, score)
                    payload = json.dumps({"type": "leaderboard", "board": board})
                    for c in set(request.app["clients"]):
                        try:
                            await c.send_str(payload)
                        except Exception:
                            request.app["clients"].discard(c)
    finally:
        request.app["clients"].discard(ws)
    return ws


async def broadcast(app, payload: dict):
    msg = json.dumps(payload)
    for ws in set(app["clients"]):
        try:
            await ws.send_str(msg)
        except Exception:
            app["clients"].discard(ws)


async def game_event_forwarder(app):
    q = app["game_events"]
    while True:
        try:
            ev = q.get_nowait()
        except Empty:
            await asyncio.sleep(0.02)
            continue
        await broadcast(app, ev)


def create_app():
    app = web.Application()
    app["game_events"] = Queue()
    app["ui_to_game"] = Queue()
    app["clients"] = set()

    app.router.add_get("/", lambda r: web.FileResponse(STATIC_DIR / "index.html"))
    app.router.add_get("/main.js", lambda r: web.FileResponse(STATIC_DIR / "main.js"))
    app.router.add_get("/styles.css", lambda r: web.FileResponse(STATIC_DIR / "styles.css"))
    app.router.add_get("/ws", websocket_handler)

    return app


def main():
    app = create_app()
    runner = web.AppRunner(app)
    threading.Thread(target=game_thread, args=(app["game_events"], app["ui_to_game"]), daemon=True).start()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    loop.run_until_complete(site.start())
    loop.create_task(game_event_forwarder(app))
    print(f"StarryPad Simon Says – open http://localhost:{WEB_PORT}")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(runner.cleanup())


if __name__ == "__main__":
    main()
