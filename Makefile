# pypi deploy Makefile

ORG:=rstms
PROJECT:=$(shell basename `pwd` | tr - _ | tr [A-Z] [a-z])
PROJECT_NAME:=$(shell basename `pwd` | tr [A-Z] [a-z])
ENVDIR=./env

GIT_HEAD=$(shell git rev-parse --abbrev-ref HEAD)
GIT_HASH=$(shell git log --pretty=format:'%h' -n 1)


names:
	$(info PROJECT=${PROJECT})
	$(info PROJECT_NAME=${PROJECT_NAME})
	$(info PIP=${PROJECT_NAME})
	$(info DOCKER=${ORG}/${PROJECT_NAME})
	$(info GIT_HEAD=${GIT_HEAD})
	$(info GIT_HASH=${GIT_HASH})
	@echo DIR=$$(pwd)

PYTHON=python3

# find all python sources (used to determine when to bump build number)
PYTHON_SOURCES:=$(shell find setup.py ${PROJECT} tests -name '*.py' -not -name version.py -not -name revision.py)
OTHER_SOURCES:=Makefile Dockerfile setup.py setup.cfg tox.ini README.md LICENSE .gitignore .style.yapf
SOURCES:=${PYTHON_SOURCES} ${OTHER_SOURCES}

# if VERSION=major or VERSION=minor specified, be sure a version bump will happen
$(if ${VERSION},$(shell touch ${PROJECT}/version.py))

help: 
	@echo "make tools|install|uninstall|test|dist|publish|release|clean"

# install python modules for development and testing
tools: 
	${PYTHON} -m pip install --upgrade setuptools pybump pytest tox twine wheel yapf

#TPARM:=-vvx
#test:
#	@echo Testing...
#	pytest $(TPARM)

install:
	@echo Installing ${PROJECT} locally
	${PYTHON} -m pip install --upgrade --editable .

uninstall: 
	@echo Uninstalling ${PROJECT} locally
	${PYTHON} -m pip uninstall -y ${PROJECT} 

# ensure no uncommitted changes exist and that VERSION, version.h and revision.h are correct
gitclean:
	$(if $(shell [ "${GIT_HEAD}" = $(shell cat VERSION) ] || echo 1), $(error version_branch_mismatch))
	$(if $(shell [ "$$(awk -F\' '/^VERSION=/{print $$2}' <txtrader/version.py)" = "$$(cat VERSION)" ] || echo 1), $(error version.py_mismatch))
	$(if $(shell [ "$$(awk -F\' '/^REVISION=/{print $$2}' <txtrader/revision.py)" = "${GIT_HEAD} ${GIT_HASH}" ] || echo 1), $(error revision.py_mismatch))
	$(if $(shell git status --porcelain), $(error "git status dirty, commit and push first"))


# yapf format all changed python sources
fmt: .fmt  
.fmt: ${PYTHON_SOURCES}
	@$(foreach s,$?,yapf -i -vv ${s};) 
	@touch $@

# bump version in VERSION and in python source if source files have changed since last version bump
# set version from branch name
version: VERSION 
VERSION: ${SOURCES}
	@echo Changed files: $?
	@echo ${GIT_HEAD} >VERSION
	@/bin/echo -e >${PROJECT}/version.py "DATE='$$(date +%Y-%m-%d)'\nTIME='$$(date +%H:%M:%S)'\nVERSION='$$(cat VERSION)'"
	@echo "Version is $$(cat VERSION)"
	@touch $@

revision: REVISION
REVISION: ${SOURCES}
	@echo Changed files: $?
	@/bin/echo -e >REVISION "$$(git rev-parse --abbrev-ref HEAD) $$(git log --pretty=format:'%h' -n 1)"
	@/bin/echo -e >${PROJECT}/revision.py "REVISION='$$(cat REVISION)'"
	@cat ${PROJECT}/revision.py
	@touch $@

# test with tox if sources have changed
.PHONY: tox
tox: .tox
.tox: ${SOURCES} VERSION
	@echo Changed files: $?
	TOX_TESTENV_PASSENV="TXTRADER_HOST TXTRADER_HTTP_PORT TXTRADER_TCP_PORT TXTRADER_USERNAME TXTRADER_PASSWORD TXTRADER_API_ACCOUNT" tox
	@touch $@

# create distributable files if sources have changed
dist: .dist
.dist:	${SOURCES} .tox
	@echo Changed files: $?
	@echo Building ${PROJECT}
	${PYTHON} setup.py sdist bdist_wheel
	@touch $@

# set a git release tag and push it to github
release: gitclean .dist 
	@echo pushing Release ${PROJECT} v`cat VERSION` to github...
	TAG="v`cat VERSION`"; git tag -a $$TAG -m "Release $$TAG"; git push origin $$TAG

LOCAL_VERSION=$(shell cat VERSION)
PYPI_VERSION=$(shell pip search txtrader|awk '/${PROJECT_NAME}/{print substr($$2,2,length($$2)-2)}')

pypi: release
	$(if $(wildcard ~/.pypirc),,$(error publish failed; ~/.pypirc required))
	@if [ "${LOCAL_VERSION}" != "${PYPI_VERSION}" ]; then \
	  echo publishing ${PROJECT} `cat VERSION` to PyPI...;\
	  ${PYTHON} -m twine upload dist/*;\
	else \
	  echo ${PROJECT} ${LOCAL_VERSION} is up-to-date on PyPI;\
	fi

docker: .docker
.docker: pypi
	@echo building docker image
	docker images | awk '/^${ORG}\/${PROJECT_NAME}/{print $$3}' | xargs -r -n 1 docker rmi -f
	docker build dockerhub --tag ${ORG}/${PROJECT_NAME}:$(shell cat VERSION)
	docker build dockerhub --tag ${ORG}/${PROJECT_NAME}:latest
	@touch $@

dockerhub: .dockerhub
.dockerhub: .docker 
	$(if $(wildcard ~/.docker/config.json),,$(error docker-publish failed; ~/.docker/config.json required))
	@echo pushing images to dockerhub
	docker login
	docker push ${ORG}/${PROJECT_NAME}:$(shell cat VERSION)
	docker push ${ORG}/${PROJECT_NAME}:latest

publish: .dockerhub

# remove all temporary files
clean:
	@echo Cleaning up...
	rm -rf build dist .dist ./*.egg-info .pytest_cache .tox
	find . -type d -name __pycache__ | xargs rm -rf
	find . -name '*.pyc' | xargs rm -f


rebuild: fmt version revision
	docker-compose build --no-cache

build: fmt version revision 
	docker-compose build 

# run the service locally
run:
	envdir ${ENVDIR} docker-compose run --rm --service-ports txtrader | tee log

# start the service locally in the background
start:
	envdir ${ENVDIR} docker-compose up --build -d txtrader

# stop the local running service
stop:
	docker-compose down 

# stop and restart the local running service
restart: stop start

# run the regression tests
TPARM?=-svx
test: build
	envdir ${ENVDIR} docker-compose run --rm --entrypoint /bin/bash txtrader -l -c 'pytest ${TPARM} ${TESTS}'

# start a shell in the container with the dev directory bind-mounted
shell:
	envdir ${ENVDIR} docker-compose run --rm --entrypoint /bin/bash -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader -l

debug: build
	envdir ${ENVDIR} docker-compose run --rm --service-ports -v $$(pwd)/txtrader:/home/txtrader/txtrader txtrader /bin/bash -l -c "txtraderd --debug"

# tail the log of any running txtrader container
tail:
	@while true; do docker-compose logs -f txtrader; sleep 3; done
