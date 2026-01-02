"""
Minimal GGUF metadata reader.

We only need a small subset of GGUF: the header + key/value metadata section.
This lets us detect model families (e.g. qwen vs gemma) even when the filename
doesn't contain the model name.
"""

from __future__ import annotations

import os
import struct
from typing import Any


class GGUFReadError(RuntimeError):
    pass


# GGUF value types (gguf.h)
_GGUF_TYPE_UINT8 = 0
_GGUF_TYPE_INT8 = 1
_GGUF_TYPE_UINT16 = 2
_GGUF_TYPE_INT16 = 3
_GGUF_TYPE_UINT32 = 4
_GGUF_TYPE_INT32 = 5
_GGUF_TYPE_FLOAT32 = 6
_GGUF_TYPE_BOOL = 7
_GGUF_TYPE_STRING = 8
_GGUF_TYPE_ARRAY = 9
_GGUF_TYPE_UINT64 = 10
_GGUF_TYPE_INT64 = 11
_GGUF_TYPE_FLOAT64 = 12


def _read_exact(f, n: int) -> bytes:
    b = f.read(n)
    if len(b) != n:
        raise GGUFReadError("Unexpected EOF while reading GGUF")
    return b


def _read_u32(f) -> int:
    return struct.unpack("<I", _read_exact(f, 4))[0]


def _read_u64(f) -> int:
    return struct.unpack("<Q", _read_exact(f, 8))[0]


def _read_i32(f) -> int:
    return struct.unpack("<i", _read_exact(f, 4))[0]


def _read_i64(f) -> int:
    return struct.unpack("<q", _read_exact(f, 8))[0]


def _read_f32(f) -> float:
    return struct.unpack("<f", _read_exact(f, 4))[0]


def _read_f64(f) -> float:
    return struct.unpack("<d", _read_exact(f, 8))[0]


def _read_bool(f) -> bool:
    return struct.unpack("<?", _read_exact(f, 1))[0]


def _read_string(f) -> str:
    # gguf: u64 length + bytes (utf-8)
    n = _read_u64(f)
    if n > 64 * 1024 * 1024:
        raise GGUFReadError("String too large in GGUF metadata")
    return _read_exact(f, n).decode("utf-8", errors="replace")


def _read_scalar(f, vtype: int) -> Any:
    if vtype == _GGUF_TYPE_UINT8:
        return struct.unpack("<B", _read_exact(f, 1))[0]
    if vtype == _GGUF_TYPE_INT8:
        return struct.unpack("<b", _read_exact(f, 1))[0]
    if vtype == _GGUF_TYPE_UINT16:
        return struct.unpack("<H", _read_exact(f, 2))[0]
    if vtype == _GGUF_TYPE_INT16:
        return struct.unpack("<h", _read_exact(f, 2))[0]
    if vtype == _GGUF_TYPE_UINT32:
        return _read_u32(f)
    if vtype == _GGUF_TYPE_INT32:
        return _read_i32(f)
    if vtype == _GGUF_TYPE_UINT64:
        return _read_u64(f)
    if vtype == _GGUF_TYPE_INT64:
        return _read_i64(f)
    if vtype == _GGUF_TYPE_FLOAT32:
        return _read_f32(f)
    if vtype == _GGUF_TYPE_FLOAT64:
        return _read_f64(f)
    if vtype == _GGUF_TYPE_BOOL:
        return _read_bool(f)
    if vtype == _GGUF_TYPE_STRING:
        return _read_string(f)
    raise GGUFReadError(f"Unsupported GGUF scalar type: {vtype}")


def _read_value(f, vtype: int) -> Any:
    if vtype != _GGUF_TYPE_ARRAY:
        return _read_scalar(f, vtype)

    elem_type = _read_u32(f)
    length = _read_u64(f)
    # Bound arrays for safety. We only use small arrays (if any) in metadata.
    if length > 1_000_000:
        raise GGUFReadError("Array too large in GGUF metadata")

    # Strings in arrays have variable length; others are fixed-width.
    if elem_type == _GGUF_TYPE_STRING:
        return [_read_string(f) for _ in range(length)]

    return [_read_scalar(f, elem_type) for _ in range(length)]


def read_gguf_metadata(path: str, *, wanted_keys: set[str] | None = None) -> dict[str, Any]:
    """
    Read GGUF key/value metadata from `path`.

    If wanted_keys is provided, we only keep those keys (but we still must
    parse the stream to skip unknown values safely).
    """
    if not path or not os.path.exists(path):
        raise GGUFReadError("GGUF file not found")

    out: dict[str, Any] = {}
    with open(path, "rb") as f:
        magic = _read_exact(f, 4)
        if magic != b"GGUF":
            raise GGUFReadError("Not a GGUF file (bad magic)")

        _version = _read_u32(f)
        _tensor_count = _read_u64(f)
        kv_count = _read_u64(f)

        for _ in range(kv_count):
            key = _read_string(f)
            vtype = _read_u32(f)
            value = _read_value(f, vtype)

            if wanted_keys is None or key in wanted_keys:
                out[key] = value

    return out


