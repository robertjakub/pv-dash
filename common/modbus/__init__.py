"""The modbus package: the wire core and the shared client/write-shape
primitives — one implementation for the whole family (stdlib only)."""

from .protocol import (AUTH_DOMAIN, AUTH_ERR, AUTH_FRAME_LEN, AUTH_MAGIC,
                       AUTH_MAC_LEN, AUTH_MIN_KEY, AUTH_NONCE_LEN, AUTH_OK,
                       FC_NAMES, SLAVE_BUSY, WAVESHARE_REPLY_MAX, DeviceError,
                       ModbusError, ReplyTimeout, auth_handshake_client,
                       auth_handshake_server, auth_mac, check_head,
                       describe_fc, exception_frame, frame, is_busy_error,
                       pack_bits, unit_in_range,
                       read_frame, recv_exact, unpack_bits,
                       waveshare_handshake_client)
from .client import ClientBase, check_data_bytes, check_reply, open_socket
from .blocks import (BIT_READ_FUNCS, MAX_BITS, MAX_COUNT, READ_FUNCS,
                     block_stat, build_blocks, span)
from .server import serve_modbus
from .writes import describe_write, write_kv, write_shape_error, write_target

