from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright


class Tests(StaticLiveServerTestCase):
    def test_opens(self):
        with sync_playwright() as p:
            p.chromium.launch()
