import random
import re

# Words grouped by semantic concept.
# Fixed-form slots (pronouns) are strings; open-class slots are lists to pick from.
# "goblin" = native goblin tongue  (SVO word order)
# "common" = the common trade tongue (SVO word order, like English)
VOCABULARY = {
    "goblin": {
        # Pronouns — fixed forms
        "1sg":      "Gra",          # I
        "1pl":      "Ke",           # we
        "2sg":      "u",            # you
        # Observation verbs - prsent tense
        "v_obs_present":    ["kukg", "ug"],
        # Aggression verbs - future tense
        "v_agg_future":    ["gehikh", "kide", "ked", "kutu", "gatakud", "gatep ewtidid"],

        # Interjections
        "interj":   ["U ikg!", "", "", ""],
        # Prey
        "prey":     ["dedou", "grupekker dedou"],
        # Remains
        "remains":  ["gegretou", "gri gehikh", "gri rurek gepig"],
        # Future fear
        "will_fear": ["tag kata", "kuwarde"],
        # Progressive hurt
        "hurting": ["putakud", "putep did gru", "poutktigeptud"]

    },
    "common": {
        # Pronouns
        ""
        "1sg":      "Me",
        "1pl":      "we",
        "2sg":      "you",
        # Observation verbs - present
        "v_obs_present":    ["see", "spot", "notice"],
        # Aggression verbs - future tense
        "v_agg_future":    ["gut", "bite", "slash", "kill", "hurt", "break the skin of"],
        # Interjections
        "interj":   ["You there!", "", "", ""],

        # Prey
        "prey":     ["meat", "fresh meat"],
        # Remains
        "remains":  ["bones", "your insides", "your bits"],
        # Future fear
        "will_fear": ["will regret", "will fear"],
        # Progressive hurt
        "hurting": ["hurting", "breaking the skin of", "bleeding"],

    },
}

# Templates enforce SVO word order for both languages.
# Slots referencing lists are resolved randomly at generation time.
TEMPLATES = {
    "goblin": {
        "observe": [
            "{interj} {1sg} {v_obs_present} {2sg}!",
            "{interj} {1sg} {v_obs_present} {prey} kadek ikg!",
            "{1sg} {v_obs_present} {prey}, gra tag ak u!",
            "{interj} gre gekit gugk {prey}!",
            "{1sg} kede tikg {prey} pe gred!",
        ],
        "threat": [
            "{interj} {1sg} tag {v_agg_future} {2sg} tet reragre!",
            "{interj} {1sg} tag {v_agg_future} {remains}!",
            "{2sg} ki rouk gred!",
            "{interj} {remains} tag kout gra!",
            "u kede ki gidak pe ke!",
            "{interj} {1sg} tag {v_agg_future} {2sg}. Grah!",
        ],
        "hurt": [
            "{2sg} {will_fear} {hurting} {1sg}!",
            "{interj} {2sg} {will_fear} {1sg}.",
            ""
        ]
    },
    "common": {
        "observe": [
            "{interj} {1sg} {v_obs_present} {2sg}!",
            "{interj} {1sg} {v_obs_present} {prey} over there!",
            "{1sg} {v_obs_present} {prey}!",
            "{interj} {1sg} have eyes on {prey}!",
            "{1sg} can {v_obs_present} {prey} from here!",
        ],
        "threat": [
            "{interj} {1sg} will {v_agg_future} {2sg} real good!",
            "{interj} {1sg} will {v_agg_future} {remains}.",
            "{2sg} will not leave here.",
            "{interj} {remains} will be mine.",
            "{2sg} cannot run from us!",
            "{interj} {1sg} will {v_agg_future} {2sg}. Ha!",
        ],
        "hurt": [
            "{2sg} {will_fear} {hurting} {1sg}!",
            "{interj} {2sg} {will_fear} {1sg}.",
        ]
    },
}


class _VocabMap:
    """Wraps a vocab dict so that list-valued slots resolve to a random choice."""
    def __init__(self, vocab: dict):
        self._vocab = vocab

    def __getitem__(self, key: str) -> str:
        val = self._vocab[key]
        return random.choice(val) if isinstance(val, list) else val


def build_reverse_lookup(from_lang: str, to_lang: str) -> list[tuple[str, str]]:
    """Build (source_word, translation) pairs sorted longest-first."""
    src = VOCABULARY[from_lang]
    dst = VOCABULARY[to_lang]
    pairs: list[tuple[str, str]] = []
    for key in src:
        sv, dv = src.get(key), dst.get(key)
        if sv is None or dv is None:
            continue
        if isinstance(sv, list) and isinstance(dv, list):
            for s, d in zip(sv, dv):
                if s and d:
                    pairs.append((s.lower(), d.lower()))
        elif isinstance(sv, str) and isinstance(dv, str) and sv and dv:
            pairs.append((sv.lower(), dv.lower()))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def reverse_translate(sentence: str, from_lang: str = "goblin", to_lang: str = "common") -> str:
    """Partially translate a sentence word-by-word. Grammar structure stays native."""
    pairs = build_reverse_lookup(from_lang, to_lang)
    result = sentence
    for native, translation in pairs:
        pattern = re.compile(r'\b' + re.escape(native) + r'\b', re.IGNORECASE)
        def _replace(m: re.Match, t=translation) -> str:
            return t[0].upper() + t[1:] if m.group(0)[0].isupper() else t
        result = pattern.sub(_replace, result)
    return result


def _clean(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s([!?.,:;])', r'\1', s)
    s = re.sub(r'([.!?])\s+([a-z])', lambda m: m.group(1) + ' ' + m.group(2).upper(), s)
    return s


def generate_sentence(intent: str, language: str = "goblin", known: bool = False) -> str:
    """Generate a sentence in the given language.

    known=False  →  native tongue (goblin)
    known=True   →  common tongue
    """
    lang_key = "common" if known else language
    vocab_map = _VocabMap(VOCABULARY[lang_key])
    template = random.choice(TEMPLATES[lang_key][intent])
    sentence = template.format_map(vocab_map)
    sentence = _clean(sentence)
    return sentence[0].upper() + sentence[1:] if sentence else sentence


# Demo
for lang in ["goblin"]:
    print(f"\n--- {lang.upper()} ---")
    for intent in ("observe", "threat"):
        for _ in range(3):
            native = generate_sentence(intent, lang, known=False)
            common = generate_sentence(intent, lang, known=True)
            print(f"  {native}")
            print(f"  ~ {common}")