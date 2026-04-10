from flask import Blueprint

bp = Blueprint('api', __name__)

from api import routes  # noqa: F401, E402
