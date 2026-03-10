import csv
import os
import json
from typing import List, Dict
from ..config import settings

DEFAULT_QUESTIONS = [
    {"order_index": 0, "question_text": "请简单介绍一下你自己"},
    {"order_index": 1, "question_text": "你为什么应聘这个岗位？"},
    {"order_index": 2, "question_text": "你最大的优势是什么？"},
]

def generate_questions(position: str = None, resume_brief: str = None) -> List[Dict]:
    """
    根据岗位从 CSV 题库中选取题目，若无匹配则返回默认题目。
    """
    try:
        csv_path = settings.QUESTION_BANK_CSV_PATH
        if not os.path.exists(csv_path):
            # Try relative to project root if not found
            alt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), csv_path)
            if os.path.exists(alt_path):
                csv_path = alt_path
            else:
                return DEFAULT_QUESTIONS

        field_map = json.loads(settings.QUESTION_BANK_FIELD_MAP)
        pos_column = field_map.get("position", "岗位")
        
        matched_questions = []
        with open(csv_path, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if position and row.get(pos_column) == position:
                    matched_questions.append(row.get("题目", row.get("question_text")))
        
        if not matched_questions:
            return DEFAULT_QUESTIONS
        
        # Limit to 3-5 questions or as needed
        selected = matched_questions[:5]
        return [
            {"order_index": i, "question_text": q} 
            for i, q in enumerate(selected)
        ]
        
    except Exception as e:
        print(f"Error generating questions from CSV: {e}")
        return DEFAULT_QUESTIONS
