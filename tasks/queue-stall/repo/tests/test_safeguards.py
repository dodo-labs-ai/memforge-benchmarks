import unittest

from kestrel.app import App, QueueConfig
from kestrel.safeguards import install_stall_safeguards


class SafeguardsTest(unittest.TestCase):
    def test_the_default_configuration_starts(self):
        app = App(QueueConfig())
        install_stall_safeguards(app)
        app.start()


if __name__ == "__main__":
    unittest.main()
