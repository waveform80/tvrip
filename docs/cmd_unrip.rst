=======
unrip
=======

::

    unrip <episodes>

The ``unrip`` command is used to set the status of an episode or episodes to
unripped. Episodes may be specified as a range (``1-5``) or as a comma
separated list (``4,2,1``) or some combination (``1,3-5``), or ``*`` to
indicate all episodes in the currently selected season.

Episodes are automatically set to ripped during the operation of the
:doc:`cmd_rip` command.  Episodes marked as ripped will be automatically mapped
to titles by the :doc:`cmd_map` command when the disc they were ripped from is
scanned (they can be mapped manually too). For example::

    (tvrip) unrip 3
    (tvrip) unrip 7

See also :doc:`cmd_rip`, :doc:`cmd_map`
