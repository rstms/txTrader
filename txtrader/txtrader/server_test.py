# -*- coding: utf-8 -*-
"""
  test-server.py
  --------------

  TxTrader unit/regression test server Object

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
from txtrader.client import API
import subprocess
import os
import signal
import time

testmode = 'RTX'

# 'netstat -ant | egrep LISTEN | egrep 50090>/dev/null'
def _listening(host, port, timeout=1):
    return not subprocess.call('ansible -i "127.0.0.1," -c local -v -m wait_for -a "host=%s port=%d timeout=%d" all' % (str(host), int(port), int(timeout)) , shell=True)

class Server(object):
    def __init__(self):
        self.mode = os.environ['TXTRADER_TEST_MODE'] if 'TXTRADER_TEST_MODE' in os.environ else 'RTX'
        self.mode = self.mode.upper()
        testmode = self.mode
        print('Starting test txTrader %s server...' % self.mode)
        assert subprocess.call('ps -ax | egrep [t]wistd', shell=True)
        subprocess.call('truncate --size 0 test.log', shell=True)
        self.setup_env()
        self.logfile = open('test.log', 'a')
        self.process = subprocess.Popen(['envdir', '../etc/txtrader', 'twistd', '--nodaemon',
                                         '--logfile=-', '--python=../service/txtrader/txtrader.tac'], stdout=self.logfile)
        assert self.process
        print('%s created as pid %d' % (repr(self.process), self.process.pid))
        print('Waiting for txtrader listen ports...')
        while not _listening('localhost', 50090):
            time.sleep(.25)
        assert not subprocess.call('ps -ax | egrep [t]wistd >/dev/null', shell=True)
        assert _listening('localhost', 50090, timeout=20)
        assert _listening('localhost', 50070, timeout=20)

        print('Waiting for txtrader status "Up"...')
        while subprocess.call("[ \"$(txtrader rtx status)\" = '\"Up\"' ]", shell=True):
            time.sleep(1)

        print('Test server ready.')

    def set_env(self, key, value):
        subprocess.call('echo "%s" > ../etc/txtrader/%s' % (value, key), shell=True)

    def setup_env(self):
        self.set_env('TXTRADER_LOG_API_MESSAGES', '1')

    def restore_env(self):
        self.set_env('TXTRADER_LOG_API_MESSAGES', '0')

    def init(self):
        self.api = API(self.mode)
        assert self.api
        account = self.api.account
        assert account
        print('setting account %s' % account) 
        self.api.set_account(account)
        return self.api

    def __del__(self):
        print()
        print('Stopping txTrader:  Waiting for %s to terminate...' % repr(self.process.pid))
        self.api.shutdown('test_termination')
        #os.kill(self.process.pid, signal.SIGTERM)
        self.process.wait()
        print('Terminated; exit=%d' % (self.process.returncode))
        self.logfile.close()
        self.restore_env()
        #print('Waiting 15 seconds to avoid sqlBlocked at Realtick...')
        #time.sleep(15)

    def __enter__(self):
        return self

    def __exit__(self, ex_type, ex_value, traceback):
        pass
