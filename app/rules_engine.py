from pathlib import Path


class RulesEngine:
    def __init__(self, path: str):
        self.path = Path(path)
        self.words = self._load_words()

    def _load_words(self) -> list[str]:
        if not self.path.exists():
            return []

        result: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            word = line.strip().lower()
            if word:
                result.append(word)
        return result

    def match(self, text: str | None) -> str | None:
        haystack = (text or "").lower()
        for word in self.words:
            if word in haystack:
                return word
        return None