# -*- coding: utf-8 -*-
"""
  monitor_test.py
  --------------

  TxTrader monitor unit/regression test script

  Copyright (c) 2018 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
import pytest
from txtrader_monitor import Monitor
import os
import time
import ujson as json
from pprint import pprint

test_host = os.environ['TXTRADER_HOST']
test_port = os.environ['TXTRADER_TCP_PORT']
test_username = os.environ['TXTRADER_USERNAME']
test_password = os.environ['TXTRADER_PASSWORD']


def _listening(timeout=1):
    return bool(os.system(f'wait-for-it -s {test_host}:{test_port} -t {timeout}'))


@pytest.fixture(scope='module')
def server():
    print()

    print('waiting for server to be listening')
    # wait up to 15 seconds for server to be listening
    start = time.time()
    while not _listening():
        assert time.time() - start < 15, "timed out waiting for server"
    assert _listening(), 'server should be listening'

    yield True


def dump(label, o):
    print('%s:\n%s' % (label, json.dumps(o, indent=2, separators=(',', ':'))))


# callback will store update messages in _rx, and return False to when a time update arrives
def _callback(label, msg):
    print('%s: %s' % (label, msg))
    _rx[label] = msg
    return label != 'TIME'


_rx = {}


def test_monitor_connect_and_wait_for_time_update(server):

    monitor = Monitor(username=test_username, password=test_password, callbacks={'*': _callback})

    print(f"\ntxtrader monitor connected: {monitor}")
    assert monitor
    print('waiting for time update...')
    monitor.run()
    print('monitor run() returned')
    assert 'STATUS' in _rx
    assert 'TIME' in _rx
    assert 'SHUTDOWN' in _rx


_rx_accounts = {}
