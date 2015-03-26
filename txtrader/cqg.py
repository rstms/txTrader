#!/usr/bin/env python

# Copyright (c) 2015 Reliance Systems, Inc.


from version import __version__, __date__, __label__

if __name__=='__main__':
    print 'installing win32eventreactor'
    from twisted.internet import win32eventreactor
    win32eventreactor.install()

import sys, win32com.client, mx.DateTime, types, datetime, json, time
win32com.client.gencache.is_readonly=False
from win32com.client import Dispatch, constants
from os import environ
import traceback

QUERY_TIMEOUT_SECONDS = 3

ORDERS_PER_SECOND = 4.5

SHUTDOWN_IF_NO_DATA_CONNECTION = 1  # 0==never shutdown, 1==shutdown after DISCONNECT_TIMEOUT seconds
DISCONNECT_TIMEOUT = 10

from twisted.python import log
from twisted.internet.protocol import Factory, Protocol
from twisted.internet import reactor, defer
from twisted.internet.task import LoopingCall
from twisted.web import xmlrpc, server
from twisted.protocols import basic
from socket import gethostname
import Queue

from xmlserver import xmlserver
from tcpserver import serverFactory

class CQG_Quote():
    def __init__(self, comid):
        self.comid=comid
        if comid:
            self.quote = Dispatch(comid)
        else:
            self.quote = None

    def export(self):
        ret={}
        if self.IsValid():
            ret['Name']=self.quote.Name
            ret['Type']=self.quote.Type
            ret['Price']=self.quote.Price
            if self.quote.HasVolume:
                ret['Volume']=self.quote.Volume
        return ret
            
    def IsValid(self):
        return self.quote and self.quote.IsValid
            
    def __str__(self):
        if self.quote:
            if self.quote.IsValid:
                ret='Name=%s,Type=%d,Price=%f' % (self.quote.Name, self.quote.Type, self.quote.Price)
                if self.quote.HasVolume:
                    ret += ',Volume=%d' % self.quote.Volume
            else:
                ret='Invalid'
        else:
            ret='None'
        return '<CQG_Quote:%s>' % ret

    def __repr__(self):
        return self.__str__()

class CQG_Symbol():
    def __init__(self, cel, symbol, client):
        self.cel=cel
        self.output=cel.output
        self.ID=-1
        self.symbol=symbol
        self.instrument=None
        self.bid=0
        self.bidsize=0
        self.ask=0
        self.asksize=0
        self.last=0
        self.size=0
        self.volume=0
        self.Bid=None
        self.Ask=None
        self.Trade=None
        self.last_quote=''
        self.last_volume=-1
        self.clients=set([])
        self.add_client(client)
        self.cel.NewInstrument(symbol)
        
    def set_instrument(self, comid):
        self.comid=comid
        self.instrument=Dispatch(comid)
        self.ID = self.instrument.InstrumentID
        
    def update(self, instrument):
        self.bid = instrument.Bid.Price 
        self.bidsize = instrument.Bid.Volume
        self.ask = instrument.Ask.Price 
        self.asksize = instrument.Ask.Volume
        self.update_quote()
        self.last =  instrument.Trade.Price
        self.size = instrument.Trade.Volume
        self.volume = instrument.TodayCTotalVolume
        self.update_trade()
        
    def export(self):
        if self.instrument:
          fullname=self.instrument.FullName
        else:
          fullname=''
        return {
          'symbol': self.symbol,
          'fullname': fullname,
          'bid': self.bid,
          'bidsize': self.bidsize,
          'ask': self.ask,
          'asksize': self.asksize,
          'last': self.last,
          'size': self.size,
          'volume': self.volume
        }
    
    def __str__(self):
        items=[self.ID, self.symbol]
        if self.instrument:
            items.extend([self.instrument.FullName, self.Bid, self.Ask, self.Trade])
        return '<CQG_Symbol:%s>' % repr(items)

    def __repr__(self):
        return self.__str__()
    
    def add_client(self, client):
        self.output('CQG_Symbol %s %s adding client %s' % (self, self.symbol, client))
        self.clients.add(client)
      
    def del_client(self, client):
        self.output('CQG_Symbol %s %s deleting client %s' % (self, self.symbol, client))
        self.clients.discard(client)
        if not self.clients:
            instr=self.cel.Instruments(self.ID)
            if instr:
              self.cel.RemoveInstrument(instr)
    
    def update_quote(self):
        quote = 'quote.%s:%s %d %s %d' % (self.symbol, self.bid, self.bidsize, self.ask, self.asksize)
        if quote != self.last_quote:
            self.last_quote = quote
            self.cel.WriteAllClients(quote)
          
    def update_trade(self):
        if self.last_volume != self.volume:
            self.last_volume = self.volume
            self.cel.WriteAllClients('trade.%s:%s %d %d' % (self.symbol, self.last, self.size, self.volume))

