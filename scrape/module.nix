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
  };

  config = lib.mkIf cfg.enable {
    warnings = lib.optional (cfg.authToken != null && cfg.authTokenFile != null)
      "services.modbus-scraper: both authToken and authTokenFile are set — the inline token wins and the file is ignored."
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
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        ProtectKernelTunables = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" ];
      };
    };
  };
}
