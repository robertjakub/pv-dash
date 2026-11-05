{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.modbus-scraper;

  configIni = pkgs.writeText "scraper.ini" (lib.generators.toINI { } {
    scraper = {
      host = cfg.inverterHost;
      modbus_port = toString cfg.inverterPort;
      unit = toString cfg.unitId;
      modbus_offset = toString cfg.modbusOffset;
      timeout = toString cfg.timeout;
      pv_register = toString cfg.pvRegister;
      grid_register = toString cfg.gridRegister;
      scale = toString cfg.scale;
      grid_scale = toString cfg.gridScale;
      max_kwp = toString cfg.maxKwp;
      max_grid_kw = toString cfg.maxGridKw;
      battery = lib.boolToString cfg.battery;
      battery_register = toString cfg.batteryRegister;
      battery_soc_register = toString cfg.batterySocRegister;
      grid_positive_import = lib.boolToString cfg.gridPositiveImport;
      listen = "${cfg.listenHost}:${toString cfg.listenPort}";
      interval = toString cfg.interval;
      log_level = cfg.logLevel;
      local_time = lib.boolToString cfg.localTime;
      log_access = lib.boolToString cfg.logAccess;
      auth_token = if cfg.authToken == null then "" else cfg.authToken;
      auth_token_file = if cfg.authTokenFile == null then "" else cfg.authTokenFile;
      max_clients = toString cfg.maxClients;
      client_timeout = toString cfg.clientTimeout;
      max_conn_per_ip = toString cfg.maxConnPerIp;
    } // lib.optionalAttrs (cfg.auditLog != null) {
      audit_log = cfg.auditLog;
      audit_max_mb = toString cfg.auditMaxMb;
      audit_files = toString cfg.auditFiles;
    } // lib.optionalAttrs (cfg.controlPort != null) {
      control_port = toString cfg.controlPort;
    } // lib.optionalAttrs (cfg.controlToken != null) {
      control_token = cfg.controlToken;
    } // lib.optionalAttrs (cfg.controlTokenFile != null) {
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      control_token_file = "/run/credentials/modbus-scraper/control-token";
    } // lib.optionalAttrs (cfg.controlTrustUids != null) {
      control_trust_uids = cfg.controlTrustUids;
    };
  });
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

    inverterHost = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Inverter/dongle Modbus TCP address (set to its LAN IP).";
    };

    inverterPort = lib.mkOption {
      type = lib.types.port;
      default = 5502;
      description = "Inverter Modbus TCP port.";
    };

    unitId = lib.mkOption {
      type = lib.types.int;
      default = 1;
      description = "Modbus unit id.";
    };

    modbusOffset = lib.mkOption {
      type = lib.types.int;
      default = 0;
      description = "Offset added to register addresses (set -1 for gateways that need 0-based addressing).";
    };

    pvRegister = lib.mkOption {
      type = lib.types.int;
      default = 32064;
      description = "Holding register of the signed 32-bit PV input power.";
    };

    gridRegister = lib.mkOption {
      type = lib.types.int;
      default = 37113;
      description = "Holding register of the signed 32-bit grid/active power (positive = feed-in).";
    };

    battery = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Battery support (experimental, untested against real hardware).";
    };

    batteryRegister = lib.mkOption {
      type = lib.types.int;
      default = 37001;
      description = "Holding register of the signed 32-bit battery power in watts, positive = charging (37001 on the default profile); used when battery is enabled.";
    };

    batterySocRegister = lib.mkOption {
      type = lib.types.int;
      default = 37004;
      description = "Holding register of the battery state of charge (U16, percent*10); used when battery is enabled.";
    };

    scale = lib.mkOption {
      type = lib.types.float;
      default = 1.0;
      description = "Multiplier for the PV register raw value (the default profile's power registers already report watts via the gain convention; set 1000.0 for devices reporting kW).";
    };

    gridScale = lib.mkOption {
      type = lib.types.float;
      default = 1.0;
      description = ''
        Multiplier for the grid register raw value. Defaults to 1.0 (the
        [Power meter collection] register 37113 reports watts); set 1000.0
        for devices reporting kW.
      '';
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
        into the world-readable ini in the nix store — prefer controlTokenFile.
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
  };

  config = lib.mkIf cfg.enable {
    warnings = lib.optional (cfg.authToken != null && cfg.authTokenFile != null)
      "services.modbus-scraper: both authToken and authTokenFile are set — the inline token wins and the file is ignored."
      ++ lib.optional (cfg.controlToken != null)
      "services.modbus-scraper: controlToken is rendered into the world-readable ini in the nix store — prefer controlTokenFile."
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
        ExecStart = "${lib.getExe cfg.package} --config ${configIni}";
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
      } // lib.optionalAttrs (cfg.controlTokenFile != null) {
        LoadCredential = [ "control-token:${toString cfg.controlTokenFile}" ];
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
