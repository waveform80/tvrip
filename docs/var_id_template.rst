===========
id_template
===========

::

    set id_template <format>

Sets the format used to fill out the ``{id}`` portion of the
:doc:`var_template` setting. This format string may contain the following
substitution variables:

``{season}``
    The season number of the episode being ripped

``{episode}``
    The number of the episode being ripped

Each of these substitution variables use the Python format-string syntax. After
a separating ":" (colon), additional fields may be specified customizing the
output. The following table shows several example values for this field, and
the resulting output for episode 3 of season 2:

=================================  =========
Value                              Output
=================================  =========
``{season}x{episode}``             3x2
``{season}x{episode:02d}``         3x02
``S{season:02d}E{episode:02d}``    S03E02
=================================  =========

The reason that this portion of the :doc:`var_template` is contained in its own
setting is that, sometimes, a single title may contain multiple episodes (this
is commonly done when releasing was were multipart TV episodes on DVD). In this
case, the "id" portion of the template may be repeated. For example: ``Stargate
Universe - 1x01 1x02 1x03 - Air.mp4"``

See also :doc:`var_template`
