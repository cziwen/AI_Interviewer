from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import openai

from ...config import settings


@dataclass
class GeneratedResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class ResponseGenerator:
    def __init__(self, api_key: Optional[str]):
        self._client = (
            openai.AsyncOpenAI(api_key=api_key, base_url=settings.ARK_BASE_URL)
            if api_key else None
        )

    async def generate(self, control_instruction: str, candidate_name: str, position: str) -> GeneratedResponse:
        if not self._client:
            return GeneratedResponse(text="抱歉，模型服务当前不可用，请稍后重试。")

        system_prompt = (
            "你是专业中文面试官。"
            "严格遵守用户提供的控制指令。"
            "只输出可直接播报给候选人的自然中文。"
            "禁止输出JSON、禁止解释你的策略。"
        )
        user_prompt = (
            f"候选人：{candidate_name}\n"
            f"岗位：{position}\n"
            f"控制指令如下，请严格执行：\n{control_instruction}"
        )
        response = await self._client.chat.completions.create(
            model=settings.ARK_LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )

        text = ((response.choices[0].message.content if response.choices else "") or "").strip()
        usage = response.usage
        return GeneratedResponse(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
