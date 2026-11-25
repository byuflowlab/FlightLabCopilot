"""HTTP routes. The browser gets live updates from /api/stream (Server-Sent Events)."""

from __future__ import annotations

import io
import json
import queue
import re
import time
import zipfile
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import maptiles
from .engine import Engine
from .sources import list_serial_ports, read_log
from .storage import Store

STATIC = Path(__file__).parent / "static"
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or "file").name).strip("._")
    return name or "file"


def create_app(data_dir=None) -> Flask:
    store = Store(data_dir)
    engine = Engine(store)
    app = Flask(__name__, static_folder=None)
    app.config["ENGINE"] = engine
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

    def bad(msg, code=400):
        return jsonify({"error": msg}), code

    @app.errorhandler(ValueError)
    def on_value_error(e):
        return bad(str(e))

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html", max_age=0)

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC, name, max_age=0)

    @app.get("/map/<path:name>")
    def map_files(name):
        return send_from_directory(store.root / "map", name)

    @app.get("/api/state")
    def state():
        return jsonify(engine.snapshot(full=True))

    @app.get("/api/stream")
    def stream():
        q = engine.subscribe()

        def gen():
            try:
                yield f"data: {json.dumps(engine.snapshot())}\n\n"
                while True:
                    try:
                        snap = q.get(timeout=10)
                        yield f"data: {json.dumps(snap)}\n\n"
                    except queue.Empty:
                        yield ": keep-alive\n\n"
            finally:
                engine.unsubscribe(q)

        return Response(gen(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- GPS source
    @app.get("/api/ports")
    def ports():
        return jsonify(list_serial_ports())

    @app.post("/api/source")
    def source():
        body = request.get_json(force=True)
        kind = body.get("kind")
        if kind == "serial" and not body.get("port"):
            return bad("pick a serial port")
        engine.set_source(kind, port=body.get("port"), baudrate=body.get("baudrate"))
        return jsonify(ok=True)

    @app.post("/api/source/replay")
    def replay():
        f = request.files.get("file")
        if not f:
            return bad("choose a CSV file")
        folder = store.root / "replays"
        folder.mkdir(exist_ok=True)
        name = _safe_name(f.filename)
        path = folder / name
        f.save(path)
        read_log(path)  # raises ValueError with a readable message if it is not a GPS log
        engine.set_source("replay", path=path, name=name, speed=float(request.form.get("speed") or 1.0))
        return jsonify(ok=True)

    # ---- course and progress
    @app.put("/api/course")
    def put_course():
        engine.set_course(request.get_json(force=True))
        return jsonify(ok=True)

    @app.get("/api/course/export")
    def export_course():
        with engine.lock:
            c = engine.course
        fname = _safe_name(c["name"]) + ".course.json"
        return Response(json.dumps(c, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.post("/api/waypoint/<int:i>")
    def mark(i):
        engine.mark(i, request.get_json(force=True).get("status"))
        return jsonify(ok=True)

    @app.post("/api/run/restart")
    def restart():
        engine.restart_run()
        return jsonify(ok=True)

    @app.post("/api/home")
    def home():
        engine.set_home_here()
        return jsonify(ok=True)

    @app.post("/api/settings")
    def settings():
        engine.update_settings(request.get_json(force=True))
        return jsonify(ok=True)

    # ---- recording and history
    @app.post("/api/record")
    def record():
        action = request.get_json(force=True).get("action")
        if action == "start":
            engine.start_recording()
        elif action == "stop":
            engine.stop_recording()
        else:
            return bad("action must be start or stop")
        return jsonify(ok=True)

    @app.get("/api/history/download")
    def history_download():
        files = engine.history_files()
        if not files:
            return bad("there are no recordings yet; click Record first", 404)
        if len(files) == 1:
            return send_from_directory(files[0].parent, files[0].name, as_attachment=True, max_age=0)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                z.write(p, p.name)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return Response(buf.getvalue(), mimetype="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="flight-history-{stamp}.zip"'})

    @app.post("/api/history/clear")
    def history_clear():
        engine.clear_history()
        return jsonify(ok=True)

    # ---- map background
    @app.post("/api/map/image")
    def map_image():
        f = request.files.get("file")
        if not f:
            return bad("choose an image")
        ext = Path(f.filename or "").suffix.lower()
        if ext not in IMAGE_TYPES:
            return bad("use a PNG, JPEG, GIF or WebP image")
        try:
            edges = {k: float(request.form[k]) for k in ("north", "south", "east", "west")}
        except (KeyError, ValueError):
            return bad("enter the latitude of the top and bottom edges and the longitude of the left and right edges")
        if edges["north"] <= edges["south"] or edges["east"] <= edges["west"]:
            return bad("top must be north of bottom, and right east of left")
        name = "background" + ext
        for old in (store.root / "map").glob("background.*"):
            old.unlink()
        f.save(store.root / "map" / name)
        engine.update_settings({"map": {**engine.settings["map"], "kind": "image", "image": {"file": name, **edges}}})
        return jsonify(ok=True)

    @app.get("/api/map/estimate")
    def map_estimate():
        z = int(request.args.get("zoom", 18))
        with engine.lock:
            n = len(maptiles.plan(maptiles.course_bbox(engine.course), z))
        return jsonify(tiles=n, limit=maptiles.MAX_TILES)

    @app.post("/api/map/download")
    def map_download():
        maptiles.download(engine, int(request.get_json(force=True).get("zoom", 18)))
        return jsonify(ok=True)

    @app.post("/api/exit")
    def exit_app():
        engine.shutdown()
        app.config["SHUTDOWN"]()
        return jsonify(ok=True)

    return app
