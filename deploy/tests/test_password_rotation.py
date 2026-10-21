# SPDX-FileCopyrightText: OpenAI
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import unittest

from oeds_ops.password_rotation import (
    PASSWORD_ALPHABET,
    current_passwords,
    generate_password,
    render_env_file,
)


class PasswordRotationHelpersTest(unittest.TestCase):
    def test_generate_password_meets_complexity_and_safe_charset(self) -> None:
        password = generate_password(32)

        self.assertEqual(len(password), 32)
        self.assertTrue(any(character.islower() for character in password))
        self.assertTrue(any(character.isupper() for character in password))
        self.assertTrue(any(character.isdigit() for character in password))
        self.assertTrue(any(character in "!-_." for character in password))
        self.assertTrue(set(password).issubset(set(PASSWORD_ALPHABET)))

    def test_render_env_file_updates_existing_values_and_appends_missing_ones(self) -> None:
        original = (
            "COMPOSE_PROJECT_NAME=oeds\n"
            "OEDS_RUNTIME_DIR=/open_energy_data_server/runtime\n"
            "# keep this comment\n"
            "OEDS_DB_PASSWORD=old-db\n"
        )

        rendered = render_env_file(
            original,
            {
                "OEDS_DB_PASSWORD": "new-db",
                "OEDS_READONLY_PASSWORD": "new-ro",
            },
        )

        self.assertIn("COMPOSE_PROJECT_NAME=oeds\n", rendered)
        self.assertIn("# keep this comment\n", rendered)
        self.assertIn("OEDS_DB_PASSWORD=new-db\n", rendered)
        self.assertIn("OEDS_READONLY_PASSWORD=new-ro\n", rendered)

    def test_current_passwords_falls_back_to_public_defaults(self) -> None:
        passwords = current_passwords({"OEDS_DB_PASSWORD": "custom-db"})

        self.assertEqual(passwords["OEDS_DB_PASSWORD"], "custom-db")
        self.assertEqual(passwords["OEDS_READONLY_PASSWORD"], "readonly")
        self.assertEqual(passwords["OEDS_GRAFANA_ADMIN_PASSWORD"], "opendata")
        self.assertEqual(passwords["OEDS_PGADMIN_DEFAULT_PASSWORD"], "admin")


if __name__ == "__main__":
    unittest.main()
