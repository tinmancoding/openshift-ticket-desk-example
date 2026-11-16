"""Ticket HTTP contract. Persistence and HTTP dependencies are replaceable in tests."""
import os
import urllib.error
import urllib.request
import json

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

VERSION = "1.1.0"
PRIORITIES = {"normal", "high", "urgent"}


def http_preview(url, ticket):
    payload = json.dumps(ticket).encode()
    req = urllib.request.Request(url.rstrip("/") + "/render", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        body = response.read(16 * 1024 + 1)
        if len(body) > 16 * 1024:
            raise ValueError("renderer response too large")
        return json.loads(body)


def create_app(repository=None, preview=http_preview):
    if repository is None:
        from .repository import PostgresRepository
        repository = PostgresRepository()
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.get("/readyz")
    def ready():
        try:
            repository.ready()
            return jsonify(status="ready")
        except Exception:
            app.logger.warning("database readiness failed")
            return jsonify(error="database unavailable or schema not initialized"), 503

    @app.get("/version")
    def version():
        return jsonify(version=VERSION, component="api")

    @app.post("/tickets")
    def create_ticket():
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400
        title = data.get("title")
        description = data.get("description", "")
        priority = data.get("priority", "normal")
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
            return jsonify(error="title must contain 1-120 nonblank characters"), 400
        if not isinstance(description, str) or len(description) > 2000:
            return jsonify(error="description must be at most 2000 characters"), 400
        if not isinstance(priority, str) or priority not in PRIORITIES:
            return jsonify(error="unsupported priority"), 400
        ticket = repository.create(title.strip(), description, priority)
        response = jsonify(ticket)
        response.status_code = 201
        response.headers["Location"] = f"/tickets/{ticket['id']}"
        return response

    @app.get("/tickets")
    def tickets():
        # A bounded teaching API, not an unbounded database export.
        return jsonify(tickets=repository.list_recent())

    @app.get("/tickets/<int:ticket_id>")
    def get_ticket(ticket_id):
        ticket = repository.get(ticket_id)
        if ticket is None:
            return jsonify(error="ticket not found"), 404
        return jsonify(ticket)

    @app.get("/tickets/<int:ticket_id>/notification-preview")
    def notification_preview(ticket_id):
        ticket = repository.get(ticket_id)
        if ticket is None:
            return jsonify(error="ticket not found"), 404
        url = os.environ.get("RENDERER_URL", "")
        if not url:
            return jsonify(error="renderer not configured"), 503
        try:
            result = preview(url, ticket)
            if (not isinstance(result, dict) or result.get("ticket_id") != ticket_id
                    or not isinstance(result.get("subject"), str)
                    or not isinstance(result.get("text"), str)):
                raise ValueError("invalid renderer response")
            return jsonify(result)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            app.logger.warning("notification preview unavailable")
            return jsonify(error="notification preview temporarily unavailable"), 503

    @app.errorhandler(Exception)
    def unavailable(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        # Do not return database details, credentials or internal URLs to clients.
        app.logger.error("request failed: %s", type(error).__name__)
        return jsonify(error="service temporarily unavailable"), 503

    return app
