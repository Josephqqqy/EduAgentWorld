import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class ConfigTests(unittest.TestCase):
    def test_reads_dotenv_and_environment_overrides_without_exposing_key(self):
        from rollout.config import load_config

        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                'AGENT_API_KEY = "file-secret"\n'
                'AGENT_BASE_URL= "https://example.test/v1/"\n'
                'AGENT_MODEL = "fixture-model"\n'
                "AGENT_API_TYPE=openai_compatible\n"
                "AGENT_TEMPERATURE=0.2\n"
                "AGENT_MAX_TOKENS=4096\n"
                "AGENT_TIMEOUT=120\n",
                encoding="utf-8",
            )
            config = load_config(
                env_file=env_file, environ={"AGENT_API_KEY": "override-secret"}
            )

        self.assertEqual(config.api_key, "override-secret")
        self.assertEqual(config.base_url, "https://example.test/v1")
        self.assertEqual(config.model, "fixture-model")
        self.assertEqual(config.temperature, 0.2)
        self.assertEqual(config.max_tokens, 4096)
        self.assertEqual(config.timeout, 120)
        self.assertNotIn("override-secret", repr(config))

    def test_rejects_missing_settings_and_unsupported_type(self):
        from rollout.config import load_config

        with TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            with self.assertRaisesRegex(ValueError, "AGENT_API_KEY"):
                load_config(env_file=env_file, environ={})
            with self.assertRaisesRegex(ValueError, "AGENT_API_TYPE"):
                load_config(
                    env_file=env_file,
                    environ={
                        "AGENT_API_KEY": "secret",
                        "AGENT_BASE_URL": "https://example.test/v1",
                        "AGENT_MODEL": "fixture-model",
                        "AGENT_API_TYPE": "other",
                    },
                )


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class ModelClientTests(unittest.TestCase):
    def setUp(self):
        from rollout.config import ModelConfig

        self.config = ModelConfig(
            api_key="test-secret",
            base_url="https://example.test/v1",
            model="fixture-model",
            api_type="openai_compatible",
            temperature=0.2,
            max_tokens=4096,
            timeout=120,
        )

    def test_sends_messages_and_parses_text_response(self):
        from rollout.model_client import ModelClient

        requests = []

        def transport(request, timeout):
            requests.append((request, timeout))
            return FakeResponse(
                {
                    "id": "chat-1",
                    "model": "fixture-model",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "42"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 2},
                }
            )

        messages = [{"role": "user", "content": "What is 12 + 30?"}]
        result = ModelClient(self.config, transport=transport).complete(messages)

        request, timeout = requests[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(timeout, 120)
        self.assertEqual(payload["messages"], messages)
        self.assertEqual(payload["model"], "fixture-model")
        self.assertNotIn("tools", payload)
        self.assertEqual(result.content, "42")
        self.assertEqual(result.tool_calls, ())
        self.assertEqual(result.usage["prompt_tokens"], 8)
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_parses_native_tool_calls_and_preserves_assistant_message(self):
        from rollout.model_client import ModelClient

        captured = []
        assistant = {
            "role": "assistant",
            "content": "",
            "refusal": None,
            "reasoning": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "arguments": '{ "a": 12, "b": 30 }',
                    },
                }
            ],
        }

        def transport(request, timeout):
            captured.append(json.loads(request.data))
            return FakeResponse(
                {
                    "choices": [
                        {"message": assistant, "finish_reason": "tool_calls"}
                    ]
                }
            )

        tools = [{"type": "function", "function": {"name": "calculator"}}]
        result = ModelClient(self.config, transport=transport).complete(
            [{"role": "user", "content": "Calculate"}],
            tools=tools,
            tool_choice="auto",
        )

        self.assertEqual(captured[0]["tools"], tools)
        self.assertEqual(captured[0]["tool_choice"], "auto")
        self.assertEqual(
            result.message,
            {
                "role": "assistant",
                "content": "",
                "tool_calls": assistant["tool_calls"],
            },
        )
        self.assertEqual(result.tool_calls[0].id, "call-1")
        self.assertEqual(result.tool_calls[0].name, "calculator")
        self.assertEqual(result.tool_calls[0].arguments, {"a": 12, "b": 30})
        self.assertEqual(result.finish_reason, "tool_calls")

    def test_rejects_invalid_tool_arguments(self):
        from rollout.model_client import ModelClient, ModelClientError

        def transport(request, timeout):
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "calculator",
                                            "arguments": "{not-json}",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            )

        with self.assertRaisesRegex(ModelClientError, "tool arguments"):
            ModelClient(self.config, transport=transport).complete(
                [{"role": "user", "content": "Calculate"}]
            )

    def test_retries_rate_limit_but_not_authentication_failure(self):
        from rollout.model_client import ModelClient, ModelClientError

        attempts = []
        delays = []

        def transport(request, timeout):
            attempts.append(request)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 429, "rate limit", {}, None)
            return FakeResponse(
                {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
            )

        result = ModelClient(
            self.config, transport=transport, sleep=delays.append
        ).complete([{"role": "user", "content": "hello"}])
        self.assertEqual(result.content, "ok")
        self.assertEqual(len(attempts), 2)
        self.assertEqual(delays, [0.5])

        def forbidden(request, timeout):
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)

        with self.assertRaisesRegex(ModelClientError, "HTTP 401") as error:
            ModelClient(self.config, transport=forbidden).complete(
                [{"role": "user", "content": "hello"}]
            )
        self.assertNotIn(self.config.api_key, str(error.exception))
        self.assertEqual(error.exception.category, "http")
        self.assertEqual(error.exception.details, {"status_code": 401})

    def test_connection_error_exposes_only_sanitized_diagnostics(self):
        from rollout.model_client import ModelClient, ModelClientError

        def timeout(_request, timeout):
            raise TimeoutError("secret provider response")

        with self.assertRaises(ModelClientError) as caught:
            ModelClient(self.config, transport=timeout).complete(
                [{"role": "user", "content": "hello"}]
            )

        error = caught.exception
        self.assertEqual(error.category, "connection")
        self.assertEqual(error.details, {"exception_type": "TimeoutError"})
        self.assertEqual(
            str(error), "Model API connection failed: TimeoutError"
        )
        self.assertNotIn("secret provider response", str(error))


if __name__ == "__main__":
    unittest.main()
