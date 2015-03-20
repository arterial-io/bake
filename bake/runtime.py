import optparse
import os
import shlex
import sys
import textwrap
from collections import defaultdict, namedtuple
from datetime import datetime
from operator import attrgetter
from tempfile import mkstemp
from textwrap import dedent
from traceback import format_exc

try:
    raw_input
except NameError:
    raw_input = input

try:
    from ConfigParser import SafeConfigParser
except ImportError:
    from configparser import SafeConfigParser

try:
    from urllib import urlretrieve
except ImportError:
    from urllib.request import urlretrieve

from bake.appdirs import user_config_dir
from bake.color import ansify
from bake.environment import *
from bake.exceptions import *
from bake.path import path
from bake.process import Process
from bake.task import Tasks, Task
from bake.util import *

BAKECONFIG = 'bake.yaml'
BAKEFILES = ('Bakefile', 'bakefile', 'Bakefile.py', 'bakefile.py')
BAKEOPTS = 'BAKEOPTS'

USAGE = 'Usage: %s [options] %s [param=value] ...'
DESCRIPTION = """
...
"""

Option = namedtuple('Option', 'signature name type description')

class OptionParser(optparse.OptionParser):
    Options = (
        Option('-c, --color', 'color', 'flag', 'use color in output'),
        Option('-d, --dryrun', 'dryrun', 'flag', 'run tasks in dry-run mode'),
        Option('-D, --debug', 'debug', 'flag', 'run tasks in debug mode'),
        Option('-e, --env FILE', 'sources', 'list',
            'populate runtime environment from specified file'),
        Option('-f, --find PATTERN', 'pattern', 'list',
            'find and describe tasks matching pattern'),
        Option('-h, --help [TASK]', 'help', 'flag', 'display help [on specified task]'),
        Option('-i, --interactive', 'interactive', 'flag', 'run tasks in interactive mode'),
        Option('    --isolated', 'isolated', 'flag',
            'run isolated (no env variables, no bakefiles)'),
        Option('-l, --logfile FILE', 'logfiles', 'list', 'log messages to specified file'),
        Option('-m, --module MODULE', 'modules', 'list', 'load tasks from specified module'),
        Option('    --nocolor', 'nocolor', 'flag', 'force no color in output'),
        Option('-n, --nosearch', 'nosearch', 'flag',
            'do not search parent directories for bakefiles'),
        Option('-N, --nobakefile', 'nobakefile', 'flag', 'do not load bakefiles'),
        Option('-p, --path PATH', 'path', 'value', 'run tasks under specified path'),
        Option('    --prefix PREFIX', 'prefix', 'value', 'apply specified prefix to task names'),
        Option('-P, --pythonpath PATH', 'pythonpath', 'list', 'add specified path to python path'),
        Option('-q, --quiet', 'quiet', 'flag', 'only log error messages'),
        Option('-s, --set PARAM=VALUE', 'params', 'list',
            'sets the specified parameter in the runtime environment'),
        Option('-t, --timestamps', 'timestamps', 'flag', 'include timestamps in all messages'),
        Option('-T, --timing', 'timing', 'flag', 'calculate and display timing for each task'),
        Option('-v, --verbose', 'verbose', 'flag', 'log all messages'),
        Option('-V, --version', 'version', 'flag', 'display version information')
    )

    def __init__(self):
        optparse.OptionParser.__init__(self, add_help_option=False)

        self.options = {}
        for option in self.Options:
            self.options[option.name] = option
            self.add_option(option)

    def add_option(self, option):
        arguments, params = [], {}
        if ',' in option.signature:
            short, remaining = option.signature.split(', ', 1)
            arguments.append(short.strip())
        else:
            remaining = option.signature.strip()

        if ' ' in remaining:
            remaining = remaining.split(' ')[0].strip()

        arguments.append(remaining)
        if option.type == 'flag':
            params['action'] = 'store_true'
        elif option.type == 'list':
            params['action'] = 'append'

        params['dest'] = option.name
        optparse.OptionParser.add_option(self, *arguments, **params)

        if option.type == 'flag':
            self.set_default(option.name, False)

    def error(self, msg):
        raise RuntimeError(msg)

    def generate_help(self, runtime):
        sections = [USAGE % (runtime.executable, '{task}'), DESCRIPTION.strip()]

        length = 0
        for option in self.Options:
            length = max(length, len(option.signature))
        for name in Tasks.by_name.keys():
            length = max(length, len(name))

        template = '  %%-%ds    %%s' % length
        indent = ' ' * (length + 6)

        options = []
        for option in self.Options:
            options.append(template % (option.signature, option.description))

        sections.append('Options:\n%s' % '\n'.join(options))
        for source, tasks in sorted(Tasks.by_source.items()):
            entries = []
            for name, task in sorted(tasks.items()):
                description = self._format_text(task.description, indent)
                entries.append(template % (name, description))
            sections.append('Tasks from %s:\n%s' % (source, '\n'.join(entries)))

        return '\n\n'.join(sections)

    def generate_task_help(self, runtime, task):
        sections = [USAGE % (runtime.executable, task.name)]
        if task.notes:
            sections.append(self._format_text(task.notes))

        required = []
        optional = []

        length = 0
        for name, parameter in task.configuration.items():
            if parameter.hidden:
                continue

            length = max(length, len(name))
            if parameter.required:
                required.append(parameter)
            else:
                optional.append(parameter)

        template = '  %%-%ds    %%s' % length
        indent = ' ' * (length + 6)

        if required:
            params = self._format_parameters(template, indent, required)
            sections.append('Required parameters:\n' + params)

        if optional:
            params = self._format_parameters(template, indent, optional)
            sections.append('Optional parameters:\n' + params)

        return '\n\n'.join(sections)

    def merge_values(self, original, addition):
        for name, option in self.options.items():
            value = getattr(addition, name, None)
            if value:
                original_value = getattr(original, name, None)
                if option.type == 'list' and original_value is not None:
                    original_value.extend(value)
                else:
                    setattr(original, name, value)

        return original

    def _format_parameters(self, template, indent, parameters):
        lines = []
        for param in sorted(parameters, key=attrgetter('name')):
            lines.append(template % (param.name,
                self._format_text(param.description, indent)))

        return '\n'.join(lines)

    def _format_text(self, text, indent='', width=70):
        if text:
            return textwrap.fill(text, width, initial_indent=indent,
                subsequent_indent=indent).strip()
        else:
            return ''

