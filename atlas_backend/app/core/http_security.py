"""Browser-origin and request-size guards, independent of proxy authentication."""

from starlette.responses import JSONResponse


class RequestGuard:
    """Bound request bodies before multipart parsing and reject foreign writes.

    Origin checks protect local browser sessions. They are not authentication:
    a non-browser client can omit Origin, so deployment still needs a gateway.
    """

    def __init__(self, app, origins: list[str], max_body_bytes: int):
        self.app = app
        self.origins = set(origins)
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode("latin-1")
        host = headers.get(b"host", b"").decode("latin-1")
        same_origin = f"{scope.get('scheme', 'http')}://{host}"
        if (scope["method"] not in {"GET", "HEAD", "OPTIONS"}
                and origin and origin not in self.origins and origin != same_origin):
            return await JSONResponse({"detail": "Origin not allowed."}, status_code=403)(
                scope, receive, send
            )

        chunks = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self.max_body_bytes:
                return await JSONResponse({"detail": "Request too large."}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(body)
            if not message.get("more_body", False):
                break

        pending = True

        async def bounded_receive():
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
