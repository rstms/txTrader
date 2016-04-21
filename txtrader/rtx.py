#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  rtx.py
  ------

  RealTick TWS API interface module

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""


from version import __version__, __date__, __label__

import sys, mx.DateTime, types, datetime
from uuid import uuid1
import json
import time

from client import Config

DEFAULT_CALLBACK_TIMEOUT = 5

# allow disable of tick requests for testing
ENABLE_TICK_REQUESTS = True 

DISCONNECT_SECONDS = 15
SHUTDOWN_ON_DISCONNECT = True
ADD_SYMBOL_TIMEOUT = 5

from twisted.python import log
from twisted.internet.protocol import Factory, Protocol
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web import xmlrpc, server
from socket import gethostname


class API_Symbol():
    def __init__(self, api, symbol, client_id, init_callback):
        self.api = api 
        self.id = str(uuid1())
        self.output = api.output
        self.clients=set([client_id])
        self.callback = init_callback
        self.symbol=symbol
        self.fullname=''
        self.bid=0.0
        self.bid_size=0
        self.ask=0.0
        self.ask_size=0
        self.last=0.0
        self.size=0
        self.volume=0
	self.close=0.0
        self.rawdata=''
        self.api.symbols[symbol]=self
        self.last_quote = ''
        self.output('API_Symbol %s %s created for client %s' % (self, symbol, client_id))
        self.output('Adding %s to watchlist' % self.symbol)
        self.cxn = api.cxn_get('TA_SRV', 'LIVEQUOTE')
        cb = API_Callback(self.api, self.cxn.id, 'init_symbol', RTX_LocalCallback(self.api, self.init_handler), ADD_SYMBOL_TIMEOUT)
        self.cxn.request('LIVEQUOTE', '*', "DISP_NAME='%s'" % symbol, cb)
        
    def __str__(self):
        return 'API_Symbol(%s bid=%s bidsize=%d ask=%s asksize=%d last=%s size=%d volume=%d close=%s clients=%s' % (self.symbol, self.bid, self.bid_size, self.ask, self.ask_size, self.last, self.size, self.volume, self.close, self.clients)
        
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
          'fullname': self.fullname
        }
      
    def add_client(self, client):
        self.output('API_Symbol %s %s adding client %s' % (self, self.symbol, client))
        self.clients.add(client)
      
    def del_client(self, client):
        self.output('API_Symbol %s %s deleting client %s' % (self, self.symbol, client))
        self.clients.discard(client)
        if not self.clients:
            self.output('Removing %s from watchlist' % self.symbol)
            # TODO: stop live updates of market data from RTX
            
    def update_quote(self):
        quote = 'quote.%s:%s %d %s %d' % (self.symbol, self.bid, self.bid_size, self.ask, self.ask_size)
        if quote != self.last_quote:
            self.last_quote = quote
            self.api.WriteAllClients(quote)
          
    def update_trade(self):
        self.api.WriteAllClients('trade.%s:%s %d %d' % (self.symbol, self.last, self.size, self.volume))

    def init_handler(self, data):
        self.output('API_Symbol init: %s' % data)
        self.rawdata = data
        self.parse_fields(None, data[0])
        if self.api.symbol_init(self):
            self.cxn = self.api.cxn_get('TA_SRV', 'LIVEQUOTE')
            self.cxn.advise('LIVEQUOTE', 'TRDPRC_1,TRDVOL_1,BID,BIDSIZE,ASK,ASKSIZE,ACVOL_1', "DISP_NAME='%s'" % self.symbol, self.parse_fields)

    def parse_fields(self, cxn, data):
        trade_flag=False
        quote_flag=False
        if 'TRDPRC_1' in data.keys():
           self.last = float(data['TRDPRC_1'])
           trade_flag=True
        if 'TRDVOL_1' in data.keys():
           self.size = int(data['TRDVOL_1'])
           trade_flag=True
        if 'ACVOL_1' in data.keys():
           self.volume = int(data['ACVOL_1'])
           trade_flag=True
        if 'BID' in data.keys():
           self.bid = float(data['BID'])
           quote_flag=True
        if 'BIDSIZE' in data.keys():
           self.bidsize = int(data['BIDSIZE'])
           quote_flag=True
        if 'ASK' in data.keys():
           self.ask = float(data['ASK'])
           quote_flag=True
        if 'ASKSIZE' in data.keys():
           self.asksize = int(data['ASKSIZE'])
           quote_flag=True
        if 'COMPANY_NAME' in data.keys():
           self.fullname = data['COMPANY_NAME']
        if 'HST_CLOSE' in data.keys():
           self.close = float(data['HST_CLOSE'])

        if quote_flag:
           self.update_quote()

        if trade_flag:
           self.update_trade()

    def update_handler(self, data):
        self.output('API_Symbol update: %s' % data)
        self.rawdata = data
        
