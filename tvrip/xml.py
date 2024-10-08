# tvrip: extract and transcode DVDs of TV series
#
# Copyright (c) 2024 Dave Jones <dave@waveform.org.uk>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"Provides an XML element factory"

import xml.etree.ElementTree as et

class ElementFactory:
    """
    A class inspired by Genshi for easy creation of ElementTree Elements.

    The ElementFactory class was inspired by the Genshi builder unit in that it
    permits simple creation of Elements by calling methods on the tag object
    named after the element you wish to create. Positional arguments become
    content within the element, and keyword arguments become attributes.

    If you need an attribute or element tag that conflicts with a Python
    keyword, simply append an underscore to the name (which will be
    automatically stripped off).

    Content can be just about anything, including booleans, integers, longs,
    dates, times, etc. This class simply applies their default string
    conversion to them (except basestring derived types like string and unicode
    which are simply used verbatim).

    For example::

        >>> tostring(tag.a('A link'))
        '<a>A link</a>'
        >>> tostring(tag.a('A link', class_='menuitem'))
        '<a class="menuitem">A link</a>'
        >>> tostring(tag.p('A ', tag.a('link', class_='menuitem')))
        '<p>A <a class="menuitem">link</a></p>'
    """

    def __init__(self, namespace=None):
        """Intializes an instance of the factory.

        The optional namespace parameter can be used to specify the namespace
        used to qualify all elements generated by an instance of the class.
        Rather than specifying this explicitly when constructing the class it
        is recommended that developers sub-class this class, and specify the
        namespace as part of an overridden __init__ method. In other words,
        make dialect specific sub-classes of this generic class (an
        HTMLElementFactory class for instance).
        """
        self._namespace = namespace

    def _format(self, content):
        """
        Re-formats *content* to a human-readable string.

        This method should be overridden to customize the representation of
        types (such as :class:`int`, :class:`~datetime.datetime` and so on).
        """
        return str(content)

    def _append(self, node, contents):
        """
        Adds *contents* (which can be a :class:`str`, element, element-list, or
        any type accepted by :meth:`_format`) to a *node*.
        """
        if isinstance(contents, str):
            if contents:
                if len(node) == 0:
                    if node.text is None:
                        node.text = contents
                    else:
                        node.text += contents
                else:
                    last = node[-1]
                    if last.tail is None:
                        last.tail = contents
                    else:
                        last.tail += contents
        elif et.iselement(contents):
            node.append(contents)
        else:
            try:
                it = iter(contents)
            except TypeError:
                self._append(node, self._format(contents))
            else:
                for content in it:
                    self._append(node, content)

    def _element(self, _name, *contents, **attrs):
        """
        Generates an XML element with the tag *name*, containing *contents*
        and with attributes *attrs*.
        """
        if self._namespace:
            _name = f'{{{self._namespace}}}{_name}'
            attrs = {
                f'{{{self._namespace}}}{key}': value
                for (key, value) in attrs.items()
            }
        e = et.Element(_name, {
            key.rstrip('_') if isinstance(key, str) else
            str(key):
            key if value is True else
            value if isinstance(value, str) else
            str(value)
            for key, value in attrs.items()
            if value is not None
            and value is not False
        })
        for content in contents:
            self._append(e, content)
        return e

    def __getattr__(self, name):
        elem_name = name.rstrip('_')
        def generator(*content, **attrs):
            return self._element(elem_name, *content, **attrs)
        setattr(self, name, generator)
        return generator


tag = ElementFactory()
