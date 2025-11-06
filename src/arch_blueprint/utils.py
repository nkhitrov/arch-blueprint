def filter_substr(string_set: set[str]) -> set[str]:
    """Filter out strings that are substrings of other strings in the set."""
    sorted_strings = sorted(string_set, key=len, reverse=True)
    result: set[str] = set()

    for string in sorted_strings:
        is_substring = False
        for longer_string in list(result):
            if string in longer_string:
                is_substring = True
                continue

        if not is_substring:
            result.add(string)

    return result
