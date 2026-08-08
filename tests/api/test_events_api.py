from tests.api.test_runs_api import client


def test_event_endpoint_returns_json_array() -> None:
    test_client, services = client()
    response = test_client.get(f"/api/runs/{services.run_service.run.id}/events")
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), list)
