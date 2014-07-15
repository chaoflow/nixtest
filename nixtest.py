#!/usr/bin/env python

from __future__ import print_function

"""nixtest -- test runner for nix

Work in Progress
"""

__author__ = 'Florian Friesdorf <flo@chaoflow.net>'
__version__ = '0.20140726'


import click
import logging
import os
import shutil
import sys
import tempfile

from plumbum import local


# monkey-patch local to support local._.ls()
class LocalCommands(object):
    def __init__(self, local):
        self.__local = local

    def __getattr__(self, name):
        try:
            return self.__local[name]
        except:
            raise AttributeError(name)

def local_getattr(self, name):
    if name != "_":
        raise AttributeError(name)
    return LocalCommands(self)

local.__class__.__getattr__ = local_getattr


def absjoin(*args):
    return os.path.abspath(os.path.join(*args))


def envvars(profile):
    return dict(
        PATH=absjoin(profile, 'bin'),
        LD_LIBRARY_PATH=absjoin(profile, 'lib'),
        NIX_LDFLAGS='-L ' + absjoin(profile, 'lib'),
        NIX_CFLAGS_COMPILE='-I ' + absjoin(profile, 'include'),
        PKG_CONFIG_PATH=absjoin(profile, 'lib/pkgconfig'),
    )


class TestModifier(object):
    def __init__(self, log):
        self.log = log

    def __call__(self, msg="very well."):
        self.msg = msg
        return self

    def _run(self, cmd):
        rv = (retcode, stdout, stderr) = cmd.run(retcode=None, stdin=None)

        if stdout:
            self.log.debug("stdout: %s", stdout)
        if stderr:
            self.log.debug("stderr: %s", stderr)

        return rv


class Fails(TestModifier):
    def __rand__(self, cmd):
        (retcode, stdout, stderr) = self._run(cmd)
        assert retcode != 0, self.msg
        self.log.debug("expected fail: %s.", self.msg)


class Succeeds(TestModifier):
    def __rand__(self, cmd):
        (retcode, stdout, stderr) = self._run(cmd)
        assert retcode == 0, self.msg
        self.log.debug("success: %s.", self.msg)


def maketestglobs(log, **kw):
    return dict(
        absjoin=absjoin,
        envvars=envvars,
        fails=Fails(log),
        succeeds=Succeeds(log),
        log=log,
        **kw
    )


UMASK=os.umask(0)
os.umask(UMASK)
UMASKED_WRITE=(0o222 - (0o222 & UMASK))

def make_umasked_writable(x):
    if os.path.islink(x):
        return
    os.chmod(x, os.stat(x).st_mode | UMASKED_WRITE)
    if os.path.isdir(x):
        for y in (os.path.join(x, y) for y in os.listdir(x)):
            make_umasked_writable(y)


@click.command()
@click.option('--debug', help='Enable debug output', is_flag=True)
@click.option('--ipdb', help='Launch ipdb on exception.', is_flag=True)
@click.option('--testfile', help='Testfile to execute.',
              prompt=True, type=click.Path(exists=True))
@click.option('--testname',
              help="Explicit test name, mostly for logging.")
@click.option('--skel',
              help='Skeleton directory to use as base for test workdir.',
              type=click.Path(exists=True))
@click.option('sources', '--sources',
              help='Sources are copied to test workdir, writable for user.',
              envvar='SOURCES', multiple=True)
@click.option('symlinks', '--symlink',
              help='Symlinks to create in test workdir (name:target)',
              envvar='SYMLINKS', multiple=True)
def run(debug, ipdb, testfile, testname, skel, sources, symlinks):
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    log = logging.getLogger('nixtest')
    log.debug("Called with: %r", locals())

    if not testname:
        testname = os.path.basename(testfile)

    # XXX: hack to work around too long shebang line when run via nix-build
    if os.getcwd().startswith('/tmp/'):
        tempdir = os.getcwd()
    else:
        tempdir = tempfile.mkdtemp(prefix="nix-test-run.")
    workdir = os.path.join(tempdir, 'workdir')

    # Setup working directory for test
    if skel:
        shutil.copytree(skel, workdir)
    else:
        os.mkdir(workdir)
    os.chmod(workdir, 0755)

    # Change to working directory
    with local.cwd(workdir):
        for name, source in map(lambda x: x.split(':'), sources):
            shutil.copytree(source, name)
            make_umasked_writable(name)

        # Create symlinks, among others for "profile"
        for name, target in map(lambda x: x.split(':'), symlinks):
            os.symlink(target, name)

        # Setup profile as test environment using environment
        # variables.
        #
        # `from plumbum.cmd import X` will produce commands local to
        # that environment.
        #
        # probably we should rescue some variables
        local.env.clear()
        with local.env(**envvars("profile")):
            log = log.getChild(testname)
            testglobs = maketestglobs(local=local, log=log)
            if ipdb:
                from ipdb import launch_ipdb_on_exception
                with launch_ipdb_on_exception():
                    log.info("ipdb running tests in: %s" % workdir)
                    execfile(testfile, testglobs)
            else:
                log.info("Running tests in: %s" % workdir)
                execfile(testfile, testglobs)


def main():
    run(auto_envvar_prefix="NIXTEST")
    sys.exit(0)


if __name__ == '__main__':
    main()
