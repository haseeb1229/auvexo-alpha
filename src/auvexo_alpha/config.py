"""Explicit local configuration. No dotenv loading or trading credential fields."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from auvexo_alpha.domain.contracts import Mode


class Settings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)
    mode: Mode = Mode.RESEARCH
    bind_host: Literal["127.0.0.1"] = "127.0.0.1"
    port: Annotated[int, Field(ge=1024, le=65535)] = 8765
    database_host: Literal["127.0.0.1"] = "127.0.0.1"
    database_port: Annotated[int, Field(ge=1024, le=65535)] = 55432
    database_name: Annotated[
        str, Field(pattern=r"^auvexo_(dev|test|restore)(_[a-z0-9]{1,32})?$")
    ] = "auvexo_dev"
    database_user: Literal["auvexo_app"] = "auvexo_app"
    database_password: SecretStr = Field(repr=False)
    api_token: SecretStr = Field(repr=False)
    execution_enabled: Literal[False] = False
    policy_version: Literal["phase1.disabled.v1"] = "phase1.disabled.v1"

    @field_validator("api_token", "database_password")
    @classmethod
    def nontrivial_secret(cls, value: SecretStr) -> SecretStr:
        if not 32 <= len(value.get_secret_value()) <= 128:
            raise ValueError("local secret length outside allowed bounds")
        return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    fields = {
        "AUVEXO_MODE": "mode",
        "AUVEXO_BIND_HOST": "bind_host",
        "AUVEXO_PORT": "port",
        "AUVEXO_DB_HOST": "database_host",
        "AUVEXO_DB_PORT": "database_port",
        "AUVEXO_DB_NAME": "database_name",
        "AUVEXO_DB_USER": "database_user",
        "AUVEXO_DB_PASSWORD": "database_password",
        "AUVEXO_API_TOKEN": "api_token",
    }
    if any(key.startswith("AUVEXO_") and key not in fields for key in env):
        raise ValueError(
            "unknown AUVEXO configuration key; execution/account options are forbidden"
        )
    values: dict[str, object] = {field: env[key] for key, field in fields.items() if key in env}
    if "mode" in values:
        values["mode"] = Mode(str(values["mode"]))
    for field in ("port", "database_port"):
        if field in values:
            raw = str(values[field])
            if not raw.isascii() or not raw.isdecimal():
                raise ValueError("port must be an ASCII integer")
            values[field] = int(raw)
    for field in ("api_token", "database_password"):
        if field in values:
            values[field] = SecretStr(str(values[field]))
    return Settings.model_validate(values)
