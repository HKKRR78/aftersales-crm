import unittest

from crm_acceptance_status import acceptance_passed


def command(step, exit_code=0):
    return {"step": step, "kind": "command", "exit_code": exit_code}


def gate(accepted=True, unchanged=True):
    return {
        "step": "publication_gate",
        "kind": "gate",
        "accepted": accepted,
        "current_pointer_unchanged": unchanged,
    }


class AcceptanceStatusTests(unittest.TestCase):
    def test_acceptance_requires_every_command_and_gate(self):
        steps = [command("sales"), command("cases"), command("excel"), gate()]
        self.assertTrue(acceptance_passed(steps))

    def test_failed_command_cannot_be_hidden_by_successful_gate(self):
        steps = [command("sales"), command("cases", 1), command("excel"), gate()]
        self.assertFalse(acceptance_passed(steps))

    def test_rejected_gate_is_a_failed_acceptance(self):
        steps = [command("sales"), command("cases"), command("excel"), gate(False)]
        self.assertFalse(acceptance_passed(steps))

    def test_pointer_change_is_a_failed_acceptance(self):
        steps = [command("sales"), command("cases"), command("excel"), gate(True, False)]
        self.assertFalse(acceptance_passed(steps))

    def test_timeout_is_a_failed_command(self):
        steps = [command("sales"), {"step": "excel", "kind": "command", "exit_code": None, "timeout": True}, gate()]
        self.assertFalse(acceptance_passed(steps))
