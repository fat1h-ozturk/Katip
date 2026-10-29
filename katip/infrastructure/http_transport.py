"""Synchronous worker facade over cancellable, event-driven Qt networking.

The facade must only run on a background thread. Each request owns its Qt
objects on that thread; no manager or reply is accessed across threads.
"""

from contextlib import contextmanager
from contextvars import ContextVar
import json as json_module
import time

import requests

_job = ContextVar("katip_http_job", default=None)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def current_job():
    return _job.get()


@contextmanager
def execution_scope(job):
    token = _job.set(job)
    try:
        yield
    finally:
        _job.reset(token)


class Response:
    def __init__(self, status, body, headers):
        self.status_code = status
        self.content = body
        self.headers = headers
        self.text = body.decode("utf-8", errors="replace")

    def json(self):
        return json_module.loads(self.text)


class HttpSession:
    def __init__(self):
        self.headers = {}

    def close(self):
        pass  # Each request's Qt objects are destroyed on their owning thread.

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method, url, *, json=None, data=None, files=None, headers=None, timeout=90):
        from PySide6.QtCore import (QByteArray, QCoreApplication, QEventLoop, QThread, QTimer, QUrl)
        from PySide6.QtNetwork import (QHttpMultiPart, QHttpPart, QNetworkAccessManager,
                                      QNetworkReply, QNetworkRequest)
        app = QCoreApplication.instance()
        if app is None or QThread.currentThread() == app.thread():
            raise RuntimeError("HTTP requests must run on a background worker with a Qt application.")
        job = _job.get()
        if job:
            job.check()
        manager = QNetworkAccessManager()
        request = QNetworkRequest(QUrl(url))
        # Never forward authorization across an unexpected redirect.
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        merged = {**self.headers, **(headers or {})}
        multipart = None
        if files:
            merged.pop("Content-Type", None)
            multipart = QHttpMultiPart(QHttpMultiPart.ContentType.FormDataType)
            for key, value in (data or {}).items():
                part = QHttpPart()
                part.setHeader(QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                               f'form-data; name="{key}"')
                part.setBody(str(value).encode("utf-8"))
                multipart.append(part)
            for key, (filename, content, mime) in files.items():
                part = QHttpPart()
                part.setHeader(QNetworkRequest.KnownHeaders.ContentDispositionHeader,
                               f'form-data; name="{key}"; filename="{filename}"')
                part.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, mime)
                part.setBody(content)
                multipart.append(part)
            body = multipart
        elif json is not None:
            merged["Content-Type"] = "application/json"
            body = QByteArray(json_module.dumps(json, ensure_ascii=False).encode("utf-8"))
        else:
            body = QByteArray(data or b"")
        for key, value in merged.items():
            request.setRawHeader(key.encode("ascii"), str(value).encode("utf-8"))
        reply = manager.post(request, body)
        if multipart:
            multipart.setParent(reply)
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        timer = QTimer()
        timer.setInterval(25)
        started = time.monotonic()
        error = []
        chunks = bytearray()

        def consume():
            chunks.extend(bytes(reply.readAll()))
            if len(chunks) > MAX_RESPONSE_BYTES and not error:
                error.append(requests.RequestException("Response exceeds local size limit"))
                reply.abort()

        def check():
            try:
                if job:
                    job.check()
                seconds = max(timeout) if isinstance(timeout, tuple) else timeout
                if time.monotonic() - started >= seconds:
                    raise requests.Timeout("Stage deadline exceeded")
            except (RuntimeError, requests.RequestException) as exc:
                error.append(exc)
                reply.abort()

        reply.readyRead.connect(consume)
        timer.timeout.connect(check)
        timer.start()
        if not reply.isFinished():
            loop.exec()
        timer.stop()
        consume()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        reply_error = reply.error()
        response_headers = {bytes(k).decode("ascii", "replace"): bytes(v).decode("utf-8", "replace")
                            for k, v in reply.rawHeaderPairs()}
        # Explicitly release all Qt objects on the creating thread.
        reply.deleteLater()
        manager.deleteLater()
        from PySide6.QtCore import QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if error:
            raise error[0]
        if status is None and reply_error != QNetworkReply.NetworkError.NoError:
            raise requests.ConnectionError("Network connection failed")
        return Response(int(status or 0), bytes(chunks), response_headers)


def http_post(url, **kwargs):
    return HttpSession().post(url, **kwargs)
