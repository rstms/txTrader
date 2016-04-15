#txTrader Makefile

THIS_FILE := $(lastword $(MAKEFILE_LIST))

REQUIRED_PACKAGES = daemontools-run ucspi-tcp
REQUIRED_PIP = Twisted egenix-mx-base pudb ./dist/*.tar.gz ~/IbPy/dist/*.tar.gz

TXTRADER_PYTHON = /usr/local/lib/python2.7.11/bin/python
TXTRADER_ENVDIR = /etc/txtrader
TXTRADER_VENV = $(HOME)/txtrader-venv

TXTRADER_MODE = rtx 

TXTRADER_TEST_HOST = 127.0.0.1
TXTRADER_TEST_PORT = 17496
# set account to AUTO for make testconfig to auto-set demo account
TXTRADER_TEST_ACCOUNT = AUTO

default:
	@echo "\nQuick Start:\n\nmake build; sudo make -e TXTRADER_MODE=tws install; sudo make -e TXTRADER_MODE=rtx install\n"

clean:
	@echo "Cleaning up..."
	rm -f txtrader/*.pyc
	rm -rf build
	rm -rf $(TXTRADER_VENV)
	rm -f .make-*

build:  .make-build

.make-build: .make-config setup.py txtrader/*.py
	@echo "Building..."
	python bumpbuild.py
	python setup.py sdist 
	touch .make-build

config: .make-config

.make-config:
	@echo "Configuring..."
	@getent >/dev/null passwd txtrader && echo "User txtrader exists." || adduser --gecos "" --home / --shell /bin/false --no-create-home --disabled-login txtrader
	@echo $(TXTRADER_VENV)>etc/txtrader/TXTRADER_VENV
	@echo txtrader>etc/txtrader/TXTRADER_DAEMON_USER
	@for package in $(REQUIRED_PACKAGES); do \
	  dpkg-query >/dev/null -l $$package && echo "verified package $$package" || break;\
	done;
	mkdir -p /etc/txtrader
	cp -r etc/txtrader/* $(TXTRADER_ENVDIR)
	chown -R txtrader.txtrader $(TXTRADER_ENVDIR)
	chmod 700 $(TXTRADER_ENVDIR)
	chmod 600 $(TXTRADER_ENVDIR)/*
	touch .make-config

testconfig:
	@echo "Configuring test API..."
	$(MAKE) start
	sudo sh -c "echo $(TXTRADER_TEST_HOST)>$(TXTRADER_ENVDIR)/TXTRADER_API_HOST"
	sudo sh -c "echo $(TXTRADER_TEST_PORT)>$(TXTRADER_ENVDIR)/TXTRADER_API_PORT"
	sudo sh -c "echo $(TXTRADER_TEST_ACCOUNT)>$(TXTRADER_ENVDIR)/TXTRADER_API_ACCOUNT"
	@echo -n "Restarting txTrader service..."
	@sudo svc -t /etc/service/txtrader
	@while ! (txtrader 2>/dev/null $(TXTRADER_TEST_MODE) status); do echo -n .; sleep 1; done
	@if [ "$(TXTRADER_TEST_ACCOUNT)" = "AUTO" ]; then\
	  . $(TXTRADER_VENV)/bin/activate;\
          export ACCOUNT="`envdir /etc/txtrader txtrader $(TXTRADER_TEST_MODE) query_accounts | tr -d \"[]\'\n\"`";\
	else\
	  export ACCOUNT="$(TXTRADER_TEST_ACCOUNT)";\
	fi;\
	sudo sh -c "echo $$ACCOUNT>$(TXTRADER_ENVDIR)/TXTRADER_API_ACCOUNT";\
	echo "Set test ACCOUNT=$$ACCOUNT"

.make-venv: .make-build
	rm -rf $(TXTRADER_VENV)
	virtualenv -p $(TXTRADER_PYTHON) $(TXTRADER_VENV)
	. $(TXTRADER_VENV)/bin/activate; \
	for package in $(REQUIRED_PIP); do \
          echo -n "Installing package $$package into virtual env..."; pip install $$package || false;\
        done;
	touch .make-venv

install: .make-venv
	@echo "Installing txtrader.$(TXTRADER_MODE)..."
	cp bin/txtrader /usr/local/bin
	rm -rf /var/svc.d/txtrader.$(TXTRADER_MODE)
	cp -r service/txtrader.$(TXTRADER_MODE) /var/svc.d
	touch /var/svc.d/txtrader.$(TXTRADER_MODE)/down
	update-service --add /var/svc.d/txtrader.$(TXTRADER_MODE)

start:
	@echo "Starting Service..."
	sudo rm -f /etc/service/txtrader.$(TXTRADER_MODE)/down
	sudo svc -u /etc/service/txtrader.$(TXTRADER_MODE)

stop:
	@echo "Stopping Service..."
	sudo touch /etc/service/txtrader.$(TXTRADER_MODE)/down
	sudo svc -d /etc/service/txtrader.$(TXTRADER_MODE)

restart: stop start
	@echo "Restarting Service..."
		
uninstall:
	@echo "Uninstalling..."
	if [ -e /etc/service/txtrader.$(TXTRADER_MODE) ]; then\
	  svc -d /etc/service/txtrader.$(TXTRADER_MODE);\
	  svc -d /etc/service/txtrader.$(TXTRADER_MODE)/log;\
	  update-service --remove /var/svc.d/txtrader.$(TXTRADER_MODE);\
	fi
	rm -rf /var/svc.d/txtrader.$(TXTRADER_MODE)
	rm -rf $(TXTRADER_ENVDIR)
	cat files.txt | xargs rm -f
	rm -f /usr/local/bin/txtrader

TESTS := $(wildcard txtrader/test-*.py)

.PHONY: test 

test: $(TESTS)
	@echo "Testing..."
	cd txtrader; envdir ../etc/txtrader py.test -vvx $(notdir $^)
