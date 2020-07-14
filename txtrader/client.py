#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  client.py
  ---------

  TxTrader Client module - Expose class API as user interface.

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

import os
import sys
import requests
import json

from txtrader.version import VERSION
from txtrader.config import Config

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


def requests_retry_session(
    retries=5,
    backoff_factor=0.3,
    status_forcelist=(502, 504),
    session=None,
):
    session = session or requests.Session()
    retry = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


class API(object):

    def __init__(self, server=None):
        #sys.stderr.write('txTrader.client.API.__init__(%s, %s)\n' % (repr(self), repr(server)))
        self.server = server
        self.config = Config(server)
        self.hostname = self.config.get('HOST')
        self.port = self.config.get('HTTP_PORT')
        self.username = self.config.get('USERNAME')
        self.password = self.config.get('PASSWORD')
        self.account = self.config.get('API_ACCOUNT')
        self.order_route = self.config.get('API_ROUTE')
        self.mode = self.config.get('MODE')
        self.get_retries = int(self.config.get('GET_RETRIES'))
        self.get_backoff_factor = float(self.config.get('GET_BACKOFF_FACTOR'))

        self.url = 'http://%s:%s' % (self.hostname, self.port)

        self.cmdmap = {
            'help': (self.help, False, ()),
            'status': (self.status, False, ()),
            'version': (self.version, False, ()),
            'time': (self.time, False, ()),
            'shutdown': (self.shutdown, False, ('message')),
            'uptime': (self.uptime, False, ()),
            'query_bars': (self.query_bars, True, ('symbol', 'interval', 'start_time', 'end_time')),
            'add_symbol': (self.add_symbol, True, ('symbol', )),
            'del_symbol': (self.del_symbol, True, ('symbol', )),
            'query_symbol': (self.query_symbol, True, ('symbol', )),
            'query_symbol_data': (self.query_symbol_data, True, ('symbol', )),
            'query_symbol_bars': (self.query_symbol_bars, True, ('symbol', )),
            'query_symbols': (self.query_symbols, True, ()),
            'set_account': (self.set_account, False, ('account', )),
            'set_order_route': (self.set_order_route, True, ('route', )),
            'get_order_route': (self.get_order_route, True, ()),
            'query_accounts': (self.query_accounts, False, ()),
            'query_account': (self.query_account, True, ('account', 'fields')),
            'query_positions': (self.query_positions, True, ()),
            'query_orders': (self.query_orders, True, ()),
            'query_tickets': (self.query_tickets, True, ()),
            'query_order': (self.query_order, True, ('order_id', )),
            'cancel_order': (self.cancel_order, True, ('order_id', )),
            'query_executions': (self.query_executions, True, ()),
            'query_order_executions': (self.query_order_executions, True, ('order_id', )),
            'market_order': (self.market_order, True, ('symbol', 'quantity')),
            'create_staged_order_ticket': (self.create_staged_order_ticket, True, ()),
            'stage_market_order': (self.stage_market_order, True, ('tag', 'symbol', 'quantity')),
            'limit_order': (self.limit_order, True, ('symbol', 'limit_price', 'quantity')),
            'stop_order': (self.stop_order, True, ('symbol', 'stop_price', 'quantity')),
            'stoplimit_order': (self.stoplimit_order, True, ('symbol', 'stop_price', 'limit_price', 'quantity')),
            'global_cancel': (self.global_cancel, True, ()),
            'gateway_logon': (self.gateway_logon, True, ('username', 'password')),
            'gateway_logoff': (self.gateway_logoff, True, ()),
            'set_primary_exchange': (self.set_primary_exchange, True, ('symbol', 'exchange')),
        }

    def cmd(self, cmd, args):
        if cmd in self.cmdmap.keys():
            func, require_account, parms = self.cmdmap[cmd]
            if require_account:
                if not self.set_account(self.account):
                    raise Exception('Error: set_account required')
            return func(*args)
        else:
            raise Exception('Error: unknown command: %s\n' % cmd)

    def call_txtrader_post(self, function_name, args):
        #print('call_txtrader_post(%s, %s)' % (repr(function_name), repr(args)))
        url = '%s/%s' % (self.url, function_name)
        headers = {'Content-type': 'application/json'}
        r = requests.post(url, json=args, headers=headers, auth=(self.username, self.password))
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
        ret = r.json()
        r.close()
        return ret

    def call_txtrader_get(self, function_name, args):
        url = '%s/%s' % (self.url, function_name)
        headers = {'Content-type': 'application/json'}
        r = requests_retry_session(
            retries=self.get_retries, backoff_factor=self.get_backoff_factor
        ).get(
            url, params=args, headers=headers, auth=(self.username, self.password)
        )
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
        ret = r.json()
        r.close()
        return ret

    def help(self, *args):
        helptext = self.call_txtrader_get('help', {})
        commands = helptext.keys()
        commands.sort()
        print('\nTxTrader [%s] commands:\n%s' % (self.mode, '=' * 80))
        for c in commands:
            print('%s\n' % (helptext[c].strip().replace('\n\n', '\n')))
        return None

    def status(self, *args):
        return self.call_txtrader_get('status', {})

    def version(self, *args):
        return self.call_txtrader_get('version', {})

    def shutdown(self, *args):
        return self.call_txtrader_post('shutdown', {'message': args[0]})

    def uptime(self, *args):
        return self.call_txtrader_get('uptime', {})

    def time(self, *args):
        return self.call_txtrader_get('time', {})

    def query_bars(self, *args):
        args = {'symbol': args[0], 'period': args[1], 'start': args[2], 'end': args[3]}
        return self.call_txtrader_get('query_bars', args)

    def add_symbol(self, *args):
        return self.call_txtrader_post('add_symbol', {'symbol': args[0]})

    def del_symbol(self, *args):
        return self.call_txtrader_post('del_symbol', {'symbol': args[0]})

    def query_symbols(self, *args):
        return self.call_txtrader_get('query_symbols', {})

    def query_symbol(self, *args):
        return self.call_txtrader_get('query_symbol', {'symbol': args[0]})

    def query_symbol_data(self, *args):
        return self.call_txtrader_get('query_symbol_data', {'symbol': args[0]})

    def query_symbol_bars(self, *args):
        return self.call_txtrader_get('query_symbol_bars', {'symbol': args[0]})

    def query_accounts(self, *args):
        return self.call_txtrader_get('query_accounts', {})

    def query_account(self, *args):
        account = args[0]
        fields = None
        if (len(args) > 1) and args[1]:
            if isinstance(args[1], str):
                fields = args[1]
            elif isinstance(args[1], list):
                fields = args[1].join(',')
        args = {'account': account}
        if fields:
            args['fields'] = fields
        return self.call_txtrader_get('query_account', args)

    def set_account(self, *args):
        account = args[0]
        ret = self.call_txtrader_post('set_account', {'account': account})
        if ret:
            self.account = account
        return ret

    def query_positions(self, *args):
        return self.call_txtrader_get('query_positions', {})

    def query_orders(self, *args):
        return self.call_txtrader_get('query_orders', {})

    def query_tickets(self, *args):
        return self.call_txtrader_get('query_tickets', {})

    def query_order(self, *args):
        return self.call_txtrader_get('query_order', {'id': args[0]})

    def cancel_order(self, *args):
        return self.call_txtrader_post('cancel_order', {'id': args[0]})

    def query_executions(self, *args):
        return self.call_txtrader_get('query_executions', {})

    def query_order_executions(self, *args):
        return self.call_txtrader_get('query_order_executions', {'id': args[0]})

    def create_staged_order_ticket(self, *args):
        return self.call_txtrader_post('create_staged_order_ticket', {})

    def market_order(self, *args):
        symbol, quantity = args[0:2]
        return self.call_txtrader_post(
            'market_order', {
                'account': self.account,
                'route': self.order_route,
                'symbol': symbol,
                'quantity': int(quantity)
            }
        )

    def stage_market_order(self, *args):
        tag, symbol, quantity = args[0:3]
        return self.call_txtrader_post(
            'stage_market_order', {
                'tag': tag,
                'account': self.account,
                'route': self.order_route,
                'symbol': symbol,
                'quantity': int(quantity)
            }
        )

    def limit_order(self, *args):
        symbol, limit_price, quantity = args[0:3]
        return self.call_txtrader_post(
            'limit_order', {
                'account': self.account,
                'route': self.order_route,
                'symbol': symbol,
                'limit_price': float(limit_price),
                'quantity': int(quantity)
            }
        )

    def stop_order(self, *args):
        symbol, stop_price, quantity = args[0:3]
        return self.call_txtrader_post(
            'stop_order', {
                'account': self.account,
                'route': self.order_route,
                'symbol': symbol,
                'stop_price': float(limit_price),
                'quantity': int(quantity)
            }
        )

    def stoplimit_order(self, *args):
        symbol, stop_price, limit_price, quantity = args[0:4]
        return self.call_txtrader_post(
            'stoplimit_order', {
                'account': self.account,
                'route': self.order_route,
                'symbol': symbol,
                'stop_price': float(limit_price),
                'limit_price': float(limit_price),
                'quantity': int(quantity)
            }
        )

    def global_cancel(self, *args):
        return self.call_txtrader_post('global_cancel', {})

    def gateway_logon(self, *args):
        username, password = args[0:2]
        return self.call_txtrader_post('gateway_logon', {'username': username, 'password': password})

    def gateway_logoff(self, *args):
        return self.call_txtrader_post('gateway_logoff', {})

    def set_primary_exchange(self, *args):
        return self.call_txtrader_post('set_primary_exchange', {'symbol': args[0], 'exchange': args[1]})

    def get_order_route(self, *args):
        # post locally configured order route to server and return it
        return self.set_order_route(self.order_route)

    def set_order_route(self, *args):
        ret = self.call_txtrader_post('set_order_route', {'route': args[0]})
        if ret:
            self.order_route = ret
        return ret


if __name__ == '__main__':
    from sys import argv
    flags = []
    while argv[1].startswith('-'):
        flags.append(argv[1])
        del (argv[1])
    server, command = argv[1:3]
    args = argv[3:]
    try:
        ret = API(server).cmd(command, args)
    except Exception as ex:
        sys.stderr.write('%s\n' % repr(ex))
        exit(2)
    if ret != None:
        if '-p' in flags:
            print(json.dumps(ret, sort_keys=True, indent=2, separators=(',', ': ')))
        else:
            print(json.dumps(ret))
