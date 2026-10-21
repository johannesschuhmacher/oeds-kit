# SPDX-FileCopyrightText: OEDS Contributors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path


class FakeDisplay:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.warnings: list[str] = []

    def display(self, message: str) -> None:
        self.messages.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


class FakeCallbackBase:
    def __init__(self) -> None:
        self._display = FakeDisplay()


class FakeStats:
    processed = ["intern-test"]

    def __init__(self, *, failed: bool) -> None:
        self.failed = failed

    def summarize(self, host: str) -> dict[str, int]:
        return {
            "ok": 1,
            "changed": 0,
            "unreachable": 0,
            "failures": 1 if self.failed else 0,
            "skipped": 0,
            "rescued": 0,
            "ignored": 0,
        }


@contextmanager
def fake_ansible_modules():
    module_names = [
        "ansible",
        "ansible.plugins",
        "ansible.plugins.callback",
    ]
    previous = {name: sys.modules.get(name) for name in module_names}

    ansible_module = types.ModuleType("ansible")
    plugins_module = types.ModuleType("ansible.plugins")
    callback_module = types.ModuleType("ansible.plugins.callback")
    callback_module.CallbackBase = FakeCallbackBase

    sys.modules["ansible"] = ansible_module
    sys.modules["ansible.plugins"] = plugins_module
    sys.modules["ansible.plugins.callback"] = callback_module

    try:
        yield
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def load_oeds_mail_module():
    module_path = Path(__file__).resolve().parents[1] / "playbooks" / "callback_plugins" / "oeds_mail.py"
    spec = importlib.util.spec_from_file_location("oeds_mail_test_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load oeds_mail callback module.")

    module = importlib.util.module_from_spec(spec)
    with fake_ansible_modules():
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    return module


@contextmanager
def isolated_oeds_env(values: dict[str, str]):
    saved = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("OEDS_")
    }
    for key in saved:
        os.environ.pop(key, None)
    os.environ.update(values)

    try:
        yield
    finally:
        for key in list(os.environ):
            if key.startswith("OEDS_"):
                os.environ.pop(key, None)
        os.environ.update(saved)


class AnsibleMailRateLimitTest(unittest.TestCase):
    def test_rate_limit_seconds_can_be_configured_in_seconds_or_minutes(self) -> None:
        module = load_oeds_mail_module()

        with isolated_oeds_env({"OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS": "45"}):
            self.assertEqual(
                module._get_rate_limit_seconds(
                    seconds_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS",),
                    minutes_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES",),
                    default=3600,
                ),
                45,
            )

        with isolated_oeds_env({"OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES": "2.5"}):
            self.assertEqual(
                module._get_rate_limit_seconds(
                    seconds_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS",),
                    minutes_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES",),
                    default=3600,
                ),
                150,
            )

        with isolated_oeds_env({"OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS": "bad"}):
            self.assertEqual(
                module._get_rate_limit_seconds(
                    seconds_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS",),
                    minutes_names=("OEDS_ANSIBLE_EMAIL_RATE_LIMIT_MINUTES",),
                    default=3600,
                ),
                3600,
            )

    def test_rate_limit_persists_in_state_file(self) -> None:
        module = load_oeds_mail_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir) / "ansible_mail_state.json"
            config = module.MailConfig(
                enabled=True,
                mailhost="smtp.example.test",
                port=25,
                fromaddr="from@example.test",
                toaddrs=("to@example.test",),
                subject_template=module.DEFAULT_SUBJECT,
                username="",
                password="",
                use_starttls=False,
                use_ssl=False,
                timeout=15,
                dry_run=False,
                dry_run_file="",
                rate_limit_seconds=3600,
                rate_limit_state_file=str(state_file),
            )

            self.assertFalse(module._is_rate_limited(config, "OEDS Ansible FAILED: smoke.yml"))
            self.assertTrue(module._is_rate_limited(config, "OEDS Ansible FAILED: smoke.yml"))
            self.assertFalse(module._is_rate_limited(config, "OEDS Ansible SUCCESS: smoke.yml"))

    def test_callback_suppresses_duplicate_status_mail(self) -> None:
        module = load_oeds_mail_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "OEDS_ANSIBLE_EMAIL_LOAD_CRAWLER_ENV": "false",
                "OEDS_ANSIBLE_EMAIL_MAILHOST": "smtp.example.test",
                "OEDS_ANSIBLE_EMAIL_FROMADDR": "from@example.test",
                "OEDS_ANSIBLE_EMAIL_TOADDRS": "to@example.test",
                "OEDS_ANSIBLE_EMAIL_RATE_LIMIT_SECONDS": "3600",
                "OEDS_ANSIBLE_EMAIL_RATE_LIMIT_STATE_FILE": str(Path(temp_dir) / "ansible_mail_state.json"),
            }
            with isolated_oeds_env(env):
                callback = module.CallbackModule()
                sent_subjects: list[str] = []

                def record_message(config, subject: str, body: str) -> None:
                    sent_subjects.append(subject)

                callback._send_message = record_message
                callback.v2_playbook_on_stats(FakeStats(failed=True))
                callback.v2_playbook_on_stats(FakeStats(failed=True))

        self.assertEqual(sent_subjects, ["OEDS Ansible FAILED: unknown playbook"])


if __name__ == "__main__":
    unittest.main()