class API_Callback():
    def __init__(self, api, id, label, callable, timeout=0):
        """callable is stored and used to return results later"""
        api.output('API_Callback.__init__() %s' % self)
        self.api=api
        self.id=id
        self.label=label
        if not timeout:
          timeout = api.callback_timeout
        self.expire=int(mx.DateTime.now())+timeout
        self.callable=callable
        self.done=False
        self.data=None

    def complete(self, results):
        """complete callback by calling callable function with value of results"""
        self.api.output('API_Callback.complete() %s' % self)
        if not self.done:
            if self.callable.callback.__name__=='write':
                results='%s.%s: %s\n' % (self.api.channel, self.label, json.dumps(results))
            self.callable.callback(results)
            self.done=True
        else:
            self.api.output('error: callback: %s was already done!' % self)
            
    def check_expire(self):
        self.api.output('API_Callback.check_expire() %s' % self)
        if not self.done:
            if int(mx.DateTime.now()) > self.expire:
                self.api.WriteAllClients('error: callback expired: %s' % repr((self.id, self.label)))
                if self.callable.callback.__name__=='write':
                    self.callable.callback('%s.error: %s callback expired\n', (self.api.channel, self.label))
                else:
                    self.callable.callback(None)
                self.done=True

# set an update_handler to handle async updates
# set response pending,
class RTX_Connection():
  def __init__(self, api, service, topic):
    self.api = api
    self.id = str(uuid1())
    self.service = service
    self.topic = topic
    self.key = '%s;%s' % (service, topic)
    self.api.cxn_register(self)
    self.api.gateway_send('connect %s %s' % (self.id, self.key))
    self.response_pending='CONNECTION PENDING'
    self.response_callback=None
    self.status_pending = 'OnInitAck'
    self.status_callback=None
    self.update_callback=None
    self.update_handler=None
    self.connected = False
    self.on_connect_action=None
    self.update_ready()

  def update_ready(self):
    self.ready = not(self.response_pending or self.response_callback or self.status_pending or self.status_callback or self.update_callback or self.update_handler)
    self.api.output('update_ready() %s %s' % (self, self.ready))
    if self.ready:
      self.api.cxn_activate(self) 

  def receive(self, type, data):
    if type=='response':
      self.handle_response(data)
    elif type == 'status':
      self.handle_status(data)
    elif type == 'update':
      self.handle_update(data)
    else:
      self.api.error_handler(self.id, 'Message Type Unexpected: %s' % data) 
    self.update_ready()

  def handle_response(self, data):
    self.api.output('Connection Response: %s %s' % (self, data))
    if self.response_pending:
      if data == self.response_pending:
        self.response_pending=None
      else:
        self.api.error_handler(id, 'Response Error: %s' % data) 
      if self.response_callback:
        self.response_callback.complete(data)
        self.response_callback = None
    else:
      self.api.error_handler(id, 'Response Unexpected: %s' % data) 

  def handle_status(self, s):
    self.api.output('Connection Status: %s %s' % (self, s))
    if self.status_pending and s['msg']==self.status_pending:
      self.status_pending = None
      if s['status']=='1':
        if s['msg']=='OnInitAck':
          self.connected = True
          if self.on_connect_action:
            self.ready = True
            cmd, arg, exr, cbr, exs, cbs, cbu, uhr = self.on_connect_action
            self.api.output('Sending on_connect_action: %s' % repr(self.on_connect_action))
            self.send(cmd, arg, exr, cbr, exs, cbs, cbu, uhr)
            self.on_connect_action = None
      else:
        self.api.error_handler(self.id, 'Status Error: %s' % data) 
    else:
      self.api.error_handler(self.id, 'Status Unexpected: %s' % data) 

  def handle_update(self, d):
    self.api.output('Connection Update: %s %s' % (self, repr(d)))
    if self.update_callback:
      self.update_callback.complete(d)
      self.update_callback=None
    else:
      if self.update_handler:
        self.update_handler(self, d)
      else:
        self.api.error_handler(self.id, 'Update Unexpected: %s' % repr(d)) 

  def query(self, cmd, table, what, where, ex_response, cb_response, ex_status, cb_status, cb_update, update_handler):
    ret = self.send(cmd, '%s;%s;%s' % (table, what, where), ex_response, cb_response, ex_status, cb_status, cb_update, update_handler)

  def request(self, table, what, where, callback):
    return self.query('request', table, what, where, 'REQUEST_OK', None, None, None, callback, None)

  def advise(self, table, what, where, handler):
    return self.query('advise', table, what, where, 'ADVISE_OK', None, 'OnOtherAck', None, None, handler)

  def adviserequest(self, table, what, where, callback, handler):
    return self.query('adviserequest', table, what, where, 'ADVISEREQUEST_OK', None, 'OnOtherAck', None, callback, handler)

  def unadvise(self, table, what, where, callback):
    return self.query('unadvise', table, what, where, 'UNADVISE_OK', None, 'OnOtherAck', callback, None, None)

  def poke(self, table, what, where, data, callback):
    return self.send('poke', '%s;%s;%s!%s' % (table, what, where, data), "POKE_OK", callback)

  def execute(self, command, callback):
    return self.send('execute', command, "EXECUTE_OK", callback)
   
  def terminate(self, code, callback):
    return self.send('terminate', str(code), "TERMINATE_OK", callback)
  
  def send(self, cmd, args, ex_response=None, cb_response=None, ex_status=None, cb_status=None, cb_update=None, update_handler=None):
    if self.ready:
      ret = self.api.gateway_send('%s %s %s' % (cmd, self.id, args))
      self.response_pending = ex_response
      self.response_callback = cb_response
      self.status_pending = ex_status
      self.status_callback = cb_status
      self.update_callback = cb_update
      self.update_handler = update_handler
    else:
      if self.on_connect_action:
        self.api.error_handler(self.id, 'Failure: on_connect_action already exists: %s' % repr(self.on_connect_action)) 
        ret=False
      else:
        self.api.output('storing on_connect_action...%s' % self)
        self.on_connect_action=(cmd, args, ex_response, cb_response, ex_status, cb_status, cb_update, update_handler)
        ret=True
    return ret

