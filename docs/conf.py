#!/usr/bin/env python3
# vim: set et sw=4 sts=4 fileencoding=utf-8:
#
# Copyright 2012-2017 Dave Jones <dave@waveform.org.uk>.
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

import sys
import os
import configparser
from pathlib import Path
from datetime import datetime
from setuptools.config import read_configuration

on_rtd = os.environ.get('READTHEDOCS', '').lower() == 'true'
config = configparser.ConfigParser()
config.read([Path(__file__).parent / '..' / 'setup.cfg'])
info = config['metadata']

# -- Project information -----------------------------------------------------

project = info['name']
author = info['author']
now = datetime.now()
copyright = (
    f'2012-{now:%Y} {author}' if now.year > 2012 else f'2012 {author}')
release = info['version']
version = release

# -- General configuration ------------------------------------------------

needs_sphinx = '4.0'
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx.ext.imgmath',
]
if on_rtd:
    tags.add('rtd')

root_doc = 'index'
templates_path = ['_templates']
exclude_patterns = ['_build']
highlight_language = 'console'
pygments_style = 'sphinx'
nitpicky = True

# -- Autodoc configuration ------------------------------------------------

autodoc_member_order = 'groupwise'
autodoc_default_options = {
    'members': True,
}
autodoc_mock_imports = []

# -- Intersphinx configuration --------------------------------------------

intersphinx_mapping = {
    'python': ('https://docs.python.org/3.12', None),
    'rich': ('https://rich.readthedocs.io/en/stable', None),
    'docutils': ('https://tristanlatr.github.io/apidocs/docutils', None),
}

# -- Options for HTML output ----------------------------------------------

html_theme = 'sphinx_rtd_theme'
html_theme_options = {
    'collapse_navigation': False,
    'navigation_depth': 2,
}
html_title = f'{project} {version} Documentation'
html_static_path = ['_static']
manpages_url = 'https://manpages.ubuntu.com/manpages/noble/en/man{section}/{page}.{section}.html'

# Hack to make wide tables work properly in RTD
# See https://github.com/snide/sphinx_rtd_theme/issues/117 for details
def setup(app):
    app.add_css_file('style_override.css')

# -- Options for LaTeX output ---------------------------------------------

latex_engine = 'xelatex'

latex_elements = {
    'papersize': 'a4paper',
    'pointsize': '10pt',
    'preamble': r'\def\thempfootnote{\arabic{mpfootnote}}', # workaround sphinx issue #2530
}

latex_documents = [
    (
        'index',            # source start file
        project + '.tex',   # target filename
        html_title,         # title
        author,             # author
        'manual',           # documentclass
        True,               # documents ref'd from toctree only
    ),
]

latex_show_pagerefs = True
latex_show_urls = 'footnote'

# -- Options for epub output ----------------------------------------------

epub_basename = project
epub_author = author
epub_identifier = f'https://{info["name"]}.readthedocs.io/'
epub_show_urls = 'no'

# -- Options for manual page output ---------------------------------------

man_pages = [
    (
        'tvrip',            # root document
        project,            # manual page name
        f'{project} {version} Documentation', # description
        [info['author']],   # authors
        1,                  # section
    ),
]

man_show_urls = True

# -- Options for linkcheck builder ----------------------------------------

linkcheck_retries = 3
linkcheck_workers = 20
linkcheck_anchors = True
