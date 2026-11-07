{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.modbus-scraper;

  # the set-grammar config script (the ini format is gone): every line a
  # `set <name> <value>` — the file pipes through modbus-scraper-ctl unchanged
  setLine = name: value: "set ${name} ${value}";
  configScript = pkgs.writeText "scraper.conf" (lib.concatStringsSep "\n" (lib.flatten [
    "# modbus-scraper configuration — the control grammar: every line a `set <name> <value>`"
    "# rendered by services.modbus-scraper; the flags and the env still win over this file"
    ""
    "# --- the device (upstream inverter) and the register map ---"
    # the register map itself (addresses, types, gains, function codes) comes
    # from the device profile alone — `set profile <file-or-name>` swaps it live
    (setLine "upstream" cfg.upstream)
    (setLine "modbus-unit" (toString cfg.modbusUnit))
    (setLine "modbus-offset" (toString cfg.modbusOffset))
    (lib.optionals (cfg.auth != null) [ (setLine "auth" cfg.auth) ])
    (lib.optionals (cfg.authKey != null) [ (setLine "auth-key" cfg.authKey) ])
    (setLine "timeout" (toString cfg.timeout))
    (setLine "max-kwp" (toString cfg.maxKwp))
    (setLine "max-grid-kw" (toString cfg.maxGridKw))
    (setLine "battery" (lib.boolToString cfg.battery))
    (setLine "grid-positive-import" (lib.boolToString cfg.gridPositiveImport))
    ""
    "# --- what the tool serves and where ---"
    (setLine "listen" "${cfg.listenHost}:${toString cfg.listenPort}")
    (setLine "interval" (toString cfg.interval))
    (setLine "local-time" (lib.boolToString cfg.localTime))
    ""
    "# --- the connection caps ---"
    (setLine "max-clients" (toString cfg.maxClients))
    (setLine "client-timeout" (toString cfg.clientTimeout))
    (setLine "max-conn-per-ip" (toString cfg.maxConnPerIp))
    ""
    "# --- the /metrics bearer token ---"
    (lib.optionals (cfg.authToken != null) [ (setLine "auth-token" cfg.authToken) ])
    (lib.optionals (cfg.authTokenFile != null) [ (setLine "auth-token-file" cfg.authTokenFile) ])
    ""
    "# --- the control plane ---"
    (lib.optionals (cfg.controlPort != null) [ (setLine "control-port" (toString cfg.controlPort)) ])
    (lib.optionals (cfg.controlToken != null) [ (setLine "control-token" cfg.controlToken) ])
    (lib.optionals (cfg.controlTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      (setLine "control-token-file" "/run/credentials/modbus-scraper/control-token")
    ])
    (lib.optionals (cfg.controlOpsToken != null) [ (setLine "control-ops-token" cfg.controlOpsToken) ])
    (lib.optionals (cfg.controlOpsTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      (setLine "control-ops-token-file" "/run/credentials/modbus-scraper/control-ops-token")
    ])
    (lib.optionals (cfg.controlOpsVerbs != null) [ (setLine "control-ops-verbs" cfg.controlOpsVerbs) ])
    (lib.optionals (cfg.controlTrustUids != null) [ (setLine "control-trust-uids" cfg.controlTrustUids) ])
    (lib.optionals (cfg.profile != null) [ (setLine "profile" (toString cfg.profile)) ])
    (lib.optionals (cfg.metricsSpec != null) [ (setLine "metrics-spec" cfg.metricsSpec) ])
    (lib.optionals (cfg.metricPrefix != null) [ (setLine "metric-prefix" cfg.metricPrefix) ])
    ""
    "# --- the state dump (the live overrides' write-behind) ---"
    (lib.optionals (cfg.dumpPath != null) [ (setLine "dump-path" cfg.dumpPath) ])
    (lib.optionals (cfg.dumpPath != null && cfg.dumpKey != null) [ (setLine "dump-key" cfg.dumpKey) ])
    (setLine "restore-on-start" (lib.boolToString cfg.restoreOnStart))
    ""
    "# --- the audit trail ---"
    (lib.optionals (cfg.auditLog != null) [
      (setLine "audit-log" cfg.auditLog)
      (setLine "audit-max-mb" (toString cfg.auditMaxMb))
      (setLine "audit-files" (toString cfg.auditFiles))
    ])
    ""
    "# --- the log surface ---"
    (setLine "log-level" cfg.logLevel)
    (setLine "log-access" (lib.boolToString cfg.logAccess))
  ]));
in
{
  options.services.modbus-scraper = {
    enable = lib.mkEnableOption "the Modbus TCP Prometheus exporter";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The modbus-scraper package to run.";
    };

    upstream = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1:5502";
      description = "The inverter Modbus TCP endpoint HOST:PORT (`:PORT` = 127.0.0.1:PORT) — set HOST to the inverter/dongle's LAN IP.";
    };

    modbusUnit = lib.mkOption {
      type = lib.types.int;
      default = 1;
      description = "Modbus unit id.";
    };

    modbusOffset = lib.mkOption {
      type = lib.types.int;
      default = 0;
      description = "Offset added to register addresses (set -1 for gateways that need 0-based addressing).";
    };

    auth = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "suite" ]);
      default = null;
      description = ''
        The inverter's Modbus auth scheme the session must speak: "suite"
        proves the shared authKey with a crypt handshake right after every
        connect (the peer answers OK, or ERR and the connection fails —
        the poller keeps retrying). null = no auth at all.
      '';
    };

    authKey = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The shared key the suite handshake proves (min 16 characters).
        Needs auth = "suite".
      '';
    };

    battery = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Battery support (experimental, untested against real hardware).";
    };

    maxKwp = lib.mkOption {
      type = lib.types.float;
      default = 6.0;
      description = ''
        Maximum kWp of the PV array (default 6.0). When input power from
        register 32064 exceeds maxKwp * 1000 watts, /metrics returns HTTP
        503 and an error is logged; negative readings are clamped to 0.
        0 disables the check.
      '';
    };

    maxGridKw = lib.mkOption {
      type = lib.types.float;
      default = 12.0;
      description = ''
        Maximum kW the power line can exchange with the grid (default 12.0).
        When |grid power| from register 37113 exceeds maxGridKw * 1000
        watts in either direction, /metrics returns HTTP 503 and an error
        is logged. 0 disables the check.
      '';
    };

    gridPositiveImport = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Grid register is positive when importing from the grid (default: positive = export).";
    };

    timeout = lib.mkOption {
      type = lib.types.float;
      default = 3.0;
      description = "Modbus connect/read timeout in seconds.";
    };

    interval = lib.mkOption {
      type = lib.types.float;
      default = 10.0;
      description = "Seconds between Modbus polls.";
    };

    listenHost = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Exporter bind address (loopback by default — set 0.0.0.0 when Prometheus scrapes from another host).";
    };

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 9350;
      description = "Exporter listen port (Prometheus scrape target).";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listen port in the firewall (needed when Prometheus runs on another host).";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum [ "DEBUG" "INFO" "WARNING" "ERROR" ];
      default = "INFO";
      description = "Log level.";
    };

    localTime = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Log timestamps in the system time zone instead of UTC.";
    };

    logAccess = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Log every HTTP request (Prometheus scrape) at INFO — audit trail for who polled /metrics and when.";
    };

    maxClients = lib.mkOption {
      type = lib.types.int;
      default = 64;
      description = "Maximum concurrent HTTP clients; extras get an immediate 503 (0 = unlimited).";
    };

    clientTimeout = lib.mkOption {
      type = lib.types.float;
      default = 300.0;
      description = "Seconds an idle keep-alive HTTP client is kept before being kicked (0 = off).";
    };

    maxConnPerIp = lib.mkOption {
      type = lib.types.int;
      default = 0;
      description = "Maximum concurrent HTTP connections from one peer IP; extras get an immediate 503 (0 = no per-IP limit).";
    };

    authToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Require `Authorization: Bearer <token>` on every HTTP request (default: no auth).
        Caution: the token is written to the world-readable Nix store as part of the
        rendered config — prefer `authTokenFile` for anything non-trivial.
      '';
    };

    authTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Path to a file with the bearer token (single line, trimmed). Keeps the secret out
        of the Nix store; the file is read at startup and **on every SIGHUP reload**, so a
        token rotates with `systemctl reload` after rewriting the file. The service user
        must be able to read the path (note: `ProtectHome = true` blocks `/root` — put the
        file under `/etc` or use systemd `LoadCredential`).
      '';
    };

    controlPort = lib.mkOption {
      type = lib.types.nullOr (lib.types.either lib.types.int lib.types.str);
      default = null;
      description = ''
        The JSON-lines control server target: a TCP port (bound to
        127.0.0.1) or a unix socket path. The service has PrivateTmp — a
        socket under /tmp is unreachable from outside; use a path under
        /run/modbus-scraper/ (created for the service). The control
        surface speaks the signed wire (the full sha256 HMAC of every
        frame, keyed by the token) and is talked to with
        modbus-scraper-ctl / modbus-scraper-cli. null = the scraper
        default (a /tmp unix socket, private to the service).
      '';
    };

    controlToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Require a token on TCP control connections. WARNING: it is rendered
        into the world-readable config script in the nix store — prefer
        controlTokenFile.
      '';
    };

    controlTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        The control token from a file (the first line is the token),
        mounted via systemd LoadCredential — the hardened way to pass the
        secret. Mutually exclusive with controlToken.
      '';
    };

    controlOpsToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        A second, read-only control token: sessions authenticating with it
        run the show/clear verbs only (no set/unset, no poll now, no
        request reload, no restart, no shutdown) — the ops shift against
        the admin key. Needs controlToken/controlTokenFile. WARNING: it is
        rendered into the world-readable config script in the nix store —
        prefer controlOpsTokenFile.
      '';
    };

    controlOpsTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        The read-only ops token from a file (the first line is the token),
        mounted via systemd LoadCredential. Mutually exclusive with
        controlOpsToken; needs controlToken/controlTokenFile.
      '';
    };

    controlOpsVerbs = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The read-only ops role's RBAC policy: the verbs its sessions may
        run, comma-separated (default: show,clear). Validated against the
        control grammar at start; needs controlOpsToken/controlOpsTokenFile.
      '';
    };

    profile = lib.mkOption {
      type = lib.types.nullOr (lib.types.either lib.types.path lib.types.str);
      default = null;
      description = ''
        The device profile: a path, or a bare name resolved in
        profiles/profiles/ (default: the bundled sun2000 profile).
      '';
    };

    controlTrustUids = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Extra peer uids the unix control socket trusts without the token
        (SO_PEERCRED): a comma-separated uid list — a local systemd unit
        speaks without the secret. Root and the daemon's own user are
        always trusted. null = the defaults only.
      '';
    };

    auditLog = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = "-";
      description = ''
        The SCR audit trail (the control commands, the auth attempts,
        reloads, shutdowns): a file path, or "-" for stdout (default —
        journald captures it; the hardened service cannot write the XDG
        state home). null = the tool's default (the XDG state home).
      '';
    };

    auditMaxMb = lib.mkOption {
      type = lib.types.float;
      default = 10.0;
      description = "Rotate the audit log at this size in MB, keeping auditFiles backups; 0 = off.";
    };

    auditFiles = lib.mkOption {
      type = lib.types.int;
      default = 3;
      description = "Rotated audit backups to keep.";
    };

    noAuditLog = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Disable the SCR audit trail entirely.";
    };

    metricsSpec = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "The metrics spec JSON path, merged in memory over the built-in lib/metrics.json scraper_* block (default: the bundled sectioned metrics.json).";
    };

    metricPrefix = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "The prefix on the profile- and compute-fed metric names (default: huawei).";
    };

    dumpPath = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The state dump file: the live setting overrides (set through the
        control surface) as one JSON, written 0600 with an integrity hash on
        `request dump` and the graceful shutdown, and re-applied on start
        when restoreOnStart is set. null = the dumps are off.
      '';
    };

    restoreOnStart = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Load the state dump when the service starts (needs dumpPath) — the live overrides ride again instead of a cold start.";
    };

    dumpKey = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The key that seals the state dumps and the reload's state file: the
        state rides encrypted (an HMAC-SHA256 counter-mode keystream,
        authenticated — a restore refuses a wrong or missing key, and a
        configured key refuses an unsealed dump). Needs dumpPath. null =
        the dumps stay 0600 plaintext with the integrity hash.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    warnings = lib.optional (cfg.authToken != null && cfg.authTokenFile != null)
      "services.modbus-scraper: both authToken and authTokenFile are set — the inline token wins and the file is ignored."
      ++ lib.optional (cfg.controlToken != null)
      "services.modbus-scraper: controlToken is rendered into the world-readable config script in the nix store — prefer controlTokenFile."
      ++ lib.optional (cfg.controlOpsToken != null)
      "services.modbus-scraper: controlOpsToken is rendered into the world-readable config script in the nix store — prefer controlOpsTokenFile."
      ++ lib.optionals (cfg.controlPort != null
          && lib.isString cfg.controlPort
          && lib.hasPrefix "/tmp/" cfg.controlPort)
      [
        "services.modbus-scraper: the control socket is under /tmp, which the service's PrivateTmp makes private — the CLI outside cannot reach it; use a path under /run/modbus-scraper/ instead."
      ]
      ++ lib.optional (cfg.openFirewall && cfg.listenHost == "127.0.0.1")
      "services.modbus-scraper: openFirewall is set but the exporter binds to 127.0.0.1 — the firewall hole is unreachable; set listenHost to 0.0.0.0 (or the external IP) if Prometheus scrapes from another host.";

    assertions = [
      {
        assertion = cfg.maxKwp == 0 || cfg.maxKwp > 0;
        message = "services.modbus-scraper: maxKwp must be 0 (checks off) or a positive kW value, got ${toString cfg.maxKwp}";
      }
      {
        assertion = cfg.maxGridKw == 0 || cfg.maxGridKw > 0;
        message = "services.modbus-scraper: maxGridKw must be 0 (checks off) or a positive kW value, got ${toString cfg.maxGridKw}";
      }
    ];

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.listenPort ];

    systemd.services.modbus-scraper = {
      description = "Modbus TCP Prometheus exporter";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      reloadIfChanged = true;
      restartIfChanged = false;

      serviceConfig = {
        ExecStart = "${lib.getExe cfg.package} --config ${configScript}";
        ExecReload = "${pkgs.util-linux}/bin/kill -HUP $MAINPID";
        DynamicUser = true;
        Restart = "on-failure";
        RestartSec = 3;
        UMask = "0077";
        # the sandbox pass (verified with systemd-analyze security in the
        # flake's hardening check): the whole filesystem read-only but the
        # explicit RW paths, no /home, no /tmp sharing, no device nodes, no
        # kernel interfaces, no namespace/clock/hostname mutation, no
        # privileges, no writable+executable memory, only the AF_UNIX +
        # INET* socket families and the @system-service calls.
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
      } // lib.optionalAttrs (cfg.controlTokenFile != null || cfg.controlOpsTokenFile != null) {
        LoadCredential = lib.optionals (cfg.controlTokenFile != null) [ "control-token:${toString cfg.controlTokenFile}" ]
          ++ lib.optionals (cfg.controlOpsTokenFile != null) [ "control-ops-token:${toString cfg.controlOpsTokenFile}" ];
      } // lib.optionalAttrs (cfg.controlPort != null
          && lib.isString cfg.controlPort
          && lib.hasPrefix "/run/modbus-scraper/" cfg.controlPort) {
        # the control socket's directory, owned by the dynamic user
        RuntimeDirectory = "modbus-scraper";
        RuntimeDirectoryMode = "0755";
      };
    };
  };
}
