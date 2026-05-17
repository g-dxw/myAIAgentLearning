
import os
import uuid
from fastapi import APIRouter, File, HTTPException, UploadFile
from schemas.commonResponse import APIResponse
from faster_whisper import WhisperModel

uploads_router = APIRouter(prefix="/upload", tags=["上传"])

model = WhisperModel("small", device="cpu", compute_type="int8")

@uploads_router.post("/audioasr")
async def upload_file(file: UploadFile = File(...)):
    """
    上传语音文件，返回 ASR 识别文本
    file: UploadFile 提供 .filename / .content_type / .read() / .size
    """
    # 校验文件类型
    AlLOWED_AUDIO_TYPES = ["audio/mpeg", "audio/wav", "audio/x-wav", "audio/x-m4a"]
    if file.content_type not in AlLOWED_AUDIO_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型：{file.content_type}")
    
    # 校验文件大小（UploadFile 默认没有 .size，需要读完后才知道）
    contents = await file.read()  # 读取文件内容
    max_size = 10 * 1024 * 1024  # 10MB
    if len(contents) > max_size:
        raise HTTPException(status_code=400, detail="文件大小超过限制（10MB）")
    # 保存文件
    file_path = f"/path/to/save/{uuid.uuid4()}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(contents)

    # 调 ASR 服务（腾讯云 / Whisper）
    # transcript = await asr_service.transcribe(file_path)
    segments, info = model.transcribe(file_path, language="zh")
    text = "".join([seg.text for seg in segments])
    os.remove(file_path)
    # 处理文件上传
    return APIResponse(success=True, data=text)

# @uploads_router.post("/audio/batch")
# async def upload_multiple_audio(
#     files: list[UploadFile] = File(...),
# ):
#     """批量上传照护录音"""
#     results = []
#     for file in files:
#         contents = await file.read()
#         results.append({
#             "filename": file.filename,
#             "size": len(contents),
#             "saved": True,
#         })
#     return APIResponse(success=True, data={
#         "files": results,
#     })