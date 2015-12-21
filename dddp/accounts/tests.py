from dddp import tests


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
                {'msg': 'connected', 'session': msgs[0].get('session', None)},
            ],
        )

        id_ = sockjs.call(
            'login', {'user': 'invalid@example.com', 'password': 'foo'},
        )
        msgs = sockjs.recv()
        self.assertEqual(
            msgs, [
                {
                    'msg': 'result',
                    'error': {
                        'error': 500,
                        'reason': "(403, 'Authentication failed.')",
                    },
                    'id': id_,
                },
            ],
        )

        sockjs.close()
