from typing import List, Dict

DEFAULT_QUESTIONS = [
    {"order_index": 1, "question_text": "你为什么应聘这个岗位？"},
    {"order_index": 2, "question_text": "你最大的优势是什么？"},
    {"order_index": 3, "question_text": "请谈谈你对 AI Agent 的理解。"},
]

def generate_questions(position: str = None, resume_brief: str = None) -> List[Dict]:
    """
    当前实现：统一返回默认题目。
    预留参数以便未来根据岗位 / 简历生成题目。
    """
    return DEFAULT_QUESTIONS
