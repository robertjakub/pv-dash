# Solar Energy Flow dashboard

> **Experimental — work in progress.**

A single-page dashboard for home PV monitoring, fed by Prometheus. Part
of the **pv-suite** family — the scraper, cache proxy, fake inverter and
packaging overview live in the [suite root](../../README.md). The
bundled stdlib-only server serves the page and proxies `/prom/*` to your
Prometheus, so the browser never talks to Prometheus directly.

The full reference — the `config.js` keys, the URL params, the reverse
proxy recipes, the metrics source, the control wire and every knob — is
[the manual](../../extras/manuals/dashboard.md) (generated from the
registry).

## Usage

```bash
python3 bin/dashboard.py                          # upstream http://localhost:9090
python3 bin/dashboard.py --listen 127.0.0.1:8080 --upstream http://192.168.1.50:9090
PROM_URL=http://pi:9090 python3 bin/dashboard.py  # via env
# open http://localhost:8080
```

- the server binds `127.0.0.1:8080` by default; `--listen 0.0.0.0:8080`
  serves the LAN — beyond loopback `--auth-token` is mandatory (a
  token-less non-loopback bind refuses to start); the browser opens
  `http://host:8080/?auth=<token>` once — the exchange sets an HttpOnly
  session cookie;
- page settings live in `config.js` (the metric selectors, the battery
  switch, the scrape interval — the shipped example is
  `examples/config.js`, served at `/config.js`);
- the Prometheus job name must be `sun2000` (the dashboard filters on
  it) — the [modbus-scraper](../scraper/README.md) serves exactly the
  metrics the page expects;
- live control rides the unix control socket — `dashboard-cli` speaks
  one-shot words, piped batches or the console; `SIGHUP` re-reads
  `dashboard.conf`.

## Security

- loopback is open, the LAN needs the bearer token (F21 — a token-less
  non-loopback bind refuses to start), and TLS terminates at an
  authenticating reverse proxy;
- the tokens, the auth and the caps never render back; a token value
  takes a `file:<path>` reference;
- the control wire is the family's signed JSON lines (a TCP control port
  refuses to start without the admin token, F5) and every command lands
  in the hash-chained audit trail (`--audit-log`, the DSH trail).

The full story is [docs/SECURITY.md](../../docs/SECURITY.md).

## License

The dashboard code (server, page, Nix packaging) is licensed under the
**BSD 3-Clause License** — see the `LICENSE` file. The bundled chart
library `static/vendor/echarts.min.js` is
[Apache ECharts](https://echarts.apache.org/) 5.5.1, licensed under the
**Apache License 2.0** (© the Apache Software Foundation); the license
notice is preserved in the vendored file.
