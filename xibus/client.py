from .schema import Schema


class Client:
    def __init__(self, con):
        self.con = con
        self.introspect_cache = {}

    async def introspect(self, name, path):
        key = f'{name}{path}'
        if key not in self.introspect_cache:
            iface = 'org.freedesktop.DBus.Introspectable'
            (xml,) = await self.con.call(name, path, iface, 'Introspect', [], '')
            self.introspect_cache[key] = Schema.from_xml(xml)
        return self.introspect_cache[key]

    async def call(self, name, path, iface, method, params=(), sig=None):
        schema = await self.introspect(name, path)
        m = schema.interfaces[iface].methods[method]
        if sig is None:
            sig = ''.join([v for _, v in m.args])

        result = await self.con.call(name, path, iface, method, params, sig)
        if len(m.returns) == 1:
            return result[0]
        elif len(m.returns) > 1:
            return result
