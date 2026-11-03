"""The production-write gate: one declared door, one word per write, two rails nobody relaxes."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prod_write_gate import Gate, authorisation, verdict  # noqa: E402

GATE = Gate(declared="prod-exec.sh", word="PROD OK", closed=("resolve-connection.sh",))
WRITE = 'bash .claude/skills/db-explorer/scripts/prod-exec.sh "INSERT INTO providers (id) VALUES (1)"'
READ = 'bash .claude/skills/db-explorer/scripts/prod-query.sh "SELECT count(*) FROM providers"'

SAID = [("2026-11-03T18:00:00Z", "заведи провайдера Payswix со ставками из сообщения Анастасии"),
        ("2026-11-03T18:05:00Z", "PROD OK")]


class TheWord(unittest.TestCase):
    def test_the_developer_s_word_authorises_the_run(self):
        self.assertEqual(authorisation(SAID, "PROD OK"), "2026-11-03T18:05:00Z")

    def test_a_word_already_spent_does_not_cover_the_next_write(self):
        self.assertIsNone(authorisation(SAID, "PROD OK", spent="2026-11-03T18:05:00Z"))

    def test_a_newer_word_after_a_spent_one_authorises_again(self):
        said = SAID + [("2026-11-03T18:40:00Z", "PROD OK")]
        self.assertEqual(authorisation(said, "PROD OK", spent="2026-11-03T18:05:00Z"),
                         "2026-11-03T18:40:00Z")

    def test_nothing_the_developer_said_is_an_authorisation(self):
        self.assertIsNone(authorisation([("2026-11-03T18:00:00Z", "ок, делай")], "PROD OK"))

    def test_the_word_inside_a_longer_word_does_not_count(self):
        self.assertIsNone(authorisation([("2026-11-03T18:00:00Z", "PROD OKAY?")], "PROD OK"))

    def test_a_message_with_no_timestamp_cannot_be_spent_so_it_does_not_authorise(self):
        self.assertIsNone(authorisation([("", "PROD OK")], "PROD OK"))


class TheDoor(unittest.TestCase):
    def test_a_read_is_none_of_the_gate_s_business(self):
        self.assertIsNone(verdict(READ, GATE, []))

    def test_a_write_without_the_word_is_denied(self):
        decision, reason, _ = verdict(WRITE, GATE, [])
        self.assertEqual(decision, "deny")
        self.assertIn("PROD OK", reason)

    def test_a_write_on_the_word_is_allowed_and_names_the_authorisation_it_spends(self):
        self.assertEqual(verdict(WRITE, GATE, SAID),
                         ("allow", "the developer's `PROD OK` in this conversation covers this run",
                          "2026-11-03T18:05:00Z"))

    def test_the_second_write_on_one_word_is_denied(self):
        decision, _, _ = verdict(WRITE, GATE, SAID, spent="2026-11-03T18:05:00Z")
        self.assertEqual(decision, "deny")

    def test_a_route_around_the_door_is_denied_even_with_the_word(self):
        decision, reason, _ = verdict(
            'source .claude/skills/db-explorer/scripts/resolve-connection.sh && psql -c "UPDATE clients SET x=1 WHERE id=2"',
            GATE, SAID)
        self.assertEqual(decision, "deny")
        self.assertIn("not the door", reason)

    def test_a_project_that_declares_no_door_gets_no_opinion(self):
        self.assertIsNone(verdict(WRITE, Gate("", "PROD OK", ()), SAID))


class RailsNobodyRelaxes(unittest.TestCase):
    """Two denials the developer's word does not lift."""

    def test_a_schema_change_is_denied_with_the_word(self):
        decision, reason, _ = verdict(
            'bash prod-exec.sh "ALTER TABLE providers ADD COLUMN slug text"', GATE, SAID)
        self.assertEqual(decision, "deny")
        self.assertIn("migration", reason)

    def test_a_truncate_is_denied_with_the_word(self):
        decision, _, _ = verdict('bash prod-exec.sh "TRUNCATE settlement_records"', GATE, SAID)
        self.assertEqual(decision, "deny")

    def test_an_update_with_no_where_is_denied_with_the_word(self):
        decision, reason, _ = verdict(
            'bash prod-exec.sh "UPDATE provider_acquirer_fees SET acquirer_refund_fee = 0"', GATE, SAID)
        self.assertEqual(decision, "deny")
        self.assertIn("WHERE", reason)

    def test_an_update_that_names_its_rows_passes(self):
        decision, _, _ = verdict(
            'bash prod-exec.sh "UPDATE provider_acquirer_fees SET acquirer_refund_fee = 0.30 '
            'WHERE provider_id = \'psxprv\'"', GATE, SAID)
        self.assertEqual(decision, "allow")

    def test_an_insert_needs_no_where(self):
        self.assertEqual(verdict(WRITE, GATE, SAID)[0], "allow")


if __name__ == "__main__":
    unittest.main()