class Runtime(object):
    """The bake runtime."""

    flags = ('color', 'debug', 'dryrun', 'interactive', 'nocolor', 'quiet', 'strict',
        'timestamps', 'timing', 'verbose')

    def __init__(self, executable='bake', environment=None, stream=sys.stdout,
            modules=None, **params):

        self.completed = []
        self.context = []
        self.environment = Environment(environment)
        self.executable = executable
        self.logfiles = []
        self.modules = []
        self.queue = []
        self.sources = []
        self.stream = stream

        self.color = params.get('color', False)
        self.debug = params.get('debug', False)
        self.dryrun = params.get('dryrun', False)
        self.interactive = params.get('interactive', False)
        self.isolated = params.get('isolated', False)
        self.nocolor = params.get('nocolor', False)
        self.nobakefile = params.get('nobakefile', False)
        self.nosearch = params.get('nosearch', False)
        self.path = params.get('path', None)
        self.prefix = params.get('prefix', None)
        self.quiet = params.get('quiet', False)
        self.strict = params.get('strict', False)
        self.timestamps = params.get('timestamps', False)
        self.timing = params.get('timing', False)
        self.verbose = params.get('verbose', False)

    @property
    def curdir(self):
        return path(os.getcwd())

    @property
    def use_color(self):
        return (self.color and not self.nocolor)

    def chdir(self, path):
        curdir = self.curdir
        if self.verbose:
            self.info('changing directory to %s' % path)

        os.chdir(str(path))
        return curdir

    def check(self, message, default=False):
        token = {True: 'y', False: 'n'}[default]
        if self.context:
            message = '[!b][%s][!] %s' % (' '.join(self.context), message)

        message = '%s [%s]' % (message, token)
        while True:
            response = raw_input(ansify(message, self.color)) or token
            if response[0] == 'y':
                return True
            elif response[0] == 'n':
                return False

    def error(self, message, exception=False, asis=False):
        if not message:
            return
        if exception:
            message = '[!R]%s[!]\n%s' % (message.rstrip(), format_exc())
        self._report_message(message, asis)

    def execute(self, task, environment=None, **params):
        if environment or params:
            environment = self.environment.overlay(environment, **params)

        if isinstance(task, string):
            task = Tasks.get(task)(self)
        
        if task.independent:
            self._reset_path()

        self.context.append(task.name)
        try:
            if task.execute(environment) is False:
                raise TaskFailed()
        finally:
            self.context.pop()

    def info(self, message, asis=False, debug=False):
        if debug and not self.debug:
            return
        if not (message and (self.debug or self.verbose)):
            return

        self._report_message(message, asis)

    def invoke(self, invocation):
        parser = OptionParser()
        try:
            options, arguments = parser.parse_args(invocation)
        except RuntimeError as exception:
            self.error(exception.args[0])
            return False

        if options.isolated:
            self.isolated = True

        if not self.isolated and BAKEOPTS in os.environ:
            base_invocation = shlex.split(os.environ[BAKEOPTS])
            try:
                base_options, _ = parser.parse_args(base_invocation)
            except RuntimeError as exception:
                self.error(exception.args[0] + ' (specified in BAKEOPTS)')
                return False
            else:
                options = parser.merge_values(base_options, options)
                   
        if options.version:
            return self._display_version()

        self._parse_options(options.__dict__, True)
        if options.nobakefile:
            self.nobakefile = True
        if options.nosearch:
            self.nosearch = True
        if options.path:
            self.path = options.path
        if options.prefix:
            self.prefix = options.prefix

        sys.path.insert(0, '.')
        if self.path:
            if self._reset_path() is False:
                return False
        else:
            self.path = os.getcwd()

        if not self.isolated:
            if self._parse_config_file() is False:
                return False
            if not self.nobakefile:
                if self._load_bakefiles(self.nosearch) is False:
                    return False

        if self._parse_options(options.__dict__) is False:
            return False

        if options.help:
            return self._display_help(parser, arguments, options.pattern)

        if options.params:
            for pair in options.params:
                param, value = parse_argument_pair(pair)
                self.environment.set(param, value)

        self.queue = self._parse_arguments(arguments)
        if self.queue is False:
            return False

        try:
            self.run()
        except TaskError as exception:
            self.error(exception.args[0])
            return False

    def linefeed(self, lines=1):
        if self.quiet:
            return
        self._report_message('\n' * lines, True)

    def load(self, target, is_filename=False):
        self.info('attempting to load module: %s' % target, debug=True)

        environment = None
        try:
            source = None
            if is_filename or target[-3:] == '.py':
                source = path(target).relpath()

            Tasks.begin_declaration(source)
            try:
                if source:
                    import_source(target)
                else:
                    import_object(target)
            finally:
                environment = Tasks.end_declaration()
        except Exception:
            if self.interactive:
                if not self.check('failed to load %r; continue?' % target):
                    return False
            else:
                self.error('failed to load %r' % target, True)
                return False

        if not environment:
            return

        options = environment.pop('bake', None)
        if environment:
            self.environment.merge(environment)

        if options:
            return self._parse_options(options)

    def prompt(self, message, default=None):
        if self.context:
            message = '[!b][%s][!] %s' % (' '.join(self.context), message)

        if default is not None:
            message = '%s [%s] ' % (message, default)
        else:
            message = str(message)

        response = raw_input(ansify(message, self.color))
        if response == '':
            return default
        else:
            return response
    
    def report(self, message, asis=False):
        if not message or self.quiet:
            return
        self._report_message(message, asis)

    def retrieve(self, url, filename):
        try:
            urlretrieve(url, filename)
        except Exception:
            raise

    def run(self):
        queue = self.queue
        if not queue:
            return

        tasks = defaultdict(set)
        for task in queue:
            tasks[task.name].add(task)

        graph = {}
        while queue:
            task = queue.pop(0)
            graph[task] = task.dependencies

            if task.requires:
                for requirement in task.requires:
                    if requirement not in tasks:
                        required_task = Tasks.get(requirement)(self, independent=True)
                        tasks[requirement].add(required_task)
                        queue.append(required_task)
                    task.dependencies.update(tasks[requirement])

        self.queue = topological_sort(graph)
        while self.queue:
            task = self.queue.pop(0)
            try:
                self.execute(task, self.environment)
            except TaskFailed:
                return False
            else:
                self.completed.append(task)

    def run_script(self, script):
        fileno, filename = mkstemp('.sh', 'bake')
        os.write(fileno, dedent(script))
        os.close(fileno)

        self.shell(['bash', '-x', filename], merge_output=True)
        os.unlink(filename)

    def shell(self, cmdline, data=None, environ=None, shell=False, timeout=None,
            merge_output=False, passthrough=False):

        report = None
        if self.verbose:
            report, passthrough = self.report, True

        process = Process(cmdline, environ, shell, merge_output, passthrough)
        process.run(data, timeout, report)
        return process

    def spawn(self, cmdline, environment=None):
        if isinstance(cmdline, string):
            cmdline = shlex.split(cmdline)

        if environment:
            environ = dict(os.environ)
            environ.update(environment)
            os.execvpe(cmdline[0], cmdline, environ)
        else:
            os.execvp(cmdline[0], cmdline)

    def warn(self, message, asis=False):
        if not message or self.quiet:
            return
        return self._report_message(message, asis)

    def _display_help(self, parser, arguments, pattern=None):
        if not arguments:
            self.report(parser.generate_help(self))
            return

        task = self._find_task(arguments[0])
        if task and task is not True:
            self.report(parser.generate_task_help(self, task))
            return True
        else:
            return task

    def _display_version(self):
        self.report('bake 2.0')

    def _find_task(self, name):
        try:
            task = Tasks.get(name, self.prefix)
        except MultipleTasksError as exception:
            self.error('multiple tasks')
            return False
        except UnknownTaskError:
            if self.interactive:
                return self.check('cannot find task %r; continue?' % name)
            else:
                self.error('cannot find task %r' % name)
                return False
        else:
            return task

    def _load_bakefiles(self, nosearch=False):
        candidates = []
        path = self.path

        while True:
            for bakefile in BAKEFILES:
                candidate = os.path.join(path, bakefile)
                if os.path.exists(candidate):
                    candidates.insert(0, candidate)

            if path == self.path and nosearch:
                break

            up = os.path.dirname(path)
            if up != path:
                path = up
            else:
                break

        for candidate in candidates:
            if self.load(candidate, True) is False:
                return False

    def _parse_arguments(self, arguments):
        parameters = None
        task = None

        tasks = []
        for argument in arguments:
            if '=' in argument:
                if task is True:
                    continue
                elif task:
                    path, value = parse_argument_pair(argument)
                    parameters[path] = value
                else:
                    self.error('!!!')
                    return False
            else:
                if task:
                    tasks.append(task(self, parameters or None))

                parameters = {}
                task = self._find_task(argument)
                if task is False:
                    return False

        if task:
            tasks.append(task(self, parameters or None))

        return tasks

    def _parse_config_file(self):
        path = os.path.join(user_config_dir('bake'), BAKECONFIG)
        if os.path.exists(path):
            return self._parse_source(path)

    def _parse_options(self, options, partial=False):
        for flag in self.flags:
            flagged = options.get(flag, False)
            if flagged:
                setattr(self, flag, True)

        logfiles = options.get('logfiles', None)
        if logfiles:
            self.logfiles.extend(logfiles)

        if partial:
            return

        pythonpath = options.get('pythonpath')
        if pythonpath:
            for addition in pythonpath:
                if addition not in sys.path:
                    sys.path.insert(1, addition)

        modules = options.get('modules')
        if modules:
            for module in modules:
                if self.load(module) is False:
                    return False

        sources = options.get('sources')
        if sources:
            for source in sources:
                if self._parse_source(source) is False:
                    return False

    def _parse_source(self, path):
        self.info('attempting to parse source: %s' % path, debug=True)
        try:
            options = self.environment.parse(path)
        except RuntimeError as exception:
            if self.interactive:
                return self.check('%s; continue?' % exception.args[0])
            else:
                self.error(exception.args[0])
                return False
        except Exception as exception:
            if self.interactive:
                return self.check('failed to parse %s; continue?' % path)
            else:
                self.error('failed to parse %r' % path, True)
                return False

        if options:
            return self._parse_options(options)

    def _report_message(self, message, asis=False):
        if self.context and not asis:
            message = '[!b][%s][!] %s ' % (' '.join(self.context), message)
        if self.timestamps:
            message = '[!b]%s[!] %s' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), message)
        if message[-1] != '\n':
            message += '\n'

        self.stream.write(ansify(message, self.color))
        self.stream.flush()

    def _reset_path(self):
        path = self.path
        if path == os.getcwd():
            return
        
        try:
            os.chdir(path)
        except OSError as exception:
            if self.interactive:
                return self.check('failed to change path to %r; continue?' % path)
            else:
                self.error('failed to change path to %r' % path)
                return False

def run(**params):
    runtime = Runtime(os.path.basename(sys.argv[0]), **params)
    exitcode = 0

    if runtime.invoke(sys.argv[1:]) is False:
        runtime.error('aborted')
        exitcode = 1

    sys.exit(exitcode)
