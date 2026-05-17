from fastapi import FastAPI
from api.v1.agents import agents_router
from api.v1.conversations import conv_router
from api.v1.tools import tools_router
from api.v1.chat import chat_router
from api.v1.uploads import uploads_router

def register_routers(app: FastAPI):
    api_prefix = "/api/v1"
    app.include_router(tools_router, prefix=api_prefix)
    app.include_router(agents_router, prefix=api_prefix)
    app.include_router(uploads_router, prefix=api_prefix)
    app.include_router(conv_router, prefix=api_prefix)
    app.include_router(chat_router, prefix=api_prefix)