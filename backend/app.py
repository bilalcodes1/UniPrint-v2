import os
import sys

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, send_from_directory, redirect
from flask_cors import CORS
from extensions import socketio
from models import init_db
from api import bp as api_bp
from workers.outbox import start_outbox_worker
from workers.telegram_bot import start_bot
from workers.supabase_sync import start_supabase_sync
from workers.mdns import start_mdns
from workers.scheduler import start_scheduler

if getattr(sys, 'frozen', False):
    _RESOURCES        = os.path.dirname(sys.executable)
    _DATA_DIR         = os.path.join(_RESOURCES, 'backend')
    STUDENT_PAGES_DIR = os.path.join(_RESOURCES, 'student-pages')
    DASHBOARD_BUILD   = os.path.join(_RESOURCES, 'dashboard')
else:
    _DATA_DIR         = os.path.dirname(os.path.abspath(__file__))
    STUDENT_PAGES_DIR = os.path.join(_DATA_DIR, '..', 'student-pages')
    DASHBOARD_BUILD   = os.path.join(_DATA_DIR, '..', 'frontend', 'build')


def create_app():
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uniprint-secret-2025')
    app.config['UPLOAD_FOLDER'] = os.path.join(_DATA_DIR, 'uploads')
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB total
    app.config['DB_PATH'] = os.path.join(_DATA_DIR, 'uniprint.db')

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    CORS(app, resources={r'/api/*': {'origins': '*'}})

    socketio.init_app(app)

    app.register_blueprint(api_bp, url_prefix='/api')

    with app.app_context():
        init_db(app.config['DB_PATH'])

    start_outbox_worker(app.config['DB_PATH'], socketio)
    start_bot(app.config['DB_PATH'])
    start_supabase_sync(app.config['DB_PATH'], socketio)
    start_mdns(port=int(os.environ.get('PORT', 5001)))
    start_scheduler(app.config['DB_PATH'], app.config['UPLOAD_FOLDER'], socketio)

    @app.route('/')
    def index():
        return redirect('/dashboard/')

    @app.route('/dashboard/')
    @app.route('/dashboard')
    def dashboard_index():
        build_dir = os.path.abspath(DASHBOARD_BUILD)
        return send_from_directory(build_dir, 'index.html')

    @app.route('/dashboard/<path:filename>')
    def dashboard_static(filename):
        build_dir = os.path.abspath(DASHBOARD_BUILD)
        full = os.path.join(build_dir, filename)
        if os.path.isfile(full):
            return send_from_directory(build_dir, filename)
        return send_from_directory(build_dir, 'index.html')

    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'UniPrint Backend'}

    @app.route('/student/')
    @app.route('/student/lan/')
    def student_index():
        pages_dir = os.path.abspath(STUDENT_PAGES_DIR)
        return send_from_directory(os.path.join(pages_dir, 'lan'), 'index.html')

    @app.route('/student/lan/<path:filename>')
    def student_static(filename):
        pages_dir = os.path.abspath(STUDENT_PAGES_DIR)
        return send_from_directory(os.path.join(pages_dir, 'lan'), filename)

    @app.route('/student/offline.html')
    def student_offline():
        pages_dir = os.path.abspath(STUDENT_PAGES_DIR)
        return send_from_directory(pages_dir, 'offline.html')

    @app.route('/student/online/')
    @app.route('/student/online')
    def student_online_index():
        pages_dir = os.path.abspath(STUDENT_PAGES_DIR)
        return send_from_directory(os.path.join(pages_dir, 'online'), 'index.html')

    @app.route('/student/online/<path:filename>')
    def student_online_static(filename):
        pages_dir = os.path.abspath(STUDENT_PAGES_DIR)
        return send_from_directory(os.path.join(pages_dir, 'online'), filename)

    return app


if __name__ == '__main__':
    app = create_app()
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)
