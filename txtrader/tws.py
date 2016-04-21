#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  tws.py
  ------

  TxTrader Interactive Brokers TWS API interface module

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

from version import __version__, __date__, __label__

import sys, mx.DateTime, types, datetime
import json
import time

from client import Config

DEFAULT_TWS_CALLBACK_TIMEOUT = 5

SHUTDOWN_ON_TWS_DISCONNECT = True

from twisted.python import log
from twisted.internet.protocol import Factory, Protocol
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web import xmlrpc, server
from twisted.protocols import basic
from socket import gethostname

from xmlserver import xmlserver
from tcpserver import serverFactory

from ib.ext.Contract import Contract
from ib.ext.TickType import TickType
from ib.ext.Order import Order
from ib.ext.ExecutionFilter import ExecutionFilter
from ib.ext.Execution import Execution
from ib.opt import Connection, message

class TWS_Symbol():
    def __init__(self, tws, symbol, client_id):
        self.tws = tws
        self.output = tws.output
        self.ticktype = TickType()
        self.clients=set([client_id])
        self.ticker_id=tws.next_id()
        self.symbol=symbol
        self.bid=0.0
        self.bid_size=0
        self.ask=0.0
        self.ask_size=0
        self.last=0.0
        self.size=0
        self.volume=0
	self.close=0.0
        self.tws.symbols[symbol]=self
        self.last_quote = ''
        self.tws.symbols_by_id[self.ticker_id]=self
        contract = self.tws.create_contract(symbol, 'STK', 'SMART', 'SMART', 'USD')
        self.output('TWS_Symbol %s %s created for client %s' % (self, symbol, client_id))
        self.output('reqMktData(%d, %s)' % (self.ticker_id, symbol))
        self.tws.tws_conn.reqMktData(self.ticker_id, contract, '', False)
        
    def __str__(self):
        return 'TWS_Symbol(%s bid=%s bidsize=%d ask=%s asksize=%d last=%s size=%d volume=%d close=%s clients=%s' % (self.symbol, self.bid, self.bid_size, self.ask, self.ask_size, self.last, self.size, self.volume, self.close, self.clients)
        
    def __repr__(self):
        return str(self)
      
    def export(self):
        return {
          'symbol': self.symbol,
          'bid': self.bid,
          'bidsize': self.bid_size,
          'ask': self.ask,
          'asksize': self.ask_size,
          'last': self.last,
          'size': self.size,
          'volume': self.volume,
          'close': self.close,
          'fullname': self.symbol,
        }
      
    def add_client(self, client):
        self.output('TWS_Symbol %s %s adding client %s' % (self, self.symbol, client))
        self.clients.add(client)
      
    def del_client(self, client):
        self.output('TWS_Symbol %s %s deleting client %s' % (self, self.symbol, client))
        self.clients.discard(client)
        if not self.clients:
            self.output('cancelMktData(%d)' % self.ticker_id)
            self.tws.tws_conn.cancelMktData(self.ticker_id)
            
    def update_quote(self):
        quote = 'quote.%s:%s %d %s %d' % (self.symbol, self.bid, self.bid_size, self.ask, self.ask_size)
        if quote != self.last_quote:
            self.last_quote = quote
            self.tws.WriteAllClients(quote)
          
    def update_trade(self):
        self.tws.WriteAllClients('trade.%s:%s %d %d' % (self.symbol, self.last, self.size, self.volume))
        
class TWS_Callback():
    def __init__(self, tws, id, label, callable, timeout=0):
        """type is stored and used to index dict of return results on callback"""
        self.tws=tws
        self.id=id
        self.label=label
        if not timeout:
          timeout = tws.callback_timeout
        self.expire=int(mx.DateTime.now())+timeout
        self.callable=callable
        self.done=False
        self.data=None

    def complete(self, results):
        """complete callback by calling callable function with value of results[self.type]"""
        if not self.done:
            if self.callable.callback.__name__=='write':
                results='%s.%s: %s\n' % (self.tws.channel, self.label, json.dumps(results))
            self.callable.callback(results)
            self.done=True
        else:
            self.tws.output('error: callback: %s was already done!' % self)
            
    def check_expire(self):
        if not self.done:
            if int(mx.DateTime.now()) > self.expire:
                self.tws.WriteAllClients('error: callback expired: %s' % repr((self.id, self.label)))
                if self.callable.callback.__name__=='write':
                    self.callable.callback('%s.error: %s callback expired\n', (self.tws.channel, self.label))
                else:
                    self.callable.callback(None)
                self.done=True
        
