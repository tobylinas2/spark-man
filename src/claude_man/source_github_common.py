"""GitHub Source 共享函数。"""


def ensure_source_dir(source_dir: str) -> None:
    import os
    os.makedirs(source_dir, exist_ok=True)


def ensure_list(val):
    return val if isinstance(val, list) else []
