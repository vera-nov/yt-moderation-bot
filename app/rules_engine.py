from pathlib import Path


class RulesEngine:
    def __init__(self, path: str):
        """
        Initialize rules engine and load stop words
        """
        self.path = Path(path)
        self.words = self._load_words()

    def _load_words(self) -> list[str]:
        """
        Load stop words from file
        """
        if not self.path.exists():
            return []

        result: list[str] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            word = line.strip().lower()
            if word:
                result.append(word)
        return result

    def match(self, text: str | None) -> str | None:
        """
        Return matched stop word if text contains it
        """
        haystack = (text or "").lower()
        for word in self.words:
            if word in haystack:
                return word
        return None