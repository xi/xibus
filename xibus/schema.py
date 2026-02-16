import xml.etree.ElementTree as ET
from collections import namedtuple

_Property = namedtuple('Property', ['type', 'access'])
_Method = namedtuple('Method', ['args', 'returns'])
_Signal = namedtuple('Signal', ['args'])
_Interface = namedtuple('Interface', ['methods', 'properties', 'signals'])


def get_all_ordered(node, tag, parse):
    return [(n.get('name'), parse(n)) for n in node.findall(tag)]


def get_all(node, tag, parse):
    return dict(get_all_ordered(node, tag, parse))


def parse_arg(node):
    return node.get('type')


class Method(_Method):
    @classmethod
    def parse(cls, node):
        # inout args must be included in both
        return cls(
            args=get_all_ordered(node, './/arg[@direction!="out"]', parse_arg),
            returns=get_all_ordered(node, './/arg[@direction!="in"]', parse_arg),
        )


class Property(_Property):
    @classmethod
    def parse(cls, node):
        return cls(
            type=node.get('type'),
            access=node.get('access'),
        )


class Signal(_Signal):
    @classmethod
    def parse(cls, node):
        return cls(
            args=get_all_ordered(node, 'arg', parse_arg),
        )


class Interface(_Interface):
    @classmethod
    def parse(cls, node):
        return cls(
            methods=get_all(node, 'method', Method.parse),
            properties=get_all(node, 'property', Property.parse),
            signals=get_all(node, 'signal', Signal.parse),
        )


class Schema:
    def __init__(self, interfaces=None, nodes=None):
        self.interfaces = interfaces or {}
        self.nodes = nodes or []

    @classmethod
    def from_xml(cls, s):
        tree = ET.fromstring(s)
        return cls(
            interfaces=get_all(tree, 'interface', Interface.parse),
            nodes=[n.get('name') for n in tree.findall('node')],
        )
