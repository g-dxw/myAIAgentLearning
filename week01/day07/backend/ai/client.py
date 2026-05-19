import json
import re

import anthropic

from config import ANTHROPIC_API_KEY, AI_MODEL


class AIClient:
    """Anthropic SDK wrapper for chat and JSON extraction."""

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured")
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def chat(self, messages: list, system_prompt: str, max_tokens: int = 1024) -> str:
        """General chat interface. Returns AI response text."""
        response = self.client.messages.create(
            model=AI_MODEL,
            system=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.content[0].text

    def extract_json(self, messages: list, system_prompt: str) -> dict:
        """Extract structured JSON from conversation. Handles format errors."""
        response = self.client.messages.create(
            model=AI_MODEL,
            system=system_prompt + "\n请只输出 JSON，不要包含其他文字。",
            messages=messages,
            max_tokens=1024,
        )
        text = response.content[0].text

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1)

        # Try direct parse
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"AI 返回的不是有效的 JSON: {text[:200]}")
