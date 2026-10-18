"""File provenance and validation-report types shared by all readers.

Maturity: M2
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from georeservoir._version import __version__

__all__ = ["CheckStatus", "FileProvenance", "QualityCheck", "ValidationReport", "file_provenance"]

CheckStatus = Literal["pass", "info", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class FileProvenance:
    """Where data came from and how it was read.

    ``sha256`` identifies the exact bytes read. ``read_at_utc`` is informative only and is
    never part of any calculation hash.
    """

    file_name: str
    sha256: str
    size_bytes: int
    read_at_utc: str
    file_format: str
    format_version: str
    parser: str
    parser_version: str
    georeservoir_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "read_at_utc": self.read_at_utc,
            "file_format": self.file_format,
            "format_version": self.format_version,
            "parser": self.parser,
            "parser_version": self.parser_version,
            "georeservoir_version": self.georeservoir_version,
        }


def file_provenance(
    path: Path,
    data: bytes,
    *,
    file_format: str,
    format_version: str,
    parser: str,
    parser_version: str,
) -> FileProvenance:
    """Build a :class:`FileProvenance` from the exact bytes that were parsed."""
    return FileProvenance(
        file_name=path.name,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        read_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        file_format=file_format,
        format_version=format_version,
        parser=parser,
        parser_version=parser_version,
        georeservoir_version=__version__,
    )


@dataclass(frozen=True, slots=True)
class QualityCheck:
    """One finding of a validation report."""

    code: str
    status: CheckStatus
    message: str
    curve: str = ""
    indices: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "message": self.message,
            "curve": self.curve,
            "n_indices": len(self.indices),
            "indices_head": list(self.indices[:20]),
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Ordered list of checks; ``status`` is the worst status found."""

    checks: tuple[QualityCheck, ...] = field(default_factory=tuple)

    @property
    def status(self) -> CheckStatus:
        order: dict[CheckStatus, int] = {"pass": 0, "info": 1, "warn": 2, "fail": 3}
        worst: CheckStatus = "pass"
        for c in self.checks:
            if order[c.status] > order[worst]:
                worst = c.status
        return worst

    def codes(self, status: Sequence[CheckStatus] = ("info", "warn", "fail")) -> set[str]:
        return {c.code for c in self.checks if c.status in status}

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checks": [c.to_dict() for c in self.checks]}

    def to_markdown(self) -> str:
        lines = [
            f"**Validation status: {self.status.upper()}**",
            "",
            "| Status | Code | Curve | Message |",
            "|---|---|---|---|",
        ]
        for c in self.checks:
            msg = c.message.replace("|", "\\|")
            lines.append(f"| {c.status} | {c.code} | {c.curve} | {msg} |")
        return "\n".join(lines) + "\n"
