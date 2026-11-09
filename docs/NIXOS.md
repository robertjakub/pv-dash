# Nix / NixOS — the flake, the packages, the service modules

One flake at the repo root packages the whole suite: four packages, an
overlay, and a **NixOS service module for every daemon** (the fake inverter
is the exception — it is a test tool, not a deployment). This file is the
one Nix reference; the per-tool READMEs link here instead of carrying their
own Nix sections.

- **Packages:** `dashboard` (the flake's `default`), `modbus-scraper`,
  `modbus-cache`, `modbus-fake-inverter`
- **Overlay:** `overlays.default` (exposes `dashboard`; the other packages
  come from the same callPackage shape)
- **Modules:** `nixosModules.modbus-scraper`, `nixosModules.modbus-cache`,
  `nixosModules.dashboard` (`default` = dashboard)
- **Checks:** `nix flake check` runs the **hardening VM test**
  (`tests/hardening.nix`) — a NixOS VM boots the scraper's and cache's
  units and asserts every sandbox knob with `systemd-analyze security`

## The flake

```bash
nix run .#dashboard              # the dashboard (bin/dashboard.py + static page)
nix run .#modbus-scraper -- --upstream <inverter-lan-ip>:502 --listen 0.0.0.0:9350
nix run .#modbus-cache -- --upstream 192.168.1.100:5502
nix run .#modbus-fake-inverter -- --static --control-port 15599
nix build .#modbus-scraper       # or any other package
```

Each package installs the daemon, its `*-ctl` / `*-cli` clients, the
generated man pages under `share/man/man1/` and — where the tool has them —
the bundled profile, the `examples/` samples and the `schema/` JSON Schemas.

## How the service modules work

All three modules behave the same way:

- **The config renders into the store.** The module writes the tool's config
  as a **set-grammar script** (every line a `set <name> <value>` — the ini
  format is gone) into the Nix store and runs the service with `--config`.
  Flags and env still win over the file.
- **`nixos-rebuild switch` applies changes with `systemctl reload`**
  (SIGHUP) — the units are `reloadIfChanged`, never
  `restartIfChanged`. What the reload picks up and what needs a manual
  `systemctl restart` is the tool's own SIGHUP surface (each README's
  *Runtime control* section has the row); roughly: poll plans, caps, ACLs,
  profiles and the upstream apply live, the **listen binds and log level
  need a restart**.
- **Secrets ride `LoadCredential`.** Every `*TokenFile` option mounts the
  file via systemd `LoadCredential` and renders the daemon a
  `file:/run/credentials/<tool>/<name>` reference — the value never lands
  in the store. The inline `*Token` options DO render into the
  **world-readable store config** (the module attaches a warning); prefer
  the file options. The daemons refuse group/world-readable token files
  (the audit's F12).
- **The audit trail goes to stdout** (`auditLog` default = `-`): journald
  captures it — a hardened service cannot write the XDG state home. Set
  `auditLog` to a path (the module opens its `ReadWritePaths`) to keep a
  file.
- **The control socket needs a path, not `/tmp`.** The services run with
  `PrivateTmp` — a `/tmp` socket is unreachable from outside (the module
  warns); give `controlPort` a path under `/run/<tool>/` and the module
  creates the `RuntimeDirectory` for it. A TCP `controlPort` binds
  127.0.0.1 and **refuses to start without a token** (F5).
- **Hardened units, verified.** `DynamicUser`, `UMask 0077`,
  `ProtectSystem=strict`, `PrivateDevices`, `PrivateTmp`, `ProtectHome`,
  the kernel/control-group/clock/hostname protections,
  `MemoryDenyWriteExecute`, `CapabilityBoundingSet=""`,
  `RestrictAddressFamilies = AF_UNIX + INET*` (AF_UNIX is what the default
  control socket speaks), `SystemCallFilter = @system-service` — the flake
  check boots the units in a VM and scores them.
- **`openFirewall`** opens the listen port; with the default loopback bind
  the module warns that the hole is unreachable.

`scripts/check_options.py` (the one-knob-one-source gate) keeps every
module option name aligned with the knob registry — the spellings that
differ from the flags are fixed renames (`unitId`/`listenHost` on the
cache, `modbusUnit`/`listenHost` on the scraper). Unset options keep the
daemon defaults.

## services.modbus-scraper

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-scraper ];

