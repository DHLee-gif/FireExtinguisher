import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_HOST = os.environ.get("FIRECAR_DB_HOST", "172.30.1.65")
DB_PORT = int(os.environ.get("FIRECAR_DB_PORT", "3306"))
DB_USER = os.environ.get("FIRECAR_DB_USER", "ktech")
DB_PASSWORD = os.environ.get("FIRECAR_DB_PASSWORD", "ktech1234")
DB_NAME = os.environ.get("FIRECAR_DB_NAME", "firecar")

SQLALCHEMY_URL = (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
)

SECRET_KEY = os.environ.get("FIRECAR_SECRET_KEY", "firecar-secret-key")

LOGIN_BYPASS = os.environ.get("FIRECAR_LOGIN_BYPASS", "1") == "1"

STREAM_URL = os.environ.get("FIRECAR_STREAM_URL", "http://raspberrypi.local:8000/stream.mjpg")

SERVER_HOST = "0.0.0.0"
SERVER_PORT = int(os.environ.get("FIRECAR_PORT", "5000"))
DEBUG = os.environ.get("FIRECAR_DEBUG", "0") == "1"

DEVICE_ID = 1
DEVICE_NAME = "FireCar-01"
ONLINE_TIMEOUT_SEC = 10
LIVE_POLL_MS = 3000

UPLOAD_SUBDIR = "uploads"
UPLOAD_DIR = os.path.join(BASE_DIR, "static", UPLOAD_SUBDIR)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png"}
MAX_UPLOAD_MB = 16

LIST_LIMIT = 500
