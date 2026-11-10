import unittest

from kestrel.alerts import ack_deadline_seconds, alert_channel
from kestrel.escalation import is_overdue


class EscalationTest(unittest.TestCase):
    def test_an_alert_is_overdue_after_its_deadline(self):
        self.assertTrue(is_overdue(0, ack_deadline_seconds() + 1))
        self.assertFalse(is_overdue(0, ack_deadline_seconds()))

    def test_an_alert_has_a_channel(self):
        self.assertTrue(alert_channel())


if __name__ == "__main__":
    unittest.main()
