"""Shared, UI-friendly problem records.

Every parser in the app reports problems as `Issue` instead of raising, so the
window can show "3 行有问题" and keep going. Fatals raise `WgdiError`.
"""
from __future__ import annotations

from dataclasses import dataclass


class WgdiError(Exception):
    """Fatal problem: the input cannot be used at all."""


@dataclass(frozen=True)
class Issue:
    level: str        # "error" | "warning"
    where: str        # e.g. "Sjap.gff:1204"
    message: str

    def __str__(self) -> str:
        tag = "错误" if self.level == "error" else "警告"
        return f"{tag} {self.where}：{self.message}"


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


def warnings(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "warning"]
