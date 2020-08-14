# -*- coding: utf-8 -*-
"""
  client_test.py
  --------------

  TxTrader client unit/regression test script

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

from txtrader_client import API

import ujson as json
from pprint import pprint
import pytest
import subprocess
import time

test_mode = 'RTX'
test_account = 'REALTICKDEMO.REALTICK.DEMO32.TRADING'

QUERY_POSITION_ITERS = 10
QUERY_ACCOUNT_ITERS = 10


@pytest.fixture(scope='module')
def api():
    api = API(test_mode)
    assert api
    start = time.time()
    while api.status() != 'Up':
        assert (time.time() - start) < 60, "timeout waiting for api initialization"
        time.sleep(1)

    print('\ntxtrader client connected: %s' % api)
    yield api


def dump(label, o):
    print('%s:\n%s' % (label, json.dumps(o, indent=2, separators=(',', ':'))))


def test_version(api):
    v = api.version()
    assert v
    pprint(v)
    assert type(v) == dict
    assert 'python' in v
    assert 'txtrader' in v


def test_status(api):
    s = api.status()
    assert s
    pprint(s)

    start_time = time.time()
    while api.status() != 'Up':
        assert time.time() - start_time < 30, 'timeout waiting for initialization'
    assert api.status() == 'Up'


def test_symbol_functions(api):
    symbols = api.query_symbols()
    assert type(symbols) == list
    assert symbols != None

    s = api.add_symbol('IBM')
    assert s
    assert type(s) == dict
    pprint(s)

    d = api.query_symbol('IBM')
    assert d
    assert type(d) == dict
    pprint(d)


def test_query_positions(api):
    for i in range(QUERY_POSITION_ITERS):
        p = api.query_positions()
        assert p
        assert type(p) == dict
        assert test_account in p.keys()
        assert type(p[test_account]) == dict


def test_query_account_data(api):
    for i in range(QUERY_ACCOUNT_ITERS):
        p = api.query_account(test_account)
        assert p
        assert type(p) == dict
        assert '_cash' in p.keys()
        assert type(p['_cash']) == float
