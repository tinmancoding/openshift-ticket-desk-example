#!/usr/bin/env python3
"""Opt-in HTTP acceptance. Creates one synthetic persistent ticket; never prints secrets."""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid


def request(base, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    headers = {} if body is None else {'Content-Type': 'application/json'}
    with urllib.request.urlopen(urllib.request.Request(base.rstrip('/') + path, data=body, headers=headers), timeout=60) as response:
        return response.status, json.load(response)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--url', required=True)
    cli.add_argument('--expected-version', required=True)
    cli.add_argument('--priority', default='normal')
    cli.add_argument('--existing-id', type=int, help='Read an earlier ticket to verify persistence across release/rollback')
    cli.add_argument('--confirm-create', action='store_true', required=True)
    args = cli.parse_args()
    assert request(args.url, '/readyz')[0] == 200
    assert request(args.url, '/version')[1]['version'] == args.expected_version
    if args.existing_id:
        existing = request(args.url, '/tickets/' + str(args.existing_id))[1]
        assert existing['id'] == args.existing_id
        print('Earlier ticket remains readable:', args.existing_id)
    title = 'Synthetic acceptance ' + uuid.uuid4().hex[:10]
    status, ticket = request(args.url, '/tickets', {'title': title, 'priority': args.priority,
                                                  'description': 'Disposable example test data'})
    assert status == 201, ticket
    assert ticket['priority'] == args.priority
    assert request(args.url, '/tickets/' + str(ticket['id']))[1] == ticket
    # A cold Knative backend can outlast the API's short dependency timeout.
    # Retry this safe GET only, never silently retry ticket creation.
    deadline = time.monotonic() + 120
    while True:
        try:
            status, preview = request(args.url, f"/tickets/{ticket['id']}/notification-preview")
            break
        except urllib.error.HTTPError as error:
            if error.code != 503 or time.monotonic() >= deadline:
                raise
            time.sleep(3)
    assert status == 200 and preview['ticket_id'] == ticket['id'], preview
    assert title in preview['subject'], preview
    print(json.dumps({'ticket_id': ticket['id'], 'api_version': args.expected_version,
                      'priority': ticket['priority'], 'renderer_version': preview['renderer_version'],
                      'result': 'passed'}))


if __name__ == '__main__':
    main()
