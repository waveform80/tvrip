=============
output_format
=============

::

    set output_format mp4|mkv


Description
===========

Specifies the file format that episodes will be ripped to. This can be set to
either ``mp4``, which is more widely supported, or ``mkv`` which is the more
advanced format (and is the only format suitable for things like PGS subtitle
pass-through on Blu-ray discs). Example::

    (tvrip) set output_format mkv

This setting affects the ``{ext}`` substitution in the :doc:`var_template`.


See Also
========

:doc:`var_template`
