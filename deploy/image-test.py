#!/usr/local/bin/python
"""Test the actual built image before returning it as a release candidate."""
import os
import sys
sys.path.insert(0, '/app')
component = os.environ['COMPONENT']
if component == 'api':
    from ticket_api import create_app
    app = create_app()
    client = app.test_client()
    assert client.get('/healthz').status_code == 200
    assert client.get('/version').get_json()['component'] == 'api'
    # This invalid request must not require a database connection.
    assert client.post('/tickets', json={'title': ''}).status_code == 400
elif component == 'renderer':
    from notification_renderer import create_app
    client = create_app().test_client()
    result = client.post('/render', json={'id': 7, 'title': 'Printer offline', 'priority': 'normal'})
    assert result.status_code == 200, result.data
    assert result.get_json()['ticket_id'] == 7
    assert 'Printer offline' in result.get_json()['subject']
else:
    raise SystemExit('Unknown component')
print('Built-image contract checks passed:', component)
