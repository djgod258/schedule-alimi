import unittest
from unittest.mock import patch

import notifier_telegram as tg


class _Response:
    ok = True

    def __init__(self, updates):
        self._updates = updates

    def json(self):
        return {"result": self._updates}


class FetchUpdatesChatFilterTest(unittest.TestCase):
    def test_only_configured_chat_is_processed(self):
        updates = [
            {"update_id": 1, "message": {"chat": {"id": -10042}, "text": "/fixed"}},
            {"update_id": 2, "message": {"chat": {"id": -99999}, "text": "/list"}},
            {
                "update_id": 3,
                "callback_query": {
                    "id": "expected",
                    "data": "done:mine",
                    "message": {"chat": {"id": -10042}},
                },
            },
            {
                "update_id": 4,
                "callback_query": {
                    "id": "other",
                    "data": "done:not-mine",
                    "message": {"chat": {"id": -99999}},
                },
            },
        ]

        with (
            patch.object(tg, "TELEGRAM_CHAT_ID", "-10042"),
            patch.object(tg.requests, "get", return_value=_Response(updates)),
            patch.object(tg, "_answer_callback") as answer_callback,
        ):
            done, commands, texts, offset = tg.fetch_updates(0)

        self.assertEqual(done, ["mine"])
        self.assertEqual(commands, ["/fixed"])
        self.assertEqual(texts, [])
        self.assertEqual(offset, 4)
        answer_callback.assert_called_once_with("expected")


if __name__ == "__main__":
    unittest.main()
