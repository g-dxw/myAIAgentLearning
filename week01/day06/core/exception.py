# ==========================================
# 全局异常处理（所有错误都走这里）
# ==========================================
from fastapi.responses import JSONResponse
from fastapi import FastAPI, Request
from schemas.commonResponse import APIResponse

async def global_exception_handler(request: Request, exc: Exception):
    # 打印错误日志
    print(f"❌ 错误：{str(exc)}")

    # 返回统一格式
    return JSONResponse(
        status_code=500,
        content= APIResponse(
            success=False,
            error=f"服务器异常：{str(exc)}",
            data=None
        ).model_dump()
    )

def register_exception_handlers(app: FastAPI):
    app.add_exception_handler(Exception, global_exception_handler)