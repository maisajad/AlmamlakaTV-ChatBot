"""Run the evals against a deployed instance instead of an in-process ChatBot.

    python -m eval.answer_eval --url https://your-app.onrender.com
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class RemoteBot:
    """Same chat(session_id, message) shape as app.pipeline.ChatBot, over HTTP."""

    def __init__(self, base_url: str, timeout: float = 180):
        self.url = base_url.rstrip("/") + "/api/chat"
        self.timeout = timeout

    def chat(self, session_id: str | None, message: str) -> dict:
        body = json.dumps({"message": message, "session_id": session_id}).encode("utf-8")
        for attempt in range(3):  # a sleeping free instance can drop the first request while waking
            try:
                request = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(10)
