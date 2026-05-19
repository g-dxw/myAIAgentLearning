import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_DIR = os.path.join(_BASE_DIR, "..", "database")
os.makedirs(_DB_DIR, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DB_DIR}/db.sqlite")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = "claude-3-5-sonnet-20241022"
CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]
