#!/usr/bin/env python3
"""Fake Huawei SUN2000 inverter: a Modbus TCP server with demo values.

Simulates a sunny day (bell-curve PV between 06:00 and 18:00, home load
with morning and evening peaks) and serves the registers from Huawei's
Modbus Interface Definitions the sun2000-scraper reads: 32064 PV input
power and 37113 grid active power (positive = feed-in, as reported by the
simulated smart meter), plus the smart meter block (37100+ status/
voltages/currents/energies), device status (32089), inverter output
(32080), PV strings (32016-32019, voltage x10 V / current x100 A), phase
voltages (32069+), grid frequency (32085), temperature (32087) and PV
yields (32106/32114). Raw register values are watts and kWh*100, matching
the Huawei gain convention.
"""
import argparse
import logging
import math
import os
import socket
import struct
import threading
import time

logger = logging.getLogger('fake-sun2000')

SUNRISE, SUNSET = 6.0, 18.0
METER_EXPORT_KWH = 12500.0
METER_IMPORT_KWH = 9800.0


def bell(t, center, width):
    return math.exp(-((t - center) ** 2) / (2.0 * width * width))


def put_i32(regs, addr, value):
    value = int(round(value))
    regs[addr] = (value >> 16) & 0xFFFF
    regs[addr + 1] = value & 0xFFFF


