"""配信タイムアウト時に受信側も再接続できることを確認する。"""
import unittest
from unittest.mock import AsyncMock
import server


class BroadcastTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_move_is_not_reported_as_a_persistent_engine_error(self):
        previous = server.latest.pop('error', None)
        try:
            await server.broadcast(dict(type='error', message='Move source frame is no longer available', source_sequence=1))
            self.assertNotIn('error', server.latest)
        finally:
            server.latest.pop('error', None)
            if previous is not None:
                server.latest['error'] = previous

    async def test_timed_out_client_is_closed_instead_of_silently_abandoned(self):
        class Client:
            send_text = AsyncMock(side_effect=TimeoutError('Backpressure'))
            close = AsyncMock()
        client = Client()
        server.clients.add(client)
        with self.assertLogs('roze', level='WARNING'):
            await server.broadcast(dict(type='frame'))
        self.assertNotIn(client, server.clients)
        client.close.assert_awaited_once()
