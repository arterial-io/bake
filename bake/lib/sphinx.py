from __future__ import absolute_import

from scheme import Boolean, Text

from bake.path import *
from bake.task import *

try:
    import sphinx
except ImportError:
    sphinx = None

class SphinxTask(Task):
    supported = bool(sphinx)
    parameters = {
        'binary': Text(description='path to sphinx binary', default='sphinx-build'),
        'cachedir': FilePath(description='path to cache directory for doctrees'),
        'outdir': FilePath(description='path to output directory for generated docs'),
        'sourcedir': FilePath(description='path to source directory', default=Path('docs')),
        'nocache': Boolean(description='do not use cached environment', default=False),
    }

    def _collate_options(self, options=None):
        sourcedir = self['sourcedir']
        if not sourcedir.exists():
            raise TaskError("source directory '%s' does not exist" % sourcedir)

        if not self['cachedir']:
            self['cachedir'] = sourcedir / '_doctrees'
        if not self['outdir']:
            self['outdir'] = sourcedir / 'html'

        options = options or []
        options += ['-N', '-d %s' % self['cachedir'], str(sourcedir), str(self['outdir'])]
        return options

class BuildHtml(SphinxTask):
    name = 'sphinx.html'
    description = 'build html documentation using sphinx'
    parameters = {
        'view': Boolean(description='view documentation after build', default=False),
    }

    def run(self, runtime):
        options = self._collate_options([self['binary'], '-b html'])
        runtime.shell(' '.join(options))

        if self['view']:
            import webbrowser
            webbrowser.open('file://%s' % str(self['outdir'] / 'index.html'))
