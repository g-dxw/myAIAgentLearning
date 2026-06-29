import json

import httpx

import core.config as config


class Generator:
    def __init__(self):
        self.base_url = config.LLM_BASE_URL
        self.model = config.LLM_MODEL
        self.api_key = config.LLM_KEY
        self.max_tokens = config.LLM_MAX_TOKENS
        self.temperature = config.LLM_TEMPERATURE

    def build_prompt(self, question: str, contexts: list[dict]) -> str:
        """构建RAG Prompt，包含上下文和问题"""
        if not contexts:
            context_text = "（无相关参考文档）"
        else:
            context_text = "\n\n".join([
                f"[{i+1}] {ctx['text']}" for i, ctx in enumerate(contexts)
            ])

        prompt = (
            "你是一个智能问答助手。请严格基于以下提供的参考文档内容回答用户问题。\n"
            "重要规则（必须遵守）：\n"
            "1. 只要文档中有任何相关信息，就必须回答，绝对不许说不知道。\n"
            "2. 如果用户问'有哪些'、'是什么'、'怎么'等列举/说明类问题，必须从文档中提取并列出所有具体项目或步骤，不能只给总结。\n"
            "3. 如果文档包含代码示例，请引用关键代码行。\n"
            "4. 即使信息分散在多个片段中，也要综合所有片段给出最完整的回答。\n"
            "5. 不要编造超出文档范围的内容。\n\n"
            "参考文档（共" + str(len(contexts)) + "条片段，请仔细阅读每一条）：\n" + context_text + "\n\n"
            "用户问题：" + question + "\n\n"
            "请基于上述所有参考文档片段，给出准确、完整、详细的回答："
        )
        return prompt

    async def generate(self, question: str, contexts: list[dict]) -> dict:
        """非流式生成 → {answer, sources, usage}"""
        import asyncio as _asyncio
        prompt = self.build_prompt(question, contexts)
        messages = [{"role": "user", "content": prompt}]

        data = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        self.base_url + "/chat/completions",
                        headers={
                            "Authorization": "Bearer " + self.api_key,
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "max_tokens": self.max_tokens,
                            "temperature": self.temperature,
                            "stream": False
                        }
                    )
                    if resp.status_code == 429 or resp.status_code == 403:
                        await _asyncio.sleep(5 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    break
            except (httpx.HTTPStatusError, httpx.ConnectError):
                if attempt < 2:
                    await _asyncio.sleep(5 * (attempt + 1))
                    continue
                raise

        if not data:
            return {"answer": "LLM 服务暂时不可用，请稍后重试", "sources": self._extract_sources(contexts), "usage": {}}

        answer = data["choices"][0]["message"]["content"]
        sources = self._extract_sources(contexts)
        usage = data.get("usage", {})

        return {
            "answer": answer,
            "sources": sources,
            "usage": usage
        }

    async def generate_stream(self, question: str, contexts: list[dict]):
        """SSE流式生成 → 逐token yield {delta, done}"""
        prompt = self.build_prompt(question, contexts)
        messages = [{"role": "user", "content": prompt}]
        sources = self._extract_sources(contexts)
        done_yielded = False

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "stream": True
                }
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        done_yielded = True
                        yield {"delta": "", "done": True, "sources": sources}
                        break

                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    if "choices" not in chunk or not chunk["choices"]:
                        continue

                    choice = chunk["choices"][0]
                    delta = choice.get("delta", {})
                    content = delta.get("content") or ""

                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        done_yielded = True
                        yield {"delta": "", "done": True, "sources": sources}
                        break

                    yield {"delta": content, "done": False}

        if not done_yielded:
            yield {"delta": "", "done": True, "sources": sources}

    def _extract_sources(self, contexts: list[dict]) -> list[dict]:
        """提取来源信息"""
        sources = []
        for ctx in contexts:
            meta = ctx.get("metadata", {})
            text = ctx.get("text", "")
            source = {
                "text": text[:300] + "..." if len(text) > 300 else text,
                "metadata": meta
            }
            sources.append(source)
        return sources
