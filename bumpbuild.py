#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  bumpbuild.py
  ------------

  TxTrader build helper script

  Copyright (c) 2015 Reliance Systems Inc. <mkrueger@rstms.net>
  Licensed under the MIT license.  See LICENSE for details.

"""
import datetime
from subprocess import check_output

filename = 'txtrader/version.py'

ifile=open(filename)
ilines = ifile.readlines()
ifile.close()

bflag=True
dflag=True
tflag=True
cflag=True

olines=[]
for line in ilines:
    if bflag and line.startswith('BUILD'):
        build=int(line.split('=')[1])+1
        olines.append('BUILD=%d\n' % build)
        bflag=False
    elif dflag and line.startswith('DATE'):
        now = datetime.datetime.now()
        olines.append('DATE=\'%s\'\n' % now.strftime('%Y-%m-%d'))
        dflag = False
    elif tflag and line.startswith('TIME'):
        now = datetime.datetime.now()
        olines.append('TIME=\'%s\'\n' % now.strftime('%H:%M:%S'))
        tflag = False
    elif cflag and line.startswith('COMMIT'):
        commit = check_output('git log --decorate=full | head -1', shell=True)
        olines.append('COMMIT=\'%s\'\n' % str(commit).strip())
        cflag = False
    else:
        olines.append(line)

ofile=open(filename,'w')
for line in olines:
    ofile.write(line)
ofile.close()
