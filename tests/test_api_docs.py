"""
tests/test_api_docs.py
=======================
The OpenAPI spec and Swagger UI routes (Task 12).
"""


class TestApiDocs:
    def test_openapi_spec_is_served(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/api/openapi.yaml")
        assert resp.status_code == 200
        assert b"openapi:" in resp.data

    def test_openapi_spec_is_valid_yaml(self, app_module):
        import yaml

        client = app_module.app.test_client()
        resp = client.get("/api/openapi.yaml")
        spec = yaml.safe_load(resp.data)
        assert "paths" in spec
        assert "/copilot/ask" in spec["paths"]

    def test_swagger_ui_page_loads(self, app_module):
        client = app_module.app.test_client()
        resp = client.get("/api/docs")
        assert resp.status_code == 200
        assert b"swagger-ui" in resp.data

    def test_docs_do_not_require_login(self, app_module):
        client = app_module.app.test_client()
        assert client.get("/api/docs").status_code == 200
        assert client.get("/api/openapi.yaml").status_code == 200
