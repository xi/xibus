import asyncio
import os
import re
import socket
from contextlib import contextmanager

from .message import Msg
from .message import MsgFlag
from .message import MsgType

RE_PATH = re.compile(r'^/[A-Za-z0-9_/]*$')


class DBusError(Exception):
    pass


class InvalidPathError(ValueError):
    pass


async def iter_queue(queue):
    while True:
        item = await queue.get()
        try:
            yield item
        finally:
            queue.task_done()


class Connection:
    def __init__(self, addr, loop=None):
        self.addr = addr
        self.loop = loop
        self.serial = 0
        self.send_queue = []
        self.replies = {}
        self.call_queues = {}
        self.signal_queues = set()

        if not self.loop:
            self.loop = asyncio.get_running_loop()

        # set in __aenter__()
        self.sock = None
        self.unique_name = None

    def get_serial(self):
        self.serial += 1
        return self.serial

    def on_read(self):
        buf, fds, _, _ = socket.recv_fds(self.sock, 134217728, 255)
        while buf:
            msg, buf, fds = Msg.unmarshal(buf, fds)
            if msg.reply_serial is not None:
                if msg.reply_serial in self.replies:
                    future = self.replies.pop(msg.reply_serial)
                    future.set_result(msg)
            elif msg.type == MsgType.METHOD_CALL:
                self.call_queues[msg.destination].put_nowait(msg)
            elif msg.type == MsgType.SIGNAL:
                for queue in self.signal_queues:
                    queue.put_nowait(msg)
            else:
                raise ValueError(msg)

    def on_write(self):
        if self.send_queue:
            buf, fds, future = self.send_queue.pop(0)
            size = socket.send_fds(self.sock, [buf], fds)
            if size < len(buf):
                self.send_queue.insert(0, (buf[size:], [], future))
            else:
                future.set_result(None)
        else:
            self.loop.remove_writer(self.sock.fileno())

    async def send(self, buf, fds=[]):
        if not self.send_queue:
            self.loop.add_writer(self.sock.fileno(), self.on_write)
        future = self.loop.create_future()
        self.send_queue.append((buf, fds, future))
        await future

    async def recv(self, nbytes):
        return await self.loop.sock_recv(self.sock, nbytes)

    async def auth(self):
        uid = os.getuid()
        uid_encoded = str(uid).encode('ascii').hex()
        await self.send(f'AUTH EXTERNAL {uid_encoded}\r\n'.encode('ascii'))
        assert (await self.recv(128)).startswith(b'OK')
        await self.send(b'NEGOTIATE_UNIX_FD\r\n')
        assert (await self.recv(128)).startswith(b'AGREE_UNIX_FD')
        await self.send(b'BEGIN\r\n')

    async def __aenter__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.setblocking(False)  # noqa
        await self.loop.sock_connect(self.sock, self.addr)

        await self.send(b'\0')
        await self.auth()

        self.loop.add_reader(self.sock.fileno(), self.on_read)

        (self.unique_name,) = await self.call(
            'org.freedesktop.DBus',
            '/org/freedesktop/DBus',
            'org.freedesktop.DBus',
            'Hello',
            [],
            '',
        )

        return self

    async def __aexit__(self, *args, **kwargs):
        self.unique_name = None
        self.loop.remove_reader(self.sock.fileno())
        self.loop.remove_writer(self.sock.fileno())
        self.sock.shutdown(socket.SHUT_RDWR)
        self.sock.close()
        self.sock = None

    @contextmanager
    def signal_queue(self):
        queue = asyncio.Queue()
        self.signal_queues.add(queue)
        try:
            yield iter_queue(queue)
        finally:
            self.signal_queues.remove(queue)
            queue.shutdown()

    @contextmanager
    def call_queue(self, name):
        if name in self.call_queues:
            raise ValueError(name)
        queue = asyncio.Queue()
        self.call_queues[name] = queue
        try:
            yield iter_queue(queue)
        finally:
            self.call_queues.pop(name)
            queue.shutdown()

    async def call(self, dest, path, iface, method, body, sig, flags=MsgFlag.NONE):
        if not RE_PATH.match(path):
            raise InvalidPathError(path)

        request = Msg(
            MsgType.METHOD_CALL,
            self.get_serial(),
            destination=dest,
            path=path,
            iface=iface,
            member=method,
            body=body,
            sig=sig,
            flags=flags,
        )

        if flags & MsgFlag.NO_REPLY_EXPECTED:
            await self.send(*request.marshal())
            return

        future = self.loop.create_future()
        self.replies[request.serial] = future

        try:
            await self.send(*request.marshal())
            response = await future
        finally:
            self.replies.pop(request.serial, None)

        if response.type == MsgType.METHOD_RETURN:
            return response.body
        elif response.type == MsgType.ERROR:
            e = DBusError(response.error_name)
            if response.body and isinstance(response.body[0], str):
                e.add_note(response.body[0])
            raise e
        else:
            raise ValueError(response.type)

    async def emit_signal(self, path, iface, signal, body, sig, flags=MsgFlag.NONE):
        if not RE_PATH.match(path):
            raise InvalidPathError(path)

        msg = Msg(
            MsgType.SIGNAL,
            self.get_serial(),
            path=path,
            iface=iface,
            member=signal,
            body=body,
            sig=sig,
            flags=flags,
        )

        await self.send(*msg.marshal())

    async def send_reply(self, call, handler):
        try:
            sig, body = await handler(call)
            reply = Msg(
                MsgType.METHOD_RETURN,
                self.get_serial(),
                reply_serial=call.serial,
                destination=call.sender,
                body=body,
                sig=sig,
            )
        except Exception as e:
            # TODO: better error conversion
            # (what is the quivalent of 404 not found?)
            reply = Msg(
                MsgType.ERROR,
                self.get_serial(),
                reply_serial=call.serial,
                destination=call.sender,
                error_name='org.freedesktop.DBus.Error.AccessDenied',
                body=(str(e),),
                sig='s',
            )

        if not call.flags & MsgFlag.NO_REPLY_EXPECTED:
            await self.send(*reply.marshal())


def get_connection(bus):
    if bus == 'session':
        addr = os.getenv(
            'DBUS_SESSION_BUS_ADDRESS',
            f'unix:path=/run/user/{os.getuid()}/bus',
        )
    else:  # pragma: no cover
        addr = os.getenv(
            'DBUS_SYSTEM_BUS_ADDRESS',
            'unix:path=/run/dbus/system_bus_socket',
        )
    return Connection(addr.removeprefix('unix:path=').split(',', 1)[0])
