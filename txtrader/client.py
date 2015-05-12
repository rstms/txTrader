#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  client.py
  ---------

  TxTrader Client module - Expose class API as user interface.

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

import httplib
import xmlrpclib
import socket
import traceback
from sys import stderr
from os import environ

class TimeoutHTTPConnection(httplib.HTTPConnection):
    def connect(self):
        httplib.HTTPConnection.connect(self)
        self.sock.settimeout(self.timeout)

class TimeoutTransport(xmlrpclib.Transport):
    def __init__(self, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, *args, **kwargs):
        xmlrpclib.Transport.__init__(self, *args, **kwargs)
        self.timeout = timeout

    def make_connection(self, host):
        if self._connection and host == self._connection[0]:
            return self._connection[1]

        chost, self._extra_headers, x509 = self.get_host_info(host)
        self._connection = host, TimeoutHTTPConnection(chost)
        self._connection[1].timeout = self.timeout
        return self._connection[1]

class API():
  def __init__(self, server):
    self.server=server
    self.hostname = environ['TXTRADER_HOST']
    username = environ['TXTRADER_USERNAME']
    password = environ['TXTRADER_PASSWORD']
    self.port = environ['TXTRADER_XMLRPC_PORT']
    self.account = environ['TXTRADER_API_ACCOUNT']
    self.retry_limit = int(environ['TXTRADER_XMLRPC_RETRY_LIMIT'])
    self.timeout = float(environ['TXTRADER_XMLRPC_TIMEOUT'])
    url='http://%s:%s@%s:%s' % (username, password, self.hostname, self.port)
    self.transport = TimeoutTransport(timeout=self.timeout)
    self.proxy = xmlrpclib.ServerProxy(url, transport=self.transport, verbose=False, allow_none=True)

    self.cmdmap={
      'help': (self.help, False, ()),
      'status': (self.status, False, ()),
      'shutdown': (self.shutdown, False, ()),
      'uptime': (self.uptime, False, ()),
      'query_bars': (self.query_bars, True, ('symbol', 'interval', 'start_time', 'end_time')),
      'add_symbol': (self.add_symbol, True, ('symbol',)),
      'del_symbol': (self.del_symbol, True, ('symbol',)),
      'query_symbol': (self.query_symbol, True, ('symbol',)),
      'query_symbols': (self.query_symbols, True, ()),
      'set_account': (self.set_account, False, ('account',)),
      'query_accounts': (self.query_accounts, False, ()),
      'query_account': (self.query_account, True, ('account',)),
      'query_positions': (self.query_positions, True, ()),
      'query_orders': (self.query_orders, True, ()),
      'query_order': (self.query_order, True, ('order_id',)),
      'cancel_order': (self.cancel_order, True, ('order_id',)),
      'query_executions': (self.query_executions, True, ()),
      'market_order': (self.market_order, True, ('symbol', 'quantity')),
      'limit_order': (self.limit_order, True, ('symbol', 'limit_price', 'quantity')),
      'stop_order': (self.stop_order, True, ('symbol', 'stop_price', 'quantity')),
      'stoplimit_order': (self.stoplimit_order, True, ('symbol', 'stop_price', 'limit_price', 'quantity')),
      'global_cancel': (self.global_cancel, True, ()),
      'gateway_logon': (self.gateway_logon, True, ('username', 'password')),
      'gateway_logoff': (self.gateway_logoff, True, ()),
      'set_primary_exchange': (self.set_primary_exchange, True, ('symbol', 'exchange'))
    }

  def cmd(self, cmd, args):
    if cmd in self.cmdmap.keys():
      func, require_account, parms = self.cmdmap[cmd]
      if require_account:
	if not self.set_account(self.account):
      	  raise Exception('Error: set_account required')
      return func(*args)
    else:
      return 'API Client commands:\n  %s' % '\n  '.join([k+repr(v[1]) for k,v in self.cmdmap.iteritems()])

  def help(self, *args):
    ret=''
    methods = self.proxy.system.listMethods()
    methods.sort()
    for method in methods:
      help = self.proxy.system.methodHelp(method)
      if not help.startswith(method):
        ret += '%s %s\n' % (method, self.proxy.system.methodSignature(method))
      ret += '%s\n' % self.proxy.system.methodHelp(method)
    return ret

  def call_with_retry(self, function_name, args):
    require_account = self.cmdmap[function_name][1]
    if require_account:
      if not self.set_account(self.account):
        raise Exception('Error: set_account required')
    tries=0
    while True:
      try:
        tries+=1
	ret = getattr(self.proxy, function_name)(*args)
      except socket.timeout, ex:
        if tries < self.retry_limit:
          stderr.write('Exception: API(%s)@%s:%s %s (will retry)\n' % (self.server, self.hostname, self.port, repr(ex)))
        else:
          self.process_error(ex)
      except Exception, ex:
          self.process_error(ex)
      else:
        return ret

  def process_error(self, ex):
    stderr.write('Error: API(%s)@%s:%s call failed: %s\n' % (self.server, self.hostname, self.port, traceback.format_exc()))
    raise ex

  def status(self, *args):
    return self.call_with_retry('status', args)

  def shutdown(self, *args):
    return self.call_with_retry('shutdown', args)
 
  def uptime(self, *args):
    return self.call_with_retry('uptime', args)

  def query_bars(self, *args):
    return self.call_with_retry('query_bars', args)

  def add_symbol(self, *args):
    return self.call_with_retry('add_symbol', args)

  def del_symbol(self, *args):
    return self.call_with_retry('del_symbol', args)

  def query_symbols(self, *args):
    return self.call_with_retry('query_symbols', args)

  def query_symbol(self, *args):
    return self.call_with_retry('query_symbol', args)

  def query_accounts(self, *args):
    return self.call_with_retry('query_accounts', args)

  def query_account(self, *args):
    return self.call_with_retry('query_account', args)

  def set_account(self, *args):
    account = args[0]
    ret = self.call_with_retry('set_account', args)
    if ret: 
      self.account = account
    return ret

  def query_positions(self, *args):
    return self.call_with_retry('query_positions', args)

  def query_orders(self, *args):
    return self.call_with_retry('query_orders', args)

  def query_order(self, *args):
    return self.call_with_retry('query_order', args)

  def cancel_order(self, *args):
    return self.call_with_retry('cancel_order', args)

  def query_executions(self, *args):
    return self.call_with_retry('query_executions', args)

  def market_order(self, *args):
    symbol, quantity = args[0:2]
    try:
      return self.proxy.market_order(symbol, quantity)
    except Exception, ex:
      self.process_error(ex)

  def limit_order(self, *args):
    symbol, limit_price, quantity = args[0:3]
    try:
      return self.proxy.limit_order(symbol, limit_price, quantity)
    except Exception, ex:
      self.process_error(ex)
  
  def stop_order(self, *args):
    symbol, stop_price, quantity = args[0:3]
    try:
      return self.proxy.stop_order(symbol, stop_price, quantity)
    except Exception, ex:
      self.process_error(ex)

  def stoplimit_order(self, *args):
    symbol, stop_price, limit_price, quantity = args[0:4]
    try:
      return self.proxy.stoplimit_order(symbol, stop_price, limit_price, quantity)
    except Exception, ex:
      self.process_error(ex)

  def global_cancel(self, *args):
    return self.call_with_retry('global_cancel', args)

  def gateway_logon(self, *args):
    return self.call_with_retry('gateway_logon', args)

  def gateway_logoff(self, *args):
    return self.call_with_retry('gateway_logoff', args)

  def set_primary_exchange(self, *args):
    return self.call_with_retry('set_primary_exchange', args)

if __name__=='__main__':
  from sys import argv
  server, command = argv[1:3]
  args = argv[3:]
  print API(server).cmd(command, args)