class TWS():

    def __init__(self):
        self.output('TWS init')
        self.channel = 'tws'
        self.config = Config(self.channel)
        self.username = self.config.get('USERNAME')
        self.password = self.config.get('PASSWORD')
        self.xmlrpc_port = int(self.config.get('XMLRPC_PORT'))
        self.tcp_port = int(self.config.get('TCP_PORT'))
        self.callback_timeout = int(self.config.get('CALLBACK_TIMEOUT'))
        if not self.callback_timeout:
          self.callback_timeout = DEFAULT_TWS_CALLBACK_TIMEOUT
        self.output('callback_timeout=%d' % self.callback_timeout)
        self.enable_ticker = bool(int(self.config.get('ENABLE_TICKER')))
        self.label = 'TWS Gateway'
        self.current_account=''
        self.clients=set([])
        self.orders={}
        self.pending_orders={}
        self.openorder_callbacks=[]
        self.accounts=[]
        self.account_data={}
        self.pending_account_data_requests=set([])
        self.positions={}
        self.position_callbacks=[]
        self.executions={}
        self.execution_callbacks=[]
        self.bardata_callbacks=[]
        self.cancel_callbacks=[]
        self.order_callbacks=[]
        self.addsymbol_callbacks=[]
        self.accountdata_callbacks=[]
        self.last_connection_status=''
        self.connection_status='Initializing'
        self.LastError=-1
        self.next_order_id=-1
        self.last_minute=-1
        self.handlers={
          'error': self.error_handler,
          'tickSize': self.handle_tick_size,
          'tickPrice': self.handle_tick_price,
          'tickString': self.handle_tick_string,
          'nextValidId': self.handle_next_valid_id,
          'currentTime': self.handle_time,
          'managedAccounts': self.handle_accounts,
          'orderStatus': self.handle_order_status,
          'openOrder': self.handle_open_order,
          'openOrderEnd': self.handle_open_order_end,
          'execDetails': self.handle_exec_details,
          'execDetailsEnd': self.handle_exec_details_end,
          'position': self.handle_position,
          'positionEnd': self.handle_position_end,
          'historicalData': self.handle_historical_data,
          'updateAccountValue': self.handle_account_value,
          'accountDownloadEnd': self.handle_account_download_end,
        }
        self.ticker_ids={}
        self.symbols={}
        self.symbols_by_id={}
        self.primary_exchange_map={}
        self.tws_conn=None
        repeater = LoopingCall(self.EverySecond)
        repeater.start(1)

    def output(self, msg):
        sys.stderr.write(msg+'\n')
        sys.stderr.flush()
        
    def open_client(self, client):
        self.clients.add(client)
       
    def close_client(self, client):
        self.clients.discard(client)
        symbols = self.symbols.values()
        for ts in symbols:
            if client in ts.clients:
                ts.del_client(client)
                if not ts.clients:
                    del(self.symbols[ts.symbol])

    def set_primary_exchange(self, symbol, exchange):
        if exchange:
            self.primary_exchange_map[symbol] = exchange
        else:
            del(self.primary_exchange_map[symbol])
        return self.primary_exchange_map
              
    def CheckPendingResults(self):
        # check each callback list for timeouts
        for cblist in [self.position_callbacks, self.openorder_callbacks, self.execution_callbacks, self.bardata_callbacks, self.order_callbacks, self.cancel_callbacks, self.addsymbol_callbacks, self.accountdata_callbacks]:
            dlist=[]
            for cb in cblist:
                cb.check_expire()
                if cb.done:
                    dlist.append(cb)
                    if cblist == self.order_callbacks:
                        mid=str(cb.id)
                        if mid in self.pending_orders.keys():
                            del(self.pending_orders[mid])
                            self.output('pending order %s expired' % mid)
            # delete any callbacks that are done
            for cb in dlist:  
                cblist.remove(cb)
              
    def process_pending_order(self, mid, pid):
        # if there's a pending order with this msg id, this is the first time we
        # know the permid for the order, so move it to the real orders dict
        if mid in self.pending_orders.keys():
          self.orders[pid]=self.pending_orders[mid]
          self.orders[pid]['permid']=pid
          del(self.pending_orders[mid])
          self.output('pending order %s assigned permid %s' % (mid, pid))
        
    def handle_order_status(self, msg):
        mid=str(msg.orderId)
        pid=str(msg.permId)
        self.process_pending_order(mid, pid)
        if not pid in self.orders.keys():
            self.orders[pid] = {}
        m=self.orders[pid]
        if 'status' in m.keys():
            oldstatus=json.dumps(m)
        else:
            oldstatus=''
        m['permid']=msg.permId
        m['id']=msg.orderId
        m['status']=msg.status
        m['filled']=msg.filled
        m['remaining']=msg.remaining
        m['avgfillprice']=msg.avgFillPrice
        m['parentid']=msg.parentId
        m['lastfillprice']=msg.lastFillPrice
        m['clientid']=msg.clientId
        m['whyheld']=msg.whyHeld
        
        # callbacks are keyed by message-id, not permid
        for cb in self.cancel_callbacks:
            if cb.id == mid:
                self.output('cancel_callback[%s] completed' % mid)
                cb.complete(m)
                
        for cb in self.order_callbacks:
            if cb.id == mid:
                self.output('order_callback[%s] completed' % mid)
                cb.complete(m)

        if json.dumps(m) != oldstatus:
            self.send_order_status(m)
            
    def send_order_status(self, order):
        self.WriteAllClients('order.%s: %s' % (order['permid'], json.dumps(order)))
      
    def handle_open_order(self, msg):
        mid = str(msg.orderId)
        pid = str(msg.order.m_permId)
        self.process_pending_order(mid, pid)
        if not pid in self.orders.keys():
            self.orders[pid] = {}
        m=self.orders[pid]
        if 'status' in m.keys():
            oldstatus=json.dumps(m)
        else:
            oldstatus=''
        m['id']=msg.orderId
        m['symbol']=msg.contract.m_symbol
        m['action']=msg.order.m_action
        m['quantity']=msg.order.m_totalQuantity
        m['account']=msg.order.m_account
        m['clientid']=msg.order.m_clientId
        m['permid']=msg.order.m_permId
        m['price']=msg.order.m_lmtPrice
        m['aux_price']=msg.order.m_auxPrice
        m['type']=msg.order.m_orderType
        m['status']=msg.orderState.m_status
        m['warning']=msg.orderState.m_warningText
        if oldstatus != json.dumps(m):
            self.WriteAllClients('open-order.%s: %s' % (m['permid'], json.dumps(m)))
        
    def handle_accounts(self, msg):
        self.accounts = msg.accountsList.split(',')
        self.WriteAllClients('accounts: %s' % json.dumps(self.accounts))

    def set_account(self, account_name, callback):
        if account_name in self.accounts:
            self.current_account = account_name
            msg = 'current account set to %s' % account_name
            self.output(msg)
            ret=True
        else:
            msg = 'account %s not found' % account_name
            self.output('Error: set_account(): %s' % msg)
            ret=False
        self.WriteAllClients('current-account: %s' % self.current_account)
        if callback:
            TWS_Callback(self, 0, 'current-account', callback).complete(ret)
        else:
           return ret

    def EverySecond(self):
        if self.tws_conn:
            self.tws_conn.reqCurrentTime()
        else:
            self.connect()

        self.CheckPendingResults()
    
        if self.LastError == 504:
            self.output('TWS API disconnected; forcing shutdown')
            if SHUTDOWN_ON_TWS_DISCONNECT:
                reactor.stop()
      
    def WriteAllClients(self, msg):
        #self.output('WriteAllClients: %s.%s' % (self.channel, msg))
        msg = str('%s.%s\n' % (self.channel, msg))      
        for c in self.clients:
            c.transport.write(msg)
      
    def error_handler(self, msg):
        """Handles the capturing of error messages"""
        if msg.id is None and msg.errorCode is None:
            return
        self.LastError = msg.errorCode
        self.output('error: %s' % msg)
        result={'status':'Error','id':msg.id,'errorCode':msg.errorCode,'errorMsg':msg.errorMsg}

        for cb in self.order_callbacks:
            if str(cb.id) == str(msg.id):
                cb.complete(result)

        for cb in self.cancel_callbacks:
            if str(cb.id) == str(msg.id):
                cb.complete(result)

        for cb in self.addsymbol_callbacks:
            if str(cb.id.ticker_id) == str(msg.id):
                cb.complete(False)
                del(self.symbols[self.symbols_by_id[msg.id].symbol])
                del(self.symbols_by_id[msg.id])

        order = self.find_order_with_id(str(msg.id))
        if order:
            order['previous_status']=order['status']
            order['status']='Error'
            order['errorCode']=msg.errorCode
            order['errorMsg']=msg.errorMsg
            self.send_order_status(order)
            
        if msg.errorCode in [1100, 1300]:
            self.update_connection_status('Disconnected')
        elif msg.errorCode in [1101, 1102, 2104]:
            self.update_connection_status('Up')

        self.WriteAllClients('error: %s' % msg)

    def find_order_with_id(self, id):
        for order in self.orders.values():
           if 'id' in order.keys() and str(order['id'])==str(id):
                return order
        return None

    def reply_handler(self, msg):
        """Handles of server replies"""
        #self.output('message: %s %s ' % (repr(msg.typeName), msg))
        if msg.typeName in self.handlers.keys():
            self.handlers[msg.typeName](msg)
        else:
            self.output('unhandled: %s' % msg)
            
    def handle_time(self, msg):
        t = time.localtime(msg.time)
        if t[4] != self.last_minute:
            self.last_minute = t[4]
            self.WriteAllClients('time: %s' % time.strftime('%Y-%m-%d %H:%M:00', t))
      
    def create_contract(self, symbol, sec_type, exch, prim_exch, curr):
        """Create a Contract object defining what will
        be purchased, at which exchange and in which currency.
    
        symbol - The ticker symbol for the contract
        sec_type - The security type for the contract ('STK' is 'stock')
        exch - The exchange to carry out the contract on
        prim_exch - The primary exchange to carry out the contract on
        curr - The currency in which to purchase the contract

        In cases where SMART exchange results in ambiguity SYMBOL:PRIMARY_EXCHANGE can be passed."""

        contract = Contract()
        contract.m_symbol = symbol
        contract.m_secType = sec_type
        contract.m_exchange = exch
        if symbol in self.primary_exchange_map.keys():
            contract.m_primaryExch = self.primary_exchange_map[symbol]
        else:
            contract.m_primaryExch = prim_exch
        contract.m_currency = curr
        return contract

    def create_order(self, order_type, quantity, action):
        """Create an Order object (Market/Limit) to go long/short.
        order_type - 'MKT', 'LMT' for Market or Limit orders
        quantity - Integral number of assets to order
        action - 'BUY' or 'SELL'"""
        order = Order()
        order.m_orderType = order_type
        order.m_totalQuantity = quantity
        order.m_action = action
        order.m_account = self.current_account
        return order
    
    def connect(self):
        self.update_connection_status('Connecting')
        api_hostname = self.config.get('API_HOST')
        api_port = int(self.config.get('API_PORT'))
        api_client_id = int(self.config.get('API_CLIENT_ID'))
        self.output('Connnecting to TWS API at %s:%d with client id %d' % (api_hostname, api_port, api_client_id))
        self.tws_conn = Connection.create(host=api_hostname, port=api_port, clientId=api_client_id)
        self.tws_conn.registerAll(self.reply_handler)
        self.tws_conn.connect()
    
    def market_order(self, symbol, quantity, callback):
        return self.submit_order('MKT', 0, 0, symbol, int(quantity), callback)
      
    def limit_order(self, symbol, limit_price, quantity, callback):
        return self.submit_order('LMT', float(limit_price), 0, symbol, int(quantity), callback)
      
    def stop_order(self, symbol, stop_price, quantity, callback):
        return self.submit_order('STP', 0, float(stop_price), symbol, int(quantity), callback)
    
    def stoplimit_order(self, symbol, stop_price, limit_price, quantity, callback):
        return self.submit_order('STP LMT', float(limit_price), float(stop_price), symbol, int(quantity), callback)
    
    def submit_order(self, order_type, price, stop_price, symbol, quantity, callback): 
        order_id = self.next_id()
        tcb = TWS_Callback(self, str(order_id), 'order', callback)
        if(order_id < 0):
            ret={'status': 'Error', 'errorMsg': 'Cannot create order; next_order_id is not set'}
            tcb.complete(ret)
        else:
            status='Initialized'
            self.pending_orders[str(order_id)]={}
            self.pending_orders[str(order_id)]['status']=status
            self.output('created pending order %s' % str(order_id))
            contract = self.create_contract(symbol, 'STK', 'SMART', 'SMART', 'USD')
            if quantity > 0:
                type = 'BUY'
            else:
                type = 'SELL'
                quantity *= -1
            order = self.create_order(order_type, quantity, type)
            if order_type in ['STP', 'STP LMT']:
                order.m_auxPrice = stop_price
            if order_type in ['LMT', 'STP LMT']:
                order.m_lmtPrice = price
            self.order_callbacks.append(tcb)
            resp = self.tws_conn.placeOrder(order_id, contract, order)
            self.output('placeOrder(%s) returned %s' % (repr((order_id, contract, order)), repr(resp)))
        
    def cancel_order(self, id, callback):
        self.output('cancel_order%s' % repr((id)))
        mid=str(id)
        tcb = TWS_Callback(self, mid, 'cancel_order', callback)
        order = self.find_order_with_id(mid)
        if order:
            if order['status'] == 'Cancelled':
                tcb.complete({'status': 'Error', 'errorMsg': 'Already cancelled.', 'id': id})
            else:
                resp = self.tws_conn.cancelOrder(mid)
                self.output('cancelOrder(%s) returned %s' % (repr(mid), repr(resp)))
                self.cancel_callbacks.append(tcb)
        else:
            tcb.complete({'status': 'Error', 'errorMsg': 'Order not found', 'id': mid})
      
    def symbol_enable(self, symbol, client, callback):
        if not symbol in self.symbols.keys():
            self.addsymbol_callbacks.append(TWS_Callback(self, TWS_Symbol(self, symbol, client), 'add-symbol', callback))
        else:
            self.symbols[symbol].add_client(client)
            TWS_Callback(self, 0, 'add-symbol', callback).complete(True)
          
    def symbol_disable(self, symbol, client):
        if symbol in self.symbols.keys():
            ts = self.symbols[symbol]
            ts.del_client(client)
            if not ts.clients:
                del(self.symbols[symbol])
            return True     
          
    def handle_tick_size(self, msg):
        if self.enable_ticker:
          self.output('%s %d %s %d' % (repr(msg), msg.field, TickType().getField(msg.field), msg.size))
        symbol = self.symbols_by_id[msg.tickerId]
        if msg.field==0: # bid_size
            symbol.bid_size=msg.size
            if self.enable_ticker:
                symbol.update_quote()
        elif msg.field==3: # ask_size
            symbol.ask_size=msg.size
            if self.enable_ticker:
                symbol.update_quote()
        elif msg.field==5: # last_size
            symbol.size=msg.size
        elif msg.field==8: # volume
            symbol.volume=msg.size
            if self.enable_ticker:
                symbol.update_trade()

    def handle_tick_price(self, msg):
        for cb in self.addsymbol_callbacks:
            if str(cb.id.ticker_id) == str(msg.tickerId):
                cb.complete(True)
        if self.enable_ticker:
            self.output('%s %d %s %s' % (repr(msg), msg.field, TickType().getField(msg.field), msg.price))
        symbol = self.symbols_by_id[msg.tickerId]
        if msg.field==1: # bid
            symbol.bid=msg.price
            if self.enable_ticker:
                symbol.update_quote()
        elif msg.field==2: # ask
            symbol.ask=msg.price
            if self.enable_ticker:
                symbol.update_quote()
        elif msg.field==4: # last
            symbol.last=msg.price
        elif msg.field==9: # close
            symbol.close=msg.price
              
    def handle_tick_string(self, msg):
        if self.enable_ticker:
            self.output('%s %d %s %s' % (repr(msg), msg.tickType, TickType().getField(msg.tickType), msg.value))
        
    def handle_next_valid_id(self, msg):
        self.next_order_id = msg.orderId
        msg='next_valid_id: %d' % msg.orderId
        self.WriteAllClients(msg)
        self.output(msg)
        
    def disconnect(self):
        # Disconnect from TWS
        self.output('TWS disconnected')
        self.update_connection_status('Disconnected')
        self.WriteAllClients('error: TWS API Disconnected')
        self.tws_conn.disconnect()
        
    def update_connection_status(self, status):
        self.connection_status = status
        if status != self.last_connection_status:
            self.last_connection_status=status
            self.WriteAllClients('connection-status-changed: %s' % status)
        
    def next_id(self):
        id = self.next_order_id
        self.next_order_id += 1
        return id
 
    def request_accounts(self, callback):
        TWS_Callback(self, 0, 'request-accounts', callback).complete(self.accounts)
        
    def request_positions(self, callback):
        if not self.position_callbacks:
            self.positions={}
            self.tws_conn.reqPositions()
        id = self.next_id()
        self.position_callbacks.append(TWS_Callback(self, 0, 'positions', callback))
        return id
        
    def handle_position(self, msg):
        if not msg.account in self.positions.keys():
            self.positions[msg.account] = {}
        # only return STOCK positions
        if msg.contract.m_secType == 'STK':
          pos = self.positions[msg.account]
          pos[msg.contract.m_symbol] = msg.pos  
        
    def handle_position_end(self, msg):
        for cb in self.position_callbacks:
            cb.complete(self.positions)
        self.position_callbacks=[]
        
    def request_orders(self, callback):
        if not self.openorder_callbacks:
            self.tws_conn.reqAllOpenOrders()
        self.openorder_callbacks.append(TWS_Callback(self, 0, 'orders', callback))
          
    def handle_open_order_end(self, msg):
        for cb in self.openorder_callbacks:
            cb.complete(self.orders)
        self.openorder_callbacks=[]
      
    def request_executions(self, callback):
        if not self.execution_callbacks:
            self.executions={}
            filter=ExecutionFilter()
            id=self.next_id()
            self.tws_conn.reqExecutions(id, filter)
        self.execution_callbacks.append(TWS_Callback(self, 0, 'executions', callback))

    def request_account_data(self, account, fields, callback):
        need_request = False
        if account not in self.pending_account_data_requests:
            self.account_data[account]={}
            need_request = True
        
        cb = TWS_Callback(self, account, 'account_data', callback)
        cb.data = fields
        self.accountdata_callbacks.append(cb)

        if need_request:
            self.output('requesting account updates: %s' % account)
            self.pending_account_data_requests.add(account)
            self.tws_conn.reqAccountUpdates(False, account)
            self.tws_conn.reqAccountUpdates(True, account)
        else:
            self.output('NOT requesting account updates: %s (one is already pending)' % account)

    def handle_account_value(self, msg):
        self.output('%s %s %s %s %s' % (repr(msg), msg.key, msg.value, msg.currency, msg.accountName))
        if not msg.accountName in self.account_data.keys():
          self.account_data[msg.accountName]={}
        self.account_data[msg.accountName][msg.key]=(msg.value, msg.currency)

    def handle_account_download_end(self, msg):
        self.output('%s %s' % (repr(msg), msg.accountName))
        dcb=[]
        for cb in self.accountdata_callbacks:
            if cb.id == msg.accountName:
                account_data = self.account_data[msg.accountName]
                # if field list specified, only return those fields, else return all fields
                if cb.data:
                  response_data={}
                  for field in cb.data:
                    response_data[field] = account_data[field] if field in account_data.keys() else None
                else:
                  response_data = account_data
                cb.complete(response_data)
                dcb.append(cb)
                self.tws_conn.reqAccountUpdates(False, msg.accountName)
                self.output('cancelling account updates: %s' % msg.accountName)
                self.pending_account_data_requests.discard(msg.accountName)
        for cb in dcb:
           del self.accountdata_callbacks[self.accountdata_callbacks.index(cb)]
        
    def handle_exec_details(self, msg):
        self.output('%s %s %s %s %s' % (repr(msg), msg.execution.m_side, msg.contract.m_symbol, msg.execution.m_cumQty, msg.execution.m_price))
        self.executions[msg.execution.m_execId] = {}
        e=self.executions[msg.execution.m_execId]
        e['execId']=msg.execution.m_execId
        e['symbol']=msg.contract.m_symbol
        e['account']=msg.execution.m_acctNumber
        e['avgprice']=msg.execution.m_avgPrice
        e['cumqty']=msg.execution.m_cumQty
        e['exchange']=msg.execution.m_exchange
        e['clientid']=msg.execution.m_clientId
        e['orderid']=msg.execution.m_orderId
        e['permid']=msg.execution.m_permId
        e['shares']=msg.execution.m_shares
        e['price']=msg.execution.m_price
        e['side']=msg.execution.m_side
        e['time']=msg.execution.m_time
        self.WriteAllClients('execution.%s: %s' % (e['execId'], json.dumps(e)))
        
    def handle_exec_details_end(self, msg):
        for cb in self.execution_callbacks:
            cb.complete(self.executions)
        self.execution_callbacks=[]
        
    def request_global_cancel(self):
        self.tws_conn.reqGlobalCancel()
        
    def query_bars(self, symbol, period, bar_start, bar_end, callback):
        id = self.next_id()
        self.output('bardata request id=%s' % id)
        cb=TWS_Callback(self, id, 'bardata', callback, 30) # 30 second timeout for bar data
        contract = self.create_contract(symbol, 'STK', 'SMART', 'SMART', 'USD')
        if type(bar_start)!=types.IntType:
            mxd = mx.DateTime.ISO.ParseDateTime(bar_start)
            bar_start=datetime.datetime(mxd.year, mxd.month, mxd.day, mxd.hour, mxd.minute, int(mxd.second))
        if type(bar_end)!=types.IntType:
            mxd = mx.DateTime.ISO.ParseDateTime(bar_end)
            bar_end=datetime.datetime(mxd.year, mxd.month, mxd.day, mxd.hour, mxd.minute, int(mxd.second))
        #try:
        if 1==1:
            endDateTime = bar_end.strftime('%Y%m%d %H:%M:%S')
            durationStr = '%s S' % (bar_end - bar_start).seconds
            barSizeSetting = {'1': '1 min', '5': '5 mins'}[str(period)]  # legal period values are '1' and '5' 
            whatToShow = 'TRADES'
            useRTH = 0
            formatDate = 1
            self.bardata_callbacks.append(cb)
            self.output('edt:%s ds:%s bss:%s' % (endDateTime, durationStr, barSizeSetting))
            self.tws_conn.reqHistoricalData(id, contract, endDateTime, durationStr, barSizeSetting, whatToShow, useRTH, formatDate)
        #except:
        if 1==2:
            cb.complete(['Error', 'query_bars(%s) failed!' % repr((bar_symbol, bar_period, bar_start, bar_end)), 'Count: 0'])
            
    def handle_historical_data(self, msg):
        for cb in self.bardata_callbacks:
            if cb.id==msg.reqId:
                if not cb.data:
                    cb.data=[]
                if msg.date.startswith('finished'):
                    cb.complete(['OK', cb.data])
                else:
                    cb.data.append(dict(msg.items()))
        #self.output('historical_data: %s' % msg) #repr((id, start_date, bar_open, bar_high, bar_low, bar_close, bar_volume, count, WAP, hasGaps)))

    def query_connection_status(self):
        return self.connection_status
    
        
if __name__=='__main__':
    log.startLogging(sys.stdout)
    tws=TWS()
    reactor.listenTCP(tws.tcp_port, serverFactory(tws))
    xmlsvr=xmlserver(tws)

    xmlrpc.addIntrospection(xmlsvr)
    reactor.listenTCP(tws.xmlrpc_port, server.Site(xmlsvr))
    reactor.run()
