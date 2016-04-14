#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  tcpclient.py
  -------------

  TxTrader Twisted TCP Client Factory

  Copyright (c) 2016 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""

LINE_BUFFER_SIZE=1048576

from twisted.internet import protocol
from twisted.protocols.basic import LineReceiver

class CLI(LineReceiver):
  delimiter = '\n'
  MAX_LENGTH = LINE_BUFFER_SIZE

  def __init__(self, connect_function, label):
    self.cli_connect = connect_function
    self.label = label

  def __str__(self):
    return 'CLI(%s)' % self.label

  def __repr__(self):
    return str(self)

  def connectionMade(self):
    print("+++ connectionMade: %s" % repr(self))
    if getattr(self, 'factory', None):
      self.factory.resetDelay()
    self.cli_receive = self.cli_connect(self)

  def lineReceived(self, line):
    print("+++ lineReceived(%s): %s" % (self.label, repr(line)))
    if not self.cli_receive(line):
      self.transport.loseConnection()

  def connectionLost(self, reason):
    print("+++ connectionLost: %s reason=%s" % (repr(self), reason))
    self.cli_connect(None)

  def lineLengthExceeded(self, line):
    print("!!! Error: line length exceeded: %s" % repr(line))

class clientFactory(protocol.ReconnectingClientFactory):
  def __init__(self, connect_function, label):
    self.connect_function = connect_function
    self.label = label 

  def buildProtocol(self, addr):
    c = CLI(self.connect_function, self.label)
    c.factory = self
    return c

  def clientConnectionLost(self, connector, reason):
    print("+++ tcp clientConnectionLost")
    self.connect_function(None)
    self.retry(connector)

  def clientConnectionFailed(self, connector, reason):
    print("+++ tcp clientConnectionFailed")
    self.connect_function(None)
    self.retry(connector)
