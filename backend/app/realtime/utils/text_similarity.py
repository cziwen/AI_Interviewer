import numpy as np
from difflib import SequenceMatcher

class TextSimilarity:
    def __init__(self, focus='end', n_words=5):
        self.focus = focus
        self.n_words = n_words

    def calculate_similarity(self, text1, text2):
        if not text1 or not text2:
            return 0.0
        
        t1 = text1.strip().lower()
        t2 = text2.strip().lower()
        
        if self.focus == 'end':
            w1 = t1.split()[-self.n_words:]
            w2 = t2.split()[-self.n_words:]
            t1 = " ".join(w1)
            t2 = " ".join(w2)
            
        return SequenceMatcher(None, t1, t2).ratio()
