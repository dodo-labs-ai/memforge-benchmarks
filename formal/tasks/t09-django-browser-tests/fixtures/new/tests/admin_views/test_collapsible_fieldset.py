from playwright_tests import PlaywrightTestCase


class Tests(PlaywrightTestCase):
    def test_opens(self):
        self.page.locator('summary').click()
