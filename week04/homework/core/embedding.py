
from typing import List

import httpx

class Embedding():

    def __init__(
        self,
        model: str =  "nomic-embed-text:latest",
        base_url: str = "http://localhost:11434",
        timeout: int = 10
    ):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout


    def embed_text(self, text: str)-> List[float]:
        """
        将单段文本转为 Embedding 向量。

        Ollama 的 Embedding endpoint 是 POST /api/embeddings，
        请求体: {"model": "...", "prompt": "..."}
        响应体: {"embedding": [0.1, 0.2, ...]}
        """
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("待向量化文本不能为空")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": clean_text},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            raise ConnectionError(f"无法连接Ollama：{self.base_url}，服务未启动？")
        except httpx.TimeoutException:
            raise TimeoutError(f"向量化请求超时（{self.timeout}s），Embedding 服务 ({self.base_url}) 是否已启动？")
        except httpx.ConnectError:
            raise ConnectionError(f"无法连接 Embedding 服务 ({self.base_url})，服务是否已启动？")
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"接口异常 {e.response.status_code}: {e.response.text}")
        # 优先Ollama原生格式
        if "embedding" in data and isinstance(data["embedding"], list):
            return data["embedding"]
        # 兼容OpenAI代理格式
        if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
            item = data["data"][0]
            if "embedding" in item and isinstance(item["embedding"], list):
                return item["embedding"]

        raise RuntimeError(f"未知返回格式，response: {data}")
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量文本生成向量"""
        vectors = []
        for txt in texts:
            vec = self.embed_text(txt)
            vectors.append(vec)
        return vectors

    async def embed_text_async(self, text: str) -> List[float]:
        """异步单条文本向量化"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.embed_text, text)

    async def embed_batch_async(self, texts: List[str], concurrency: int = 8) -> List[List[float]]:
        """并发批量文本生成向量"""
        import asyncio
        semaphore = asyncio.Semaphore(concurrency)

        async def _embed_one(txt: str) -> List[float]:
            async with semaphore:
                return await self.embed_text_async(txt)

        tasks = [_embed_one(t) for t in texts]
        return await asyncio.gather(*tasks)