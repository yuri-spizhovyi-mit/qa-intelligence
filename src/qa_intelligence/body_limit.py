import json

ANALYSES_PATH = "/api/v1/analyses"
MAX_BODY_BYTES = 262144


class BodyLimitMiddleware:
    """Cap analysis and review POST bodies before JSON parsing."""

    def __init__(self, app, path: str = ANALYSES_PATH, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.path = path
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not (
                scope["path"] == self.path
                or (
                    scope["path"].startswith(self.path + "/")
                    and scope["path"].endswith("/reviews")
                )
            )
        ):
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(send)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_bytes:
                await self._reject(send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": b"".join(chunks),
                    "more_body": False,
                }
            # After the body, defer to the real channel so disconnects propagate.
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, send) -> None:
        payload = json.dumps(
            {"detail": f"Request body exceeds {self.max_bytes} bytes"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
