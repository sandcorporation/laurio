"""`test_gunicorn_idle_connections.py` 가 실제 gunicorn 으로 띄우는 가장 작은 WSGI 앱.

Django 를 통째로 띄우면 기동만으로 시험 하나의 CPU 한도를 넘는다 — 보려는 것은
워커가 연결을 어떻게 받는가(gunicorn 설정)뿐이라 앱은 무엇이든 된다.
"""


def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", "2")])
    return [b"ok"]
