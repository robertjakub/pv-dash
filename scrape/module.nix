{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.sun2000-scraper;

  execArgs = lib.concatStringsSep " " (
    [
      "--host ${cfg.inverterHost}"
      "--modbus-port ${toString cfg.inverterPort}"
      "--unit ${toString cfg.unitId}"
      "--listen ${cfg.listenHost}:${toString cfg.listenPort}"
      "--interval ${toString cfg.interval}"
      "--pv-register ${toString cfg.pvRegister}"
      "--grid-register ${toString cfg.gridRegister}"
      "--scale ${toString cfg.scale}"
      "--grid-scale ${toString cfg.gridScale}"
      "--timeout ${toString cfg.timeout}"
    ]
    ++ lib.optional (cfg.modbusOffset != 0) "--modbus-offset ${toString cfg.modbusOffset}"
    ++ lib.optional (cfg.maxKwp > 0.0) "--max-kwp ${toString cfg.maxKwp}"
    ++ lib.optional (cfg.maxGridKw > 0.0) "--max-grid-kw ${toString cfg.maxGridKw}"
    ++ lib.optionals cfg.battery [
      "--battery"
      "--battery-register ${toString cfg.batteryRegister}"
      "--battery-soc-register ${toString cfg.batterySocRegister}"
    ]
    ++ lib.optional cfg.gridPositiveImport "--grid-positive-import"
  );
in
{
  options.services.sun2000-scraper = {
    enable = lib.mkEnableOption "the Huawei SUN2000 Modbus TCP Prometheus exporter";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The sun2000-scraper package to run.";
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
      description = ''
        Battery support enabled (Huawei LUNA2000): reads the battery
        registers, adds the battery term to the home derivation
        (home = PV - battery - net grid) and exports the battery metrics
        huawei_battery_net_watts / huawei_battery_charge_watts /
        huawei_battery_discharge_watts / huawei_battery_soc_percent.
      '';
    };

    batteryRegister = lib.mkOption {
      type = lib.types.int;
      default = 37001;
      description = "Holding register of the signed 32-bit battery power in watts, positive = charging (LUNA2000: 37001); used when battery is enabled.";
    };

    batterySocRegister = lib.mkOption {
      type = lib.types.int;
      default = 37004;
      description = "Holding register of the battery state of charge (U16, percent*10); used when battery is enabled.";
    };

    scale = lib.mkOption {
      type = lib.types.float;
      default = 1.0;
      description = "Multiplier for the PV register raw value (Huawei power registers already report watts via the gain convention; set 1000.0 for devices reporting kW).";
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
      default = 5.0;
      description = "Seconds between Modbus polls.";
    };

    listenHost = lib.mkOption {
      type = lib.types.str;
      default = "0.0.0.0";
      description = "Exporter bind address.";
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
  };

  config = lib.mkIf cfg.enable {
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.listenPort ];

    systemd.services.sun2000-scraper = {
      description = "Huawei SUN2000 Modbus TCP Prometheus exporter";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        ExecStart = "${lib.getExe cfg.package} ${execArgs}";
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
