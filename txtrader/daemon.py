import click
import subprocess
import pkg_resources


@click.command('txtraderd', short_help='run the txtrader daemon')
@click.option('--reactor', default='poll', envvar='TXTRADER_DAEMON_REACTOR')
@click.option('--daemon/--nodaemon', default=False)
@click.option('--logfile', default='-', envvar='TXTRADER_DAEMON_LOGFILE')
@click.option('--pidfile', default='', envvar='TXTRADER_DAEMON_PIDFILE')
@click.option('--debug/--nodebug', default=False)
def txtraderd(reactor, daemon, logfile, pidfile, debug):
    tacfile = pkg_resources.resource_filename('txtrader', 'txtrader.tac')
    cmd = ['twistd']
    if not daemon:
        cmd.append('--nodaemon')
    if debug:
        cmd.append('--debug')
    cmd.append(f'--reactor={reactor}')
    cmd.append(f'--logfile={logfile}')
    cmd.append(f'--pidfile={pidfile}')
    cmd.append(f'--python={tacfile}')
    subprocess.run(cmd)
