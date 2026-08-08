"""
service_auth.py の回帰テスト。

main.py 全体(bootstrap_app/core.db初期化)を起動すると重くなるため、
service_auth_middleware だけを最小のFastAPIアプリに載せてテストする。
確認したい不変条件はシンプル:

  1. "/" と "/health_check" はCookie無しでも通る(静的シェル)。
  2. それ以外のパスはCookie無しだと401になる(直接ポートアクセス対策)。
  3. 正しいトークンのCookieがあれば通る(gateway経由のリクエストを模す)。
  4. 誤ったトークンのCookieは拒否される。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth import service_auth_middleware, SESSION_COOKIE_NAME  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    # モジュールレベルでos.environを書き換えると、同じプロセス内で他の
    # テストファイルが先に(または後に)収集された時にGATEWAY_AUTH_TOKENの
    # 値が衝突する(実際にarchlife-fastapiの既存テスト群と衝突する形で
    # 発覚した)。monkeypatchならテスト関数ごとに自動で元に戻るため安全。
    monkeypatch.setenv("GATEWAY_AUTH_TOKEN", "test-token-12345")
    app = FastAPI()
    app.middleware("http")(service_auth_middleware)

    @app.get("/")
    def root():
        return {"ok": True}

    @app.get("/health_check")
    def health_check():
        return {"ok": True}

    @app.get("/logs")
    def list_logs():
        return {"logs": []}

    return TestClient(app)


def test_public_paths_allowed_without_cookie(client):
    assert client.get("/").status_code == 200
    assert client.get("/health_check").status_code == 200


def test_protected_path_rejected_without_cookie(client):
    resp = client.get("/logs")
    assert resp.status_code == 401


def test_protected_path_allowed_with_correct_token(client):
    client.cookies.set(SESSION_COOKIE_NAME, "test-token-12345")
    resp = client.get("/logs")
    assert resp.status_code == 200


def test_protected_path_rejected_with_wrong_token(client):
    client.cookies.set(SESSION_COOKIE_NAME, "wrong-token")
    resp = client.get("/logs")
    assert resp.status_code == 401
