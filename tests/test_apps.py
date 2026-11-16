import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/renderer')]
from ticket_api import create_app, PRIORITIES
from notification_renderer import create_app as renderer_app


class MemoryRepository:
    """Unit-test double only; cluster acceptance must exercise PostgreSQL."""
    def __init__(self):
        self.rows = {}

    def ready(self):
        pass

    def create(self, title, description, priority):
        item = dict(id=len(self.rows) + 1, title=title, description=description,
                    priority=priority, created_at='2026-01-01T00:00:00+00:00')
        self.rows[item['id']] = item
        return item

    def get(self, ticket_id):
        return self.rows.get(ticket_id)

    def list_recent(self):
        return list(self.rows.values())[-50:][::-1]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository()
        self.app = create_app(self.repo)
        self.client = self.app.test_client()

    def test_create_read_and_default_priority(self):
        response = self.client.post('/tickets', json={'title': ' Printer broken '})
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data['title'], 'Printer broken')
        self.assertEqual(data['priority'], 'normal')
        self.assertEqual(response.headers['Location'], f"/tickets/{data['id']}")
        self.assertEqual(self.client.get(response.headers['Location']).get_json(), data)
        self.assertEqual(self.client.get('/tickets').get_json()['tickets'], [data])

    def test_urgent_ticket(self):
        response = self.client.post('/tickets', json={'title': 'System unavailable', 'priority': 'urgent'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['priority'], 'urgent')

    def test_all_supported_priorities(self):
        for priority in PRIORITIES:
            response = self.client.post('/tickets', json={'title': 'Help', 'priority': priority})
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()['priority'], priority)

    def test_validation(self):
        for data in [[], {}, {'title': ''}, {'title': '   '}, {'title': 4},
                     {'title': 'x' * 121}, {'title': 'ok', 'description': 'x' * 2001},
                     {'title': 'ok', 'priority': []}, {'title': 'ok', 'priority': 'unknown'}]:
            self.assertEqual(self.client.post('/tickets', json=data).status_code, 400, data)
        self.assertEqual(len(self.repo.rows), 0)

    def test_invalid_json_and_content_type(self):
        self.assertEqual(self.client.post('/tickets', data='{', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post('/tickets', data='text').status_code, 415)
        self.assertEqual(self.client.post('/tickets', json={'title': 'x' * 20000}).status_code, 413)

    def test_missing_ticket(self):
        self.assertEqual(self.client.get('/tickets/999').status_code, 404)
        self.assertEqual(self.client.get('/tickets/999/notification-preview').status_code, 404)

    def test_dependency_failure_does_not_lose_ticket(self):
        def unavailable(*args):
            raise urllib.error.URLError('private dependency details')
        self.repo.create('Help', '', 'normal')
        with patch.dict(os.environ, RENDERER_URL='http://renderer.invalid'):
            client = create_app(self.repo, unavailable).test_client()
            response = client.get('/tickets/1/notification-preview')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.get_data(as_text=True))
        self.assertEqual(self.repo.get(1)['title'], 'Help')

    def test_renderer_integration_contract(self):
        renderer = renderer_app().test_client()
        def preview(url, ticket):
            response = renderer.post('/render', json=ticket)
            self.assertEqual(response.status_code, 200)
            return response.get_json()
        self.repo.create('Printer broken', '', 'high')
        with patch.dict(os.environ, RENDERER_URL='http://renderer.invalid'):
            response = create_app(self.repo, preview).test_client().get('/tickets/1/notification-preview')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket_id'], 1)
        self.assertIn('Printer broken', response.get_json()['subject'])

    def test_malformed_preview_is_rejected(self):
        self.repo.create('Help', '', 'normal')
        with patch.dict(os.environ, RENDERER_URL='http://renderer.invalid'):
            for payload in ([], {}, {'ticket_id': 999, 'subject': 'wrong ticket', 'text': 'x'}):
                client = create_app(self.repo, lambda url, ticket: payload).test_client()
                self.assertEqual(client.get('/tickets/1/notification-preview').status_code, 503)

    def test_readiness_checks_database(self):
        self.assertEqual(self.client.get('/readyz').status_code, 200)
        with patch.object(self.repo, 'ready', side_effect=OSError('secret')):
            self.assertEqual(self.client.get('/readyz').status_code, 503)
            self.assertEqual(self.client.get('/healthz').status_code, 200)

    def test_database_error_redacted(self):
        with patch.object(self.repo, 'create', side_effect=RuntimeError('password=secret')):
            response = self.client.post('/tickets', json={'title': 'Help'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.get_data(as_text=True))


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.client = renderer_app().test_client()

    def test_plain_text_preview(self):
        data = self.client.post('/render', json={'id': 42, 'title': 'Help\nplease', 'priority': 'normal'}).get_json()
        self.assertEqual(data['subject'], 'Ticket #42: Help please')
        self.assertIn('Priority: normal', data['text'])

    def test_reject_invalid_contract(self):
        for data in [[], {}, {'id': True, 'title': 'x', 'priority': 'high'},
                     {'id': -1, 'title': 'x', 'priority': 'high'},
                     {'id': 1, 'title': [], 'priority': 'high'}]:
            self.assertEqual(self.client.post('/render', json=data).status_code, 400)

    def test_stateless_health_and_version(self):
        self.assertEqual(self.client.get('/readyz').status_code, 200)
        self.assertEqual(self.client.get('/version').get_json()['component'], 'renderer')


if __name__ == '__main__':
    unittest.main()
