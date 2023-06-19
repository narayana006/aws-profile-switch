"""Read profile names and settings from the AWS config and credentials files.

Only the files are read; nothing here calls AWS. Paths follow the same rules
as the AWS CLI: AWS_CONFIG_FILE and AWS_SHARED_CREDENTIALS_FILE override the
defaults of ~/.aws/config and ~/.aws/credentials.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional


@dataclass
class Profile:
    name: str
    settings: dict = field(default_factory=dict)
    has_static_keys: bool = False

    @property
    def kind(self) -> str:
        if "sso_session" in self.settings or "sso_start_url" in self.settings:
            return "sso"
        if "role_arn" in self.settings:
            return "role"
        if "credential_process" in self.settings:
            return "process"
        if self.has_static_keys or "aws_access_key_id" in self.settings:
            return "keys"
        return "other"


@dataclass
class AwsConfig:
    profiles: dict[str, Profile] = field(default_factory=dict)
    sso_sessions: dict[str, dict] = field(default_factory=dict)

    def sso_base(self, name: str) -> Optional[Profile]:
        """The SSO profile that `name` ultimately gets credentials from.

        Follows source_profile links, so a role profile layered on an SSO
        profile resolves to that SSO profile. Returns None if there is none.
        """
        seen: set[str] = set()
        current = self.profiles.get(name)
        while current and current.name not in seen:
            seen.add(current.name)
            if current.kind == "sso":
                return current
            current = self.profiles.get(current.settings.get("source_profile", ""))
        return None


def home(env: Mapping[str, str]) -> Path:
    return Path(env["HOME"]) if env.get("HOME") else Path.home()


def config_path(env: Mapping[str, str]) -> Path:
    return Path(env.get("AWS_CONFIG_FILE") or home(env) / ".aws" / "config").expanduser()


def credentials_path(env: Mapping[str, str]) -> Path:
    return Path(env.get("AWS_SHARED_CREDENTIALS_FILE") or home(env) / ".aws" / "credentials").expanduser()


def _read_ini(path: Path) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser(strict=False, default_section="\0unused", interpolation=None)
    parser.optionxform = str  # keep key case as written
    if path.is_file():
        try:
            parser.read_string(path.read_text(encoding="utf-8"), source=str(path))
        except configparser.Error as exc:
            raise ValueError(f"cannot parse {path}: {exc}") from exc
    return parser


def load(env: Mapping[str, str]) -> AwsConfig:
    config = AwsConfig()
    parsed = _read_ini(config_path(env))
    for section in parsed.sections():
        words = section.split(None, 1)
        if section == "default":
            name = "default"
        elif len(words) == 2 and words[0] == "profile":
            name = words[1].strip()
        elif len(words) == 2 and words[0] == "sso-session":
            config.sso_sessions[words[1].strip()] = dict(parsed.items(section))
            continue
        else:
            continue  # e.g. [services ...]
        config.profiles[name] = Profile(name, dict(parsed.items(section)))
    for section in _read_ini(credentials_path(env)).sections():
        profile = config.profiles.setdefault(section, Profile(section))
        profile.has_static_keys = True
    return config
