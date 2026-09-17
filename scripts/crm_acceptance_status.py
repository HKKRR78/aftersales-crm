"""Final acceptance status rules shared by release diagnostics.

An acceptance run passes only when every required command succeeds, the
publication gate accepts the same candidate, and the read-only check leaves
the current report pointer unchanged.
"""


def acceptance_passed(steps):
    commands = [step for step in steps if step.get("kind") == "command"]
    gates = [step for step in steps if step.get("step") == "publication_gate"]
    return (
        bool(commands)
        and all(step.get("exit_code") == 0 for step in commands)
        and len(gates) == 1
        and gates[0].get("accepted") is True
        and gates[0].get("current_pointer_unchanged") is True
    )
