import inflect

class TextEngine:
    def __init__(self):
        self.inflect = inflect.engine()

    def inflect_word(self, word: str) -> str:
        """Inflects a word to its correct form"""
        return self.inflect.a(word)