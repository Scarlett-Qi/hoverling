"""Screen-text recognition and local phrase matching; no GUI or network access."""
from __future__ import annotations

import csv
import ctypes as C
import ctypes.util
import io
import json
import re
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Word:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float
    line: tuple[int, int, int, int]


@dataclass(frozen=True)
class Target:
    word: str
    query: str
    context: str
    explanation: str = ""
    phrase: bool = False
    explicit: bool = False


def clip_utf8(text: str, limit: int = 480) -> str:
    return text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


def tokens(text: str) -> list[re.Match]:
    return list(re.finditer(r"[A-Za-z]+(?:['’][A-Za-z]+)*", text))


@lru_cache(maxsize=1)
def phrase_entries():
    entries = json.loads((ROOT / "phrases.json").read_text(encoding="utf-8"))
    return sorted(entries.items(), key=lambda item: -len(item[0].split()))


def local_target(context: str, start: int, end: int) -> Target:
    """Only recognize a phrase if it actually includes the pointed-at word."""
    words = tokens(context)
    normal = [m.group().lower().replace("’", "'") for m in words]
    hit = next((i for i, m in enumerate(words) if m.start() < end and m.end() > start), None)
    original = context[start:end]
    if hit is not None:
        for phrase, meaning in phrase_entries():
            parts = phrase.split()
            for first in range(max(0, hit - len(parts) + 1), hit + 1):
                if normal[first:first + len(parts)] != parts:
                    continue
                # A phrase may span a line, but never cross a sentence boundary.
                last = first + len(parts) - 1
                between = context[words[first].start():words[last].end()]
                if re.search(r"[.!?;。！？；]", between):
                    continue
                return Target(original, between, clip_utf8(context), meaning, True)
    ambiguous = {
        "fine": "常见义：好的；精细的；罚款。需根据句子判断。",
        "right": "常见义：正确的；右边；权利；恰好。需根据句子判断。",
        "mean": "常见义：意思是；意味着；刻薄的；平均值。需根据句子判断。",
        "bank": "常见义：银行；河岸。需根据句子判断。",
        "charge": "常见义：收费；充电；指控；负责；冲锋。需根据句子判断。",
        "issue": "常见义：问题；议题；发行；（刊物的）期。需根据句子判断。",
        "interest": "常见义：兴趣；利息；利益。需根据句子判断。",
        "address": "常见义：地址；演说；处理、应对（问题）。需根据句子判断。",
        "run": "常见义：跑步；运行；经营；持续。需根据句子判断。",
        "pretty": "常见义：漂亮的；相当、颇为。需根据句子判断。",
        "literally": "常见义：字面上、确实；口语中也可用于夸张强调。",
        "sick": "常见义：生病的；俚语中可表示非常棒，也可能表示令人反感。",
        "ship": "常见义：船；运送；发布（产品）；网络用语中也可指支持某对情侣。",
        "based": "常见义：基于；网络俚语中有赞同、称赞对方敢于表达观点的用法。",
        "yet": "常见义：还、尚未；但是；用于比较级时可表示更加。",
    }
    return Target(original, original, clip_utf8(context), ambiguous.get(original.lower(), ""))


def explicit_target(text: str) -> Target:
    """Translate exactly a user-selected/pasted range, without expanding it."""
    text = text.strip()
    if not text:
        raise ValueError("没有读取到选中文字。请先划选；读不到时可复制后使用“翻译剪贴板”。")
    if len(text) > 5000:
        raise ValueError("所选文字超过 5000 个字符，请缩小选区；不会自动截断。")
    normalized = text.replace("’", "'")
    spans, explanations = [], []
    for phrase, meaning in phrase_entries():
        pattern = r"(?<![A-Za-z])" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"(?![A-Za-z])"
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match or any(match.start() < end and match.end() > start for start, end in spans):
            continue
        spans.append(match.span())
        explanations.append(phrase + "：" + meaning)
        if len(explanations) == 3:
            break
    if explanations:
        return Target(text, text, text, "\n".join(explanations), True, True)
    word_matches = tokens(text)
    explanation = ""
    if len(word_matches) == 1:
        match = word_matches[0]
        explanation = local_target(text, match.start(), match.end()).explanation
    return Target(text, text, text, explanation, False, True)


def parse_tsv(tsv: str) -> list[Word]:
    result = []
    # Native GetTsvText (unlike the tesseract CLI) omits the header in v4.
    if not tsv.startswith("level\t"):
        tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" + tsv
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            text = row["text"].strip()
            if int(row["level"]) != 5 or not text:
                continue
            result.append(Word(text, int(row["left"]), int(row["top"]),
                               int(row["width"]), int(row["height"]), float(row["conf"]),
                               tuple(int(row[k]) for k in ("page_num", "block_num", "par_num", "line_num"))))
        except (ValueError, KeyError, TypeError):
            continue
    return result


