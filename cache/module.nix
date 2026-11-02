{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.modbus-cache;

  renderRegisters = r:
    { inherit (r) start count; } // lib.optionalAttrs (r.name != null) { inherit (r) name; };

  registersJson = pkgs.writeText "modbus-cache-registers.json" (
    builtins.toJSON { registers = map renderRegisters cfg.registers; });

  configIni = pkgs.writeText "modbus_cache.ini" (lib.generators.toINI { } {
    cache = {
      host = cfg.inverterHost;
      port = toString cfg.inverterPort;
      unit = toString cfg.unitId;
      timeout = toString cfg.timeout;
      listen = "${cfg.listenHost}:${toString cfg.listenPort}";
      interval = toString cfg.interval;
      read_delay = toString cfg.readDelay;
      merge_gap = toString cfg.mergeGap;
      registers_file =
        if cfg.registersFile != null then toString cfg.registersFile else registersJson;
    } // lib.optionalAttrs (cfg.cacheTtl != null) {
      cache_ttl = toString cfg.cacheTtl;
    } // lib.optionalAttrs (cfg.maxClients != null) {
      max_clients = toString cfg.maxClients;
    } // lib.optionalAttrs (cfg.clientTimeout != null) {
      client_timeout = toString cfg.clientTimeout;
    } // lib.optionalAttrs (cfg.connectAcl != null) {
      connect_acl = cfg.connectAcl;
    } // lib.optionalAttrs (cfg.writeAcl != null) {
      write_acl = cfg.writeAcl;
    } // {
      allow_write = lib.boolToString cfg.allowWrite;
      local_time = lib.boolToString cfg.localTime;
      log_access = lib.boolToString cfg.logAccess;
      log_level = cfg.logLevel;
    };
  });
in
{
  options.services.modbus-cache = {
    enable = lib.mkEnableOption "the Modbus TCP caching proxy for single-client devices";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The modbus-cache package to run.";
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

    timeout = lib.mkOption {
      type = lib.types.float;
      default = 3.0;
      description = "Modbus connect/read timeout in seconds.";
    };

    interval = lib.mkOption {
      type = lib.types.float;
      default = 10.0;
      description = "Seconds between cache polls of the inverter.";
    };

    readDelay = lib.mkOption {
      type = lib.types.float;
      default = 0.05;
      description = "Seconds to wait between consecutive inverter reads within a poll cycle (gentle with the dongle/radio); 0 disables the wait.";
    };

    mergeGap = lib.mkOption {
      type = lib.types.int;
      default = 8;
      description = ''
        Maximum register gap when merging listed ranges into block reads
        (fewer, larger transactions - kinder to slow dongles). Blocks that
        fail (an unmapped register inside) are split and the pieces are
        retried on their own. 0 reads each range separately.
      '';
    };

    registers = lib.mkOption {
      type = lib.types.listOf (lib.types.submodule {
        options = {
          name = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Entry name for the logs (null = log the bare range).";
          };
          start = lib.mkOption {
            type = lib.types.int;
            description = "First register of the range.";
          };
          count = lib.mkOption {
            type = lib.types.int;
            description = "Number of registers.";
          };
        };
      });
      default = [
        { name = "PV1/PV2 voltage (/10 V) + current (/100 A)"; start = 32016; count = 4; }
        { name = "Input power DC (int32, /1000 kW)"; start = 32064; count = 2; }
        { name = "Phase A/B/C voltage (/10 V)"; start = 32069; count = 3; }
        { name = "Active power (int32, /1000 kW)"; start = 32080; count = 2; }
        { name = "Grid frequency (/100 Hz)"; start = 32085; count = 1; }
        { name = "Inverter temperature (/10 degC)"; start = 32087; count = 1; }
        { name = "Accumulated energy yield (uint32, /100 kWh)"; start = 32106; count = 2; }
        { name = "Daily energy yield (uint32, /100 kWh)"; start = 32114; count = 2; }
        { name = "Active grid power (int32, W, + = export)"; start = 37113; count = 2; }
        { name = "Grid energy: exported + imported (2 x int32, /100 kWh)"; start = 37119; count = 4; }
        { name = "Battery SOC (/10 %)"; start = 37004; count = 1; }
        { name = "Battery power, unit 1 (int32, W, + = charging)"; start = 37001; count = 2; }
        { name = "Battery energy: total charged/discharged + today (4 x uint32, /100 kWh)"; start = 37780; count = 8; }
      ];
      description = ''
        Register map the module renders to registers.json and passes via
        --registers-file. The defaults are the standard SUN2000 monitoring
        registers (same as the registers.json shipped with the package); reads
        outside these ranges are forwarded to the inverter.
      '';
    };

    registersFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Explicit JSON register map file, replacing the rendered registers option:
        { "registers": [ { "name": "PV power", "start": 32064, "count": 2 }, ... ] }
        Names only decorate the logs; reads outside the cached ranges are
        forwarded to the inverter.
      '';
    };

    cacheTtl = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = ''
        Per-register cache TTL in seconds: cached registers older than this
        are refetched from the inverter (failing with a Modbus exception
        when it is unreachable). Unset (default): three times the poll
        interval. 0 never expires the cache: the last known values are
        served no matter how old.
      '';
    };

    listenHost = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "Proxy bind address.";
    };

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 15502;
      description = "Proxy listen port (point Modbus clients here).";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum [ "DEBUG" "INFO" "WARNING" "ERROR" ];
      default = "INFO";
      description = "Log level.";
    };

    allowWrite = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Forward write requests (FC05/06/15/16) to the inverter. Disabled by
        default: write requests are refused with a Modbus illegal-function
        exception. Enable only if you know what will write to the inverter.
      '';
    };

    localTime = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Log timestamps in the system time zone instead of UTC.";
    };

    logAccess = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Log client connects/disconnects at INFO (they are DEBUG by default,
        since a polling fleet can produce a lot of them).
      '';
    };

    maxClients = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = ''
        Refuse further connections past this many simultaneous clients
        (proxy default: 64; 0 = no limit).
      '';
    };

    clientTimeout = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = ''
        Disconnect clients silent for this many seconds (proxy default:
        300; 0 = never). Set it to shed connections from clients that
        died without closing (power cut, NAT drop).
      '';
    };

    connectAcl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Clients allowed to connect: "any" or a comma-separated list of IPs
        and CIDR prefixes (e.g. "10.0.0.7,10.48.0.0/16", IPv4 or IPv6).
        null = any.
      '';
    };

    writeAcl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Clients allowed to write (also needs allowWrite): "any" or a
        comma-separated list of IPs and CIDR prefixes. null = any.
      '';
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listen port in the firewall (needed when clients run on another host).";
    };
  };

  config = lib.mkIf cfg.enable {
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.listenPort ];

    systemd.services.modbus-cache = {
      description = "Modbus TCP caching proxy";
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
