"""Minimal QR code encoder (byte mode, error correction M, versions 1 to 10), drawn as SVG.

Enough for a link to scan with a phone, with no extra dependency. It follows the ISO/IEC 18004
algorithm as laid out by Project Nayuki's reference implementation.
"""

from __future__ import annotations

from collections.abc import Callable

# Error correction level M, by version 1..10 (index 0 unused).
_ECC_PER_BLOCK = (0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26)
_NUM_BLOCKS = (0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5)
_FORMAT_M = 0  # format bits of level M
MAX_VERSION = 10


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _raw_modules(version: int) -> int:
    result = (16 * version + 128) * version + 64
    if version >= 2:
        align = version // 7 + 2
        result -= (25 * align - 10) * align - 55
        if version >= 7:
            result -= 36
    return result


def _data_capacity(version: int) -> int:
    """Data codewords at level M."""
    return _raw_modules(version) // 8 - _ECC_PER_BLOCK[version] * _NUM_BLOCKS[version]


def _alignment_positions(version: int) -> list[int]:
    if version == 1:
        return []
    size = version * 4 + 17
    count = version // 7 + 2
    step = (version * 8 + count * 3 + 5) // (count * 4 - 4) * 2
    return [6, *reversed([size - 7 - i * step for i in range(count - 1)])]


def _codewords(data: bytes) -> tuple[int, list[int]]:
    """The smallest version that fits, and its interleaved data + error correction codewords."""
    for version in range(1, MAX_VERSION + 1):
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + len(data) * 8 <= _data_capacity(version) * 8:
            break
    else:
        raise ValueError("texte trop long pour un QR code")
    bits: list[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(length)))

    put(0b0100, 4)
    put(len(data), count_bits)
    for byte in data:
        put(byte, 8)
    capacity = _data_capacity(version) * 8
    put(0, min(4, capacity - len(bits)))
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]

    blocks_n, ecc_len = _NUM_BLOCKS[version], _ECC_PER_BLOCK[version]
    raw = _raw_modules(version) // 8
    short_n = blocks_n - raw % blocks_n
    short_len = raw // blocks_n
    divisor = _rs_divisor(ecc_len)
    blocks: list[list[int]] = []
    at = 0
    for i in range(blocks_n):
        chunk = words[at : at + short_len - ecc_len + (0 if i < short_n else 1)]
        at += len(chunk)
        ecc = _rs_remainder(chunk, divisor)
        if i < short_n:
            chunk.append(0)
        blocks.append(chunk + ecc)
    out = [
        block[i]
        for i in range(len(blocks[0]))
        for j, block in enumerate(blocks)
        if i != short_len - ecc_len or j >= short_n
    ]
    return version, out


_MASKS: tuple[Callable[[int, int], bool], ...] = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


class _Matrix:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def function(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.fixed[y][x] = True

    def draw_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.function(6, i, i % 2 == 0)
            self.function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self.function(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = _alignment_positions(self.version)
        last = len(positions) - 1
        for i, ax in enumerate(positions):
            for j, ay in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.function(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                bit = (bits >> i) & 1 == 1
                a, b = size - 11 + i % 3, i // 3
                self.function(a, b, bit)
                self.function(b, a, bit)

    def draw_format(self, mask: int) -> None:
        data = _FORMAT_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = [(bits >> i) & 1 == 1 for i in range(15)]
        size = self.size
        for i in range(6):
            self.function(8, i, bit[i])
        self.function(8, 7, bit[6])
        self.function(8, 8, bit[7])
        self.function(7, 8, bit[8])
        for i in range(9, 15):
            self.function(14 - i, 8, bit[i])
        for i in range(8):
            self.function(size - 1 - i, 8, bit[i])
        for i in range(8, 15):
            self.function(8, size - 15 + i, bit[i])
        self.function(8, size - 8, True)

    def draw_data(self, words: list[int]) -> None:
        size, i, total = self.size, 0, len(words) * 8
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = (right + 1) & 2 == 0
            for vert in range(size):
                y = size - 1 - vert if upward else vert
                for x in (right, right - 1):
                    if not self.fixed[y][x] and i < total:
                        self.dark[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        test = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fixed[y][x] and test(x, y):
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        """Rules 1, 2 and 4 of the standard: long runs, 2x2 blocks, dark/light balance."""
        size, score = self.size, 0
        lines = self.dark + [list(col) for col in zip(*self.dark, strict=True)]
        for line in lines:
            run = 1
            for a, b in zip(line, line[1:], strict=False):
                if a == b:
                    run += 1
                    continue
                score += run - 2 if run >= 5 else 0
                run = 1
            score += run - 2 if run >= 5 else 0
        for y in range(size - 1):
            for x in range(size - 1):
                c = self.dark[y][x]
                if c == self.dark[y][x + 1] == self.dark[y + 1][x] == self.dark[y + 1][x + 1]:
                    score += 3
        dark = sum(map(sum, self.dark))
        return score + abs(dark * 20 - size * size * 10) // (size * size) * 10


def matrix(text: str) -> list[list[bool]]:
    """The QR code of `text` as rows of modules (True = dark), without the quiet zone."""
    version, words = _codewords(text.encode("utf-8"))
    best: _Matrix | None = None
    best_score = 0
    for mask in range(8):
        qr = _Matrix(version)
        qr.draw_patterns()
        qr.draw_data(words)
        qr.apply_mask(mask)
        qr.draw_format(mask)
        score = qr.penalty()
        if best is None or score < best_score:
            best, best_score = qr, score
    assert best is not None
    return best.dark


def svg(text: str, border: int = 4) -> str:
    """The QR code of `text` as a standalone SVG (dark modules on white, with a quiet zone)."""
    rows = matrix(text)
    size = len(rows) + border * 2
    path = "".join(
        f"M{x + border},{y + border}h1v1h-1z"
        for y, row in enumerate(rows)
        for x, dark in enumerate(row)
        if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges" role="img" aria-label="QR code">'
        f'<rect width="100%" height="100%" fill="#fff"/><path d="{path}" fill="#000"/></svg>'
    )
