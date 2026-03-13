import json
import openai
from typing import List, Dict, Any
from ..config import settings

async def evaluate_interview(answers: List[Dict[str, Any]]) -> tuple[Dict[str, Any], Dict[str, int]]:
    """
    使用 OpenAI Chat Completion API 对整场面试进行统一评分。
    返回 (result_dict, usage_dict)
    """
    if not settings.OPENAI_API_KEY:
        return {
            "total_score": 0,
            "dimension_scores": {},
            "comment": "OpenAI API Key not configured."
        }, {"input_tokens": 0, "output_tokens": 0}

    client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    # Prepare prompt
    prompt = "你是一名资深面试官。请根据以下面试问答记录，对候选人的表现进行综合评分。\n\n"
    for a in answers:
        prompt += f"问题 {a['question_index'] + 1}: {a.get('question_text', '未知问题')}\n"
        prompt += f"回答: {a['transcript']}\n\n"
    
    prompt += """
请以 JSON 格式输出评分结果，包含以下字段：
- total_score: 总分 (0-100)
- dimension_scores: 维度分 (对象，如 {"communication": 80, "technical": 70})
- comment: 综合评语

示例输出：
{
  "total_score": 85,
  "dimension_scores": {"沟通能力": 90, "专业技能": 80},
  "comment": "表现良好..."
}
"""

    try:
        response = await client.chat.completions.create(
            model=settings.EVAL_LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一名专业的面试评估专家。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        usage = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens
        }
        return result, usage
    except Exception as e:
        print(f"LLM evaluation error: {e}")
        return {
            "total_score": 0,
            "dimension_scores": {},
            "comment": f"评分生成失败: {str(e)}"
        }, {"input_tokens": 0, "output_tokens": 0}
