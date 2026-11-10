import warnings
import unicodedata

from django.utils.deprecation import RemovedInDjango7100Warning, deprecate_posargs


class Truncator:
    """An object used to truncate text, either by characters or words."""

    def __init__(self, text):
        self.text = text

    def add_truncation_text(self, text, truncate=None):
        if truncate is None:
            truncate = "…"
        return f"{text}{truncate}"

    @deprecate_posargs(RemovedInDjango7100Warning, ["truncate", "html"])
    def chars(self, num, *, truncate=None, html=False):
        """Return the text truncated to be no longer than the specified number of characters."""
        self.text = unicodedata.normalize("NFC", self.text)
        if html:
            return self._truncate_html(num, truncate)
        if len(self.text) <= num:
            return self.text
        return self.add_truncation_text(self.text[:num], truncate)

    def _truncate_html(self, num, truncate):
        return self.add_truncation_text(self.text[:num], truncate)
