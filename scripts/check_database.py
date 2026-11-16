#!/usr/bin/env python3
"""Opt-in real PostgreSQL + local HTTP integration. Not a substitute for cluster image/ingress tests."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/renderer')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm-database', required=True)
    parser.add_argument('--keep-ticket', action='store_true')
    parser.add_argument('--existing-id', type=int)
    args = parser.parse_args()
    if args.confirm_database != os.environ.get('DB_NAME'):
        raise SystemExit('Confirm the exact DB_NAME before creating schema/synthetic data')
    from ticket_api import create_app
    from ticket_api.repository import connect, migrate
    from notification_renderer import create_app as renderer_app
    from werkzeug.serving import make_server
    migrate()
    renderer = make_server('127.0.0.1', 0, renderer_app())
    renderer_thread = threading.Thread(target=renderer.serve_forever, daemon=True)
    renderer_thread.start()
    previous = os.environ.get('RENDERER_URL')
    os.environ['RENDERER_URL'] = f'http://127.0.0.1:{renderer.server_port}'
    api = make_server('127.0.0.1', 0, create_app())
    api_thread = threading.Thread(target=api.serve_forever, daemon=True)
    api_thread.start()
    base = f'http://127.0.0.1:{api.server_port}'
    ticket = None

    def request(path, data=None):
        body = None if data is None else json.dumps(data).encode()
        headers = {} if body is None else {'Content-Type': 'application/json'}
        with urllib.request.urlopen(urllib.request.Request(base + path, data=body, headers=headers), timeout=10) as response:
            return response.status, json.load(response)

    try:
        assert request('/readyz')[0] == 200
        if args.existing_id:
            existing = request('/tickets/' + str(args.existing_id))[1]
            assert existing['title'].startswith('Synthetic DB check '), existing
        title = 'Synthetic DB check ' + uuid.uuid4().hex
        status, ticket = request('/tickets', {'title': title, 'priority': 'high'})
        assert status == 201 and ticket['priority'] == 'high'
        assert request('/tickets/' + str(ticket['id']))[1] == ticket
        with connect() as connection:
            row = connection.execute('SELECT title FROM tickets WHERE id=%s', (ticket['id'],)).fetchone()
            assert row['title'] == title
        preview = request(f"/tickets/{ticket['id']}/notification-preview")[1]
        assert preview['ticket_id'] == ticket['id'] and title in preview['subject']
        renderer.shutdown()
        renderer.server_close()
        try:
            request(f"/tickets/{ticket['id']}/notification-preview")
            raise AssertionError('Unavailable renderer should return 503')
        except urllib.error.HTTPError as error:
            assert error.code == 503, error
        assert request('/tickets/' + str(ticket['id']))[1] == ticket
        print(json.dumps({'result': 'passed', 'ticket_id': ticket['id'],
                          'existing_ticket_read': args.existing_id,
                          'checks': ['schema', 'ready', 'create', 'read', 'real SQL row',
                                     'HTTP renderer preview', 'renderer outage returns 503', 'ticket survives outage'],
                          'ticket_retained': args.keep_ticket}))
    finally:
        api.shutdown()
        api.server_close()
        if renderer_thread.is_alive():
            renderer.shutdown()
        renderer.server_close()
        if previous is None:
            os.environ.pop('RENDERER_URL', None)
        else:
            os.environ['RENDERER_URL'] = previous
        with connect() as connection:
            if ticket and not args.keep_ticket:
                connection.execute('DELETE FROM tickets WHERE id=%s AND title=%s', (ticket['id'], ticket['title']))
            if args.existing_id:
                connection.execute("DELETE FROM tickets WHERE id=%s AND title LIKE 'Synthetic DB check %%'",
                                   (args.existing_id,))


if __name__ == '__main__':
    main()
