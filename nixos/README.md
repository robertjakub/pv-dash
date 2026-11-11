# Nix / NixOS — the flake, the packages, the service modules

One flake at the repo root packages the whole suite: four packages, an
overlay, and a **NixOS service module for every daemon** (the fake inverter
is the exception — it is a test tool, not a deployment). This README is the
one Nix reference and lives beside the tree it describes — `pkgs/<tool>/`
the four packages, `modules/<tool>.nix` the three service modules. The
per-tool READMEs carry no Nix sections.

- **Packages:** `dashboard` (the flake's `default`), `modbus-scraper`,
  `modbus-cache`, `modbus-fake-inverter`
- **Overlay:** `overlays.default` (= `overlays.pv-suite`) — all four
  packages onto `final`
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
the bundled profile, the `examples/` samples and the JSON Schemas (the
shared one from `shared/schema/`, the tool-local ones from `schema/`).

## How the service modules work

All three modules behave the same way:

- **One `settings` option renders the unit's environment.** A freeform
  attrset: every entry goes verbatim as `NAME=value` into a store file wired
  as the service's systemd `EnvironmentFile`. The keys are the daemon's bare
  env twins (UPSTREAM, LISTEN, INTERVAL, DUMP_PATH, ... — the generated
  `docker/env/<tool>.env.example` files document the key list; lift lines
  straight from one), the values are strings the daemon's own conv parses
  (`"true"`/`"false"`, `"10.0"`); an absent key leaves the daemon default.
  Nothing is mapped or converted — the module reads no registry at eval
  time, which is what keeps it self-contained. The layering is unchanged:
  flag > env > the bundled conf > built-in default — the env file occupies
  the env slot, and a knob the daemon keeps in its own config file can
  still beat it per knob.
- **A settings edit restarts, not reloads.** EnvironmentFile is read at
  start only, so the units are `restartIfChanged` (the config-script era's
  `reloadIfChanged` is gone). `ExecReload` (SIGHUP) stays: a manual
  `systemctl reload` still re-reads the daemon's own config file and
  re-arms the ACLs and the audit forward, and the state dump + restore
  carries the live `set` overrides across the restart.
- **The secrets ride credentials — and never the store.** Every secret has
  ONE dedicated option, the `<secret>File` form: an absolute path string
  outside the nix store (`/etc/...`, or a sops-nix/agenix render under
  `/run`), mounted via systemd `LoadCredential` and handed to the daemon as
  `file:/run/credentials/<tool>/<name>`. The inline value forms are gone —
  they are removed-option tombstones the eval REFUSES ("secrets may not be
  rendered into the world-readable nix store"), and a `*File` pointing
  into the store is an error too. The module also refuses a secret env
  name inside `settings` (the env file is world-readable).
- **The audit trail goes to stdout** (settings `AUDIT_LOG = "-"` — the
  default): journald captures it — a hardened service cannot write the XDG
  state home. Set `settings.AUDIT_LOG` to a path and the module opens its
  `ReadWritePaths` (the state dump's `DUMP_PATH` gets the same treatment)
  to keep a file. `settings.AUDIT_FORWARD` mirrors every audit line onward
  (the F10 external copy): `"syslog"`, `"syslog:/path"`,
  `"udp://host[:514]"`, `"tcp://host[:514]"` (the envelope:
  `AUDIT_FORWARD_FORMAT` = `"rfc5424"`/`"cef"`).
- **The control socket needs a path, not `/tmp`.** The services run with
  `PrivateTmp` — a `/tmp` socket is unreachable from outside (the module
  warns); give `settings.CTL` a path under `/run/<tool>/` and the module
  creates the `RuntimeDirectory` for it. A TCP `CTL` binds 127.0.0.1 and
  **refuses to start without a token** (F5).
- **Hardened units, verified.** `DynamicUser`, `UMask 0077`,
  `ProtectSystem=strict`, `PrivateDevices`, `PrivateTmp`, `ProtectHome`,
  the kernel/control-group/clock/hostname protections,
  `MemoryDenyWriteExecute`, `CapabilityBoundingSet=""`,
  `RestrictAddressFamilies = AF_UNIX + INET*` (AF_UNIX is what the default
  control socket speaks), `SystemCallFilter = @system-service` — the flake
  check boots the units in a VM and scores them.
- **`openFirewall`** opens the port `settings.LISTEN` carries (the tool's
  default port when unset); with a loopback bind the module warns that the
  hole is unreachable.

`scripts/check_options.py` (the one-knob-one-source gate) keeps the modules
structural: exactly `enable`/`package`/`openFirewall`/`settings`, every
registry secret row's `*File` credential option (the dashboard adds
`solarConfig`/`staticDir`), and nothing else — a knob option declared by
hand fails the gate.

## services.modbus-scraper

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-scraper ];

services.modbus-scraper = {
  enable = true;
  settings = {
    UPSTREAM = "192.168.1.100:502";  # the inverter's LAN IP (:PORT)
    LISTEN = "0.0.0.0:9350";         # only if Prometheus runs on another host
  };
  authTokenFile = "/etc/secrets/metrics.token";
};
```

| Option | Meaning |
|---|---|
| `settings` | the daemon's environment, verbatim `NAME=value` — every knob's env twin (UPSTREAM, LISTEN, MODBUS_AUTH, PROFILE, METRICS_SPEC, METRIC_PREFIX, MAX_KWP, DUMP_PATH, CTL, AUDIT_LOG, LOG_LEVEL, ...; `docker/env/scraper.env.example` is the key list) |
| `authKeyFile` / `authTokenFile` | the suite-handshake key / the `/metrics` bearer token, from a file outside the store (LoadCredential) |
| `controlTokenFile` / `controlOpsTokenFile` | the control plane's admin / read-only ops tokens, from a file |
| `dumpKeyFile` | the seal key for the state dump (needs settings `DUMP_PATH`) |
| `openFirewall` | open the `LISTEN` port |

The packages also ship the **alert rules pack** (`extras/alerts/` in the repo —
the F16 closure, the audit vocabulary's detection half, one file per
watched exporter): the scraper's copy sits at
`share/modbus-scraper/alerts.yml`, the cache's at
`share/modbus-cache/alerts.yml`. A Prometheus on the same host points its
`ruleFiles` at the packaged copies and the poll story alerts itself:

```nix
services.prometheus.ruleFiles =
  [ "${inputs.pv-dash.packages.${pkgs.system}.modbus-scraper}/share/modbus-scraper/alerts.yml"
    "${inputs.pv-dash.packages.${pkgs.system}.modbus-cache}/share/modbus-cache/alerts.yml" ];
```

List only the copies of the tools you run — a cache-only install still
carries its half. The cache group (`CachePollDown`, `CacheAgeSpike`,
`CacheWriteRefusalBurst`) stays silent until the cache's own `/metrics`
endpoint is scraped — set `services.modbus-cache.settings.METRICS_SERVER = "true";` and
add its scrape job to arm it. Thresholds assume the default 10 s poll
interval.

## services.modbus-cache

```nix
imports = [ inputs.pv-dash.nixosModules.modbus-cache ];

services.modbus-cache = {
  enable = true;
  settings = {
    UPSTREAM = "192.168.1.100:5502";  # the inverter's LAN IP (:PORT)
    LISTEN = "0.0.0.0:15502";         # only when Modbus clients live on other hosts
  };
  openFirewall = true;                # together with a non-loopback LISTEN
};
services.modbus-scraper = {
  enable = true;
  settings.UPSTREAM = "127.0.0.1:15502";  # the proxy
};
```

| Option | Meaning |
|---|---|
| `settings` | the daemon's environment, verbatim `NAME=value` — every knob's env twin (UPSTREAM, LISTEN, MODBUS_AUTH, MODBUS_UNIT, TIMEOUT, INTERVAL, READ_DELAY, MERGE_GAP, CACHE_TTL, ALLOW_WRITE, WRITE_REGISTERS, CONNECT_ACL, WRITE_ACL, PROFILE, SELECTION, METRICS_SERVER, METRICS_LISTEN, METRICS_ACL, MAX_CLIENTS, CTL, DUMP_PATH, DUMP_WITH_CACHE, DUMP_INTERVAL, RESTORE_ON_START, REQUESTS_AUDIT, AUDIT_LOG, AUDIT_FORWARD, LOG_LEVEL, ...; `docker/env/cache.env.example` is the key list) |
| `authKeyFile` / `authUpstreamKeyFile` | the key the cache's **own clients** prove (needs `MODBUS_AUTH = "suite"`) / the key **toward the inverter** (`suite` or `waveshare`), from a file outside the store (LoadCredential) |
| `controlTokenFile` / `controlOpsTokenFile` | the control plane's admin / read-only ops tokens, from a file |
| `metricsTokenFile` | the cache's own `/metrics` bearer token (mandatory when `settings.METRICS_SERVER = "true"`; bind `METRICS_LISTEN` 127.0.0.1:9351) |
| `dumpKeyFile` | the seal key for the state dump (needs settings `DUMP_PATH`) |
| `openFirewall` | open the `LISTEN` port |

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
            settings = {
              PROM_URL = "http://localhost:9090";
              LOG_QUERIES = "true";
            };
            solarConfig.scrapeSec = 5;    # the SOLAR_CONFIG attrset → the served config.js
          }; }
      ];
    };
  };
}
```

| Option | Meaning |
|---|---|
| `settings` | the daemon's environment, verbatim `NAME=value` — every knob's env twin (LISTEN, PROM_URL, PROM_PREFIX, MAX_CLIENTS, CLIENT_TIMEOUT, MAX_CONN_PER_IP, CTL, AUDIT_LOG, AUDIT_FORWARD, LOG_LEVEL, LOG_ACCESS, LOG_QUERIES, LOCAL_TIME, METRICS_SERVER, METRICS_LISTEN, METRICS_ACL, METRICS_MAX_CLIENTS, DUMP_PATH, RESTORE_ON_START, ...; `docker/env/dashboard.env.example` is the key list) |
| `solarConfig` | the SOLAR_CONFIG attrset rendered to the served `config.js` (a settings `CONFIG_JS` entry — a path — takes precedence) |
| `staticDir` | override the packaged `static/` (the Exec pins the package's own assets by default) |
| `authTokenFile` | the page's bearer token, from a file — mandatory beyond loopback (F21) |
| `metricsTokenFile` | the dashboard's own `/metrics` bearer token (mandatory when `settings.METRICS_SERVER = "true"`; bind `METRICS_LISTEN` 127.0.0.1:9353) |
| `controlTokenFile` / `controlOpsTokenFile` | the control plane's admin / read-only ops tokens, from a file |
| `dumpKeyFile` | the seal key for the state dump (needs settings `DUMP_PATH`) |
| `openFirewall` | open the `LISTEN` port |

Put a reverse proxy in front for LAN/HTTPS (see the dashboard README).

## The fake inverter — no service module

`modbus-fake-inverter` is a package only (`nix run .#modbus-fake-inverter`),
with the three binaries and their man pages. There is no
`services.modbus-fake-inverter` — the fake is a test/demo tool, not a
daemon you deploy (the audit's F11 posture).
