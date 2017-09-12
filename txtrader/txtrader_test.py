# -*- coding: utf-8 -*-
"""
  test-txtrader.py
  --------------

  TxTrader unit/regression test script

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from txtrader.client import API
import subprocess
import os
import signal
import time

import json

TEST_MODE = os.environ['TXTRADER_TEST_MODE']


class Server():
    def __init__(self):
        print('Starting test server...')
        assert subprocess.call('ps -ax | egrep [t]wistd', shell=True)
        subprocess.call('truncate --size 0 test.log', shell=True)
        self.logfile = open('test.log', 'a')
        self.process = subprocess.Popen(['envdir', '../etc/txtrader', 'twistd', '--nodaemon',
                                         '--logfile=-', '--python=../service/txtrader/txtrader.tac'], stdout=self.logfile)
        assert self.process
        print('%s created as pid %d' % (repr(self.process), self.process.pid))
        print('Waiting for txtrader listen ports...')
        while subprocess.call('netstat -ant | egrep LISTEN | egrep 50090>/dev/null', shell=True):
            time.sleep(.25)
        assert not subprocess.call(
            'ps -ax | egrep [t]wistd >/dev/null', shell=True)
        assert not subprocess.call(
            'netstat -ant | egrep LISTEN | egrep 50090>/dev/null', shell=True)
        assert not subprocess.call(
            'netstat -ant | egrep LISTEN | egrep 50070>/dev/null', shell=True)
        print('Test server ready.')

    def init(self):
        return API(TEST_MODE)

    def __del__(self):
        print('Waiting for %s to terminate...' % repr(self.process.pid))
        os.kill(self.process.pid, signal.SIGTERM)
        self.process.wait()
        print('Terminated; exit=%d' % (self.process.returncode))
        self.logfile.close()

    def __enter__(self):
        return self

    def __exit__(self, ex_type, ex_value, traceback):
        pass


def dump(label, o):
    print('%s:\n%s' % (label, json.dumps(o, indent=2, separators=(',', ':'))))


def test_init():
    print()
    with Server() as s:
        t = s.init()
        assert t
        print('waiting 1 second...')
        time.sleep(1)
        print('done')


def test_accounts():
    print()
    with Server() as s:
        t = s.init()
        assert t
        a = t.query_accounts()
        assert type(a) is list
        assert len(a)
        print('accounts=%s' % repr(a))
        account = a[0]
        assert t.set_account(account)
        info = t.query_account(account)
        assert info
        print('account[%s] info:' % account)
        print(json.dumps(info, indent=2, separators=(',', ':')))


def test_stock_prices():
    with Server() as s:
        t = s.init()
        assert t
        a = t.query_accounts()
        assert t.set_account(a[0])
        s = t.add_symbol('IBM')
        assert s
        s = t.add_symbol('FNORD')
        assert not s
        s = t.query_symbol('IBM')
        assert s
        dump('Symbol data for IBM', s)

        l = t.query_symbols()
        assert l
        dump('symbol list', l)
        assert l == ['IBM']

        s = t.add_symbol('TSLA')
        assert s
        dump('add TSLA', s)
        s = t.add_symbol('GOOG')
        assert s
        dump('add GOOG', s)
        s = t.add_symbol('AAPL')
        assert s
        dump('add AAPL', s)

        l = t.query_symbols()
        assert set(l) == set(['IBM', 'TSLA', 'GOOG', 'AAPL'])
        dump('symbol list', l)

        s = t.del_symbol('TSLA')
        assert s
        dump('del TSLA', s)

        l = t.query_symbols()
        assert set(l) == set(['IBM', 'GOOG', 'AAPL'])
        dump('symbol list', l)

        print(repr(l))

        print('buying IBM')
        o = t.market_order('IBM', 100)
        assert o
        assert type(o) == dict
        assert 'permid' in o.keys()
        assert 'status' in o.keys()
        dump('market_order(IBM,100)', o)

        print('selling IBM')

        o = t.market_order('IBM', -100)
        assert o
        assert type(o) == dict
        assert 'permid' in o.keys()
        assert 'status' in o.keys()
        dump('market_order(IBM,100)', o)
