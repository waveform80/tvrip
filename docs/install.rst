============
Installation
============

tvrip is distributed in several formats. The following sections detail
installation on a variety of platforms.


Download
========

You can find pre-built binary packages for several platforms available from the
`tvrip development site <https://github.com/waveform80/tvrip>`_. Installation
instructions for specific platforms are included in the sections below.

If your platform is *not* covered by one of the sections below, tvrip is
also available from PyPI and can therefore be installed with the ``pip`` tool:

.. code-block:: console

   $ pip install tvrip


Pre-requisites
==============

tvrip depends primarily on the following applications:

 * `Python <https://www.python.org/>`_

 * `Handbrake <https://handbrake.fr/>`_

 * `Atomic Parsley <https://atomicparsley.sourceforge.net>`_

 * `VLC <https://www.videolan.org/>`_

You will need these installed on your platform for tvrip to operate. Packaged
versions of tvip should install these dependencies implicitly.


Ubuntu Linux
============

For Ubuntu Linux it is simplest to install from the PPA as follows:

.. code-block:: console

    $ sudo add-apt-repository ppa://waveform/tvrip
    $ sudo apt-get update
    $ sudo apt-get install tvrip
