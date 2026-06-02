import spacy

nlp = spacy.load("en_core_web_sm")

doc = nlp("I have nothing to trade with you.")

for token in doc:
    print(token.text, token.pos_, token.morph)