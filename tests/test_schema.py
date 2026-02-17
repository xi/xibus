import unittest

from xibus.schema import Schema

SCHEMA = """<?xml version='1.0' encoding='utf-8'?>
<node>
  <interface name="org.freedesktop.DBus">
    <method name="RequestName">
      <arg direction="in" type="s" />
      <arg direction="in" type="u" />
      <arg direction="out" type="u" />
    </method>
    <method name="ReloadConfig" />
    <property name="Features" type="as" access="read" />
    <signal name="NameLost">
      <arg type="s" />
    </signal>
  </interface>
  <node name="foo" />
</node>"""


class TestSchema(unittest.TestCase):
    maxDiff = 1000

    def test_from_xml(self):
        schema = Schema.from_xml(SCHEMA)
        self.assertEqual(schema.to_xml(), SCHEMA)

    def test_construct(self):
        schema = Schema()
        schema.add_method('org.freedesktop.DBus', 'RequestName', ['s', 'u'], ['u'])
        schema.add_method('org.freedesktop.DBus', 'ReloadConfig', [], [])
        schema.add_property('org.freedesktop.DBus', 'Features', 'as', 'read')
        schema.add_signal('org.freedesktop.DBus', 'NameLost', ['s'])
        schema.nodes.append('foo')
        self.assertEqual(schema.to_xml(), SCHEMA)
