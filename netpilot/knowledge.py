"""Local retrieval over troubleshooting runbooks.

A small TF-IDF index built with the standard library, so it runs offline
with no model downloads. Each runbook is split into sections, and the agent
attaches the best-matching sections to its findings.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by for from how i if in is it of on or that the this to was what when why with you your".split())


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


@dataclass
class Passage:
    source: str
    heading: str
    text: str


class RunbookIndex:
    def __init__(self, passages: list[Passage]):
        self.passages = passages
        self._tf = [Counter(_tokens(p.heading + " " + p.text)) for p in passages]
        df = Counter(t for tf in self._tf for t in tf)
        n = len(passages) or 1
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1 for t, c in df.items()}
        self._norms = [math.sqrt(sum((c * self._idf[t]) ** 2 for t, c in tf.items())) or 1.0 for tf in self._tf]

    @classmethod
    def from_dir(cls, folder: Path) -> "RunbookIndex":
        passages: list[Passage] = []
        for path in sorted(folder.glob("*.md")):
            heading, lines = path.stem, []
            for line in path.read_text().splitlines():
                if line.startswith("#"):
                    if lines:
                        passages.append(Passage(path.name, heading, "\n".join(lines).strip()))
                    heading, lines = line.lstrip("# ").strip(), []
                else:
                    lines.append(line)
            if lines:
                passages.append(Passage(path.name, heading, "\n".join(lines).strip()))
        return cls([p for p in passages if p.text])

    def search(self, query: str, k: int = 2, min_score: float = 0.05) -> list[tuple[float, Passage]]:
        q = Counter(_tokens(query))
        if not q:
            return []
        qv = {t: c * self._idf.get(t, 0.0) for t, c in q.items()}
        qn = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        scored = []
        for i, tf in enumerate(self._tf):
            dot = sum(v * tf.get(t, 0) * self._idf.get(t, 0.0) for t, v in qv.items())
            score = dot / (qn * self._norms[i])
            if score >= min_score:
                scored.append((score, self.passages[i]))
        scored.sort(key=lambda s: s[0], reverse=True)
        return scored[:k]


def default_index() -> RunbookIndex:
    return RunbookIndex.from_dir(Path(__file__).parent / "runbooks")
