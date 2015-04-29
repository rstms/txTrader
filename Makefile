# txTrader Makefile

THIS_FILE := $(lastword $(MAKEFILE_LIST))

default: 
	@echo "Nothing to do"

clean:
	@echo "Cleaning up..."
	rm -f txtrader/*.pyc
	rm -rf build

rebuild:
	@echo "Building..."
	python bumpbuild.py
	@$(MAKE) -f $(THIS_FILE) install

config:
	@echo "Configuring..."
	getent >/dev/null passwd txtrader && echo "User txtrader exists." || adduser --gecos "" --home / --shell /bin/false --no-create-home --disabled-login txtrader;\
        echo txtrader>etc/txtrader/TXTRADER_DAEMON_USER
	pip install egenix-mx-base

install:
	@echo "Installing..."
	python setup.py install
	cp bin/txtrader /usr/local/bin
	cp -r etc/txtrader /etc/txtrader
	chgrp -R txtrader /etc/txtrader
	mkdir -p /var/svc.d/txtrader
	cp -r service/* /var/svc.d/txtrader
	update-service --add /var/svc.d/txtrader

uninstall:
	@echo "Uninstalling..."
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
