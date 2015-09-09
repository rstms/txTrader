#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  xmlserver.py
  ------------

  TxTrader XMLRPC server module - Implement user interface functions.

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

import sys, mx.DateTime, datetime

from twisted.internet import reactor, defer
from twisted.web import http
from twisted.web.xmlrpc import XMLRPC

import version

class authorized_xmlserver(XMLRPC):

    def __init__(self, api):
        self.started = mx.DateTime.now()
        self.api = api 
        self.output = api.output
        XMLRPC.__init__(self, allowNone=True)
      
    def xmlrpc_shutdown(self):
        """shutdown() 

        Request server shutdown
        """
        self.output('xmlrpc client requested shutdown')
        reactor.callLater(1, reactor.stop)
    
    def xmlrpc_status(self):
        """status() => 'status string'

        return string describing current API connection status
        """
        self.output('xmlrpc_status()')
        return self.api.query_connection_status()
    
    def xmlrpc_uptime(self):
        """uptime() => 'uptime string'

        Return string showing start time and elapsed time for current server instance
        """
        self.output('xmlrpc_uptime()')
        uptime = mx.DateTime.now()-self.started
        return 'started %s (elapsed %s)' % (self.started.strftime('%Y-%m-%d %H:%M:%S'), uptime.strftime('%H:%M:%S'))
      
    def xmlrpc_version(self):
        """version() => 'version string'

        Return string containing release version of current server instance
        """
        self.output('xmlrpc_version()')
        return version.__version__
      
    def xmlrpc_add_symbol(self, symbol):
        """add_symbol('symbol')

        Request subscription to a symbol for price updates and order entry
        """
        symbol=symbol.upper()
        self.output('xmlrpc_add_symbol%s' % repr((symbol)))
        ret = defer.Deferred()
        self.api.symbol_enable(symbol, self, ret.callback)
        return ret
      
    def xmlrpc_del_symbol(self, symbol):
        """del_symbol('symbol')

        Delete subscription to a symbol for price updates and order entry
        """
        symbol=symbol.upper()
        self.output('xmlrpc_del_symbol%s' % repr((symbol)))
        return self.api.symbol_disable(symbol, self)
    
    def xmlrpc_query_symbols(self):
        """query_symbols() => ['symbol', ...]

        Return the list of active symbols
        """
        self.output('xmlrpc_query_symbols()')
        return self.api.symbols.keys()
    
    def xmlrpc_query_symbol(self, symbol):
        """query_symbol('symbol') => {'fieldname': data, ...}

        Return dict containing current data for given symbol
        """
        symbol=symbol.upper()
        self.output('xmlrpc_query_symbol%s' % repr((symbol)))
        ret = None
        if symbol in self.api.symbols.keys():
            ret = self.api.symbols[symbol].export()
        return ret
      
    def xmlrpc_query_accounts(self):
        """query_accounts() => ['account_name', ...]

        Return array of account names
        """
        self.output('xmlrpc_query_accounts()')
        return self.api.accounts
    
    def xmlrpc_set_account(self, account):
        """set_account('account')

        Select current active trading account.
        """
        self.output('xmlrpc_set_account(%s)' % account)
        ret = defer.Deferred()
        self.api.set_account(account, ret.callback)
        return ret

    def xmlrpc_query_account(self, account):
        """query_account(account) => {'key': (value, currency), ...}

        Query account data for account.
        """
        self.output('xmlrpc_query_account(%s)' % account)
        ret = defer.Deferred()
        self.api.request_account_data(account, ret.callback)
        return ret
      
    def xmlrpc_query_positions(self):
        """query_positions() => {'account': {'fieldname': data, ...}, ...}
        
        Return dict keyed by account containing dicts of position data fields
        """
        self.output('xmlrpc_query_positions()')
        ret = defer.Deferred()
        self.api.request_positions(ret.callback)
        return ret
      
    def xmlrpc_query_order(self, id):
        """query_order('id') => {'fieldname': data, ...}

        Return dict containing order status fields for given order id
        """
        if str(id) in self.api.orders.keys():
            ret=self.api.orders[str(id)]
        else:
            ret={str(id): {'status:': 'Undefined'}}
        return ret
      
    def xmlrpc_query_orders(self):
        """query_orders() => {'order_id': {'field': data, ...}, ...}

        Return dict keyed by order id containing dicts of order data fields
        """
        self.output('xmlrpc_query_orders()')
        ret = defer.Deferred()
        self.api.request_orders(ret.callback)
        return ret
        
    def xmlrpc_query_executions(self):
        """query_executions() => {'exec_id': {'field': data, ...}, ...}

        Return dict keyed by execution id containing dicts of execution report data fields
        """
        self.output('xmlrpc_query_executions()')
        ret = defer.Deferred()
        self.api.request_executions(ret.callback)
        return ret
      
    def xmlrpc_market_order(self, symbol, quantity):
        """market_order('symbol', quantity) => {'field':, data, ...}

        Submit a market order, returning dict containing new order fields
        """
        self.output('xmlrpc_market_order%s' % repr((symbol, quantity)))
        ret = defer.Deferred()
        self.api.market_order(symbol, quantity, ret.callback)
        return ret
        
    def xmlrpc_limit_order(self, symbol, price, quantity):
        """limit_order('symbol', price, quantity) => {'field':, data, ...}

        Submit a limit order, returning dict containing new order fields
        """
        self.output('xmlrpc_limit_order%s' % repr((symbol, price, quantity)))
        ret = defer.Deferred()
        self.api.limit_order(symbol, price, quantity, ret.callback)
        return ret
      
    def xmlrpc_stop_order(self, symbol, price, quantity):
        """stop_order('symbol', price, quantity) => {'field':, data, ...}

        Submit a stop order, returning dict containing new order fields
        """
        self.output('xmlrpc_stop_order%s' % repr((symbol, price, quantity)))
        ret = defer.Deferred()
        self.api.stop_order(symbol, price, quantity, ret.callback)
        return ret
      
    def xmlrpc_stoplimit_order(self, symbol, stop_price, limit_price, quantity):
        """stoplimit_order('symbol', stop_price, limit_price, quantity) => {'field':, data, ...}

        Submit a stop-limit order, returning dict containing new order fields
        """
        self.output('xmlrpc_stoplimit_order%s' % repr((symbol, stop_price, limit_price, quantity)))
        ret = defer.Deferred()
        self.api.stoplimit_order(symbol, stop_price, limit_price, quantity, ret.callback)
        return ret
      
    def xmlrpc_query_bars(self, symbol, period, start, end):
        """query_bars('symbol', bar_period, 'start', 'end')
              => ['Status: OK', [time, open, high, low, close, volume], ...]

        Return array containing status strings and lists of bar data if successful
        """
        self.output('xmlrpc_query_bars%s' % repr((symbol, period, start, end)))
        ret = defer.Deferred()
        self.api.query_bars(symbol, period, start, end, ret.callback)
        return ret
      
    def xmlrpc_cancel_order(self, id):
        """cancel_order('id')
 
        Request cancellation of a pending order
        """
        self.output('xmlrpc_cancel_order%s' % repr((id)))
        ret = defer.Deferred()
        self.api.cancel_order(id, ret.callback)
        return ret
    
    def xmlrpc_global_cancel(self):
        """global_cancel()
  
        Request cancellation of all pending orders
        """
        self.output('xmlrpc_global_cancel()')
        self.api.request_global_cancel()
        
    def xmlrpc_gateway_logon(self, username, password):
        """gateway_logon('username', 'password')
        
        logon to gateway
        """
        self.output('xmlrpc_gateway_logon(%s)' % repr((username, '********')))
        self.api.gateway_logon(username, password)

    def xmlrpc_gateway_logoff(self):
        """gateway_logoff()
    
        Logoff from gateway
        """
        self.output('xmlrpc_gateway_logoff()')
        self.api.gateway_logoff()

    def xmlrpc_set_primary_exchange(self, symbol, exchange):
        """set_primary_exchange(symbol, exchange)

        Set primary exchange for symbol (default is SMART), delete mapping if exchange is None.
        """
        return self.api.set_primary_exchange(symbol, exchange)


class xmlserver(authorized_xmlserver):

    def __init__(self, api):
        self.api = api 
        authorized_xmlserver.__init__(self, api)

    def render(self, request):
        self.request = request
        if self.request.getUser()==self.api.username and self.request.getPassword()==self.api.password:
             return authorized_xmlserver.render(self, request)
        else:
            request.setResponseCode(http.UNAUTHORIZED)
            return 'Valid Authorization Required!'