class Simulator:
    def __init__(self, peak_w, static, frozen_time, battery=False, battery_kwh=6.9):
        self.peak_w = peak_w
        self.static = static
        self.frozen_time = frozen_time
        self.battery = battery
        self.battery_kwh = battery_kwh

    def clock(self):
        if self.frozen_time is not None:
            return self.frozen_time
        lt = time.localtime()
        return lt.tm_hour + lt.tm_min / 60.0

    def pv(self, t):
        if SUNRISE < t < SUNSET:
            return self.peak_w * math.sin(math.pi * (t - SUNRISE) / (SUNSET - SUNRISE))
        return 0.0

    def home(self, t):
        return 250.0 + 700.0 * bell(t, 7.5, 1.0) + 400.0 * bell(t, 13.0, 1.5) + 1400.0 * bell(t, 19.0, 1.8)

    def batt(self, t):
        if not self.battery:
            return 0.0
        surplus = self.pv(t) - self.home(t)
        if SUNRISE < t < SUNSET and surplus > 300.0:
            return min(surplus - 300.0, 2500.0)
        if 18.0 <= t < 23.0:
            return -min(self.home(t) - 150.0, 2000.0)
        return 0.0

    def soc(self, t):
        if not self.battery:
            return None
        if self.static:
            return 65.0
        net_kwh = self.integrate_kwh(self.batt, 0.0, t)
        return min(100.0, max(5.0, 50.0 + net_kwh / self.battery_kwh * 100.0))

    def integrate_kwh(self, fn, t0, t1):
        step = 2.0 / 60.0
        total, u = 0.0, t0
        while u < t1:
            u2 = min(u + step, t1)
            total += 0.5 * (fn(u) + fn(u2)) * (u2 - u)
            u = u2
        return total / 1000.0

    def registers(self):
        if self.static:
            pv_w, grid_w = 4000.0, -1500.0
            regs = {}
            put_i32(regs, 32064, pv_w)
            put_i32(regs, 32080, pv_w)
            put_i32(regs, 32106, 1821242)
            put_i32(regs, 32114, 1242)
            put_i32(regs, 37113, grid_w)
            regs[32087] = 280
            regs[32089] = 512
            self.string_regs(regs, pv_w, 405.0)
            self.output_regs(regs, pv_w)
            regs[32085] = 5000
            if self.battery:
                self.battery_regs(regs, 1200.0, 65.0, 25000, 18000, 1234, 890)
            self.meter_regs(regs, grid_w, METER_EXPORT_KWH, METER_IMPORT_KWH)
            return regs
        t = self.clock()
        pv_w = self.pv(t)
        home_w = self.home(t)
        batt_w = self.batt(t)
        grid_w = pv_w - batt_w - home_w
        if t <= SUNRISE:
            day_kwh = 0.0
        elif t < SUNSET:
            day_kwh = (self.peak_w / 1000.0) * (SUNSET - SUNRISE) / math.pi * (1 - math.cos(math.pi * (t - SUNRISE) / (SUNSET - SUNRISE)))
        else:
            day_kwh = 2.0 * (self.peak_w / 1000.0) * (SUNSET - SUNRISE) / math.pi
        pv_frac = pv_w / self.peak_w if self.peak_w else 0.0
        export_day = self.integrate_kwh(lambda u: max(self.pv(u) - self.batt(u) - self.home(u), 0.0), 0.0, t)
        import_day = self.integrate_kwh(lambda u: max(self.home(u) + self.batt(u) - self.pv(u), 0.0), 0.0, t)
        regs = {}
        put_i32(regs, 32064, pv_w)
        put_i32(regs, 32080, pv_w)
        put_i32(regs, 32106, (18200.0 + day_kwh) * 100)
        put_i32(regs, 32114, day_kwh * 100)
        put_i32(regs, 37113, grid_w)
        regs[32087] = int(180 + 140 * pv_frac) & 0xFFFF
        regs[32089] = 512 if pv_w > 0 else 40960
        self.string_regs(regs, pv_w, 420.0 - 40.0 * pv_frac)
        self.output_regs(regs, pv_w)
        regs[32085] = 5000
        if self.battery:
            self.battery_regs(regs, batt_w, self.soc(t),
                              int((50000.0 + self.integrate_kwh(lambda u: max(self.batt(u), 0.0), 0.0, t) * 100)),
                              int(self.integrate_kwh(lambda u: max(-self.batt(u), 0.0), 0.0, t) * 100),
                              int(self.integrate_kwh(lambda u: max(self.batt(u), 0.0), 0.0, t) * 100),
                              int(self.integrate_kwh(lambda u: max(-self.batt(u), 0.0), 0.0, t) * 100))
        self.meter_regs(regs, grid_w, METER_EXPORT_KWH + export_day, METER_IMPORT_KWH + import_day)
        return regs

    def string_regs(self, regs, pv_w, voltage):
        v = int(round(voltage * 10))
        i = int(round(pv_w / 2.0 / max(voltage, 1.0) * 100))
        for addr in (32016, 32018):
            regs[addr] = v
            regs[addr + 1] = i

    def output_regs(self, regs, pv_w):
        for addr in (32069, 32070, 32071):
            regs[addr] = 2300
        for addr in (32066, 32067, 32068):
            regs[addr] = 4000
        current = int(round(pv_w / 3.0 / 230.0 * 1000))
        for addr in (32072, 32074, 32076):
            put_i32(regs, addr, current)
        put_i32(regs, 32078, pv_w)
        put_i32(regs, 32082, 0)
        regs[32084] = 1000
        regs[32086] = 970

    def battery_regs(self, regs, batt_w, soc, charge_kwh100, discharge_kwh100, charge_day_kwh100, discharge_day_kwh100):
        put_i32(regs, 37001, batt_w)
        regs[37003] = 0
        regs[37004] = int(round(soc * 10))
        regs[37760] = int(round(soc * 10))
        for addr, value in ((37780, charge_kwh100), (37782, discharge_kwh100),
                            (37784, charge_day_kwh100), (37786, discharge_day_kwh100)):
            put_i32(regs, addr, value)

    def meter_regs(self, regs, grid_w, export_kwh, import_kwh):
        regs[37100] = 1
        for addr in (37101, 37103, 37105):
            put_i32(regs, addr, 2300)
        current = int(round(abs(grid_w) / 3.0 / 230.0 * 100))
        for addr in (37107, 37109, 37111):
            put_i32(regs, addr, current)
        put_i32(regs, 37115, 0)
        regs[37117] = 1000
        regs[37118] = 5000
        put_i32(regs, 37119, export_kwh * 100)
        put_i32(regs, 37121, import_kwh * 100)
        regs[37125] = 1
        phase_w = grid_w / 3.0
        for addr in (37132, 37134, 37136):
            put_i32(regs, addr, phase_w)


def recv_exact(sock, n):
    buf = b''
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError('client closed connection')
        buf += chunk
    return buf


