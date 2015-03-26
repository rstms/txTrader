#!/usr/bin/env python

# Copyright (c) 2015 Reliance Systems, Inc.  

import datetime

filename = 'txtrader/version.py'

ifile=open(filename)
ilines = ifile.readlines()
ifile.close()

bflag=True
dflag=True

olines=[]
for line in ilines:
    if bflag and line.startswith('BUILD'):
        build=int(line.split('=')[1])+1
        olines.append('BUILD=%d\n' % build)
        bflag=False
    elif dflag and line.startswith('DATE'):
        now = datetime.datetime.now()
        olines.append('DATE=\'%4d-%02d-%02d\'\n' % (now.year, now.month, now.day))
        dflag = False
    else:
        olines.append(line)

ofile=open(filename,'w')
for line in olines:
    ofile.write(line)
ofile.close()
