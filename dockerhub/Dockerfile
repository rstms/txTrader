FROM python:3.8.3-buster

MAINTAINER mkrueger@rstms.net

RUN pip install txtrader

RUN cp $(find / -type f -name txtrader.tac) txtrader.tac

RUN \
  echo 'America/Chicago' >/etc/timezone \
  && rm /etc/localtime \
  && dpkg-reconfigure -f noninteractive tzdata

ENTRYPOINT ["twistd"]
CMD ["--nodaemon", "--reactor=epoll", "--logfile=-", "--pidfile=", "--python=./txtrader.tac"]
