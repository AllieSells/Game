from text_utils import wrap_colored_text_to_strings, parse_colored_text

s = "This is a <white></white><green>mossy wall</green>."
print("INPUT: ", s)
wrapped = wrap_colored_text_to_strings(s, 80)
print("WRAPPED LINES:")
for line in wrapped:
    print(repr(line))
    print("PARSE:", parse_colored_text(line))

# Also test the normal case using tile name directly
s2 = f"This is a {'<green>Mossy Wall</green>'.lower()}."
print('\nINPUT2:', s2)
wrapped2 = wrap_colored_text_to_strings(s2, 80)
for line in wrapped2:
    print(repr(line))
    print("PARSE:", parse_colored_text(line))
