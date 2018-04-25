# -*- coding: utf-8 -*-
"""
  client_test.py
  --------------

  TxTrader client unit/regression test script

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from txtrader.client import API
#import subprocess
#import os
#import signal
#@import time

import simplejson as json
from pprint import pprint
import pytest
import subprocess

test_mode = 'RTX'
test_account = 'DEMO1.TEST.DEMO.2'

QUERY_POSITION_ITERS=10

from server_test import Server

@pytest.fixture(scope='module')
def api():
    subprocess.check_call('cd ..;make start', shell=True)
    api = API(test_mode)
    assert api
    print('\ntxtrader client connected: %s' % api)
    yield api
    subprocess.check_call('cd ..;make stop', shell=True)

def dump(label, o):
    print('%s:\n%s' % (label, json.dumps(o, indent=2, separators=(',', ':'))))

def test_version(api):
    v = api.version()
    assert v
    pprint(v)
    assert type(v)==dict
    assert 'python' in v
    assert 'txtrader' in v


def test_query_positions(api):
    for i in range(QUERY_POSITION_ITERS):
      p = api.query_positions()
      assert p
      assert type(p)==dict
      assert test_account in p.keys()
      assert type(p[test_account])==dict
