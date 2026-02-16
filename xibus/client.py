import contextlib

from .schema import Schema


class SignalQueue:
    def __init__(self, queue, sender, path, iface, signal):
        self.queue = queue
        self.sender = sender
        self.path = path
        self.iface = iface
        self.signal = signal

    @property
    def rule(self):
        return ','.join(
            f"{key}='{value}'"
            for key, value in {
                'type': 'signal',
                'sender': self.sender,
                'path': self.path,
                'interface': self.iface,
                'member': self.signal,
            }.items()
        )

    async def __aiter__(self):
        async for msg in self.queue:
            if (
                msg.sender == self.sender
                and msg.path == self.path
                and msg.iface == self.iface
                and msg.member == self.signal
            ):
                yield msg.body


class Proxy:
    def __init__(self, client, name, path=None, iface=None):
        self.client = client
        self.defaults = (name, path, iface)

    async def call(self, method, params=(), sig=None):
        return await self.client.call(*self.defaults, method, params, sig)

    @contextlib.asynccontextmanager
    async def subscribe_signal(self, signal):
        async with self.client.subscribe_signal(*self.defaults, signal) as queue:
            yield queue

    async def get_property(self, prop):
        return await self.client.get_property(*self.defaults, prop)

    async def set_property(self, prop, value, sig=None):
        return await self.client.set_property(*self.defaults, prop, value, sig)

    async def watch_property(self, prop):
        async for value in self.client.watch_property(*self.defaults, prop):
            yield value


class Client:
    def __init__(self, con):
        self.con = con
        self.introspect_cache = {}
        self.bus = Proxy(
            self,
            'org.freedesktop.DBus',
            '/org/freedesktop/DBus',
            'org.freedesktop.DBus',
        )

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

    @contextlib.asynccontextmanager
    async def subscribe_signal(self, name, path, iface, signal):
        # NOTE: if we register the same match rule twice and then remove one of
        # them, the other still exists on the bus. So we do not need any
        # special handling on our end.

        if not name.startswith(':'):
            name = await self.bus.call('GetNameOwner', [name], 's')
        with self.con.signal_queue() as queue:
            sq = SignalQueue(queue, name, path, iface, signal)
            await self.bus.call('AddMatch', [sq.rule], 's')
            try:
                yield sq
            finally:
                await self.bus.call('RemoveMatch', [sq.rule], 's')

    async def get_property(self, name, path, iface, prop):
        iprop = 'org.freedesktop.DBus.Properties'
        result = await self.call(name, path, iprop, 'Get', (iface, prop), 'ss')
        return result[1]

    async def set_property(self, name, path, iface, prop, value, sig=None):
        iprop = 'org.freedesktop.DBus.Properties'
        if sig is None:
            schema = await self.introspect(name, path)
            sig = schema.interfaces[iface].properties[prop].type
        await self.call(name, path, iprop, 'Set', (iface, prop, (sig, value)), 'ssv')

    async def watch_property(self, name, path, iface, prop):
        iprop = 'org.freedesktop.DBus.Properties'
        async with self.subscribe_signal(
            name, path, iprop, 'PropertiesChanged'
        ) as queue:
            yield await self.get_property(name, path, iface, prop)
            async for _iface, changed, invalidated in queue:
                if _iface == iface:
                    if prop in changed:
                        yield changed[prop][1]
                    elif prop in invalidated:
                        yield None


class MagicClient(Client):
    async def _iter_paths(self, name, path=''):
        schema = await self.introspect(name, path or '/')
        if schema.interfaces:
            yield path or '/'
        for child in schema.nodes:
            async for p in self._iter_paths(name, f'{path}/{child}'):
                yield p

    async def _guess_iface(self, name, key, value, path, iface=None):
        if iface:
            return iface
        schema = await self.introspect(name, path)
        for iface, s in schema.interfaces.items():
            if value in getattr(s, key):
                return iface
        raise ValueError((name, key, value, path))

    async def _guess_path(self, name, key, value, path=None, iface=None):
        if path:
            return path, await self._guess_iface(name, key, value, path, iface)
        async for path in self._iter_paths(name):
            try:
                return path, await self._guess_iface(name, key, value, path, iface)
            except ValueError:
                pass
        raise ValueError((name, key, value))

    async def call(self, name, path, iface, method, params=(), sig=None):
        path, iface = await self._guess_path(name, 'methods', method, path, iface)
        return await super().call(name, path, iface, method, params, sig)

    @contextlib.asynccontextmanager
    async def subscribe_signal(self, name, path, iface, signal):
        path, iface = await self._guess_path(name, 'signals', signal, path, iface)
        async with super().subscribe_signal(name, path, iface, signal) as queue:
            yield queue

    async def get_property(self, name, path, iface, prop):
        path, iface = await self._guess_path(name, 'properties', prop, path, iface)
        return await super().get_property(name, path, iface, prop)

    async def set_property(self, name, path, iface, prop, value, sig=None):
        path, iface = await self._guess_path(name, 'properties', prop, path, iface)
        await super().set_property(name, path, iface, prop, value, sig)

    async def watch_property(self, name, path, iface, prop):
        path, iface = await self._guess_path(name, 'properties', prop, path, iface)
        async for value in super().watch_property(name, path, iface, prop):
            yield value
