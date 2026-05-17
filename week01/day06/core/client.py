import httpx

async def get_llm_client():
    async with httpx.AsyncClient(base_url="http://localhost:11434",  timeout=60 ) as client:
        yield client
