from fastapi import FastAPI
from api.router import register_routers
from core.exception import register_exception_handlers
from core.middleware import register_middlewares
from core.database import init_db
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI(title="AI Agent API", version="0.4.0", lifespan=init_db)

register_exception_handlers(app)
register_middlewares(app)
register_routers(app)


app.mount("/static", StaticFiles(directory="web", html=True), name="static")

# 根路由直接返回 index.html，方便直接访问
@app.get("/")
async def read_index():
    index_path = os.path.join("web", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "index.html not found in web directory"}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.4.0"}