from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from bpsync.storage import write_text_atomic

CONFIG_VERSION = 1
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigurationError(ValueError):
    """Raised when configuration is invalid or cannot be decoded."""


def validate_profile_name(name: str) -> str:
    if not PROFILE_NAME_PATTERN.fullmatch(name):
        raise ConfigurationError(
            "profile name must start with a letter or digit and contain "
            "only letters, digits, '.', '_', or '-'"
        )
    return name


def validate_environment_name(name: str) -> str:
    if not ENVIRONMENT_NAME_PATTERN.fullmatch(name):
        raise ConfigurationError(f"'{name}' is not a valid environment-variable name")
    return name


def default_password_env(profile_name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]", "_", profile_name).upper()
    name = f"{stem}_WP_PASSWORD"
    if not ENVIRONMENT_NAME_PATTERN.fullmatch(name):
        raise ConfigurationError(
            f"profile '{profile_name}' has no valid default password variable; "
            "choose one with --password-env"
        )
    return name


def canonical_local_root(directory: str | Path) -> Path:
    candidate = Path(directory).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ConfigurationError(f"local root does not exist: {candidate}") from error
    if not resolved.is_dir():
        raise ConfigurationError(f"local root is not a directory: {candidate}")
    if resolved.parent == resolved:
        raise ConfigurationError("local root cannot be the filesystem root")
    return resolved


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _required_string(document: dict[str, Any], key: str, profile: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(
            f"profile '{profile}' {key} must be a non-empty string"
        )
    return value


@dataclass(frozen=True)
class Profile:
    site: str
    api_root: str
    username: str
    password_env: str
    local_root: Path

    def to_document(self) -> dict[str, str]:
        return {
            "site": self.site,
            "api_root": self.api_root,
            "username": self.username,
            "password_env": self.password_env,
            "local_root": os.fspath(self.local_root),
        }

    @classmethod
    def from_document(cls, name: str, document: Any) -> Profile:
        if not isinstance(document, dict):
            raise ConfigurationError(f"profile '{name}' must be an object")
        local_root = Path(_required_string(document, "local_root", name))
        if not local_root.is_absolute():
            raise ConfigurationError(f"profile '{name}' local_root must be absolute")
        return cls(
            site=_required_string(document, "site", name),
            api_root=_required_string(document, "api_root", name),
            username=_required_string(document, "username", name),
            password_env=validate_environment_name(
                _required_string(document, "password_env", name)
            ),
            local_root=local_root,
        )


@dataclass
class Configuration:
    profiles: dict[str, Profile] = field(default_factory=dict)

    def add(self, name: str, profile: Profile) -> None:
        if name in self.profiles:
            raise ConfigurationError(f"profile '{name}' already exists")
        self.check_root(name, profile.local_root)
        self.profiles[name] = profile

    def remap(self, name: str, local_root: Path) -> Profile:
        self.check_root(name, local_root)
        self.profiles[name] = replace(self.profiles[name], local_root=local_root)
        return self.profiles[name]

    def check_root(self, name: str, root: Path) -> None:
        for other_name, other in self.profiles.items():
            if other_name != name and _paths_overlap(root, other.local_root):
                raise ConfigurationError(
                    f"local root '{root}' overlaps profile '{other_name}' "
                    f"at '{other.local_root}'"
                )

    def profile_for_path(self, path: Path) -> tuple[str, Profile] | None:
        for name, profile in self.profiles.items():
            if path == profile.local_root or profile.local_root in path.parents:
                return name, profile
        return None


class ConfigurationStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".bpsync" / "config.json"

    def load(self) -> Configuration:
        if not self.path.exists():
            return Configuration()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(f"cannot read {self.path}: {error}") from error
        if not isinstance(document, dict) or document.get("version") != CONFIG_VERSION:
            raise ConfigurationError(
                f"{self.path} is not a version {CONFIG_VERSION} bpsync configuration"
            )
        profiles = document.get("profiles", {})
        if not isinstance(profiles, dict):
            raise ConfigurationError(f"{self.path}: profiles must be an object")
        configuration = Configuration()
        for name, profile in profiles.items():
            configuration.add(
                validate_profile_name(name), Profile.from_document(name, profile)
            )
        return configuration

    def save(self, configuration: Configuration) -> None:
        document = {
            "version": CONFIG_VERSION,
            "profiles": {
                name: profile.to_document()
                for name, profile in sorted(configuration.profiles.items())
            },
        }
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(document, indent=2) + "\n"
        write_text_atomic(self.path, payload, mode=0o600)