services.modbus-scraper = {
  enable = true;
  upstream = "192.168.1.100:502";  # the inverter's LAN IP (:PORT)
  listenHost = "0.0.0.0";          # only if Prometheus runs on another host
  listenPort = 9350;
};
```

| Option | Meaning |
|---|---|
| `upstream` | the inverter's Modbus TCP endpoint `HOST:PORT` (`:PORT` = loopback) |
| `modbusUnit` / `modbusOffset` | unit id (1) / register-address offset (0; −1 for 0-based gateways) |
| `auth` / `authKey` | the suite scheme + shared key toward the inverter (null = no auth) |
| `profile` | device-profile JSON path (null = the bundled `sun2000`) |
| `metricsSpec` / `metricPrefix` | the metrics spec JSON / the profile- and compute-fed metric prefix (`huawei`) |
| `maxKwp` / `maxGridKw` | the sanity caps in kW (6 / 12) |
| `gridPositiveImport` | the grid sign convention |
| `timeout` / `interval` | Modbus timeout (3 s) / poll interval (10 s) |
| `listenHost` / `listenPort` | the exporter bind (127.0.0.1 / 9350) |
| `authToken` / `authTokenFile` | the `/metrics` bearer token — prefer the file (LoadCredential) |
| `metricsAcl` / `metricsAclFile` | who may connect to `/metrics` (the ip-prefix grammar) |
| `maxClients` / `clientTimeout` / `maxConnPerIp` | the HTTP caps |
| `controlPort` | the control server target (unix path under `/run/modbus-scraper/`, or a TCP port) |
| `controlToken` / `controlTokenFile` (+ `controlOpsToken`/`controlOpsTokenFile`, `controlOpsVerbs`, `controlTrustUids`, `controlSocketGroup`) | the control plane's secrets and posture |
| `dumpPath` / `dumpKey` / `restoreOnStart` | the sealed state dump |
| `auditLog` (+ `auditMaxMb`, `auditFiles`, `noAuditLog`) | the SCR audit trail (default: stdout) |
| `logLevel` / `logAccess` / `localTime` | the log surface |
| `openFirewall` | open `listenPort` |

## services.modbus-cache

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-cache ];

services.modbus-cache = {
  enable = true;
  upstream = "192.168.1.100:5502";  # the inverter's LAN IP (:PORT)
  listenHost = "0.0.0.0";           # only when Modbus clients live on other hosts
  openFirewall = true;              # together with a non-loopback listenHost
};
services.modbus-scraper = {
  enable = true;
  upstream = "127.0.0.1:15502";     # the proxy
};
```

