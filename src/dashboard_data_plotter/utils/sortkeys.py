import re

def dataset_sort_key(title: str):
    """Sort special-case titles like R1..R99 numerically; otherwise alphabetical."""
    m = re.match(r"^\s*R(\d{1,2})\b", str(title), flags=re.IGNORECASE)
    if m:
        return (0, int(m.group(1)), str(title).casefold())
    return (1, str(title).casefold())