class RTX_LocalCallback:
  def __init__(self, api, handler):
    self.api = api
    self.callback_handler = handler

  def callback(self, data):
    if self.callback_handler:
        self.callback_handler(data)
    else:
        self.api.error_handler(self.id, 'Failure: undefined callback_handler for Connection: %s' % repr(self)) 

class RTX():
    def __init__(self):
        self.label = 'RTX Gateway'
        self.channel = 'rtx'
	self.id='RTX'
        self.output('RTX init')
        self.config = Config(self.channel)
        self.api_hostname = self.config.get('API_HOST')
        self.api_port = int(self.config.get('API_PORT'))
        self.username = self.config.get('USERNAME')
        self.password = self.config.get('PASSWORD')
        self.xmlrpc_port = int(self.config.get('XMLRPC_PORT'))
        self.tcp_port = int(self.config.get('TCP_PORT'))
        self.callback_timeout = int(self.config.get('CALLBACK_TIMEOUT'))
        if not self.callback_timeout:
          self.callback_timeout = DEFAULT_CALLBACK_TIMEOUT
        self.output('callback_timeout=%d' % self.callback_timeout)
        self.enable_ticker = bool(int(self.config.get('ENABLE_TICKER')))
        self.current_account=''
        self.clients=set([])
        self.orders={}
        self.pending_orders={}
        self.openorder_callbacks=[]
        self.accounts=None
        self.account_data={}
        self.pending_account_data_requests=set([])
        self.positions={}
        self.position_callbacks=[]
        self.executions={}
        self.execution_callbacks=[]
        self.bardata_callbacks=[]
        self.cancel_callbacks=[]
        self.order_callbacks=[]
        self.add_symbol_callbacks=[]
        self.accountdata_callbacks=[]
        self.set_account_callbacks=[]
        self.account_request_callbacks=[]
        self.account_request_pending = True
        self.timer_callbacks=[]
        self.connected=False
        self.last_connection_status=''
        self.connection_status='Initializing'
        self.LastError=-1
        self.next_order_id=-1
        self.last_minute=-1
        self.symbols={}
        self.primary_exchange_map={}
        self.gateway_sender=None
        self.active_cxn={}
        self.idle_cxn={}
        self.cx_time=None
        self.seconds_disconnected=0
        self.repeater = LoopingCall(self.EverySecond)
        self.repeater.start(1)

    def cxn_register(self, cxn):
        self.output('cxn_register: %s' % repr(cxn))
        self.active_cxn[cxn.id]=cxn

    def cxn_activate(self, cxn):
        self.output('cxn_activate: %s' % repr(cxn))
        if not cxn.key in self.idle_cxn.keys():
            self.idle_cxn[cxn.key]=[]
        self.idle_cxn[cxn.key].append(cxn)

    def cxn_get(self, service, topic):
        key = '%s;%s' % (service, topic)
        if key in self.idle_cxn.keys() and len(self.idle_cxn[key]):
          cxn = self.idle_cxn[key].pop()
        else:
          cxn = RTX_Connection(self, service, topic)
        self.output('cxn_get() returning: %s' % repr(cxn))
        return cxn

    def gateway_connect(self, protocol):
        if protocol:
            self.gateway_sender = protocol.sendLine
            self.gateway_transport = protocol.transport
        else:
            self.gateway_sender = None
            self.connected=False
            self.seconds_disconnected=0
            self.account_request_pending = False
            self.accounts=None
            self.update_connection_status('Disconnected')
            self.WriteAllClients('error: API Disconnected')
        return self.gateway_receive

    def gateway_send(self, msg):
        self.output('<-- %s' % repr(msg))
        if self.gateway_sender:
            self.gateway_sender('%s\n' % msg)

    def gateway_receive(self, msg):
        """handle input from rtgw """
        o = json.loads(msg)
        msg_type = o['type']
        msg_id =  o['id']
        msg_data = o['data']
        self.output('--> %s %s %s' % (msg_type, msg_id, msg_data))
 
        if msg_type == 'system':
            self.handle_system_message(msg_id, msg_data)
        else:
            if msg_id in self.active_cxn.keys():
                c = self.active_cxn[msg_id].receive(msg_type, msg_data)
            else:
                self.error_handler(self.id, 'Message Received on Unknown connection: %s' % repr(msg)) 

        return True

    def handle_system_message(self, id, data):
        if data['msg']=='startup':
            self.connected = True
            self.accounts=None
            self.update_connection_status('Connected')
            self.output('Connected to %s' % data['item'])
            self.setup_local_queries()
        else:
            self.error_handler(self.id, 'Unknown system message: %s' % repr(data)) 

    def setup_local_queries(self):
        """Upon connection to rtgw, start automatic queries"""
        self.rtx_request('ACCOUNT_GATEWAY', 'ORDER', 'ACCOUNT', '*', '', 'accounts', self.handle_accounts, self.accountdata_callbacks, 5)

    def output(self, msg):
        sys.stderr.write('%s\n' % msg)
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
        for cblist in [self.timer_callbacks, self.position_callbacks, self.openorder_callbacks, self.execution_callbacks, self.bardata_callbacks, self.order_callbacks, self.cancel_callbacks, self.add_symbol_callbacks, self.accountdata_callbacks, self.set_account_callbacks, self.account_request_callbacks]:
            dlist=[]
            for cb in cblist:
                cb.check_expire()
                if cb.done:
                    dlist.append(cb)
            # delete any callbacks that are done
            for cb in dlist:  
                cblist.remove(cb)
              
    def handle_order_status(self, msg):
        mid=str(msg.orderId)
        pid=str(msg.permId)
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
        if msg:
            self.accounts = []
            for row in msg:
                account = '%s.%s.%s.%s.%s' % (row['BANK'], row['BRANCH'], row['CUSTOMER'], row['DEPOSIT'], row['ACCT_TYPE'])
                self.accounts.append(account)
            self.accounts.sort()
            self.account_request_pending = False
            self.WriteAllClients('accounts: %s' % json.dumps(self.accounts))
            for cb in self.account_request_callbacks:
	        cb.complete(self.accounts)

            for cb in self.set_account_callbacks:
                self.outptut('set_account: processing deferred response.')
                process_set_account(cb.id, cb)
        else:
            self.error_handler(self.id, 'handle_accounts: unexpected null input')

    def set_account(self, account_name, callback):
        cb = API_Callback(self, account_name, 'set-account', callback)
        if self.accounts:
            self.process_set_account(account_name, cb)
        elif self.account_request_pending:
            self.account_set_callbacks.append(cb)
	else:
            self.output('Error: set_account; no data, but no account_request_pending')
            cb.complete(None)        

    def process_set_account(self, account_name, callback):
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
            callback.complete(ret)
        else:
           return ret

    def rtx_request(self, service, topic, table, what, where, label, handler, cb_list, timeout=0): 
        cxn = self.cxn_get(service, topic)
        cb = API_Callback(self, cxn.id, label, RTX_LocalCallback(self, handler), timeout)
        cxn.request(table, what, where, cb)
        cb_list.append(cb)

    def EverySecond(self):
        if self.connected:
             if ENABLE_TICK_REQUESTS:
                 self.rtx_request('TA_SRV', 'LIVEQUOTE', 'LIVEQUOTE', 'DISP_NAME,TRDTIM_1,TRD_DATE', "DISP_NAME='$TIME'", 'tick', self.handle_time, self.timer_callbacks, 5)
        else:
            self.seconds_disconnected += 1
            if self.seconds_disconnected > DISCONNECT_SECONDS:
                self.output('Realtick Gateway is disconnected; forcing shutdown')
                if SHUTDOWN_ON_DISCONNECT:
                    reactor.stop()

        self.CheckPendingResults()
      
    def WriteAllClients(self, msg):
        self.output('WriteAllClients: %s.%s' % (self.channel, msg))
        msg = str('%s.%s\n' % (self.channel, msg))      
        for c in self.clients:
            c.transport.write(msg)
      
    def error_handler(self, id, msg):
        """report error messages"""
        self.output('ERROR: %s %s' % (id, msg))
        self.WriteAllClients('error: %s %s' % (id, msg))

    def handle_time(self, rows):
        print('handle_time: %s' % json.dumps(rows))
        if rows:
          hour, minute = [int(i) for i in rows[0]['TRDTIM_1'].split(':')[0:2]]
          if minute != self.last_minute:
              self.last_minute = minute
              self.WriteAllClients('time: %s %02d:%02d:00' % (rows[0]['TRD_DATE'], hour, minute))
        else:
          self.error_handler('handle_time: unexpected null input')
      
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
        self.output('Awaiting startup response from RTX gateway at %s:%d...' % (self.api_hostname, self.api_port))
    
    def market_order(self, symbol, quantity, callback):
        return self.submit_order('market', 0, 0, symbol, int(quantity), callback)
      
    def limit_order(self, symbol, limit_price, quantity, callback):
        return self.submit_order('limit', float(limit_price), 0, symbol, int(quantity), callback)
      
    def stop_order(self, symbol, stop_price, quantity, callback):
        return self.submit_order('stop', 0, float(stop_price), symbol, int(quantity), callback)
    
    def stoplimit_order(self, symbol, stop_price, limit_price, quantity, callback):
        return self.submit_order('stoplimit', float(limit_price), float(stop_price), symbol, int(quantity), callback)
    
    def submit_order(self, order_type, price, stop_price, symbol, quantity, callback): 

        


        self.output('ERROR: submit_order unimplemented')
        
    def cancel_order(self, id, callback):
        self.output('ERROR: cancel_order unimplemented')
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
        self.output('symbol_enable(%s,%s,%s)' %(symbol, client, callback))
        if not symbol in self.symbols.keys():
            cb = API_Callback(self, symbol, 'add-symbol', callback)
            symbol = API_Symbol(self, symbol, client, cb)
            self.add_symbol_callbacks.append(cb)
        else:
            self.symbols[symbol].add_client(client)
            API_Callback(self, 0, 'add-symbol', callback).complete(True)
        self.output('symbol_enable: symbols=%s' % repr(self.symbols))

    def symbol_init(self, symbol):
        ret = not 'SYMBOL_ERROR' in symbol.rawdata[0].keys()
        if not ret:
            self.symbol_disable(symbol.symbol, list(symbol.clients)[0])
        symbol.callback.complete(ret)
        return ret

    def symbol_disable(self, symbol, client):
        self.output('symbol_disable(%s,%s)' %(symbol, client))
        self.output('self.symbols=%s' % repr(self.symbols))
        if symbol in self.symbols.keys():
            ts = self.symbols[symbol]
            ts.del_client(client)
            if not ts.clients:
                del(self.symbols[symbol])
            self.output('ret True: self.symbols=%s' % repr(self.symbols))
            return True     
        self.output('ret False: self.symbols=%s' % repr(self.symbols))
          
    def update_connection_status(self, status):
        self.connection_status = status
        if status != self.last_connection_status:
            self.last_connection_status=status
            self.WriteAllClients('connection-status-changed: %s' % status)

    def request_accounts(self, callback):
        cb = API_Callback(self, 0, 'request-accounts', callback)
        if self.accounts:
            cb.complete(self.accounts)
        elif self.account_request_pending:
            self.account_request_callbacks.append(cb)
	else:
            self.output('Error: request_accounts; no data, but no account_request_pending')
            cb.complete(None)        

    def request_positions(self, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'positions', callback)
        cxn.request('POSITION', '*', '', cb) 
        self.position_callbacks.append(cb)
        return cxn.id
        
    def request_orders(self, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'orders', callback)
        cxn.request('ORDERS', '*', '', cb) 
        self.openorder_callbacks.append(cb)
        return cxn.id
          
    def request_executions(self, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'executions', callback)
        cxn.request('ORDERS', '*', "CURRENT_STATUS='COMPLETED',TYPE='ExchangeTradeOrder'", cb) 
        self.execution_callbacks.append(cb)
        return cxn.id

    def request_account_data(self, account, fields, callback):
        cxn = self.cxn_get('ACCOUNT_GATEWAY', 'ORDER')
        cb = API_Callback(self, 0, 'account_data', callback)
        cxn.request('DEPOSIT', '*', '', cb) 
        self.accountdata_callbacks.append(cb)
        return cxn.id

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
    from xmlserver import xmlserver
    from tcpserver import serverFactory
    from tcpclient import clientFactory

    log.startLogging(sys.stdout)
    rtx=RTX()
    reactor.listenTCP(rtx.tcp_port, serverFactory(rtx))
    xmlsvr=xmlserver(rtx)
    xmlrpc.addIntrospection(xmlsvr)
    reactor.listenTCP(rtx.xmlrpc_port, server.Site(xmlsvr))
    reactor.connectTCP(rtx.api_hostname, rtx.api_port, clientFactory(rtx.gateway_connect, 'rtgw'))
    reactor.run()
