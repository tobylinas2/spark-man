import os
from dataclasses import dataclass, field
from typing import Optional

import yaml


CLAUDE_MAN_HOME = os.path.expanduser("~/.claude-man")
MANS_DIR = os.path.join(CLAUDE_MAN_HOME, "mans")


@dataclass
class PreviewConfig:
    max_preview_length: int = 200
    max_messages_per_turn: int = 10


@dataclass
class RetryConfig:
    initial_delay: int = 60
    max_delay: int = 3600
    backoff_factor: int = 5


@dataclass
class Config:
    name: str
    work_dir: str
    preview: PreviewConfig = field(default_factory=PreviewConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)

    @property
    def db_path(self) -> str:
        return os.path.join(self.work_dir, "messages.db")

    @property
    def tools_dir(self) -> str:
        return os.path.join(self.work_dir, "tools")


def get_man_dir(man_name: str) -> str:
    return os.path.join(MANS_DIR, man_name)


def load_config(man_name: str) -> Config:
    man_dir = get_man_dir(man_name)
    config_path = os.path.join(man_dir, ".claude_man")
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Configuration not found at {config_path}. "
            f"Run 'claude-man init {man_name}' first."
        )

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    if not raw or "name" not in raw:
        raise ValueError(f"Invalid config file: {config_path}")

    preview_cfg = PreviewConfig(
        max_preview_length=raw.get("preview", {}).get("max_preview_length", 200),
        max_messages_per_turn=raw.get("preview", {}).get("max_messages_per_turn", 10),
    )
    retry_cfg = RetryConfig(
        initial_delay=raw.get("retry", {}).get("initial_delay", 60),
        max_delay=raw.get("retry", {}).get("max_delay", 3600),
        backoff_factor=raw.get("retry", {}).get("backoff_factor", 5),
    )
    return Config(
        name=raw["name"],
        work_dir=os.path.expanduser(raw.get("work_dir", man_dir)),
        preview=preview_cfg,
        retry=retry_cfg,
    )


def init_config(man_name: str, work_dir: Optional[str] = None) -> Config:
    man_dir = get_man_dir(man_name)
    if work_dir:
        work_dir = os.path.expanduser(work_dir)
    else:
        work_dir = os.path.join(MANS_DIR, man_name)

    os.makedirs(man_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(os.path.join(work_dir, "tools"), exist_ok=True)

    config = Config(name=man_name, work_dir=work_dir)
    config_path = os.path.join(man_dir, ".claude_man")

    data = {
        "name": man_name,
        "work_dir": work_dir,
        "preview": {
            "max_preview_length": config.preview.max_preview_length,
            "max_messages_per_turn": config.preview.max_messages_per_turn,
        },
        "retry": {
            "initial_delay": config.retry.initial_delay,
            "max_delay": config.retry.max_delay,
            "backoff_factor": config.retry.backoff_factor,
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    return config
