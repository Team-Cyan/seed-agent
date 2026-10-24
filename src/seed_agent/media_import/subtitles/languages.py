"""Explicit language declarations; generic Chinese never proves a specific script."""

CHINESE = {"zh", "zh-Hans", "zh-Hant"}


def normalize(value):
    value = str(value or "").lower()
    return {
        "zh": "zh",
        "zho": "zh",
        "chi": "zh",
        "zh-cn": "zh-Hans",
        "zh-hans": "zh-Hans",
        "zh-tw": "zh-Hant",
        "zh-hant": "zh-Hant",
        "eng": "en",
        "en": "en",
    }.get(value, "unknown")


def matches(language, requirement):
    return language in requirement or ("zh" in requirement and language in CHINESE)


def priority(language, requirement):
    if language in requirement:
        return requirement.index(language)
    if "zh" in requirement and language in CHINESE:
        return {"zh-Hans": 0, "zh-Hant": 1, "zh": 2}[language]
    return 99