class CQG_Order():
    def __init__(self, symbol):
        self.symbol = symbol
        
    def __str__(self):
        return 'CQG_Order<%s>' % self.symbol
    
    def __repr__(self):
        return str(self)
    
class CQG_Callback():
    def __init__(self, cel, id, label, callable):
        """type is stored and used to index dict of return results on callback"""
        self.cel=cel
        self.id=id
        self.label=label
        self.expire=int(mx.DateTime.now())+QUERY_TIMEOUT_SECONDS
        self.callable=callable
        self.done=False
        
    def complete(self, results):
        """complete callback by calling callable function with value of results[self.type]"""
        if not self.done:
            if self.callable.__name__=='write':
                results='%s.%s: %s\n' % (self.cel.channel, self.label, json.dumps(results))
            self.callable(results)
            self.done=True
            
    def check_expire(self):
        if not self.done:
            if int(mx.DateTime.now()) > self.expire:
                self.cel.WriteAllClients('error: callback expired: %s' % (repr((self.id, self.label))))
                if self.callable.__name__=='write':
                    self.callable('%s.error: %s callback expired\n' % (self.cel.channel, self.label))
                else:
                    self.callable(None)
                self.done=True
    
class CQG_Catcher():
    def __init__(self):
        self.label = 'CQG Gateway'
        self.username = environ['cqg-xmlrpc-username']
        self.password = environ['cqg-xmlrpc-password']
        self.xmlrpc_port = int(environ['cqg-xmlrpc-port'])
        self.tcp_port = int(environ['cqg-tcp-port'])
        self.channel = 'cqg'
        self.clients=set([])
        self.bardata_callbacks=[]
        self.addsymbol_callbacks=[]
        self.orders_callbacks=[]
        self.placeorder_callbacks=[]
        self.order_queries=set([])
        self.symbols={}
        self.symbols_by_id={}
        self.orders={}
        self.accounts=[]
        self.current_account=''
        self.data_connection_status='Initializing'
        self.gateway_connection_status='Initializing'
        self.LastError='None'
        self.disconnect_counter=0
        repeater = LoopingCall(self.CheckPendingResults)
        repeater.start(1)
        self.order_queue = Queue.Queue()
        self.order_sender = LoopingCall(self.send_next_order)
        self.order_sender.start(1.0/ORDERS_PER_SECOND)

    def send_next_order(self):
        try:
            if not self.order_queue.empty():
                parms = self.order_queue.get(False)
                print 'send_next_order deque(%s) qsize=%d' % (repr(parms),  self.order_queue.qsize())
                symbol, otype, _stop_price, _limit_price, quantity, callback = parms
                self.process_order(symbol, otype, _stop_price, _limit_price, quantity, callback)
        except Exception, ex:
            self.WriteAllClients('exception: %s' % repr(traceback.format_exc()))

    def symbol_enable(self, symbol, client, callback):
        cb = CQG_Callback(self, symbol, 'add_symbols', callback)
        if not symbol in self.symbols.keys():
            self.addsymbol_callbacks.append(cb)
            self.symbols[symbol]=CQG_Symbol(self, symbol, client)
        else:
            self.symbols[symbol].add_client(client)
            cb.complete(True)
    
    def symbol_disable(self, symbol, client):
        if symbol in self.symbols.keys():
            ts = self.symbols[symbol]
            ts.del_client(client)
            if not ts.clients:
                del(self.symbols_by_id[ts.ID])
                del(self.symbols[symbol])
        return True

    def get_positions(self):
        ret={}
        for account in [Dispatch(a) for a in self.Accounts]:
            pos={}
            ret[account.GWAccountName]=pos
            for position in [Dispatch(p) for p in account.Positions]:
                pos[position.InstrumentName] = [position.Quantity, position.AveragePrice]
        return ret        

    def request_positions(self, callback):
        CQG_Callback(self, 0, 'position', callback).complete(self.get_positions())
                    
    def get_orders(self):
        orders={}
        for account in [Dispatch(a) for a in self.Accounts]:
            all_orders = [Dispatch(o) for o in account.Orders]
            all_orders.extend([Dispatch(o) for o in account.InternalOrders])
            for order in all_orders:
                o=self.parse_order(order)
                orders[o['GUID']]=o
        return orders    

    def get_fills(self):
        fills={}
        for account in [Dispatch(a) for a in self.Accounts]:
            orders = [Dispatch(o) for o in account.Orders]
            orders.extend([Dispatch(o) for o in account.InternalOrders])
            for order in orders:
                fa=[]
                for fill in [Dispatch(f) for f in order.Fills]:
                    fa.append(self.parse_fill(fill))
                if fa:
                    fills[order.GUID]=fa
        return fills

    def request_orders(self, callback):
        self.orders_callbacks.append(CQG_Callback(self, 0, 'orders', callback))
        self.order_query()
        
    def order_query(self):
        for Iaccount in self.Accounts:
            account = Dispatch(Iaccount)
            query = self.QueryOrders(account, cqg_instrument=None)
            if query.Status==constants.rsInProgress:
                self.output('activating order query %s' % account.GWAccountName)
                self.order_queries.add(account.GWAccountName)
            else:
                self.WriteAllClients('error: QueryOrders failed')
    
    def request_executions(self, callback):
        self.orders_callbacks.append(CQG_Callback(self, 0, 'executions', callback))
        self.order_query()
    
    def market_order(self, symbol, quantity, callback):
        return self.send_order(symbol, constants.otMarket, 0, 0, quantity, callback)

    def limit_order(self, symbol, limit_price, quantity, callback):
        return self.send_order(symbol, constants.otLimit, 0, limit_price, quantity, callback)

    def stop_order(self, symbol, stop_price, quantity, callback):
        return self.send_order(symbol, constants.otStop, stop_price, 0, quantity, callback)
    
    def stoplimit_order(self, symbol, stop_price, limit_price, quantity, callback):
        return self.send_order(symbol, constants.otStopLimit, stop_price, limit_price, quantity, callback)
    
    def set_account(self, account_name, callback):
        self.current_account=None
        for account in [Dispatch(a) for a in self.Accounts]:
            if account.GWAccountName == account_name:
                self.output('setting current_account to %s' % account_name)
                self.current_account = account
        if not self.current_account:
            msg = 'account %s not found' % account_name
            self.WriteAllClients('error: set_account(): %s' % msg)
            ret=False
        else:
            msg = 'current account set to %s' % account_name
            ret=True
        self.WriteAllClients('current-account: %s' % account_name)
        if callback:
            CQG_Callback(self, 0, 'current-account', callback).complete(ret)
    
    def send_order(self, symbol, otype, _stop_price, _limit_price, quantity, callback):
        parms = (symbol, otype, _stop_price, _limit_price, quantity, callback)
        print 'send_oorder enqueing %s; qsize=%d' % (repr(parms), self.order_queue.qsize())
        self.order_queue.put(parms, False)

    def process_order(self, symbol, otype, _stop_price, _limit_price, quantity, callback):
        print 'process_order(%s)' % repr((symbol, otype, _stop_price, _limit_price, quantity, callback))
        cb=CQG_Callback(self, 0, 'create_order', callback)
        account = self.current_account;
        if not symbol in self.symbols.keys():
            msg = 'send_order cannot find instrument for symbol %s' % symbol
            self.WriteAllClients('error: %s' % msg)
            cb.complete(None)
        else:
            instr = self.symbols[symbol].instrument            
            order = self.CreateOrder(
                otype,
                instr,
                account,
                quantity,
                limit_price=_limit_price,
                stop_price=_stop_price)
            order.Place()
            self.WriteAllClients('order: order %s placed' % order.GUID)
            cb.id=order.GUID
            self.placeorder_callbacks.append(cb)
    
    def cancel_order(self, id, callback):
        msg = 'cancel_order failed, order %s not found' % id
        ret=None
        for order in [Dispatch(o) for o in self.Orders]:
            if order.GUID == id:
                o=self.parse_order(order)
                if o['Status']=='Canceled':
                    msg = 'cancel_order failed, order %s is already canceled' % id
                    ret=None
                else:
                    order.Cancel()
                    msg = 'canceling order %s' % id
                    ret=True
        self.output(msg)
        if callback:
            CQG_Callback(self, 0, 'cancel-order', callback).complete(ret)
        
    def request_global_cancel(self):
        self.CancelAllOrders(cqg_account=None, cqg_instrument=None)

    def WriteAllClients(self, msg):  
        if msg.startswith('quote.') or msg.startswith('trade.'):
            pass
        else:
            self.output('WriteAllClients: %s.%s' % (self.channel, msg))
        msg=str('%s.%s\n' % (self.channel, msg))
        for c in self.clients:
            c.transport.write(msg)
            
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
                
    def OnQueryProgress(self, Iquery, Ierror):
        if Ierror:
            error = Dispatch(Ierror)
            if self.IsValid(error):
                self.output('error: OrdersQuery: %s' % (repr((error.Code, error.Description))))
        if Iquery:
            query = Dispatch(Iquery)
            account = Dispatch(query.Account)
            
            Dispatch(query.LastChunk).AddToLiveOrders()
            
            for order in [Dispatch(o) for o in query.LastChunk]:
                self.orders[order.GUID]=self.parse_order(order)
                
            if query.Status == constants.rsInProgress:
                self.output('order query in progress')
            else:
                if query.Status == constants.rsSuccess:
                    self.output('order query success')
                elif query.Status == constants.rsCanceled:
                    self.output('order query canceled')
                elif query.Status == constants.rsFailed:
                    self.output('order query failed')
                    
                self.output('completing order query %s' % account.GWAccountName)
                self.order_queries.discard(account.GWAccountName)
            
                if not self.order_queries:
                    for cb in self.orders_callbacks:
                        if cb.label=='orders':
                            cb.complete(self.get_orders())
                        elif cb.label=='executions':
                            cb.complete(self.get_fills())
                        else:
                            self.output('error: unknown order query callback type %s' % cb.label)
                    self.orders_callbacks=[]
            
    def parse_order(self, order):
        oeventmap = [
            'Undefined', 'InQueue', 'CancelSent', 'ModifySent', 'QueueTimeout', 'CancelQueueTimeout',
            'ModifyQueueTimeout', 'InClient', 'InTransit', 'RejectGW', 'AckPlace', 'InTransTmout',
            'RejectFCM', 'Expired', 'InCan', 'InMod', 'InModTmout', 'InCanTmout', 'Modified', 'Canceled',
            'Fill', 'RejMod', 'RejCan', 'Park', 'LinkChg', 'FillMod', 'Disconnected', 'FillCan',
            'FillBust', 'ActiveAt', 'SyntheticActivated', 'Removed', 'RejLinkChg', 'SyntheticFailed',
            'SyntheticOverFill', 'SyntheticHang', 'InfoChanged' ]
        fieldmap={
            constants.opState: [
                'NotSent', 'InQueue', 'QueueTimeout', 'ModifySent' 'CancelSent', 'ActivateSent',
                'InClient', 'AtGW', 'Removed', 'StrategyPending'
            ],
            constants.opGWStatus: [
                'NotSent',
                'InClient',
                'InTransit',
                'RejectGW',
                'InOrderBook',
                'InTransitTimeout',
                'Rejected',
                'Expired',
                'InCancel',
                'InModify',
                'Canceled',
                'Filled',
                'Parked',
                'Disconnected',
                'Contingent',
                'Busted',
                'ActiveAt',
                ],
            constants.opDurationType: [
                'Undefined',
                'Day',
                'GoodTillDate',
                'GoodTillCanceled',
                'FOK',
                'FAK',
                'ATO',
                'ATC',
                'GoodTillTime'
                ],
            constants.opLastEvent: [
                'Undefined',
                'InQueue',
                'CancelSent',
                'ModifySent',
                'QueueTimeout',
                'CancelQueueTimeout',
                'ModifyQueueTimeout',
                'InClient',
                'InTransit',
                'RejectGW,'
                'AckPlace',
                'InTransTimeout',
                'RejectFCM',
                'Expired',
                'InCan',
                'InMod'
                'InModTimeout'
                'InCanTimeout',
                'AckMod',
                'AckCan',
                'Fill',
                'RejMod',
                'RejCan',
                'Park',
                'LinkChg',
                'FillMod',
                'Disconnected',
                'FillCan',
                'FillBust',
                'ActiveAt',
                'SyntheticActivated',
                'Removed',
                'RejLinkChg',
                'SyntheticFailed',
                'SyntheticOverFill',
                'SyntheticHang',
                'InfoChanged'
            ],
            constants.opSide: [
                'Undefined',
                'Buy',
                'Sell'
            ],
            constants.opOrderType: [
                'Undefined',
                'MKT',
                'LMT',
                'STP',
                'STP LMT'
            ]
        }
        timefields = [
            constants.opPlaceTime,
            constants.opEventTimestamp,
            constants.opEventServerTimestamp,
            constants.opCanceledTime,
            constants.opGTDTime,
            constants.opLastFillTime,
            constants.opTimeActiveAt
        ]
        properties = Dispatch(order.Properties)
        self.output('parse_order(%s) (%d properties)' % (repr(order), properties.Count))
        ret = {}
        counter=0
        for prop in [Dispatch(p) for p in properties]:
            counter+=1
            #self.output('  prop %d type=%d' % (counter, prop.Type))
            # skip property types that cause enablement exceptions
            if not prop.Type in [constants.opTradingExpression, constants.opIsCareOrder, constants.opCareOrderIDs]:
                if prop.Type in fieldmap.keys():
                    if prop.Value:
                        ret[prop.Name] = fieldmap[prop.Type][prop.Value]
                elif prop.Type in timefields:
                    if prop.Value:
                        ret[prop.Name] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(prop.Value)))
                else:
                    ret[prop.Name] = prop.Value

        txnstr=''
        transactions = Dispatch(order.Transactions)
        for trxn in [Dispatch(t) for t in transactions]:
            if trxn.Status < len(oeventmap):
               sidx = trxn.Status
            else:
               sidx = 0
            txnstr += '%s-%s-%s' % (trxn.Id, time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(trxn.Timestamp))), oeventmap[sidx])
            if trxn.RejectReason:
                txnstr += '-%s' % trxn.RejectReason

            txnstr += '\n'
            ret['Transactions']=txnstr

        #print 'parse_order():'
        #for k,v in ret.iteritems():
        #  print '%s=%s' % (k,repr(v))

        return ret
    
    def parse_fill(self, fill):
        fill_status=[
            'Normal',
            'Canceled',
            'Modified',
            'Busted'
        ]
        ret = {}
        ret['Id']=fill.Id
        ret['Status']=fill_status[fill.Status]
        ret['ServerTimestamp']=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(fill.ServerTimestamp)))
        ret['Timestamp']=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(fill.Timestamp)))
        ret['LegCount']=fill.LegCount
        ret['trades']=[]
        for trade in [Dispatch(t) for t in fill.GWTrades]:
            t={}
            t['Aggressive']=trade.Aggressive
            t['Currency']=trade.Currency
            t['DisplayPrice']=trade.DisplayPrice
            t['ExchangeTradeDate']=time.strftime('%Y-%m-%d', time.localtime(int(trade.ExchangeTradeDate)))
            t['Fill-Id']=Dispatch(trade.Fill).Id
            t['Id']=trade.Id
            t['InstrumentName']=trade.InstrumentName
            t['Leg']=trade.Leg
            t['Price']=trade.Price
            t['Quantity']=trade.Quantity
            t['Side']=trade.Side
            t['StatementDate']=time.strftime('%Y-%m-%d', time.localtime(int(trade.StatementDate)))
            ret['trades'].append(t)
        return ret
            
    def OnLineTimeChanged(self, newLineTime):
        #self.output('LineTimeChanged: %s' % str(newLineTime))
        self.WriteAllClients('cqg-time: %s' % str(newLineTime))

    def CheckPendingResults(self):
        # check each callback list for timeouts
        if self.data_connection_status == 'Up':
            self.disconnect_counter = 0
        else:
            self.disconnect_counter += SHUTDOWN_IF_NO_DATA_CONNECTION
            if self.disconnect_counter > DISCONNECT_TIMEOUT:
                self.output('Disconnect timeout reached; requesting shutdown')
                reactor.callLater(1, reactor.stop)

        for cblist in [self.bardata_callbacks + self.addsymbol_callbacks + self.orders_callbacks + self.placeorder_callbacks]:
            dlist=[]
            for cb in cblist:
                cb.check_expire()
                if cb.done:
                    dlist.append(cb)
            # delete any callbacks that are done
            for cb in dlist:  
                cblist.remove(cb)

    def OnCELStarted(self):
        self.data_connection_status='Started'
        self.gateway_connection_status='Started'
        self.SendClientStatus()
        #self.output('CELStarted')

    def OnDataError(self, obj, errorDescription):
        self.output('OnDataError: %s %s' % (repr(obj), repr(errorDescription)))
        self.WriteAllClients('data-error: %s' % errorDescription)
        self.LastError=errorDescription

    def OnDataConnectionStatusChanged(self, newStatus):
        if newStatus==constants.csConnectionDelayed:
            status = 'Delayed'
        elif newStatus==constants.csConnectionDown:
            status = 'Down'
        elif newStatus==constants.csConnectionUp:
            status = 'Up'
        else:
            status = 'Unknown'
        self.data_connection_status=status
        self.SendClientStatus()

    def OnGWConnectionStatusChanged(self, newStatus):
        if newStatus==constants.csConnectionDelayed:
            status = 'Delayed'
        elif newStatus==constants.csConnectionDown:
            status = 'Down'
        elif newStatus==constants.csConnectionNotLoggedOn:
            status = 'LoggedOff'
        elif newStatus==constants.csConnectionTrouble:
            status = 'Trouble'
        elif newStatus==constants.csConnectionUp:
            status = 'Up'
        else:
            status = 'Unknown'
        self.gateway_connection_status=status
        self.SendClientStatus()

        if status == 'Up':
            self.AccountSubscriptionLevel = constants.aslAccountUpdatesAndOrders

    def SendClientStatus(self):
        msg = 'connection-status-changed: %s' % self.query_connection_status()
        self.output(msg)
        self.WriteAllClients('%s' % msg)

    def OnAccountChanged(self, changeType, account, position):
        if changeType==constants.actAccountChanged:
            change = 'Account Changed: %s' % repr(account)
        elif changeType==constants.actAccountsReloaded:
            change = 'Accounts Reloaded'
            self.accounts=[]
            for account in [Dispatch(a) for a in self.Accounts]:
                self.accounts.append(account.GWAccountName)
                if not self.current_account:
                    self.set_account(account.GWAccountName, None)
            self.order_query()
        elif changeType==constants.actPositionAdded:
            change = 'Position Added: %s %s' % (repr(account), repr(position))
        elif changeType==constants.actPositionChanged:
            change = 'Position Changed: %s %s' % (repr(account), repr(position))
        elif changeType==constants.actPositionsReloaded:
            account = Dispatch(account)
            change = 'Positions Reloaded: %s' % repr(account)
        else:
            change = 'unknown'
        self.output(change)
        if 'Position' in change:
            self.WriteAllClients('position: %s' % json.dumps(self.get_positions()))

    def OnInstrumentSubscribed(self, symbol, instrument):
        oinstrument=Dispatch(instrument)
        self.output('InstrumentSubscribed: %s %s' % (repr(symbol), repr(oinstrument)))
        oinstrument.DataSubscriptionLevel = constants.dsQuotesAndBBA
        self.symbols[symbol].set_instrument(oinstrument)
        self.symbols_by_id[oinstrument.InstrumentID]=self.symbols[symbol]
        cbd=[]
        for cb in self.addsymbol_callbacks:
            if cb.id == symbol:
                cb.complete(True)
                cbd.append(cb)
        for cb in cbd:
            self.addsymbol_callbacks.remove(cb)            

    def OnIncorrectSymbol(self, symbol):
        self.output('IncorrectSymbol: %s' % (repr(symbol)))
        del(self.symbols[symbol])
        cbd=[]
        for cb in self.addsymbol_callbacks:
            if cb.id == symbol:
                cb.complete(False)
                cbd.append(cb)
        for cb in cbd:
            self.addsymbol_callbacks.remove(cb)            
            
    def OnInstrumentChanged(self, instrument, quotes, properties):
        oinstrument=Dispatch(instrument)
        #oquotes=Dispatch(quotes)
        #oproperties=Dispatch(properties)
        #self.output('InstrumentChanged: %s' % repr((oinstrument.FullName, oinstrument.TodayCTotalVolume, oinstrument.Trade, repr(oquotes), repr(oproperties))))
        self.symbols_by_id[oinstrument.InstrumentID].update(oinstrument)

    def OnTimeSeriesChanged(self, timeSeries, timeSeriesRecord, recordIndex, changeType):
        self.output('TimeSeriesChanged: %s, %s, %s, %s' % (repr(timeSeries), repr(timeSeriesRecord), repr(recordIndex), repr(changeType)))
        ts=Dispatch(timeSeries)
        self.output(repr(ts))
        
    def OnOrderChanged(self, change_type, cqg_order, old_properties, cqg_fill, cqg_error):
        
        change_type_string = ['Added', 'Changed', 'Removed']
        self.output('OrderChanged: %s' % repr((change_type_string[change_type], cqg_order, old_properties, cqg_fill, cqg_error)))
        if cqg_order:
            order=Dispatch(cqg_order)
            guid=order.GUID
            self.orders[guid] = self.parse_order(order)
            cbd=[]
            for cb in self.placeorder_callbacks:
                if cb.id == guid:
                    cb.complete(self.parse_order(order))
                    cbd.append(cb)
            for cb in cbd:
                self.placeorder_callbacks.remove(cb)            
            self.WriteAllClients('order.%s: %s' % (guid, json.dumps(self.orders[guid])))
            
        if cqg_fill:
            fill = Dispatch(cqg_fill)
            self.WriteAllClients('execution.%s: %s' % (guid, json.dumps(self.parse_fill(fill))))
            
        if cqg_error:
            cqgerr = Dispatch(cqg_error)
            self.WriteAllClients('cqg_error: %s' % json.dumps({'code': cqgerr.Code, 'description': repr(cqgerr.Description)}))
            
    def query_connection_status(self):
        return '%s/%s' % (self.data_connection_status, self.gateway_connection_status)
            
    def query_bars(self, bar_symbol, bar_period, bar_start, bar_end, callback):
        self.output('client: query_bars%s' % repr((bar_symbol, bar_period, bar_start, bar_end)))
        cb = CQG_Callback(self, 0, 'bardata', callback)
        if type(bar_start)!=types.IntType:
            mxd = mx.DateTime.ISO.ParseDateTime(bar_start)
            bar_start=datetime.datetime(mxd.year, mxd.month, mxd.day, mxd.hour, mxd.minute, int(mxd.second))
        if type(bar_end)!=types.IntType:
            mxd = mx.DateTime.ISO.ParseDateTime(bar_end)
            bar_end=datetime.datetime(mxd.year, mxd.month, mxd.day, mxd.hour, mxd.minute, int(mxd.second))
        try:
        #if 1==1:
            req = self.CreateTimedBarsRequest()
            req.Symbol=bar_symbol
            req.RangeStart=bar_start
            req.RangeEnd=bar_end
            req.IncludeEnd=True
            req.IntradayPeriod = bar_period
            #req.SessionFlags = constants.sfDailyFromIntraday
            req.SessionsFilter=31  # All Sessions
            ret = Dispatch(self.RequestTimedBars(req))
            self.output('bardata request id=%s' % ret.Id)
            cb.id = ret.Id
            self.bardata_callbacks.append(cb)
        except:
        #if 1==2:
            self.WriteAllClients('error: QueryBars(%s) failed!' % repr((bar_symbol, bar_period, bar_start, bar_end)))
            cb.complete(None)
            
    def gateway_logon(self, username, password):
        self.output('GWLogon requested; username=%s' % username)
        self.GWLogon(username, password)
        return True
        
    def gateway_logoff(self):
        self.output('GWLogoff requested')
        self.GWLogoff()
        return True

    def OnTimedBarsResolved(self, cqgbars, cqgerr):
        self.output('TimedBarsResolved Event: %s,%s' % (repr(cqgbars), repr(cqgerr)))        
        bars=[]
        errormessage='Unknown'
        if cqgerr:
            err=Dispatch(cqgerr)
            errormessage = err.Description
            self.output('CQG Error: %s' % errormessage)  
            status='Error'
            bars.append('Error: %s %s' % (errormessage, repr(err)))

        ts=Dispatch(cqgbars)
        self.output('ID: %s' % ts.Id)
        if ts.Status==constants.rsInProgress:
            status='InProgress'
        elif ts.Status==constants.rsSuccess:
            status='Success'
        elif ts.Status==constants.rsFailed:
            status='Failed'
        elif ts.Status==constants.rsCanceled:
            status='Canceled'
        else:
            self.output('unknown status = %s' % repr(ts.Status))
    
        bars.append('Status: %s' % status)
        self.output('Status: %s' % status)
        
        if status=='Success':
            bars.append('Count: %d' % ts.Count)
            bars.append('Start: %s' % str(ts.StartTimestamp))
            bars.append('End: %s' % str(ts.EndTimestamp))
            for i in range(0, ts.Count):
                cqgbar = ts.Item(i)
                bar=Dispatch(cqgbar)
                ba=[]
                ba.append(bar.Timestamp)
                ba.append(bar.Open)
                ba.append(bar.High)
                ba.append(bar.Low)
                ba.append(bar.Close)
                ba.append(bar.ActualVolume)
                bars.append(ba)

            for bar in bars:
                if type(bar)==types.ListType:
                    dt=mx.DateTime.DateTimeFromCOMDate(bar[0])
                    # fix times ending in 59.999999 seconds to round to the next minute
                    if round(dt.second)==60:
                        dt=mx.DateTime.DateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute, 0)
                        dtd=mx.DateTime.TimeDelta(0,1,0)
                        dt+=dtd
                    dts=dt.strftime('%Y-%m-%d %H:%M:%S')
                    #print 'time: %s %s %s %s' % (repr(bar[0]), repr(dt), repr(dts), repr(round(dt.second)))
                    bar[0]=dts

        self.output(repr(bars))

        found=False        
        for cb in self.bardata_callbacks:
            if cb.id==ts.Id:
                cb.complete(bars)
                found=True
        
        if not found:
            self.output('ID not found in pending bardata_callbacks id=%s, callbacks=%s' % (repr(ts.Id), repr([cb.Id for cb in self.bardata_callbacks])))

    def output(self, msg):
        sys.stderr.write(msg+'\n')
        sys.stderr.flush()
        

class CQG():
    def __init__(self):
        self.cel=win32com.client.DispatchWithEvents('CQG.CQGCEL.4', CQG_Catcher)
        self.cel.APIConfiguration.CollectionsThrowException = False
        self.cel.APIConfiguration.ReadyStatusCheck=constants.rscOff
        self.cel.APIConfiguration.CollectionsThrowException = False
        self.cel.APIConfiguration.DefPositionSubscriptionLevel = constants.pslSnapshotAndUpdates
        self.cel.APIConfiguration.NewInstrumentChangeMode = True
        self.cel.APIConfiguration.UseOrderSide = False 
        self.cel.APIConfiguration.PriceMode = constants.pmTradesOnly
        self.cel.APIConfiguration.TimeZoneCode=constants.tzCentral
        self.cel.Startup()


if __name__=='__main__':
    log.startLogging(sys.stdout)
    cqg=CQG()
    reactor.listenTCP(cqg.cel.tcp_port, serverFactory(cqg.cel))
    rbs=xmlserver(cqg.cel)
    xmlrpc.addIntrospection(rbs)
    reactor.listenTCP(cqg.cel.xmlrpc_port, server.Site(rbs))
    reactor.run()
    

