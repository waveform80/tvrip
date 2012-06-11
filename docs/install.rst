============
Installation
============

tvrip is distributed in several formats. The following sections detail
installation on a variety of platforms.


Download
========

You can find pre-built binary packages for several platforms available from
the `tvrip development site
<http://www.waveform.org.uk/trac/tvrip/wiki/Download>`_. Installations
instructions for specific platforms are included in the sections below.

If your platform is *not* covered by one of the sections below, tvrip is
also available from PyPI and can therefore be installed with the ``pip`` or
``easy_install`` tools::

   $ pip install tvrip

   $ easy_install tvrip


Pre-requisites
==============

tvrip depends primarily on the following applications:

 * `Handbrake <http://handbrake.fr/>`_

 * `Atomic Parsley <http://atomicparsley.sourceforge.net>`_

If you wish to use OCR to convert DVD (picture-based) subtitles into SubRip
(text-based) subtitles you will also need:

 * `GOCR <http://jocr.sourceforge.net>`_

 * `Transcode Utilities <http://tcforge.berlios.de>`_

As tvrip is written in the `Python <http://www.python.org/>`_ language, you
will need a copy of this installed along with the following Python packages:

 * `sqlalchemy <http://www.sqlalchemy.org>`_


Ubuntu Linux
============

For Ubuntu Linux it is simplest to install from the PPA as follows::

    $ sudo add-apt-repository ppa://waveform/ppa
    $ sudo apt-get update
    $ sudo apt-get install tvrip

Development
-----------

If you wish to develop tvrip, you can install the pre-requisites, construct
a virtualenv sandbox, and check out the source code from subversion with the
following command lines::

   # Install the pre-requisites
   $ sudo apt-get install python-sqlalchemy python-virtualenv python-sphinx make subversion

   # Construct and activate a sandbox with access to the packages we just
   # installed
   $ virtualenv --system-site-packages sandbox
   $ source sandbox/bin/activate

   # Check out the source code and install it in the sandbox for development and testing
   $ svn co http://www.waveform.org.uk/svn/tvrip/trunk tvrip
   $ cd tvrip
   $ make develop


Microsoft Windows
=================

XXX To be written


Apple Mac OS X
==============

XXX To be written

