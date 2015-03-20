from datetime import datetime
from textwrap import dedent
from types import FunctionType

from scheme import Field, Format, Structure, Text

from bake.environment import *
from bake.exceptions import *
from bake.util import *

try:
    import repr as reprlib
except ImportError:
    import reprlib

__all__ = ('Task', 'TaskError', 'declare', 'parameter', 'requires', 'task')

COMPLETED = 'completed'
FAILED = 'failed'
PENDING = 'pending'
SKIPPED = 'skipped'

class Tasks(object):
    by_fullname = {}
    by_name = {}
    by_source = {}

    current_source = None
    declared_environment = None

    @classmethod
    def begin_declaration(cls, source=None):
        cls.current_source = source
        cls.declared_environment = {}

    @classmethod
    def declare(cls, declaration, format='yaml'):
        if isinstance(declaration, string):
            declaration = Format.unserialize(declaration, format)

        recursive_merge(cls.declared_environment, declaration)

    @classmethod
    def end_declaration(cls):
        declaration = cls.declared_environment
        cls.current_source, cls.declared_environment = None, None
        return declaration

    @classmethod
    def get(cls, name, prefix=None):
        task = cls.by_fullname.get(name)
        if task:
            return task

        if prefix and not name.startswith(prefix):
            name = prefix + name

        candidate = cls.by_name.get(name)
        if isinstance(candidate, set):
            raise MultipleTasksError(candiate)
        elif candidate:
            return candidate
        else:
            raise UnknownTaskError('no task named %r' % name)

class TaskMeta(type):
    def __new__(metatype, name, bases, namespace):
        task = type.__new__(metatype, name, bases, namespace)
        if not task.supported:
            return task

        parameters = {}
        for base in reversed(bases):
            inherited = getattr(base, 'parameters', None)
            if inherited:
                parameters.update(inherited)

        if task.parameters:
            parameters.update(task.parameters)

        task.parameters = parameters
        if task.name is None:
            return task

        task.configuration = {}
        for name, parameter in parameters.items():
            name = '%s.%s' % (task.name, name)
            task.configuration[name] = parameter.clone(name=name)

        task.fullname = task.__name__
        if task.__module__ != '__main__':
            task.fullname = '%s.%s' % (task.__module__, task.__name__)

        Tasks.by_fullname[task.fullname] = task
        if task.name in Tasks.by_name:
            value = Tasks.by_name[task.name]
            if isinstance(value, set):
                value.add(task)
            else:
                Tasks.by_name[task.name] = set([value, task])
        else:
            Tasks.by_name[task.name] = task

        source = Tasks.current_source
        if source is None:
            source = task.__module__
        
        if source in Tasks.by_source:
            Tasks.by_source[source][task.name] = task
        else:
            Tasks.by_source[source] = {task.name: task}

        docstring = task.__doc__
        if docstring and task.notes is None:
            task.notes = dedent(docstring.strip())

        return task

