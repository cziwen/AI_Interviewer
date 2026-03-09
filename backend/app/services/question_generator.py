from typing import List, Dict

DEFAULT_QUESTIONS = [
    {"order_index": 0, "question_text": "请简单介绍一下你自己"},
    {"order_index": 1, "question_text": "你为什么应聘这个岗位？"},
    {"order_index": 2, "question_text": "你最大的优势是什么？"},
]

def generate_questions(position: str = None, resume_brief: str = None) -> List[Dict]:
    # Placeholder for LLM generation
    return DEFAULT_QUESTIONS
