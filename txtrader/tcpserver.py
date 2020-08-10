#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  tcpserver.py
  ------------

  TxTrader TCP server module - Implement ASCII line oriented event interface.

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

from txtrader import VERSION, DATE, LABEL

import sys
import os

from twisted.internet.protocol import Factory
from twisted.internet import reactor, defer
from twisted.protocols import basic
from socket import gethostname
import ujson as json
import traceback

# set 512MB line buffer
LINE_BUFFER_LENGTH = 0x20000000


class tcpserver(basic.NetstringReceiver):

    MAX_LENGTH = LINE_BUFFER_LENGTH

    def __init__(self):
        self.commands = {
            'auth': self.cmd_auth,
            'help': self.cmd_help,
            'quit': self.cmd_disconnect,
            'exit': self.cmd_disconnect,
            'bye': self.cmd_disconnect,
            'status': self.cmd_status,
            'getbars': self.cmd_getbars,
            'marketorder': self.cmd_market_order,
            'stagemarketorder': self.cmd_stage_market_order,
            'stoporder': self.cmd_stop_order,
            'limitorder': self.cmd_limit_order,
            'stoplimitorder': self.cmd_stoplimit_order,
            'add': self.cmd_add,
            'del': self.cmd_del,
            'query': self.cmd_query,
            'querydata': self.cmd_query_data,
            'symbols': self.cmd_symbols,
            'positions': self.cmd_positions,
            'orders': self.cmd_orders,
            'tickets': self.cmd_tickets,
            'executions': self.cmd_executions,
            'globalcancel': self.cmd_global_cancel,
            'cancel': self.cmd_cancel,
            'setaccount': self.cmd_setaccount,
            'accounts': self.cmd_accounts,
            'shutdown': self.cmd_shutdown,
        }
        self.authmap = set([])
        self.options = {}

    def stringReceived(self, line):
        line = line.decode().strip()
        self.factory.output(
            'user command: %s' % ('%s xxxxxxxxxxx' % ' '.join(line.split()[:2]) if line.startswith('auth') else line)
        )
        if line:
            cmd = line.split()[0]
            if cmd in self.commands.keys():
                try:
                    response = self.commands[cmd](line)
                except Exception as exc:
                    self.factory.api.error_handler(self, repr(exc))
                    traceback.print_exc()
                    response = f'.error: {repr(exc)}'
                    self.send(response)
                    self.factory.api.check_exception_halt(exc, self)
                else:
                    if response:
                        self.send(response)
            else:
                self.send('.what?')

    def send(self, line):
        if len(line) > self.MAX_LENGTH:
            self.factory.api.force_disconnect(
                f"NetstringReceiver: cannot send message of length {len(line)} {repr(line[:64])}..."
            )
        else:
            return self.sendString(line.encode())

    def cmd_auth(self, line):
        auth, username, password = (line).split()[:3]
        options_field = line[len(auth) + len(username) + len(password) + 3:]
        if not options_field.startswith('{'):
            # legacy options are in string format: i.e. 'noquotes notrades'; convert to dict
            self.options = {o: True for o in options_field.strip().split()}
        else:
            self.options = json.loads(options_field) if options_field else {}
        if self.factory.validate(username, password):
            self.authmap.add(self.transport.getPeer())
            self.factory.api.open_client(self)
            return '.Authorized %s' % self.factory.api.channel
        else:
            self.check_authorized()

    def check_authorized(self):
        authorized = self.transport.getPeer() in self.authmap
        if not authorized:
            self.send('.Authorization required!')
            self.factory.api.close_client(self)
            self.transport.loseConnection()
        return authorized

    def check_initialized(self):
        initialized = self.factory.api.initialized
        if not initialized:
            self.send('.Initialization not complete!')
            self.factory.api.close_client(self)
            self.transport.loseConnection()
        return initialized

    def cmd_shutdown(self, line):
        if self.check_authorized():
            self.factory.output('client at %s requested shutdown: %s' % (self.transport.getPeer(), line))
            self.factory.api.close_client(self)
            reactor.callLater(0, reactor.stop)

    def cmd_help(self, line):
        self.send('.commands: %s' % repr(self.commands.keys()))

    def cmd_disconnect(self, line):
        self.authmap.discard(self.transport.getPeer())
        self.transport.loseConnection()

    def cmd_status(self, line):
        self.send('.status: %s' % self.factory.api.query_connection_status())

    def cmd_setaccount(self, line):
        if self.check_authorized() and self.check_initialized():
            setaccount, account = line.split()[:2]
            self.factory.api.set_account(account, self.send)

    def cmd_accounts(self, line):
        if self.check_authorized() and self.check_initialized():
            self.send('.accounts: %s' % self.factory.api.accounts)
            self.factory.api.request_accounts(self.defer_response(self.send_response, 'accounts'))

    def cmd_getbars(self, line):
        if self.check_authorized() and self.check_initialized():
            _, symbol, period, start_date, start_time, end_date, end_time = line.split()[:7]
            self.factory.api.query_bars(
                symbol, period, ' '.join((start_date, start_time)), ' '.join((end_date, end_time)), self.send
            )

    def cmd_add(self, line):
        if self.check_authorized() and self.check_initialized():
            _, symbol = line.split()[:2]
            symbol = symbol.upper()
            self.factory.api.symbol_enable(symbol, self, self.defer_response(self.send_response, 'symbol'))
            #self.send(f".symbol: {symbol} added")

    def cmd_del(self, line):
        if self.check_authorized() and self.check_initialized():
            _, symbol = line.split()[:2]
            symbol = symbol.upper()
            self.factory.api.symbol_disable(symbol, self, self.defer_response(self.send_response, 'symbol'))
            #self.send(f".symbol: {symbol} deleted")

    def cmd_query(self, line):
        if self.check_authorized() and self.check_initialized():
            _, symbol = line.split()[:2]
            symbol = symbol.upper()
            self.send_response(json.dumps(self._symbol_fields(symbol)), 'symbol')

    def cmd_query_data(self, line):
        if self.check_authorized() and self.check_initialized():
            _, symbol = line.split()[:2]
            symbol = symbol.upper()
            self.send_response(json.dumps(self._symbol_fields(symbol, raw=True)), 'symbol-data')

    def _symbol_fields(self, symbol, raw=False):
        if raw:
            symbol_fields = self.factory.api.symbols[symbol].rawdata
        else:
            symbol_fields = self.factory.api.symbols[symbol].export(self.options.get('SYMBOL_FIELDS', None))
        return symbol_fields

    def cmd_market_order(self, line):
        if self.check_authorized() and self.check_initialized():
            _, account, route, symbol, qstr = line.split()[:5]
            self.factory.api.market_order(account, route, symbol, int(qstr), self.send)

    def cmd_stage_market_order(self, line):
        if self.check_authorized() and self.check_initialized():
            _, tag, account, route, symbol, qstr = line.split()[:6]
            self.factory.api.stage_market_order(tag, account, route, symbol, int(qstr), self.send)

    def cmd_stop_order(self, line):
        if self.check_authorized() and self.check_initialized():
            _order, account, route, symbol, price, qstr = line.split()[:6]
            self.factory.api.stop_order(account, route, symbol, float(price), int(qstr), self.send)

    def cmd_limit_order(self, line):
        if self.check_authorized() and self.check_initialized():
            _, account, route, symbol, price, qstr = line.split()[:6]
            self.factory.api.limit_order(account, route, symbol, float(price), int(qstr), self.send)

    def cmd_stoplimit_order(self, line):
        if self.check_authorized() and self.check_initialized():
            _, account, route, symbol, stop_price, limit_price, qstr = line.split()[:7]
            self.factory.api.stoplimit_order(
                account, route, symbol, float(stop_price), float(limit_price), int(qstr), self.send
            )

    def cmd_cancel(self, line):
        if self.check_authorized() and self.check_initialized():
            _, _id = line.split()[:2]
            self.factory.api.cancel_order(_id, self.send)

    def cmd_symbols(self, line):
        if self.check_authorized() and self.check_initialized():
            symbols = {s: self._symbol_fields(s) for s in s.self.factory.api.symbols}
            self.send_response(json.dumps(symbols), 'symbols')

    def cmd_positions(self, line):
        if self.check_authorized() and self.check_initialized():
            self.factory.api.request_positions(self.defer_response(self.send_response, 'positions'))

    def cmd_orders(self, line):
        if self.check_authorized() and self.check_initialized():
            self.factory.api.request_orders(self.defer_response(self.send_response, 'orders'))

    def cmd_tickets(self, line):
        if self.check_authorized() and self.check_initialized():
            self.factory.api.request_tickets(self.defer_response(self.send_response, 'tickets'))

    def cmd_executions(self, line):
        if self.check_authorized() and self.check_initialized():
            self.factory.api.request_executions(self.defer_response(self.send_response, 'executions'))

    def cmd_global_cancel(self, line):
        if self.check_authorized() and self.check_initialized():
            self.factory.api.request_global_cancel()
            self.send('.global order cancel requested')

    def connectionMade(self):
        self.factory.output('client connection from %s' % self.transport.getPeer())
        self.authmap.discard(self.transport.getPeer())
        self.send(
            '.connected: %s %s %s %s on %s' % (self.factory.api.label, str(VERSION), str(DATE), str(LABEL), str(gethostname()))
        )

    def connectionLost(self, reason):
        self.factory.output('client connection from %s lost: %s' % (self.transport.getPeer(), repr(reason)))
        self.authmap.discard(self.transport.getPeer())
        self.factory.api.close_client(self)

    def send_response(self, data, label):
        self.send(f'{self.factory.api.channel}.{label}: {data}')

    def defer_response(self, sender, command):
        d = defer.Deferred()
        d.addCallback(sender, command)
        d.addErrback(self.api_error)
        d.addErrback(self.api_timeout)
        return d

    def api_timeout(self, failure):
        self.send(f'alert: API timeout errback: {repr(failure)}')
        return failure

    def api_error(self, failure):
        self.send(f'alert: API errback: {repr(failure)}')
        return failure


class serverFactory(Factory):
    protocol = tcpserver

    def __init__(self, api):
        self.api = api
        self.output = api.output

    def validate(self, username, password):
        return username == self.api.username and password == self.api.password

    def buildProtocol(self, addr):
        self.output(f'buildProtocol: addr={addr}')
        return super().buildProtocol(addr)
