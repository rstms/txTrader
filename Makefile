# txTrader Makefile

default: 
	@echo "Nothing to do"

clean:
	@echo "cleaning up"
	rm -f txtrader/*.pyc
	rm -rf build

build:
	@echo "Nothing to do"

config:
	@echo -n "Enter daemon user:";\
        read _user;\
	getent >/dev/null passwd $$_user && echo 'user $$_user exists' || adduser --gecos '' --home / --shell /bin/false --no-create-home --disabled-login $$_user \
        echo $$_user>etc/txtrader/TXTRADER_DAEMON_USER
	pip install egenix-mx-base


install:
	python bumpbuild.py
	python setup.py install
	cp bin/txtrader /usr/local/bin
	cp -r etc/txtrader /etc/txtrader
	chgrp -R txtrader /etc/txtrader
	mkdir -p /var/svc.d/txtrader
	cp -r service/* /var/svc.d/txtrader
	update-service --add /var/svc.d/txtrader

uninstall:
	svc -d /etc/service/txtrader
	svc -d /etc/service/txtrader/log
	update-service --remove /var/svc.d/txtrader
	rm -rf /var/svc.d/txtrader
	rm -rf /etc/txtrader
	cat files.txt | xargs rm -f
	rm -f /usr/local/bin/txtrader

dist:
	python setup.py sdist

TESTS := $(wildcard txtrader/test-*.py)

test: $(TESTS)
	@echo "Testing..."
	cd txtrader; envdir ../service/env py.test -vvx $(notdir $^)
