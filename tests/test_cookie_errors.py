"""Ошибки cookies: понятный текст и повтор без них."""
from __future__ import annotations

import unittest

from vertcut import downloader


class CookieErrorTest(unittest.TestCase):
    def test_detects_locked_cookie_db(self):
        exc = Exception("ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271")
        self.assertTrue(downloader._is_cookie_db_error(exc))

    def test_other_errors_are_not_cookie_errors(self):
        self.assertFalse(downloader._is_cookie_db_error(Exception("Video unavailable")))
        self.assertFalse(downloader._is_cookie_db_error(Exception("HTTP Error 403")))

    def test_message_explains_what_to_do(self):
        exc = Exception("ERROR: Could not copy Chrome cookie database.")
        text = downloader._fmt_err(exc)
        self.assertIn("Chrome", text)
        self.assertIn("Edge", text)
        self.assertIn("без cookies", text)

    def test_generic_auth_message_still_works(self):
        text = downloader._fmt_err(Exception("Sign in to confirm you are not a bot"))
        self.assertIn("авторизац", text.lower())


if __name__ == "__main__":
    unittest.main()
