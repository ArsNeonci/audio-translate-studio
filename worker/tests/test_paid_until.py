"""The monthly paid-until date read from the owner's status.json: lock after the date (online or not), unlock when the owner moves it, clock set back."""
from email.utils import formatdate
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_translate.api import license as lease, paid_until

PLACES = ['https://a.example/feed', 'https://b.example/feed']
MACHINE = 'ab' * 32
CODE = paid_until.device_code(MACHINE)
DAY = 86400
T0 = 1_800_000_000.0   # "now" of the tests


def iso(stamp):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat().replace('+00:00', 'Z')


class Reply(io.BytesIO):
    def __init__(self, body, date):
        super().__init__(body); self.headers = {'Date': formatdate(date, usegmt=True)}
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class PaidUntilTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.files, self.server_time = {}, T0
        for patcher in (patch.object(paid_until, 'DATA', Path(self.temp.name)), patch.dict(os.environ, {'AUDIO_ENDPOINT_MIRRORS': ','.join(PLACES)})):
            patcher.start(); self.addCleanup(patcher.stop)

    def publish(self, serial, devices, strict=False, place=None, message='Liên hệ 0900'):
        body = json.dumps({'serial': serial, 'updated': iso(self.server_time), 'strict': strict, 'message': message, 'devices': devices}).encode()
        for base in ([place] if place else PLACES): self.files[base + '/status.json'] = body

    def opener(self, request, timeout=None):
        body = self.files.get(request.full_url)
        if body is None: raise OSError('unreachable')
        return Reply(body, self.server_time)

    def refresh(self, local=T0): return paid_until.refresh(MACHINE, self.opener, local=local)

    def test_the_device_code_is_short_stable_and_not_the_machine_id(self):
        self.assertRegex(CODE, r'^[0-9a-f]{16}$'); self.assertEqual(CODE, paid_until.device_code(MACHINE.upper())); self.assertNotIn(CODE, MACHINE)

    def test_paid_ahead_is_ok_and_the_reminder_starts_five_days_before(self):
        self.publish(1, {CODE: iso(T0 + 20 * DAY)}); self.refresh()
        self.assertEqual(paid_until.state(local=T0)['status'], 'OK')
        soon = paid_until.state(local=T0 + 17 * DAY)
        self.assertEqual((soon['status'], soon['days_left'], soon['device_code']), ('DUE_SOON', 3, CODE))
        self.assertEqual(soon['message'], 'Liên hệ 0900')

    def test_after_the_date_the_device_is_locked_even_offline_and_the_gate_refuses_new_work(self):
        self.publish(1, {CODE: iso(T0 + DAY)}); self.refresh()
        self.files.clear()                                                         # no network any more
        self.assertEqual(paid_until.state(local=T0 + 2 * DAY)['status'], 'OVERDUE')
        with patch('time.time', lambda: T0 + 2 * DAY), patch.object(lease, 'machine_id', lambda: MACHINE):
            denied = lease.paid_until_denial()
        self.assertEqual(denied.status_code, 403); self.assertEqual(json.loads(denied.body)['error'], 'PAYMENT_DUE')

    def test_the_owner_moving_the_date_forward_unlocks_on_the_next_read(self):
        self.publish(1, {CODE: iso(T0 - DAY)}); self.refresh()
        self.assertEqual(paid_until.state(local=T0)['status'], 'OVERDUE')
        self.publish(2, {CODE: iso(T0 + 30 * DAY)})
        real = paid_until.refresh
        with patch('time.time', lambda: T0 + 16 * 60), patch.object(lease, 'machine_id', lambda: MACHINE), \
             patch.object(paid_until, 'refresh', lambda machine: real(machine, self.opener, local=T0 + 16 * 60)):
            self.assertIsNone(lease.paid_until_denial())                          # the gate itself read the file again (locked: every 15 minutes)
        self.assertEqual(paid_until.state(local=T0 + 16 * 60)['status'], 'OK')

    def test_setting_the_clock_back_does_not_stretch_the_paid_period(self):
        self.server_time = T0 + 10 * DAY                                           # the true time, as the server's Date header says
        self.publish(1, {CODE: iso(T0 + 5 * DAY)}); self.refresh(local=T0 + 10 * DAY)
        self.assertEqual(paid_until.state(local=T0)['status'], 'OVERDUE')          # the PC clock now says ten days earlier
        self.server_time = T0 + 12 * DAY                                           # and a PC clock that is simply wrong (behind) gets the server time
        self.refresh(local=T0)
        self.assertEqual(paid_until.state(local=T0)['status'], 'OVERDUE')

    def test_an_older_copy_from_a_lagging_place_does_not_undo_a_newer_one(self):
        self.publish(5, {CODE: iso(T0 - DAY)}); self.refresh()
        self.publish(4, {CODE: iso(T0 + 30 * DAY)}, place=PLACES[0]); self.files.pop(PLACES[1] + '/status.json')
        self.refresh()
        self.assertEqual(paid_until.state(local=T0)['status'], 'OVERDUE')

    def test_the_highest_serial_of_the_places_wins(self):
        self.publish(7, {CODE: iso(T0 + 30 * DAY)}, place=PLACES[1]); self.publish(6, {CODE: iso(T0 - DAY)}, place=PLACES[0])
        self.refresh(); self.assertEqual(paid_until.state(local=T0)['status'], 'OK')

    def test_an_unlisted_device_may_work_unless_the_file_is_strict(self):
        self.publish(1, {'0' * 16: iso(T0 + DAY)}); self.refresh()
        self.assertEqual(paid_until.state(local=T0)['status'], 'UNMANAGED')
        self.publish(2, {'0' * 16: iso(T0 + DAY)}, strict=True); self.refresh()
        self.assertEqual(paid_until.state(local=T0)['status'], 'OVERDUE')

    def test_never_read_or_no_places_means_no_lock(self):
        self.assertEqual(paid_until.state(local=T0)['status'], 'UNMANAGED')
        self.publish(1, {CODE: iso(T0 - DAY)}); self.refresh()
        with patch.dict(os.environ, {'AUDIO_ENDPOINT_MIRRORS': ''}): self.assertEqual(paid_until.state(local=T0)['status'], 'UNMANAGED')
        with patch.dict(os.environ, {'AUDIO_ENDPOINT_MIRRORS': ''}), patch.object(lease, 'machine_id', lambda: MACHINE): self.assertIsNone(lease.paid_until_denial())

    def test_a_broken_file_changes_nothing(self):
        self.publish(1, {CODE: iso(T0 + 30 * DAY)}); self.refresh()
        for base in PLACES: self.files[base + '/status.json'] = b'{"serial": "x"}'
        self.assertFalse(self.refresh()['ok'])
        self.assertEqual(paid_until.state(local=T0)['status'], 'OK')


if __name__ == '__main__':
    unittest.main()