class FakeInverter:
    def __init__(self, unit, simulator, strict=False):
        self.unit = unit
        self.simulator = simulator
        self.strict = strict
        self.overlay = {}

    def serve(self, host, port):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(4)
        logger.info('fake SUN2000 listening on %s:%d (unit %d, peak PV %gW)', host, port, self.unit, self.simulator.peak_w)
        while True:
            client, addr = srv.accept()
            threading.Thread(target=self.handle, args=(client, addr), daemon=True).start()

    def handle(self, client, addr):
        logger.info('client connected: %s:%d', *addr[:2])
        try:
            while True:
                txn, proto, length, unit = struct.unpack('>HHHB', recv_exact(client, 7))
                pdu = recv_exact(client, length - 1)
                func, addr_, count = struct.unpack('>BHH', pdu[:5])
                if unit != self.unit:
                    logger.debug('request for unit %d, serving %d', unit, self.unit)
                if func == 3:
                    regs = self.simulator.registers()
                    regs.update(self.overlay)
                    if self.strict and any(addr_ + i not in regs for i in range(count)):
                        body = struct.pack('>BB', 3 + 0x80, 2)
                        client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                        logger.debug('read %d regs @%d -> exception 02 (undefined register)', count, addr_)
                        continue
                    words = [regs.get(addr_ + i, 0) & 0xFFFF for i in range(count)]
                    data = struct.pack('>%dH' % count, *words) if words else b''
                    body = struct.pack('>BB', func, count * 2) + data
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.debug('read %d regs @%d -> %s', count, addr_, words)
                elif func == 6 and len(pdu) == 5:
                    self.overlay[addr_] = struct.unpack('>H', pdu[3:5])[0]
                    client.sendall(struct.pack('>HHHB', txn, 0, len(pdu) + 1, unit) + pdu)
                    logger.debug('wrote %d = %d', addr_, self.overlay[addr_])
                elif func == 16 and len(pdu) >= 6 and pdu[5] == count * 2 and len(pdu) == 6 + count * 2:
                    values = struct.unpack('>%dH' % count, pdu[6:6 + count * 2])
                    for i, w in enumerate(values):
                        self.overlay[addr_ + i] = w
                    body = struct.pack('>BHH', func, addr_, count)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
                    logger.debug('wrote %d regs @%d -> %s', count, addr_, list(values))
                else:
                    body = struct.pack('>BB', func + 0x80, 1 if func not in (6, 16) else 3)
                    client.sendall(struct.pack('>HHHB', txn, 0, len(body) + 1, unit) + body)
        except (ConnectionError, OSError) as e:
            logger.info('client %s:%d disconnected (%s)', *addr[:2], e)
        except Exception as e:
            logger.error('error handling %s:%d: %s', *addr[:2], e)
        finally:
            client.close()


def parse_time(text):
    try:
        h, m = text.split(':')
        t = int(h) + int(m) / 60.0
        if not 0 <= t < 24:
            raise ValueError
        return t
    except (ValueError, TypeError):
        raise SystemExit('--time must be HH:MM (00:00-23:59), got %r' % text)


def main():
    p = argparse.ArgumentParser(description='Fake Huawei SUN2000 inverter + smart meter (Modbus TCP server with demo values).')
    p.add_argument('--host', default='127.0.0.1', help='bind address (default %(default)s)')
    p.add_argument('--port', type=int, default=5502, help='Modbus TCP port (default %(default)s)')
    p.add_argument('--unit', type=int, default=1, help='Modbus unit id served (default %(default)s)')
    p.add_argument('--max-kwp', type=float, default=6.0, help='PV array size in kWp, peak = 75%% of it (default %(default)s)')
    p.add_argument('--time', help='freeze simulated time HH:MM (default: real clock)')
    p.add_argument('--static', action='store_true', help='constant demo values instead of the day simulation')
    p.add_argument('--battery', action='store_true', help='simulate a LUNA2000 battery')
    p.add_argument('--strict', action='store_true', help='reject reads of undefined registers with exception 02 (like the real device)')
    p.add_argument('--battery-kwh', type=float, default=6.9, help='usable battery capacity in kWh (default %(default)s)')
    p.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = p.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format='%(levelname)-7s %(message)s' if os.environ.get('JOURNAL_STREAM')
                        else '%(asctime)s %(levelname)-7s %(message)s')
    simulator = Simulator(0.75 * args.max_kwp * 1000.0, args.static, parse_time(args.time) if args.time else None,
                          battery=args.battery, battery_kwh=args.battery_kwh)
    try:
        FakeInverter(args.unit, simulator, strict=args.strict).serve(args.host, args.port)
    except KeyboardInterrupt:
        logger.info('stopped')
    except OSError as e:
        logger.error('cannot serve on %s:%d: %s', args.host, args.port, e)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
