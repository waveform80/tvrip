template
========

::

    set template <format>


Description
===========

Sets the format used to construct filenames for output video files. This format
string may contain the following substitution variables:

``program``
    The name of the program the episode belongs to

``id``
    The output of the :doc:`var_id_template` setting. This typically contains
    the season number and episode number

``season``
    The number of the season the episode belongs to

``name``
    The name of the episode itself

``now``
    The current date and time

``ext``
    The extension of the selected file format ("mp4" or "mkv")

Each of these substitution variables use the Python format-string syntax. After
a separating ":" (colon), additional fields may be specified customizing the
output. The following table shows several example values for this field, and
the resulting output for Red Dwarf episode 2 of season 3, "Marooned", assuming
:doc:`var_id_template` is set to its default of ``{season}x{episode:02d}``:

=================================================  ======================================
Value                                              Output
=================================================  ======================================
``{program} - {id} - {name}.{ext}``                Red Dwarf - 3x02 - Marooned.mp4
``{program}/Season {season}/{id} - {name}.{ext}``  Red Dwarf/Season 3/3x02 - Marooned.mp4
=================================================  ======================================


See Also
========

:doc:`var_id_template`, :doc:`var_output_format`, :doc:`var_target`
