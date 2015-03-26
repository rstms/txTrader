#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  monitor.py
  ----------

  TxTrader Monitor class - Instantiate in client to receive event notifications.

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""


from twisted.internet import reactor, protocol

class Monitor():
  def __init__(self, host='localhost', port=50090, user=None, password=None, callbacks=None):
    """Initialize Monitor:
      connection parameters: host, port, user, password, 
      callbacks: {'name':function ...}  
        where name is one of ['status', 'error', 'time', 'order', 'execution', 'quote', 'trade']
        and function(data) is the callback that will receive event data
    """
    self.host = host
    self.port = port
    self.user = user
    self.password = password
    self.channel = ''
    self.callback_types = ['status', 'error', 'time', 'order', 'execution', 'quote', 'trade']
    self.flags = 'noquotes notrades'

    if callbacks:
      self.callbacks = callbacks 
    else:
      self.callbacks = {}
      for cb_type in self.callback_types:
        self.set_callback(cb_type, self._cb_print)

  def listen(self, _reactor):
    f = StatusClientFactory(self)
    reactor.connectTCP(self.host, self.port, f)

  def set_callback(self, cb_type, cb_func):
    """Set a callback function for a message type."""
    self.callbacks[cb_type] = cb_func

  def delete_callback(self, cb_type):
    """Delete a callback function for a message type."""
    if cb_type in self.callbacks.keys():
      delete(self.callbacks[cb_type])

  def _callback(self, cb_type, cb_data):
    if cb_type in self.callbacks.keys():
      self.callbacks[cb_type](cb_type, cb_data)

  def _cb_print(self, label, msg):
    print('%s: %s' % (label, repr(msg)))

  def run(self):
    """React to gateway events, returning data via callback functions."""
    self.listen(reactor)
    reactor.run()


class StatusClient(protocol.Protocol):

  def __init__(self):
    self.channel=''
    self.message_types = []
    self.channel_map = {}
    self.last_account = ''

  def connectionMade(self):
    pass
    
  def dataReceived(self, data):
    for line in data.strip().split('\n'):
      self.processLine(line)
 
  def processLine(self, data):
    if data.startswith('.'):
      self.factory.rx._callback('status', data)
      if data.startswith('.connected'):
        self.transport.write('auth %s %s %s\n' % (self.factory.rx.user, self.factory.rx.password, self.factory.rx.flags))
      elif data.startswith('.Authorized'):
        dummy, self.channel = data.split()[:2]
        # setup channel map now that we have the channel name
        self.channel_map = {
            '%s.time: ' % self.channel: 'time',
            '%s.error:' % self.channel: 'error',
            '%s.order.' % self.channel: 'order',
            '%s.open-order.' % self.channel: 'order',
            '%s.execution.' % self.channel: 'execution',
            '%s.quote.' % self.channel: 'quote',
            '%s.trade.' % self.channel: 'trade'}
        self.account_channel = '%s.current-account' % self.channel
    else:
      for cmap in self.channel_map.keys():
        if data.startswith(cmap):
          return self.factory.rx._callback(self.channel_map[cmap], data[len(cmap):])
      # only return current_account message if different from last one
      if data.startswith(self.account_channel):
        if self.last_account == data:
          return
        else:
          self.last_account = data
      self.factory.rx._callback('status', data)
 

  def connectionLost(self, reason):
    pass

class StatusClientFactory(protocol.ClientFactory):
  protocol = StatusClient 
  def __init__(self, receiver):
    self.rx = receiver

  def clientConnectionFailed(self, connector, reason):
    self.rx._callback('error', 'connection failed')
    if reactor.running: 
      reactor.stop()
    
  def clientConnectionLost(self, connector, reason):
    self.rx._callback('error', 'connection lost')
    if reactor.running: 
      reactor.stop()


if __name__ == '__main__':

  _USER = 'change_this_username'
  _PASS = 'change_this_password'
  rx = Monitor(user=_USER, password=_PASS)
  rx.run()
