from django.contrib.admin.tests import AdminSeleniumTestCase
from selenium.webdriver.common.by import By


class Tests(AdminSeleniumTestCase):
    def test_opens(self):
        self.selenium.find_element(By.CSS_SELECTOR, 'summary').click()
