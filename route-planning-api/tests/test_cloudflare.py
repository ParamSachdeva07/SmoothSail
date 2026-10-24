from fastapi.testclient import TestClient
from pydantic import SecretStr

from service.main import app, settings


def test_internal_refresh_cannot_be_called_without_configured_secret(monkeypatch):
    monkeypatch.setattr(settings, 'tideline_internal_token', SecretStr(''))
    with TestClient(app) as client:
        assert client.post('/internal/refresh').status_code == 404
        assert '/internal/refresh' not in client.get('/openapi.json').json()['paths']


def test_internal_refresh_requires_matching_secret_and_closes_connection(monkeypatch):
    from service import data, providers
    calls = []
    class Client:
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(settings, 'tideline_internal_token', SecretStr('test-only-token'))
    monkeypatch.setattr(data, 'connect', lambda settings: (Client(), 'test-db'))
    monkeypatch.setattr(providers, 'refresh_overviews', lambda settings, db: calls.append(db))
    with TestClient(app) as client:
        assert client.post('/internal/refresh', headers={'X-Tideline-Internal-Token': 'wrong'}).status_code == 404
        assert not calls
        response = client.post('/internal/refresh', headers={'X-Tideline-Internal-Token': 'test-only-token'})
        assert response.status_code == 200
        assert calls == ['test-db', 'closed']
