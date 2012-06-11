# vim: set noet sw=4 ts=4:

# External utilities
PYTHON=python
PYFLAGS=
DEST_DIR=/
PROJECT=tvrip

# Calculate the base names of the distribution, the location of all source,
# documentation and executable script files
NAME:=$(shell $(PYTHON) $(PYFLAGS) setup.py --name)
VER:=$(shell $(PYTHON) $(PYFLAGS) setup.py --version)
PYVER:=$(shell $(PYTHON) $(PYFLAGS) -c "import sys; print 'py%d.%d' % sys.version_info[:2]")
PY_SOURCES:=$(shell \
	$(PYTHON) $(PYFLAGS) setup.py egg_info >/dev/null 2>&1 && \
	cat $(NAME).egg-info/SOURCES.txt)
DOC_SOURCES:=$(wildcard docs/*.rst)

# Calculate the name of all outputs
DIST_EGG=dist/$(NAME)-$(VER)-$(PYVER).egg
DIST_EXE=dist/$(NAME)-$(VER).win32.exe
DIST_RPM=dist/$(NAME)-$(VER)-1.src.rpm
DIST_TAR=dist/$(NAME)-$(VER).tar.gz
DIST_DEB=dist/$(NAME)_$(VER)-1~ppa1_all.deb
MAN_DIR=build/sphinx/man
MAN_PAGES=$(MAN_DIR)/tvrip.1

# Default target
all:
	@echo "make install - Install on local system"
	@echo "make doc - Generate HTML and PDF documentation"
	@echo "make source - Create source package"
	@echo "make buildegg - Generate a PyPI egg package"
	@echo "make buildrpm - Generate an RedHat package"
	@echo "make builddeb - Generate a Debian package"
	@echo "make buildexe - Generate a Windows exe installer"
	@echo "make clean - Get rid of scratch and byte files"

install:
	$(PYTHON) $(PYFLAGS) setup.py install --root $(DEST_DIR) $(COMPILE)

doc: $(DOC_SOURCES)
	$(PYTHON) $(PYFLAGS) setup.py build_sphinx -b html
	$(PYTHON) $(PYFLAGS) setup.py build_sphinx -b latex
	$(MAKE) -C build/sphinx/latex all-pdf

source: $(DIST_TAR)

buildexe: $(DIST_EXE)

buildegg: $(DIST_EGG)

buildrpm: $(DIST_RPM)

builddeb: $(DIST_DEB)

dist: $(DIST_EXE) $(DIST_EGG) $(DIST_RPM) $(DIST_DEB) $(DIST_TAR)

develop: tags
	$(PYTHON) $(PYFLAGS) setup.py develop

test:
	@echo "No tests currently implemented"
	#cd examples && ./runtests.sh

clean:
	$(PYTHON) $(PYFLAGS) setup.py clean
	$(MAKE) -f $(CURDIR)/debian/rules clean
	rm -fr build/ dist/ $(NAME).egg-info/ tags distribute-*.egg distribute-*.tar.gz
	find $(CURDIR) -name "*.pyc" -delete

tags: $(PY_SOURCES)
	ctags -R --exclude="build/*" --exclude="docs/*" --languages="Python"

ppa_release: $(PY_SOURCES) $(DOC_SOURCES)
	$(MAKE) clean
	$(PYTHON) $(PYFLAGS) setup.py build_sphinx -b man
	$(PYTHON) $(PYFLAGS) setup.py sdist $(COMPILE) --dist-dir=../
	rename -f 's/$(PROJECT)-(.*)\.tar\.gz/$(PROJECT)_$$1\.orig\.tar\.gz/' ../*
	debuild -S -i -I -Idist -Idocs -Ibuild/sphinx/doctrees -rfakeroot

$(MAN_PAGES): $(DOC_SOURCES)
	$(PYTHON) $(PYFLAGS) setup.py build_sphinx -b man

$(DIST_TAR): $(PY_SOURCES)
	$(PYTHON) $(PYFLAGS) setup.py sdist $(COMPILE)

$(DIST_EGG): $(PY_SOURCES)
	$(PYTHON) $(PYFLAGS) setup.py bdist_egg $(COMPILE)

$(DIST_EXE): $(PY_SOURCES)
	$(PYTHON) $(PYFLAGS) setup.py bdist_wininst $(COMPILE)

$(DIST_RPM): $(PY_SOURCES) $(MAN_PAGES)
	$(PYTHON) $(PYFLAGS) setup.py bdist_rpm $(COMPILE)
	# XXX Add man-pages to RPMs ... how?
	#$(PYTHON) $(PYFLAGS) setup.py bdist_rpm --post-install=rpm/postinstall --pre-uninstall=rpm/preuninstall $(COMPILE)

$(DIST_DEB): $(PY_SOURCES) $(MAN_PAGES)
	# build the source package in the parent directory then rename it to
	# project_version.orig.tar.gz
	$(PYTHON) $(PYFLAGS) setup.py sdist $(COMPILE) --dist-dir=../
	rename -f 's/$(PROJECT)-(.*)\.tar\.gz/$(PROJECT)_$$1\.orig\.tar\.gz/' ../*
	debuild -b -i -I -Idist -Idocs -Ibuild/sphinx/doctrees -rfakeroot
	mkdir -p dist/
	mv ../$(NAME)_$(VER)-1~ppa1_all.deb dist/

