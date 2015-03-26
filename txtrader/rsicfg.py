#!/usr/bin/env python

# Copyright (c) 2015 Reliance Systems, Inc.


from os import environ
from ConfigParser import ConfigParser

reliance_config=ConfigParser()

if 'RELIANCE_CONFIG' in environ:
  config_file = environ['RELIANCE_CONFIG']
else:
  config_file='/etc/reliance.cfg'

reliance_config.read(config_file)
 
def get(label, section='reliance'):
  return reliance_config.get(section, label)

def set(value, label, section='reliance'):
  reliance_config.set(section, label, value)
  with open(config_file, 'wb') as cfile:
    reliance_config.write(cfile)

if __name__=='__main__':
  print 'rsicfg'
