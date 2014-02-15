#!/usr/bin/env python
# vim: set et sw=4 sts=4:

# Copyright 2012-2014 Dave Hughes <dave@waveform.org.uk>.
#
# This file is part of tvrip.
#
# tvrip is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# tvrip is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# tvrip.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import (
    unicode_literals,
    absolute_import,
    print_function,
    division,
    )
str = type('')

import os
import sys
from setuptools import setup, find_packages
from setuptools.command.test import test as TestCommand

if sys.version_info[0] == 2:
    if not sys.version_info >= (2, 7):
        raise ValueError('This package requires Python 2.7 or newer')
elif sys.version_info[0] == 3:
    if not sys.version_info >= (3, 2):
        raise ValueError('This package requires Python 3.2 or newer')
else:
    raise ValueError('Unrecognized major version of Python')

HERE = os.path.abspath(os.path.dirname(__file__))

# Workaround <http://www.eby-sarna.com/pipermail/peak/2010-May/003357.html>
try:
    import multiprocessing
except ImportError:
    pass

# Workaround <http://bugs.python.org/issue10945>
import codecs
try:
    codecs.lookup('mbcs')
except LookupError:
    ascii = codecs.lookup('ascii')
    func = lambda name, enc=ascii: {True: enc}.get(name=='mbcs')
    codecs.register(func)

# All meta-data is defined as global variables in the package root so that
# other modules can query it easily without having to wade through distutils
# nonsense
import tvrip as app

# Add a py.test based "test" command
class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = [
            '--verbose',
            '--cov', __project__,
            '--cov-report', 'term-missing',
            '--cov-report', 'html',
            '--cov-config', 'coverage.cfg',
            'tests',
            ]
        self.test_suite = True

    def run_tests(self):
        import pytest
        errno = pytest.main(self.test_args)
        sys.exit(errno)


def main():
    import io
    with io.open(os.path.join(HERE, 'README.rst'), 'r') as readme:
        setup(
            name                 = app.__project__,
            version              = app.__version__,
            description          = app.__doc__,
            long_description     = readme.read(),
            classifiers          = app.__classifiers__,
            author               = app.__author__,
            author_email         = app.__author_email__,
            url                  = app.__url__,
            license              = [
                c.rsplit('::', 1)[1].strip()
                for c in app.__classifiers__
                if c.startswith('License ::')
                ][0],
            keywords             = ' '.join(app.__keywords__),
            packages             = find_packages(),
            package_data         = {},
            include_package_data = True,
            platforms            = app.__platforms__,
            install_requires     = app.__requires__,
            extras_require       = app.__extra_requires__,
            zip_safe             = False,
            entry_points         = app.__entry_points__,
            tests_require        = ['pytest-cov', 'pytest', 'mock'],
            cmdclass             = {'test': PyTest},
            )


if __name__ == '__main__':
    main()
