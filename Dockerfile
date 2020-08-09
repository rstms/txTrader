FROM python:3.8.3-buster

MAINTAINER mkrueger@rstms.net

RUN pip install \
  click \
  hexdump \
  pytest \ 
  pytz \ 
  requests \
  twisted \ 
  txtrader-client \
  txtrader-monitor \ 
  tzlocal \ 
  ujson \
  wait-for-it 

RUN apt-get update && apt-get install -y \
  less \
  vim

RUN \
  echo 'America/Chicago' >/etc/timezone \
  && rm /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata

RUN useradd -m txtrader
#USER txtrader
WORKDIR /home/txtrader
COPY txtrader /home/txtrader/txtrader
COPY setup.py /home/txtrader
COPY pytest.ini /home/txtrader
COPY tests /home/txtrader/tests
RUN mkdir -p /home/txtrader/.local/bin
RUN pip install . --user --no-warn-script-location

COPY entrypoint.sh /home/txtrader
COPY txtrader/txtrader.tac /home/txtrader
ENTRYPOINT ["/bin/sh", "entrypoint.sh"]
