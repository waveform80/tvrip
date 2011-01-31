# vim: set noet sw=4 ts=4:

# External utilities
PYTHON=python
PYFLAGS=
#LYNX=lynx
#LYNXFLAGS=-nonumbers -justify
LYNX=links
LYNXFLAGS=

# Calculate the base names of the distribution, the location of all source,
# documentation and executable script files
NAME:=$(shell $(PYTHON) $(PYFLAGS) setup.py --name)
BASE:=$(shell $(PYTHON) $(PYFLAGS) setup.py --fullname)
PYVER:=$(shell $(PYTHON) $(PYFLAGS) -c "import sys; print 'py%d.%d' % sys.version_info[:2]")
SCRIPTS:=$(shell $(PYTHON) $(PYFLAGS) -c "import setup; setup.get_console_scripts()")
SOURCE:=$(shell \
	$(PYTHON) $(PYFLAGS) setup.py egg_info >/dev/null 2>&1 && \
	cat $(NAME).egg-info/SOURCES.txt)

# Calculate the name of all distribution archives / installers
DIST_EGG=dist/$(BASE)-$(PYVER).egg
DIST_WININST=dist/$(BASE).win32.exe
DIST_RPM=dist/$(BASE)-1.src.rpm
DIST_TAR=dist/$(BASE).tar.gz
DIST_ZIP=dist/$(BASE).zip

# Default target
build:
	$(PYTHON) $(PYFLAGS) setup.py build

install:
	$(PYTHON) $(PYFLAGS) setup.py install

develop: tags
	$(PYTHON) $(PYFLAGS) setup.py develop
	@echo
	@echo "Please run the following to remove any redundant hash entries:"
	@echo hash -d $(SCRIPTS)

undevelop:
	$(PYTHON) $(PYFLAGS) setup.py develop --uninstall
	for s in $(SCRIPTS); do rm -f $(HOME)/bin/$$s; done
	@echo
	@echo "Please run the following to remove any redundant hash entries:"
	@echo hash -d $(SCRIPTS)

test:
	@echo "No tests currently implemented"
	#cd examples && ./runtests.sh

clean:
	$(PYTHON) $(PYFLAGS) setup.py clean
	rm -f $(DOCS) tags
	rm -fr build/ $(NAME).egg-info/

cleanall: clean
	rm -fr dist/

dist: bdist sdist

bdist: $(DIST_WININST) $(DIST_EGG)

sdist: $(DIST_TAR) $(DIST_ZIP)

$(DIST_EGG): $(SOURCE) $(DOCS)
	$(PYTHON) $(PYFLAGS) setup.py bdist_egg

$(DIST_WININST): $(SOURCE) $(DOCS)
	$(PYTHON) $(PYFLAGS) setup.py bdist_wininst

$(DIST_TAR): $(SOURCE) $(DOCS)
	$(PYTHON) $(PYFLAGS) setup.py sdist --formats=gztar

$(DIST_ZIP): $(SOURCE) $(DOCS)
	$(PYTHON) $(PYFLAGS) setup.py sdist --formats=zip

tags: $(SOURCE)
	ctags -R --exclude="build/*" --languages="Python"

FORCE:
