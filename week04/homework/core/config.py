import os
# LLM
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://n.tokeness.io/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "mimo-v2.5")
LLM_KEY = os.getenv("LLM_KEY", "sk-c0EnaHNDOgJFr60YmVtul1ULhfLarW6oQJJW2LTNAWbJqQxe")
# LLM_MODEL = os.getenv("LLM_MODEL", "mimo-v2.5-pro")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# Embedding
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text:latest")


# Chroma
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "chroma_db")


# 分割
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "4000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "300"))


# 检索
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "15"))

# 检索优化开关
USE_MULTI_QUERY = os.getenv("USE_MULTI_QUERY", "false").lower() == "true"
USE_HYDE = os.getenv("USE_HYDE", "false").lower() == "true"
USE_RE_RANK = os.getenv("USE_RE_RANK", "false").lower() == "true"


# 上传
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt", ".html"}


# 数据库
DATABASE_URL = "sqlite+aiosqlite:///./rag_agent.db"
