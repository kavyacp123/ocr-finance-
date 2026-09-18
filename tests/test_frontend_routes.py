import pytest
from fastapi.testclient import TestClient
from app.main import app


def test_frontend_root_redirect():
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (307, 302, 301)
        assert response.headers["location"].endswith("/ui")


def test_frontend_static_serving():
    with TestClient(app) as client:
        # Check index.html
        res_index = client.get("/ui/")
        assert res_index.status_code == 200
        assert "Finance Document Intelligence" in res_index.text
        assert "tab-dashboard" in res_index.text
        assert "tab-copilot" in res_index.text
        assert "tab-investigate" in res_index.text

        # Check style.css
        res_css = client.get("/ui/style.css")
        assert res_css.status_code == 200
        assert "glass-card" in res_css.text

        # Check app.js
        res_js = client.get("/ui/app.js")
        assert res_js.status_code == 200
        assert "initDashboard" in res_js.text
