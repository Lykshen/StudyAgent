"""StudyAgent: a local-first learning & practice agent platform."""
from flask import Flask


def create_app():
    from . import api, db, seed
    db.init()
    seed.seed_if_empty()
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False
    app.register_blueprint(api.bp)
    return app
