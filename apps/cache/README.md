# modbus-cache

> **Experimental — work in progress.** Verified only against simulated
> data (the fake inverter, fuzzing and regression/stress suites), not
> against real hardware.

A dependency-free (Python stdlib only) **Modbus TCP caching proxy** for
devices that accept only a single client — e.g. a Huawei SUN2000 inverter
and its SDongle/EMMA radio allow one Modbus TCP connection, so the
[modbus-scraper](../scraper/README.md) cannot share them with anything
else. Point the scraper (or any other Modbus client) at the proxy instead
of the inverter.

The full reference — every knob with its flag, env twin and default, the
signals, the ACLs, the auth schemes, the persistence, the metrics and the
audit trail — is the daemon's `--help` and the man page
(`modbus-cache --man`).

## Usage

```bash
python3 apps/cache/bin/modbus-cache.py --upstream 192.168.1.100:5502
python3 apps/scraper/bin/modbus-scraper.py --upstream :15502
```

- the proxy binds `127.0.0.1:15502` by default; `--listen 0.0.0.0:15502`
  serves the LAN;
- `--dry-run` validates the configuration and the register map without
  binding the port or contacting the inverter (exit `0` = valid, `1` =
  invalid, `2` = misuse);
- settings resolve flag > env > config script (`--config`, the set
  grammar) > built-in defaults;
- live control rides the unix control socket — `modbus-cache-cli` speaks
  one-shot words, piped batches or the console (`show cache`, `set
  modbus interval 5`, `request flush cache`, …);
- `SIGHUP` reloads the configuration without dropping client
  connections; `SIGUSR1` cleans the cache.

## Security

- Modbus TCP has no auth, no encryption and no access control — the proxy
  binds loopback by default and the write path defaults fully closed;
- writes are gated four times (the frame parse gate, `--allow-write`, the
  client on the write ACL, every touched register inside the
  allow-list) — enabling `--allow-write` alone still refuses every write;
- the six secret knobs never render back; pass each as flag, env or
  `file:<path>` (the shipped way);
- the control wire is the family's signed JSON lines (a TCP control port
  refuses to start without the admin token, F5; the read-only ops token
  scopes a session to the `show`/`flush` verbs);
- every command, auth failure and forwarded write lands in the
  hash-chained audit trail (`--audit-log`); `--audit-forward` mirrors
  every line off-box (F10).

The full story is [docs/SECURITY.md](../../docs/SECURITY.md).

## License

The proxy (source, Nix packaging, service module) is licensed under the
**BSD 3-Clause License** — see the repo-root `LICENSE` file.