| Option | Meaning |
|---|---|
| `upstream` / `unitId` / `timeout` | the inverter endpoint / unit id (1) / timeout (3 s) |
| `auth` / `authKey` | the suite scheme + key the cache's **own clients** must speak |
| `authUpstream` / `authUpstreamKey` | the scheme + key **toward the inverter** (`suite` or `waveshare`) |
| `profile` / `selection` | the device-profile path (null = bundled `sun2000`) / what is fetched: `all`, `none`, a name list (rendered to the selection JSON), or a JSON path |
| `interval` / `readDelay` / `mergeGap` / `cacheTtl` | the poll plan (10 s / 0.05 s / 8 / 3× interval) |
| `listenHost` / `listenPort` | the proxy bind (127.0.0.1 / 15502) |
| `allowWrite` | forward writes — the write gates below still apply (default false) |
| `writeRegisters` | the register allow-list: ranges, `any`, `none`, `profile`, `file:<path>` |
| `connectAcl` / `writeAcl` | the Modbus ACLs (null = `any` / `none`) |
| `metricsServer` / `metricsListen` / `metricsToken` / `metricsTokenFile` / `metricsAcl` | the cache's own `/metrics` endpoint (bind 127.0.0.1:9351; token mandatory when on) |
| `metricsMaxClients` / `metricsClientTimeout` / `metricsMaxConnPerIp` | the metrics caps |
| `maxClients` / `clientTimeout` / `maxConnPerIp` | the Modbus caps |
| `controlPort` | the control server target (unix path under `/run/modbus-cache/`, or a TCP port) |
| `controlToken` / `controlTokenFile` (+ `controlOpsToken`/`controlOpsTokenFile`, `controlOpsVerbs`, `controlTrustUids`, `controlSocketGroup`) | the control plane's secrets and posture |
| `dumpPath` / `dumpWithCache` / `dumpKey` / `dumpInterval` / `restoreOnStart` | the sealed state dump |
| `requestsAudit` | the per-client REQUESTS tally period (300 s) |
| `auditLog` (+ `auditMaxMb`, `auditDaily`, `auditFiles`, `noAuditLog`) | the CACHE audit trail (default: stdout) |
| `logLevel` / `logAccess` / `localTime` | the log surface |
| `openFirewall` | open `listenPort` |

## services.dashboard

```nix
# your flake.nix
{
  inputs.dashboard.url = "path:./pv-suite";   # or a git URL
  outputs = { self, nixpkgs, dashboard }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      modules = [
        dashboard.nixosModules.default
        { services.dashboard = {
            enable = true;
            port = 8080;
            prometheusUrl = "http://localhost:9090";
            # settings → generated config.js; or configFile = ./config.js;
          }; }
      ];
    };
  };
}
```

| Option | Meaning |
|---|---|
| `host` / `port` | the server bind (127.0.0.1 / 8080) |
| `prometheusUrl` / `promPrefix` | the upstream Prometheus (http://localhost:9090) / the proxy path (`/prom`) |
| `staticDir` | override the packaged `static/` |
| `settings` / `configFile` | the SOLAR_CONFIG attrset rendered to the served `config.js` / an explicit config.js instead |
| `authToken` / `authTokenFile` | the page's bearer token — mandatory beyond loopback (F21) |
| `metricsServer` / `metricsListen` / `metricsToken` / `metricsTokenFile` / `metricsAcl` / `metricsMaxClients` / `metricsClientTimeout` / `metricsMaxConnPerIp` | the dashboard's own `/metrics` endpoint (bind 127.0.0.1:9353) |
| `maxClients` / `clientTimeout` / `maxConnPerIp` | the HTTP caps |
| `controlPort` | the control server target (unix path under `/run/dashboard/`, or a TCP port) |
| `controlToken` / `controlTokenFile` (+ `controlOpsToken`/`controlOpsTokenFile`, `controlOpsVerbs`, `controlTrustUids`, `controlSocketGroup`) | the control plane's secrets and posture |
| `dumpPath` / `dumpKey` / `restoreOnStart` | the sealed state dump |
| `auditLog` (+ `auditMaxMb`, `auditFiles`, `noAuditLog`) | the DSH audit trail (default: stdout) |
| `logLevel` / `logQueries` / `logAccess` / `localTime` | the log surface |
| `openFirewall` | open `port` |

Put a reverse proxy in front for LAN/HTTPS (see the dashboard README).

## The fake inverter — no service module

`modbus-fake-inverter` is a package only (`nix run .#modbus-fake-inverter`),
with the three binaries and their man pages. There is no
`services.modbus-fake-inverter` — the fake is a test/demo tool, not a
daemon you deploy (the audit's F11 posture).