def target_at(words: list[Word], x: float, y: float, tolerance: int = 5) -> Target | None:
    hits = [w for w in words if w.confidence >= 35 and
            w.x - tolerance <= x <= w.x + w.width + tolerance and
            w.y - tolerance <= y <= w.y + w.height + tolerance and
            re.search(r"[A-Za-z]{2}|^[aAiI][.!?,:;]?$", w.text)]
    if not hits:
        return None
    hit = min(hits, key=lambda w: abs(x - w.x - w.width / 2) + abs(y - w.y - w.height / 2))
    # Keep immediate adjacent lines from the same paragraph for wrapped phrases.
    nearby = [w for w in words if w.line[:3] == hit.line[:3] and
              abs(w.line[3] - hit.line[3]) <= 1 and w.confidence >= 25]
    nearby.sort(key=lambda w: (w.line, w.x))
    pieces, start, end, length = [], 0, 0, 0
    for word in nearby:
        if word == hit:
            start, end = length, length + len(word.text)
        pieces.append(word.text)
        length += len(word.text) + 1
    context = " ".join(pieces)
    # Trim OCR punctuation, preserving apostrophes inside the word.
    match = re.search(r"[A-Za-z]+(?:['’][A-Za-z]+)*", context[start:end])
    if not match:
        return None
    start, end = start + match.start(), start + match.end()
    # Center the context window so that a word near the right edge is retained.
    left = max(0, start - 180)
    right = min(len(context), max(end + 180, left + 360))
    return local_target(context[left:right], start - left, end - left)


class OCR:
    """Use the installed Tesseract C library, avoiding a CLI/pip dependency.

    Own one instance on a single worker thread. Buffers remain alive until TSV
    extraction finishes, and all native allocations have matching frees.
    """
    def __init__(self):
        library = ctypes.util.find_library("tesseract")
        if not library:
            raise RuntimeError("缺少 Tesseract 库。请查看 README 的依赖安装说明。")
        self.lib = C.CDLL(library)
        signatures = {
            "TessBaseAPICreate": (C.c_void_p, []),
            "TessBaseAPIInit3": (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            "TessBaseAPISetPageSegMode": (None, [C.c_void_p, C.c_int]),
            "TessBaseAPISetVariable": (C.c_int, [C.c_void_p, C.c_char_p, C.c_char_p]),
            "TessBaseAPISetImage": (None, [C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int]),
            "TessBaseAPISetSourceResolution": (None, [C.c_void_p, C.c_int]),
            "TessBaseAPIRecognize": (C.c_int, [C.c_void_p, C.c_void_p]),
            "TessBaseAPIGetTsvText": (C.c_void_p, [C.c_void_p, C.c_int]),
            "TessDeleteText": (None, [C.c_void_p]),
            "TessBaseAPIClear": (None, [C.c_void_p]),
            "TessBaseAPIDelete": (None, [C.c_void_p]),
        }
        for name, (restype, argtypes) in signatures.items():
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = restype, argtypes
        self.handle = self.lib.TessBaseAPICreate()
        if self.lib.TessBaseAPIInit3(self.handle, str(ROOT / "tessdata").encode(), b"eng"):
            self.close()
            raise RuntimeError("英文 OCR 模型加载失败，请确认 tessdata/eng.traineddata 存在。")
        # Auto segmentation preserves paragraph/line relationships for phrase matching.
        self.lib.TessBaseAPISetPageSegMode(self.handle, 3)
        self.lib.TessBaseAPISetVariable(self.handle, b"user_defined_dpi", b"150")

    def recognize(self, pixels: bytes, width: int, height: int, channels: int, stride: int) -> list[Word]:
        self.lib.TessBaseAPIClear(self.handle)
        # Invert dark themes locally; Tesseract's automatic inversion is less
        # reliable on sparse cropped screen regions.
        samples = pixels[::max(1, len(pixels) // 2000)]
        if samples and sorted(samples)[len(samples) // 2] < 100:
            pixels = pixels.translate(bytes.maketrans(bytes(range(256)), bytes(reversed(range(256)))))
        buffer = C.create_string_buffer(pixels)
        self.lib.TessBaseAPISetImage(self.handle, buffer, width, height, channels, stride)
        self.lib.TessBaseAPISetSourceResolution(self.handle, 150)
        if self.lib.TessBaseAPIRecognize(self.handle, None):
            return []
        text = self.lib.TessBaseAPIGetTsvText(self.handle, 0)
        if not text:
            return []
        try:
            return parse_tsv(C.string_at(text).decode("utf-8", errors="replace"))
        finally:
            self.lib.TessDeleteText(text)

    def close(self):
        if getattr(self, "handle", None):
            self.lib.TessBaseAPIDelete(self.handle)
            self.handle = None
