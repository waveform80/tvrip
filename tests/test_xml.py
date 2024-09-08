from unittest import mock

import pytest
from xml.etree.ElementTree import tostring, XML

from tvrip.xml import *


tag = ElementFactory()


def test_element_factory_appends():
    assert tostring(tag.foo()) == b'<foo />'
    assert tostring(tag.foo('')) == b'<foo />'
    assert tostring(tag.foo('a')) == b'<foo>a</foo>'
    assert tostring(tag.foo('a', 'b')) == b'<foo>ab</foo>'
    assert tostring(tag.foo(tag.bar(), 'a')) == b'<foo><bar />a</foo>'
    assert tostring(tag.foo(tag.bar(), 'a', 'b')) == b'<foo><bar />ab</foo>'


def test_element_factory_formats():
    assert tostring(tag.foo(1, 2, 3)) == b'<foo>123</foo>'
    assert tostring(tag.foo([1, 2, 3])) == b'<foo>123</foo>'
    assert tostring(tag.foo([1, '2', 3])) == b'<foo>123</foo>'


def test_element_factory_namespace():
    ns_tag = ElementFactory(namespace='http://example.com/X')
    assert tostring(ns_tag.foo(bar=1)) == b'<ns0:foo xmlns:ns0="http://example.com/X" ns0:bar="1" />'
