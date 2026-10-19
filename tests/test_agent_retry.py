import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from src import agent


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class AgentRetryTests(unittest.TestCase):

    @patch("src.agent.time.sleep")
    @patch("src.agent.urllib.request.urlopen")
    def test_retries_503_then_succeeds(self, mock_urlopen, mock_sleep):
        error_body = b'{"error":{"message":"high demand"}}'

        error1 = HTTPError("url", 503, "Unavailable", {}, None)
        error1.fp = __import__("io").BytesIO(error_body)

        error2 = HTTPError("url", 503, "Unavailable", {}, None)
        error2.fp = __import__("io").BytesIO(error_body)

        mock_urlopen.side_effect = [
            error1,
            error2,
            FakeResponse({
                "candidates": [{
                    "content": {
                        "parts": [{"text": "Recovered successfully"}]
                    }
                }]
            }),
        ]

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = agent._chat_completion(
                [{"role": "user", "content": "test"}],
                "gemini-3.5-flash",
            )

        self.assertEqual(result["candidates"][0]["content"]["parts"][0]["text"], "Recovered successfully")
        self.assertEqual(mock_urlopen.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in mock_sleep.call_args_list],
            [1, 2],
        )

    @patch("src.agent.time.sleep")
    @patch("src.agent.urllib.request.urlopen")
    def test_does_not_retry_401(self, mock_urlopen, mock_sleep):
        error = HTTPError("url", 401, "Unauthorized", {}, None)
        error.fp = __import__("io").BytesIO(
            b'{"error":{"message":"invalid key"}}'
        )
        mock_urlopen.side_effect = error

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with self.assertRaises(RuntimeError):
                agent._chat_completion(
                    [{"role": "user", "content": "test"}],
                    "gemini-3.5-flash",
                )

        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
