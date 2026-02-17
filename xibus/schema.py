import xml.etree.ElementTree as ET
from collections import namedtuple

_Property = namedtuple('Property', ['type', 'access'])
_Method = namedtuple('Method', ['args', 'returns'])
_Signal = namedtuple('Signal', ['args'])
_Interface = namedtuple('Interface', ['methods', 'properties', 'signals'])


def el(tag, attrs):
    node = ET.Element(tag)
    for key, value in attrs.items():
        if value is not None:
            node.attrib[key] = value
    return node


def get_all_ordered(node, tag, parse):
    return [(n.get('name'), parse(n)) for n in node.findall(tag)]


def get_all(node, tag, parse):
    return dict(get_all_ordered(node, tag, parse))


def normalize_args(args):
    return [(None, arg) if isinstance(arg, str) else arg for arg in args]


def parse_arg(node):
    return node.get('type')


def unparse_arg(name, typ, direction=None):
    return el('arg', {
        'name': name,
        'direction': direction,
        'type': typ,
    })


class Method(_Method):
    @classmethod
    def parse(cls, node):
        # inout args must be included in both
        return cls(
            args=get_all_ordered(node, './/arg[@direction!="out"]', parse_arg),
            returns=get_all_ordered(node, './/arg[@direction!="in"]', parse_arg),
        )

    def unparse(self, name):
        node = el('method', {'name': name})
        for _name, typ in self.args:
            node.append(unparse_arg(_name, typ, 'in'))
        for _name, typ in self.returns:
            node.append(unparse_arg(_name, typ, 'out'))
        return node


class Property(_Property):
    @classmethod
    def parse(cls, node):
        return cls(
            type=node.get('type'),
            access=node.get('access'),
        )

    def unparse(self, name):
        return el('property', {
            'name': name,
            'type': self.type,
            'access': self.access,
        })


class Signal(_Signal):
    @classmethod
    def parse(cls, node):
        return cls(
            args=get_all_ordered(node, 'arg', parse_arg),
        )

    def unparse(self, name):
        node = el('signal', {'name': name})
        for _name, typ in self.args:
            node.append(unparse_arg(_name, typ))
        return node


class Interface(_Interface):
    @classmethod
    def parse(cls, node):
        return cls(
            methods=get_all(node, 'method', Method.parse),
            properties=get_all(node, 'property', Property.parse),
            signals=get_all(node, 'signal', Signal.parse),
        )

    def unparse(self, name):
        node = el('interface', {'name': name})
        for _name, method in self.methods.items():
            node.append(method.unparse(_name))
        for _name, prop in self.properties.items():
            node.append(prop.unparse(_name))
        for _name, signal in self.signals.items():
            node.append(signal.unparse(_name))
        return node


class Schema:
    def __init__(self, interfaces=None, nodes=None):
        self.interfaces = interfaces or {}
        self.nodes = nodes or []

    def add_property(self, iface, prop, typ, access):
        iface_data = self.interfaces.setdefault(iface, Interface({}, {}, {}))
        iface_data.properties[prop] = Property(typ, access)

    def add_method(self, iface, method, args, returns):
        iface_data = self.interfaces.setdefault(iface, Interface({}, {}, {}))
        iface_data.methods[method] = Method(
            normalize_args(args), normalize_args(returns)
        )

    def add_signal(self, iface, signal, args):
        iface_data = self.interfaces.setdefault(iface, Interface({}, {}, {}))
        iface_data.signals[signal] = Signal(normalize_args(args))

    def add_defaults(self):
        self.add_method('org.freedesktop.DBus.Introspectable', 'Introspect', [], ['s'])
        self.add_method('org.freedesktop.DBus.Properties', 'Get', ['s', 's'], ['v'])
        self.add_method('org.freedesktop.DBus.Properties', 'Set', ['s', 's', 'v'], [])
        self.add_method('org.freedesktop.DBus.Properties', 'GetAll', ['s'], ['a{sv}'])

    @classmethod
    def from_xml(cls, s):
        tree = ET.fromstring(s)
        return cls(
            interfaces=get_all(tree, 'interface', Interface.parse),
            nodes=[n.get('name') for n in tree.findall('node')],
        )

    def to_xml(self):
        tree = el('node', {})
        for _name, iface in self.interfaces.items():
            tree.append(iface.unparse(_name))
        for _name in self.nodes:
            tree.append(el('node', {'name': _name}))
        ET.indent(tree)
        return ET.tostring(tree, encoding='unicode', xml_declaration=True)
