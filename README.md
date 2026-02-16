# xibus - pure python async D-Bus library

This is a pure python implementation of the [D-Bus
Specification](https://dbus.freedesktop.org/doc/dbus-specification.html).
It consists of the following parts:

-   `marshal.py` implements the low-level wire format
-   `message.py` builds on that to define messages
-   `connection.py` allows to send and receive messages over a socket as well as introducing the concepts of method calls and signals
-   `client.py` provides high level abstractions
    -   properties
    -   introspection
    -   guessing the correct path and interface to reduce verbosity
    -   portal-style async responses (`org.freedesktop.portal.Request`)

## Usage

```python
import asyncio
from xibus import get_client

async def amain():
    async with get_client('session') as c:
        # call a method
        print(await c.call(
            'org.freedesktop.portal.Desktop',
            '/org/freedesktop/portal/desktop',
            'org.freedesktop.portal.Settings',
            'ReadOne',
            ('org.freedesktop.appearance', 'color-scheme'),
            'ss',
        ))

        # if path, interface, or signature are omitted,
        # they will be inferred from introspection
        print(await c.call(
            'org.freedesktop.portal.Desktop',
            None,
            None,
            'ReadOne',
            ('org.freedesktop.appearance', 'color-scheme'),
        ))

        # get a property
        print(await c.get_property(
            'org.freedesktop.portal.Desktop',
            None,
            'org.freedesktop.portal.Settings',
            'version',
        ))

        # receive signals
        async with c.subscribe_signal(
            'org.freedesktop.portal.Desktop',
            None,
            None,
            'SettingChanged',
        ) as queue:
            async for signal in queue:
                print(signal)

        # desktop portals have a different mechanism for returning values,
        # so there is a special way to call them
        await c.portal_call(
            'org.freedesktop.portal.Desktop',
            None,
            None,
            'OpenURI',
            ['', 'https://example.com', {}],
        )

asyncio.run(amain())
```

## Motivation

This library was born from my frustration with dbus. I wanted to see if that
frustration was caused by bad library design or if it was inherent in the
protocol.

### Verbosity

`org.freedesktop.portal.Desktop /org/freedesktop/portal/desktop
org.freedesktop.portal.Settings ReadOne` is extremely verbose and redundant. An
equivalent HTTP endpoint would probably be called
`desktop.portal.freedesktop.org/settings/ReadOne`, which is so much better.
Sure, namespacing has its benefits. But this is just excessive.

This is mostly an issue in the protocol. Applications could make this slightly
better by choosing `/` as the path for their primary object, but even that is
discouraged by the spec.

`GDBusProxy` is also more of a workaround than a solution. The fact that it
is a proxy for interfaces rather than objects is an indicator that those two
concepts are at least partially redundant.

My workaround here is to use the first matching path / interface that can be
found. This has a performance penalty and is brittle (e.g. if conflicting
interfaces are added later on), so this is not a real solution either.

IMHO the real solution would be to enforce `/` as the primary object path and
to do away with interfaces. In practice there are not so many interfaces on the
same object that collisions are a real issue.

### Signatures

In order to encode a dbus message, you need to know its type signature. In the
glib implementation, the caller must provide that signature. I added the option
to omit the signature, in which case it is received via introspection. Deriving
the signature from python types is not easily possible because it is unclear
how to differentiate `INT32` from `UINT64` or `STRING` from `OBJECT_PATH`.

A special case of this are variant types, where the type is only known at
runtime. I chose to represent them as simple `(signature, value)` tuples.

### Custom wire format

The most complex part of this library is the implementation of the custom wire
format. This would be much easier if dbus would reuse an existing format like
MessagePack, CBOR, or even JSON. (Each of these of course come with their own
pros and cons.)

### Layers

That said, I really like how the different layers of this protocol are stacked
on top of each other. Once you have the wire format, you can build messages on
top of that. Then you can build method calls and signals on top of messages.
Finally, you can build introspection and property access on top of method calls.

## Links

-   [dbus-next](https://github.com/altdesktop/python-dbus-next) and its forks
    [dbus-fast](https://github.com/bluetooth-devices/dbus-fast) and
    [asyncdbus](https://github.com/M-o-a-T/asyncdbus) also implements D-Bus in
    python, but the code is much more complex.
-   [Talk on why systemd is moving from D-Bus to
    Varlink](https://mirror.as35701.net/video.fosdem.org/2026/ub2147/NFNKEK-varlink-ipc-system-keynote.av1.webm)
