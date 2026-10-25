"""Loss-accounted reader for the retained Hymnary mixed-quote CSV witness.

CSV doubled quotes decode normally. A lone quote immediately after a literal
backslash inside a quoted field, where it cannot end that field, is retained
together with the backslash and reported as an unresolved source quoting
anomaly. No backslash is an escape
character: source spellings such as ``Verf\\söhner`` remain unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class SourceField:
    start: int
    end: int
    value: str
    anomalous_quote_offsets: tuple[int, ...]


@dataclass(frozen=True)
class SourceRow:
    ordinal: int
    start: int
    end: int
    fields: tuple[SourceField, ...]


def read_rows(content: bytes) -> Iterator[SourceRow]:
    """Yield complete byte-bound rows; reject every unexplained CSV boundary."""
    # Validate the entire witness, including delimiters and excluded BOM.
    content.decode("utf-8", errors="strict")
    position = 3 if content.startswith(b"\xef\xbb\xbf") else 0
    ordinal = 0
    while position < len(content):
        row_start = position
        fields: list[SourceField] = []
        while True:
            start = position
            anomalies: list[int] = []
            if position < len(content) and content[position] == 34:
                position += 1
                chunks: list[bytes] = []
                while True:
                    quote = content.find(b'"', position)
                    if quote < 0:
                        raise ValueError(f"Unterminated quoted field at byte {start}")
                    chunks.append(content[position:quote])
                    if content[quote + 1:quote + 2] == b'"':
                        chunks.append(b'"')
                        position = quote + 2
                    elif content[quote - 1:quote] == b"\\" and content[quote + 1:quote + 2] not in (b"", b",", b"\r", b"\n"):
                        chunks.append(b'"')
                        anomalies.append(quote)
                        position = quote + 1
                    else:
                        position = quote + 1
                        break
                value = b"".join(chunks).decode("utf-8")
            else:
                while position < len(content) and content[position] not in (44, 10, 13):
                    if content[position] == 34:
                        raise ValueError(f"Quote in unquoted field at byte {position}")
                    position += 1
                value = content[start:position].decode("utf-8")
            fields.append(SourceField(start, position, value, tuple(anomalies)))
            if position == len(content):
                break
            marker = content[position]
            if marker == 44:
                position += 1
                continue
            if marker == 10:
                position += 1
                break
            if marker == 13 and content[position:position + 2] == b"\r\n":
                position += 2
                break
            raise ValueError(f"Unexpected CSV field boundary at byte {position}")
        ordinal += 1
        yield SourceRow(ordinal, row_start, position, tuple(fields))


__all__ = ("SourceField", "SourceRow", "read_rows")
