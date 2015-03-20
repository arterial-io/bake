import os
import shlex
import subprocess
import sys
from threading import Thread
from time import time

from bake.util import string

class ProcessFailedError(Exception):
    pass

class Process(object):
    """A child process of the current process.

    """

    def __init__(self, cmdline, environ=None, shell=False, merge_output=False,
            passthrough=False):

        if isinstance(cmdline, string) and not shell:
            cmdline = shlex.split(cmdline)

        self.cmdline = cmdline
        self.merge_output = merge_output
        self.passthrough = passthrough
        self.process = None
        self.returncode = None
        self.shell = shell
        self.stderr = None
        self.stdout = None

        self.environ = dict(os.environ)
        if environ:
            self.environ.update(environ)

    def __call__(self, data=None, timeout=None, report=None, cwd=None):
        """Runs this child process."""

        if report:
            report('shell: %s' % ' '.join(self.cmdline))

        def _thread():
            stdout = subprocess.PIPE
            if self.passthrough:
                stdout = sys.stdout

            stderr = subprocess.PIPE
            if self.merge_output:
                stderr = subprocess.STDOUT
            elif self.passthrough:
                stderr = sys.stderr

            self.process = subprocess.Popen(self.cmdline, bufsize=0, env=self.environ,
                shell=self.shell, cwd=cwd, stdin=subprocess.PIPE, stdout=stdout,
                stderr=stderr, universal_newlines=True)

            self.stdout, self.stderr = self.process.communicate(data)

        thread = Thread(target=_thread)
        thread.start()

        thread.join(timeout)
        if thread.isAlive():
            self.process.terminate()
            thread.join()

        self.returncode = self.process.returncode
        return self.returncode

    def run(self, data=None, timeout=None, report=None, cwd=None):
        returncode = self(data, timeout, report, cwd)
        if returncode != 0:
            raise ProcessFailedError(returncode, self)
