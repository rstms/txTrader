#!/usr/bin/env python

# Copyright (c) 2015 Reliance Systems, Inc.


import rsicfg
import httplib
import xmlrpclib
import socket
import traceback
from sys import stderr

XMLRPC_TIMEOUT=15

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
    self.hostname = rsicfg.get('%s-hostname' % server, 'rsagw')
    username = rsicfg.get('%s-xmlrpc-username' % server, 'rsagw')
    password = rsicfg.get('%s-xmlrpc-password' % server, 'rsagw')
    self.port = rsicfg.get('%s-xmlrpc-port' % server, 'rsagw')
    self.account = rsicfg.get('%s-account' % server, 'rsagw')
    url='http://%s:%s@%s:%s' % (username, password, self.hostname, self.port)
    self.transport = TimeoutTransport(timeout=XMLRPC_TIMEOUT)
    self.proxy = xmlrpclib.ServerProxy(url, transport=self.transport, verbose=False, allow_none=True)
    if not self.set_account(self.account):
      raise Exception('Error: account mismatch')

    self.cmdmap={
      'help': (self.help, ()),
      'status': (self.status, ()),
      'shutdown': (self.shutdown, ()),
      'uptime': (self.uptime, ()),
      'query_bars': (self.query_bars, ('symbol', 'interval', 'start_time', 'end_time')),
      'add_symbol': (self.add_symbol, ('symbol',)),
      'del_symbol': (self.del_symbol, ('symbol',)),
      'query_symbol': (self.query_symbol, ('symbol',)),
      'query_symbols': (self.query_symbols, ()),
      'query_accounts': (self.query_accounts, ()),
      'set_account': (self.set_account, ('account',)),
      'query_positions': (self.query_positions, ()),
      'query_orders': (self.query_orders, ()),
      'query_order': (self.query_order, ('order_id',)),
      'cancel_order': (self.cancel_order, ('order_id',)),
      'query_executions': (self.query_executions, ()),
      'market_order': (self.market_order, ('symbol', 'quantity')),
      'limit_order': (self.limit_order, ('symbol', 'limit_price', 'quantity')),
      'stop_order': (self.stop_order, ('symbol', 'stop_price', 'quantity')),
      'stoplimit_order': (self.stoplimit_order, ('symbol', 'stop_price', 'limit_price', 'quantity')),
      'global_cancel': (self.global_cancel, ()),
      'gateway_logon': (self.gateway_logon, ('username', 'password')),
      'gateway_logoff': (self.gateway_logoff, ()),
      'set_primary_exchange': (self.set_primary_exchange, ('symbol', 'exchange'))
    }

  def cmd(self, cmd, args):
    if cmd in self.cmdmap.keys():
      func, parms = self.cmdmap[cmd]
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

  def status(self, *args):
    try:
      return(self.proxy.status())
    except Exception, ex:
      self.process_error(ex)

  def shutdown(self, *args):
    try: 
      return self.proxy.shutdown()
    except Exception, ex:
      self.process_error(ex)
 
  def uptime(self, *args):
    try:
      return self.proxy.uptime()
    except Exception, ex:
      self.process_error(ex)

  def query_bars(self, *args):
    symbol, interval, start_time, end_time = args
    try:
      return self.proxy.query_bars(symbol, interval, start_time, end_time)
    except Exception, ex:
      self.process_error(ex)

  def add_symbol(self, *args):
    symbol = args[0]
    try:
      return self.proxy.add_symbol(symbol)
    except Exception, ex:
      self.process_error(ex)

  def del_symbol(self, *args):
    symbol = args[0]
    try:
      return self.proxy.del_symbol(symbol)
    except Exception, ex:
      self.process_error(ex)

  def query_symbols(self, *args):
    try:
      return self.proxy.query_symbols()
    except Exception, ex:
      self.process_error(ex)

  def query_symbol(self, *args):
    symbol = args[0]
    try:
      return self.proxy.query_symbol(symbol)
    except Exception, ex:
      self.process_error(ex)
 
  def query_accounts(self, *args):
    try:
      return self.proxy.query_accounts()
    except Exception, ex:
      self.process_error(ex)

  def set_account(self, *args):
    account=args[0]
    try:
      return(self.proxy.set_account(account))
    except Exception, ex:
      self.process_error(ex)

  def process_error(self, ex):
    stderr.write('Error: API(%s)@%s:%s call failed: %s\n' % (self.server, self.hostname, self.port, traceback.format_exc()))
    raise ex

  def query_positions(self, *args):
    try:
      return self.proxy.query_positions()
    except Exception, ex:
      self.process_error(ex)

  def query_orders(self, *args):
    try:
      return self.proxy.query_orders()
    except Exception, ex:
      self.process_error(ex)

  def query_order(self, *args):
    order_id=args[0]
    try:
      return self.proxy.query_order(order_id)
    except Exception, ex:
      self.process_error(ex)

  def cancel_order(self, *args):
    order_id=args[0]
    try:
      return self.proxy.cancel_order(order_id)
    except Exception, ex:
      self.process_error(ex)

  def query_executions(self, *args):
    try:
      return self.proxy.query_executions()
    except Exception, ex:
      self.process_error(ex)

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
    try:
      return self.proxy.global_cancel()
    except Exception, ex:
      self.process_error(ex)

  def gateway_logon(self, *args):
    username, password = args
    try:
      return self.proxy.gateway_logon(username, password)
    except Exception, ex:
      self.process_error(ex)

  def gateway_logoff(self):
    try:
      return self.proxy.gateway_logoff()
    except Exception, ex:
      self.process_error(ex)


  def set_primary_exchange(self, symbol, exchange):
    try:
      return self.proxy.set_primary_exchange(symbol, exchange)
    except Exception, ex:
      self.process_error(ex)

if __name__=='__main__':
  from sys import argv
  server, command = argv[1:3]
  args = argv[3:]
  print API(server).cmd(command, args)

