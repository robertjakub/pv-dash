{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.dashboard;

  # the service contract: `settings` carries the daemon's env twins verbatim
  # (the bare upper-snake names — the generated docker/env/dashboard.env.example
  # documents the key list); the module inspects three of them for the
  # sandbox's write paths and the control socket, everything else renders
  # untouched
  listen = cfg.settings.LISTEN or "127.0.0.1:8080";
  listenParts = lib.splitString ":" listen;
  listenHost = lib.concatStringsSep ":" (lib.init listenParts);
  listenPort = lib.toInt (lib.last listenParts);
  ctl = cfg.settings.CTL or null;
  auditFile = cfg.settings.AUDIT_LOG or null;
  dumpFile = cfg.settings.DUMP_PATH or null;

  # the dirs the service may write: the audit trail and the state dump, read
  # back out of the two path knobs in settings
  rwPaths = lib.filter (p: p != null) [
    (if auditFile != null && auditFile != "-" then dirOf auditFile else null)
    (if dumpFile != null && dumpFile != "" then dirOf dumpFile else null)
  ];

  # the secret env names may never enter `settings`: the env file renders
  # into the world-readable nix store — the secrets ride the <secret>File
  # credential options instead
  secretEnvNames = [
    "CONTROL_TOKEN"
    "CONTROL_OPS_TOKEN"
    "METRICS_TOKEN"
    "AUTH_TOKEN"
    "MODBUS_AUTH_KEY"
    "MODBUS_UPSTREAM_AUTH_KEY"
    "DUMP_KEY"
  ];

  # the <secret>File credentials: mounted verbatim via LoadCredential, the
  # env file carries the file: pointer — the value never enters the store
  credentials = with cfg;
    lib.optionals (controlTokenFile != null) [ { env = "CONTROL_TOKEN"; name = "control-token"; path = controlTokenFile; } ]
    ++ lib.optionals (controlOpsTokenFile != null) [ { env = "CONTROL_OPS_TOKEN"; name = "control-ops-token"; path = controlOpsTokenFile; } ]
    ++ lib.optionals (metricsTokenFile != null) [ { env = "METRICS_TOKEN"; name = "metrics-token"; path = metricsTokenFile; } ]
    ++ lib.optionals (authTokenFile != null) [ { env = "AUTH_TOKEN"; name = "auth-token"; path = authTokenFile; } ]
    ++ lib.optionals (dumpKeyFile != null) [ { env = "DUMP_KEY"; name = "dump-key"; path = dumpKeyFile; } ];

  # the front-end config: rendered from solarConfig unless settings carries
  # its own CONFIG_JS (the store copy is fine — the front-end config is
  # public; it is served to every browser)
  configJs = pkgs.writeText "dashboard-config.js" "const SOLAR_CONFIG = ${builtins.toJSON cfg.solarConfig};";
  configJsLine = lib.optionals (!(cfg.settings ? "CONFIG_JS")) [ "CONFIG_JS=${configJs}" ];

  # the env file: every settings entry verbatim (the daemon's env layer
  # parses them: flag > env > config script > default) + the generated
  # config.js + the credential pointers — the daemon's file: reference
  # loader reads those at start
  envFile = pkgs.writeText "dashboard.env" (lib.concatStringsSep "\n"
    (lib.mapAttrsToList (name: value: "${name}=${value}") cfg.settings
      ++ configJsLine
      ++ map (c: "${c.env}=file:/run/credentials/dashboard/${c.name}") credentials)
    + "\n");

  # the eval-time gates: no secret in settings, the keys are env names, the
  # values are single lines, no credential source inside the store
  secretInSettings = lib.filter (n: lib.elem n secretEnvNames) (lib.attrNames cfg.settings);
  badKeys = lib.filter (k: builtins.match "[A-Za-z_][A-Za-z0-9_]*" k == null) (lib.attrNames cfg.settings);
  badValues = lib.filter (v: lib.hasInfix "\n" v || lib.hasInfix "\r" v) (lib.attrValues cfg.settings);
  storeCreds = lib.filter (c: lib.hasPrefix "/nix/store/" c.path) credentials;

  removedOpt = name: file: lib.mkRemovedOptionModule [ "services" "dashboard" name ]
    "secrets may not be rendered into the world-readable nix store — use services.dashboard.${file} (an absolute path outside the store, mounted via systemd LoadCredential).";

  # the <secret>File shape: an absolute path string OUTSIDE the store, mounted
  # via LoadCredential — a relative path literal would be copied into the
  # world-readable store at eval, and a store path points at one already;
  # both refuse
  mkFileOption = description: lib.mkOption {
    type = lib.types.nullOr lib.types.str;
    default = null;
    description = ''
      ${description} The path is an absolute string outside the nix store
      (`/etc/...`, or a sops-nix/agenix render under `/run`) — a store path
      is refused: the store is world-readable, and secrets never land
      there. Mounted via systemd LoadCredential; the daemon reads it as
      `file:/run/credentials/dashboard/<name>`.
    '';
  };
in
{
  imports = [
    (removedOpt "authToken" "authTokenFile")
    (removedOpt "controlToken" "controlTokenFile")
    (removedOpt "controlOpsToken" "controlOpsTokenFile")
    (removedOpt "metricsToken" "metricsTokenFile")
    (removedOpt "dumpKey" "dumpKeyFile")
    (lib.mkRemovedOptionModule [ "services" "dashboard" "configFile" ]
      "the explicit config.js moved into solarConfig — set solarConfig to the SOLAR_CONFIG attrset, or settings.CONFIG_JS to a config.js path.")
  ];

  options.services.dashboard = {
    enable = lib.mkEnableOption "the PV dashboard static server with Prometheus proxy";

    package = lib.mkOption {
      type = lib.types.package;
      defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/dashboard/package.nix { }";
      description = "The dashboard package to run.";
    };

    user = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The account the daemon runs as. null (the default) keeps the systemd
        DynamicUser; a name switches the unit to a static account — and the
        module creates it (a system user, no login) unless the host already
        defines the same users.users entry. The family's shared identity is
        `pvsuite`: one owner across the three daemons for the state dumps
        and the control sockets.
      '';
    };

    group = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The account's group; null = the user's own (the auto-created
        account's primary group of the same name). Refused without user —
        a group alone would run the daemon as root.
      '';
    };

    settings = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = { };
      description = ''
        The daemon's environment: every entry renders verbatim as
        `NAME=value` into the service's systemd EnvironmentFile. The keys
        are the bare env twins the daemon resolves (LISTEN, PROM_URL,
        MAX_CLIENTS, ... — the generated docker/env/dashboard.env.example
        documents the key list), the values are strings the daemon's own
        conv parses ("true"/"false", "10.0"); an absent key leaves the
        daemon default. Nothing is mapped, converted or validated against
        the knob registry — except the secret env names, which are refused
        here: the env file lives in the world-readable store, and the
        secrets ride the <secret>File credential options only. (The
        front-end config is NOT this option — that is solarConfig now.)
      '';
    };

    solarConfig = lib.mkOption {
      type = lib.types.attrs;
      default = {
        prometheusUrl = "/prom";
        metrics = {
          pv = "huawei_pv_generation_watts{job=\"sun2000\"}";
          gridExport = "huawei_grid_export_watts{job=\"sun2000\"}";
          gridImport = "huawei_grid_import_watts{job=\"sun2000\"}";
          load = "huawei_home_consumption_watts{job=\"sun2000\"}";
        };
        scrapeSec = 10;
        smoothMin = 30;
        refreshSec = 30;
        defaultLang = "en";
        enableAllTime = false;
      };
      description = ''
        SOLAR_CONFIG contents for the generated config.js (the module
        renders it into the store and points CONFIG_JS at it). Label
        matchers (tags) are allowed in metric selectors. A settings
        CONFIG_JS entry (a path) takes precedence over the render.
      '';
    };

    staticDir = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Override the packaged static/ directory (e.g. custom index.html).
        null = the package's own assets (share/static) — the
        Exec pins the dir explicitly either way.
      '';
    };

    controlTokenFile = mkFileOption "The control token from a file (the first line is the token) — the hardened way to pass the secret over TCP control.";
    controlOpsTokenFile = mkFileOption "The read-only ops control token from a file (the first line is the token). Needs controlTokenFile.";
    metricsTokenFile = mkFileOption "The /metrics bearer token from a file (the first line is the token) — mandatory when settings.METRICS_SERVER is on.";
    authTokenFile = mkFileOption "The page's bearer token from a file (the first line is the token) — mandatory when the listen address is beyond the loopback (F21).";
    dumpKeyFile = mkFileOption "The key that seals the state dumps and the reload's state file. Needs settings.DUMP_PATH.";

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listen port in the firewall (only needed for direct LAN access).";
    };
  };

  config = lib.mkIf cfg.enable {
    warnings =
      lib.optionals (ctl != null && lib.hasPrefix "/tmp/" ctl) [
        "services.dashboard: the control socket is under /tmp, which the service's PrivateTmp makes private — the CLI outside cannot reach it; set settings.CTL to a path under /run/dashboard/ instead."
      ]
      ++ lib.optionals (cfg.openFirewall && (listenHost == "127.0.0.1" || listenHost == "localhost")) [
        "services.dashboard: openFirewall is set but the server binds to ${listenHost} — the firewall hole is unreachable; set settings.LISTEN to 0.0.0.0:PORT (or the external IP) for direct LAN access."
      ]
      ++ lib.optionals (cfg.user == "root") [
        "services.dashboard: user is root — the sandbox is built for a service account (the dynamic user, or pvsuite); root under the empty CapabilityBoundingSet is still root."
      ];

    assertions = [
      {
        assertion = secretInSettings == [ ];
        message = "services.dashboard: the settings keys ${lib.concatStringsSep ", " secretInSettings} are secrets — the env file renders into the world-readable nix store; use the <secret>File credential options instead.";
      }
      {
        assertion = badKeys == [ ];
        message = "services.dashboard: the settings keys ${lib.concatStringsSep ", " badKeys} are not env names — the keys are the daemon's bare upper-snake env twins (NAME=value; docker/env/dashboard.env.example is the list), and the front-end config is solarConfig now.";
      }
      {
        assertion = badValues == [ ];
        message = "services.dashboard: the settings values must be single lines (no newline, no carriage return) — the env file renders them verbatim.";
      }
      {
        assertion = storeCreds == [ ];
        message = "services.dashboard: the credential source for ${lib.concatStringsSep ", " (map (c: c.name) storeCreds)} is inside the nix store — a store file is world-readable, and secrets never land there; use an absolute path outside the store (/etc/..., or a sops-nix/agenix render under /run).";
      }
      {
        assertion = cfg.group == null || cfg.user != null;
        message = "services.dashboard: group is set without user — a group alone runs the daemon as root; set user (the family's shared identity is \"pvsuite\") or drop group.";
      }
    ];

    # the static account: created when the operator names one (a system
    # user/group, no login) — an existing users.users/users.groups entry of
    # the same name merges, every attribute rides mkDefault
    users.users = lib.optionalAttrs (cfg.user != null) {
      ${cfg.user} = {
        isSystemUser = lib.mkDefault true;
        group = lib.mkDefault (if cfg.group != null then cfg.group else cfg.user);
      };
    };
    users.groups = lib.optionalAttrs (cfg.user != null) {
      ${if cfg.group != null then cfg.group else cfg.user} = { };
    };

    # the ctl client on the host's PATH: the control surface is spoken
    # through dashboard-cli, and the man pages ride the package
    environment.systemPackages = [ cfg.package ];

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ listenPort ];

    systemd.services.dashboard = {
      description = "PV dashboard server (static + Prometheus proxy)";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      restartIfChanged = true;

      serviceConfig = {
        # everything rides the EnvironmentFile: flag > env > config script
        # > default — the env file occupies the env slot; the static dir is
        # the one flag (a dedicated option, the package's own assets by
        # default)
        ExecStart = "${
          lib.getExe cfg.package
        } --static-dir ${
          if cfg.staticDir != null then toString cfg.staticDir else "${cfg.package}/share/static"
        }";
        ExecReload = "${pkgs.util-linux}/bin/kill -HUP $MAINPID";
        EnvironmentFile = [ "${envFile}" ];
        Restart = "on-failure";
        RestartSec = 3;
        UMask = "0077";
        # the sandbox pass (verified with systemd-analyze security in the
        # flake's hardening check): the whole filesystem read-only, no
        # /home, no /tmp sharing, no device nodes, no kernel interfaces, no
        # namespace/clock/hostname mutation, no privileges, no
        # writable+executable memory, only the AF_UNIX + INET* socket
        # families and the @system-service calls.
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectKernelLogs = true;
        ProtectControlGroups = true;
        ProtectClock = true;
        ProtectHostname = true;
        ProtectProc = "invisible";
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        CapabilityBoundingSet = "";
        # AF_UNIX: the default control target is a unix socket — without it
        # the socket() call fails and the control server silently never binds
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
        SystemCallArchitectures = "native";
        SystemCallFilter = [ "@system-service" ];
        # the account: the DynamicUser unless the operator names one —
        # user = "pvsuite" is the family's shared static identity (the
        # module creates it); Group rides the user's own when unset
      } // (if cfg.user == null then { DynamicUser = true; } else { User = cfg.user; })
      // lib.optionalAttrs (cfg.group != null) { Group = cfg.group; }
      // lib.optionalAttrs (rwPaths != [ ]) {
        ReadWritePaths = rwPaths;
      } // lib.optionalAttrs (credentials != [ ]) {
        LoadCredential = map (c: "${c.name}:${c.path}") credentials;
      } // lib.optionalAttrs (ctl != null
          && lib.hasPrefix "/run/dashboard/" ctl) {
        # the control socket's directory, owned by the service user (the
        # dynamic user, or the named account)
        RuntimeDirectory = "dashboard";
        RuntimeDirectoryMode = "0755";
      };
    };
  };
}
