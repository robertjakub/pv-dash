#!/usr/bin/env python3
"""Register-map encoding: the SUN2000/Meter/battery blocks as free functions
writing into a plain {addr: word} dict (raw wire values, gains applied)."""

# lifetime meter totals the demo starts from (kWh)
METER_EXPORT_KWH = 12500.0
METER_IMPORT_KWH = 9800.0


def put_i32(regs, addr, value):
    value = int(round(value))
    regs[addr] = (value >> 16) & 0xFFFF
    regs[addr + 1] = value & 0xFFFF


def string_regs(regs, pv_w, voltage):
    v = int(round(voltage * 10))
    i = int(round(pv_w / 2.0 / max(voltage, 1.0) * 100))
    for addr in (32016, 32018):
        regs[addr] = v
        regs[addr + 1] = i


def output_regs(regs, pv_w):
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


def battery_regs(regs, batt_w, soc, charge_kwh100, discharge_kwh100, charge_day_kwh100, discharge_day_kwh100):
    put_i32(regs, 37001, batt_w)
    regs[37003] = 0
    regs[37004] = int(round(soc * 10))
    regs[37760] = int(round(soc * 10))
    for addr, value in ((37780, charge_kwh100), (37782, discharge_kwh100),
                        (37784, charge_day_kwh100), (37786, discharge_day_kwh100)):
        put_i32(regs, addr, value)


def meter_regs(regs, grid_w, export_kwh, import_kwh):
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


def diag_regs(regs):
    """modbus-cache-style diagnostics block: magic, device up, cache age, uptime."""
    for i, w in enumerate((0xCAFE, 1, 7, 4242)):
        regs[65000 + i] = w
