import secrets
import struct
import zlib

from .db import UPLOAD_DIR

MAX_BYTES = 5 * 1024 * 1024


def sniff(data: bytes) -> str | None:
    """확장자·Content-Type이 아니라 실제 바이트로 이미지 종류를 판정."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def save(data: bytes) -> str:
    ext = sniff(data)
    if ext is None:
        raise ValueError("JPG/PNG/WEBP 이미지만 올릴 수 있습니다.")
    if len(data) > MAX_BYTES:
        raise ValueError("사진은 5MB 이하여야 합니다.")
    name = f"{secrets.token_hex(16)}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    return name


def delete(name: str) -> None:
    (UPLOAD_DIR / name).unlink(missing_ok=True)


def placeholder_png(rgb: tuple[int, int, int], size: int = 160) -> bytes:
    """시드용 단색 PNG (외부 라이브러리 없이 생성)."""
    row = b"\x00" + bytes(rgb) * size
    raw = zlib.compress(row * size)

    def chunk(tag: bytes, body: bytes) -> bytes:
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
