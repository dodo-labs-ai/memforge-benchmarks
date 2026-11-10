from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from selenium.webdriver.firefox.webdriver import WebDriver


class Tests(StaticLiveServerTestCase):
    def test_opens(self):
        WebDriver().get(self.live_server_url)
