import random
import re

VOCABULARY = {
    "goblin": {
        "verbs": {
            "observe": ["kukg", "kukg", "ug"],
            "threat":  ["gehikh", "kide", "ked", "kutu"],
        },
        "verbs_common": {
            "observe": ["see", "notice", "spot"],
            "threat":  ["guts", "bite", "slash", "kill"],
        },
        "subjects":        ["Gra", "Ke"],
        "subjects_common": ["I",   "we"],
        "targets":         ["dedou", "grupekker dedou", "u"],
        "targets_common":  ["meat",   "fresh meat", "you"],
        "life":            ["gegretou",  "gri gehikh",     "gri rurek gepig"],
        "life_common":     ["bones",  "your insides", "your bits"],
        "openers":         ["U ikg!", "", "", "", "", ""],
        "openers_common":  ["You there!",     "",    "",     "", "",     ""],
    }
}

# Per-language templates — adverbials are baked into specific templates
# so every combination is grammatically natural.
TEMPLATES = {
    "goblin": {
        "observe": [
            "{opener} {subject} {verb} {target}!",
            "{opener} {subject} {verb} {target} kadek ikg!",
            "{subject} {verb} {target}, gra tag ak u!",
            "{opener} gre gekit gugk {target}!",
            "{subject} kede tikg {target} pe gred!",
        ],
        "observe_common": [
            "{opener} {subject} {verb} {target}!",
            "{opener} {subject} {verb} {target} over there!",
            "{subject} {verb} {target}!",
            "{opener} My eyes on {target}!",
            "{subject} can smell {target} from here!",
        ],
        "threat": [
            "{opener} {subject} tag {verb} {target} tet reragre!",
            "{opener} {subject} tag {verb} {life}!",
            "{target} ki rouk gred!",
            "{opener} {life} tag kout gra!",
            "u kede ki gidak pe ke!",
            "{opener} {subject} tag {verb} {target}. Ha!",
        ],
        "threat_common": [
            "{opener} {subject} will {verb} {target} real good!",
            "{opener} {subject} will {verb} {life}.",
            "{target} not leave here.",
            "{opener} {life} will be mine.",
            "You cannot run from us!",
            "{opener} {subject} will {verb} {target}. Ha!",
        ],
    },
}


def build_reverse_lookup(language: str) -> list[tuple[str, str]]:
    """
    Build a list of (native_phrase, english_word) pairs from VOCABULARY,
    sorted longest-first so multi-word phrases match before their parts.
    English is represented by the first word in each vocab list.
    """
    vocab = VOCABULARY[language]
    en_vocab = VOCABULARY["english"]
    pairs: list[tuple[str, str]] = []

    slot_map = [
        ("verbs.observe", vocab["verbs"]["observe"], en_vocab["verbs"]["observe"]),
        ("verbs.threat",  vocab["verbs"]["threat"],  en_vocab["verbs"]["threat"]),
        ("subjects",      vocab["subjects"],         en_vocab["subjects"]),
        ("targets",       vocab["targets"],          en_vocab["targets"]),
        ("life",          vocab["life"],             en_vocab["life"]),
        ("openers",       vocab["openers"],          en_vocab["openers"]),
    ]

    for _slot, native_words, english_words in slot_map:
        for native, english in zip(native_words, english_words):
            if native and english:
                pairs.append((native.lower(), english.lower()))

    # Longest native phrase first so "yer bones" beats "yer"
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def reverse_translate(sentence: str, language: str) -> str:
    """
    Partially translate a native-language sentence back to English using
    the vocabulary slots. Template structure words stay native — giving a
    disjointed, half-understood feel even to someone who knows the language.
    """
    pairs = build_reverse_lookup(language)
    result = sentence
    for native, english in pairs:
        # Match whole words/phrases only, case-insensitive, with word boundaries
        pattern = re.compile(r'\b' + re.escape(native) + r'\b', re.IGNORECASE)
        def _replace(m: re.Match, eng=english) -> str:
            # Preserve capitalisation of the original token
            return eng[0].upper() + eng[1:] if m.group(0)[0].isupper() else eng
        result = pattern.sub(_replace, result)
    return result


def _clean(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\s([!?.,:;])', r'\1', s)
    s = re.sub(r'([.!?])\s+([a-z])', lambda m: m.group(1) + ' ' + m.group(2).upper(), s)
    return s


def generate_sentence(intent: str, language: str = "english", known: bool = False) -> str:
    vocab = VOCABULARY[language]

    # Pick a shared index for each slot so native[i] and _common[i] stay paired
    def pick(key):
        native_list  = vocab[key] if not isinstance(vocab[key], dict) else vocab[key][intent]
        common_key   = key + "_common"
        common_list  = vocab.get(common_key, native_list)
        if isinstance(common_list, dict):
            common_list = common_list[intent]
        i = random.randrange(len(native_list))
        word = common_list[i % len(common_list)] if known else native_list[i]
        return word

    template = random.choice(TEMPLATES[language][intent + ("_common" if known else "")])

    sentence = template.format(
        opener=pick("openers"),
        subject=pick("subjects"),
        verb=pick("verbs"),
        target=pick("targets"),
        life=pick("life"),
    )

    sentence = _clean(sentence)
    return sentence[0].upper() + sentence[1:] if sentence else sentence


# Demo: print 5 sentences per intent per language, with reverse translation

for lang in ["goblin"]:
    print(f"\n--- {lang.upper()} ---")
    for intent in ("observe", "threat"):
        #print(f"  [{intent}]")
        for _ in range(3):
            native = generate_sentence(intent, lang, known=False)
            common = generate_sentence(intent, lang, known=True)
            print(f"  {native}")
            print(f"  ~ {common}")