@with_metaclass(TaskMeta)
class Task(object):
    """``Task`` is the unit of work in bake; it accepts some input, attempts to do some work, and
    reports success or failure.

    Tasks are principally defined by implementing a subclass of :class:`Task` that specifies some
    required class-level variables and overrides one or more key methods. The following class-level
    parameters can be specified.

    """

    supported = True

    configuration = None
    description = None
    implementation = None
    name = None
    notes = None
    parameters = None
    requires = None
    source = None
    supports_dryrun = False
    supports_interactive = False

    def __init__(self, runtime, params=None, path=None, independent=True):
        self.dependencies = set()
        self.environment = None
        self.exception = None
        self.finished = None
        self.independent = independent
        self.params = params
        self.path = path
        self.runtime = runtime
        self.started = None
        self.status = PENDING
        
    def __repr__(self):
        return '%s(name=%r, status=%r)' % (type(self).__name__, self.name, self.status)

    def __getitem__(self, name):
        if not self.environment:
            raise RuntimeError()
        if name[:len(self.name)] != self.name:
            name = '%s.%s' % (self.name, name)
        return self.environment.find(name)

    def __setitem__(self, name, value):
        if not self.environment:
            raise RuntimeError()
        if name[:len(self.name)] != self.name:
            name = '%s.%s' % (self.name, name)
        self.environment.set(name, value)

    @property
    def duration(self):
        return '%.03fs' % (self.finished - self.started).total_seconds()

    def execute(self, environment):
        """Executes this task and reports the result to the runtime."""

        runtime = self.runtime
        try:
            self.environment = self._prepare_environment(runtime, environment)
        except RequiredParameterError as exception:
            runtime.error('task requires parameter %r' % exception.args[0])
            self.status = FAILED
            return False

        if runtime.interactive:
            if not runtime.check('execute task?', True):
                self.status = self.SKIPPED

        if self.status == PENDING and runtime.dryrun and not self.supports_dryrun:
            self.status = COMPLETED

        if self.status == PENDING:
            self._execute_task(runtime)

        duration = ''
        if self.started is not None and runtime.timing:
            duration = ' (%s)' % self.duration

        if self.status == COMPLETED:
            runtime.report('[!G]task completed[!]%s' % duration)
            return True
        elif self.status == SKIPPED:
            runtime.report('[!Y]task skipped[!]')
            return True
        elif runtime.interactive:
            return runtime.check('[!R]task failed[!]%s; continue?' % duration)
        else:
            runtime.report('[!R]task failed[!]%s' % duration)
            return False

    def finalize(self, runtime):
        """Finalizes the runtime environment after the execution of this task, if the task
        completed successfully. The default implementation does nothing."""

        pass

    def prepare(self, runtime):
        """Prepares the runtime environment for the execution of this task. The default
        implementation does nothing."""

        pass

    def run(self, runtime):
        raise NotImplementedError()

    def _execute_task(self, runtime):
        self.started = datetime.now()
        try:
            self.prepare(runtime)
            call_with_supported_params(self.implementation or self.run,
                task=self, runtime=runtime, environment=self.environment)
            self.finalize(runtime)
        except RequiredParameterError as exception:
            runtime.error('task requires parameter %r' % exception.args[0])
            self.status = FAILED
        except TaskError as exception:
            runtime.error(exception.args[0])
            self.status = FAILED
        except Exception as exception:
            runtime.error('task raised uncaught exception', True)
            self.status = FAILED
        else:
            self.status = COMPLETED
        finally:
            self.finished = datetime.now()

    def _prepare_environment(self, runtime, environment):
        if self.params:
            environment = environment.overlay(self.params)

        if not self.configuration:
            return environment

        overlay = Environment()
        for name, parameter in self.configuration.items():
            value = environment.find(name)
            if value is not None:
                overlay.set(name, parameter.process(value, serialized=True))
            elif parameter.default is not None:
                overlay.set(name, parameter.default)
            elif parameter.required:
                raise RequiredParameterError(name)

        return environment.overlay(overlay)

def declare(declaration):
    """Declares an envronment."""

    Tasks.declare(declaration)

def parameter(name, field=None, **params):
    if isinstance(field, string):
        if 'name' not in params:
            params['name'] = name
        field = Field.reconstruct(field, **params)
    elif not field:
        field = Text(name=name, nonnull=True)

    def decorator(function):
        try:
            function.parameters[name] = field
        except AttributeError:
            function.parameters = {name: field}
        return function
    return decorator

def requires(*args):
    def decorator(function):
        try:
            function.requires.update(args)
        except AttributeError:
            function.requires = set(args)
        return function
    return decorator

def task(name=None, description=None, supports_dryrun=False, supports_interactive=False):
    def decorator(function):
        return type(function.__name__, (Task,), {
            '__doc__': function.__doc__ or '',
            'name': name or function.__name__,
            'description': description,
            'implementation': staticmethod(function),
            'supports_dryrun': supports_dryrun,
            'supports_interactive': supports_interactive,
            'parameters': getattr(function, 'parameters', None),
            'requires': getattr(function, 'requires', []),
        })
    return decorator
