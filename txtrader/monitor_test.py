# -*- coding: utf-8 -*-
"""
  monitor_test.py
  --------------

  TxTrader monitor unit/regression test script

  Copyright (c) 2018 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from txtrader.monitor import Monitor
#import subprocess
#import os
#import signal
#@import time

import simplejson as json
from pprint import pprint
import pytest
import subprocess

test_user = 'txtrader_user'
test_password = 'change_this_password'


@pytest.fixture(scope='module')
def monitor():
    print()
    was_running = not bool(subprocess.call('ps fax | egrep -q [t]xtrader.tac', shell=True))
    if not was_running:
        subprocess.check_call('cd ..;make start_wait', shell=True)
    monitor = Monitor(
        user=test_user,
        password=test_password,
        callbacks = {
            'status':_callback, 
            'error':_callback,
            'time':_callback, 
            'order':_callback, 
            'execution':_callback,
            'quote':_callback,
            'trade':_callback,
            'time':_callback,
            'shutdown':_callback})
    print('\ntxtrader monitor connected: %s' % repr(monitor))
    assert monitor
    yield monitor
    if was_running:
        subprocess.check_call('cd ..;make stop_wait', shell=True)

def dump(label, o):
    print('%s:\n%s' % (label, json.dumps(o, indent=2, separators=(',', ':'))))

_rx = {}

def test_monitor_connect(monitor):
    assert monitor
    monitor.run()
    assert 'status' in _rx
    assert 'time' in _rx
    assert 'shutdown' in _rx
   
def _callback(label, msg):
   print('%s: %s' % (label, msg))
   _rx[label]=msg
   return label != 'time'
