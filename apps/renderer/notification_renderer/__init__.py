"""Stateless, on-demand plain-text notification previews. No email is sent."""
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

VERSION = "1.0.0"


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    @app.get("/healthz")
    @app.get("/readyz")
    def health():
        return jsonify(status="ok")

    @app.get("/version")
    def version():
        return jsonify(version=VERSION, component="renderer")

    @app.post("/render")
    def render():
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify(error="JSON object required"), 400
        ticket_id = data.get("id")
        title = data.get("title")
        priority = data.get("priority")
        if (type(ticket_id) is not int or ticket_id < 1
                or not isinstance(title, str) or not 1 <= len(title) <= 120
                or not isinstance(priority, str) or not 1 <= len(priority) <= 16):
            return jsonify(error="valid ticket id, title and priority required"), 400
        # Plain JSON text, not HTML or a raw mail header. Normalize subject newlines.
        title = " ".join(title.splitlines())
        return jsonify(subject=f"Ticket #{ticket_id}: {title}",
                       text=f"Your ticket #{ticket_id} was received. Priority: {priority}.",
                       ticket_id=ticket_id, renderer_version=VERSION)

    @app.errorhandler(HTTPException)
    def bad_request(error):
        return jsonify(error=error.description), error.code

    return app
