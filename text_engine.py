class SimpleInflect:
    """Simple inflect replacement for PyInstaller compatibility"""
    
    def a(self, word: str) -> str:
        """Add 'a' or 'an' before a word"""
        if not word:
            return "a"
        
        # Simple vowel detection for article selection
        vowels = "aeiouAEIOU"
        first_char = word[0]
        
        # Special cases
        if word.lower().startswith(('hour', 'honest', 'honor')):
            return f"an {word}"
        elif word.lower().startswith(('uni', 'use', 'one')):
            return f"a {word}"
        
        # Standard vowel rule
        if first_char in vowels:
            return f"an {word}"
        else:
            return f"a {word}"

class TextEngine:
    def __init__(self):
        self.inflect = SimpleInflect()

    def inflect_word(self, word: str) -> str:
        """Inflects a word to its correct form"""
        return self.inflect.a(word)