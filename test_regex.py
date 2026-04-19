import re

REGEX_PATTERN = r'(?:^|\s|\[|/)/?r/([\w\d_]+)'

test_titles = [
    "[r/flags] Antisemitism on r/flags",
    "Someone in r/ussr is afraid...",
    "Open and brazen Antisemitic Art on r/Catholicism",
    "[/r/jewsofconscience] post",
    "r/me_irl has become...",
    "Cross-posted on [r/PinoyVloggers] and [r/ChikaPH]",
    "From /r/test"
]

def extract(title):
    mentions = re.findall(REGEX_PATTERN, title, re.IGNORECASE)
    return [m.lower() for m in mentions if m.lower() != "antisemitisminreddit"]

for t in test_titles:
    print(f"Title: {t}")
    print(f"Extracted: {extract(t)}")
    print("-" * 20)
