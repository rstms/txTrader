#!/bin/sh
exec /usr/local/bin/twistd --nodaemon --reactor=epoll --logfile=- --pidfile= --python=./txtrader.tac
