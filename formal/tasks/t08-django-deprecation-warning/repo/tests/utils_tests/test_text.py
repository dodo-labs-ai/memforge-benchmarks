from django.test import SimpleTestCase
from django.utils.text import Truncator


class TruncatorTests(SimpleTestCase):
    def test_chars(self):
        self.assertEqual(Truncator("The quick brown fox").chars(9), "The quick…")
