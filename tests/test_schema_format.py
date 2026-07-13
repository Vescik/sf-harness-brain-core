from __future__ import annotations

import unittest

from jsonschema import Draft202012Validator

from scripts.schema_format import FORMAT_CHECKER


class SchemaFormatTests(unittest.TestCase):
    """Guard against regressing to a bare FormatChecker(), which silently skips date-time/uri."""

    def test_date_time_format_is_enforced(self) -> None:
        self.assertIn("date-time", FORMAT_CHECKER.checkers)
        validator = Draft202012Validator(
            {"type": "string", "format": "date-time"}, format_checker=FORMAT_CHECKER
        )
        self.assertTrue(list(validator.iter_errors("not-a-timestamp")))
        self.assertFalse(list(validator.iter_errors("2026-07-13T09:00:00Z")))
        self.assertFalse(list(validator.iter_errors("2026-07-13T09:00:00+00:00")))

    def test_uri_format_is_enforced(self) -> None:
        self.assertIn("uri", FORMAT_CHECKER.checkers)
        validator = Draft202012Validator(
            {"type": "string", "format": "uri"}, format_checker=FORMAT_CHECKER
        )
        self.assertTrue(list(validator.iter_errors("not a uri")))
        self.assertFalse(list(validator.iter_errors("https://example.sandbox.my.salesforce.com")))

    def test_non_string_values_are_left_to_type_validation(self) -> None:
        # Format checks must not fire on non-strings (mirrors jsonschema's built-in behavior).
        validator = Draft202012Validator(
            {"format": "date-time"}, format_checker=FORMAT_CHECKER
        )
        self.assertFalse(list(validator.iter_errors(12345)))


if __name__ == "__main__":
    unittest.main()
