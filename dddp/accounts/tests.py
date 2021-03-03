"""Django DDP Accounts test suite."""
from __future__ import unicode_literals

import sys
from dddp import tests
from django.contrib.auth import get_user_model


# gevent-websocket doesn't work with Python 3 yet
@tests.expected_failure_if(sys.version_info.major == 3)
class AccountsTestCase(tests.DDPServerTestCase):

    def test_login_no_accounts(self):
        sockjs = self.server.sockjs('/sockjs/1/a/websocket')

        resp = sockjs.websocket.recv()
        self.assertEqual(resp, 'o')

        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'server_id': '0'},
            ],
        )

        sockjs.connect('1', 'pre2', 'pre1')
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'msg': 'connected', 'session': msgs[0]['session']},
            ],
        )

        id_ = sockjs.call(
            'login', {'user': 'invalid@example.com', 'password': 'foo'},
        )
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {
                    'msg': 'result', 'id': id_,
                    'error': {
                        'error': 403, 'reason': 'Authentication failed.',
                    },
                },
            ],
        )

        sockjs.close()

    def test_login_new_account(self):
        User = get_user_model()
        new_user = User.objects.create_user(
            'user@example.com', 's3cre7-pa55w0rd!',
        )
        sockjs = self.server.sockjs('/sockjs/1/a/websocket')

        resp = sockjs.websocket.recv()
        self.assertEqual(resp, 'o')

        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'server_id': '0'},
            ],
        )

        sockjs.connect('1', 'pre2', 'pre1')
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {'msg': 'connected', 'session': msgs[0]['session']},
            ],
        )

        id_ = sockjs.call(
            'login', {
                'user': 'user@example.com', 'password': 's3cre7-pa55w0rd!',
            },
        )
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {
                    'msg': 'result', 'id': id_,
                    'error': {
                        'error': 403, 'reason': 'Authentication failed.',
                    },
                },
            ],
        )

        sockjs.close()
