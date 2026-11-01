{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.pv-dashboard;

  # config.js for the front-end: either a user-provided file or generated
  # from settings (an attrset matching the SOLAR_CONFIG structure).
  configFile =
    if cfg.configFile != null then
      cfg.configFile
    else
      pkgs.writeText "pv-dashboard-config.js" "const SOLAR_CONFIG = ${builtins.toJSON cfg.settings};";

  execArgs = lib.concatStringsSep " " (
    [
      "--port ${toString cfg.port}"
      "--bind ${cfg.host}"
      "--upstream ${cfg.prometheusUrl}"
      "--prom-prefix ${cfg.promPrefix}"
      "--config-js ${configFile}"
    ]
    ++ lib.optional (cfg.staticDir != null) "--static-dir ${cfg.staticDir}"
    ++ lib.optional cfg.battery "--battery"
  );
in
{
  options.services.pv-dashboard = {
    enable = lib.mkEnableOption "the PV dashboard static server with Prometheus proxy";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The pv-dashboard package to run.";
    };

    host = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Address to bind.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Listen port.";
    };

    prometheusUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://localhost:9090";
      description = "Upstream Prometheus URL proxied at the /prom prefix.";
    };

    promPrefix = lib.mkOption {
      type = lib.types.str;
      default = "/prom";
      description = "Path under which Prometheus is proxied; empty string proxies everything.";
    };

    staticDir = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Override the packaged static/ directory (e.g. custom index.html).";
    };

    battery = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Battery support (experimental, untested against real hardware).";
    };

    settings = lib.mkOption {
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
        SOLAR_CONFIG contents for the generated config.js. Ignored when
        configFile is set. Label matchers (tags) are allowed in metric selectors.
      '';
    };

    configFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = "Explicit config.js to serve instead of generating one from settings.";
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listen port in the firewall (only needed for direct LAN access).";
    };
  };

  config = lib.mkIf cfg.enable {
    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.port ];

    systemd.services.pv-dashboard = {
      description = "PV dashboard server (static + Prometheus proxy)";
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
