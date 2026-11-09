{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.dashboard;

  # config.js for the front-end: either a user-provided file or generated
  # from settings (an attrset matching the SOLAR_CONFIG structure).
  configFile =
    if cfg.configFile != null then
      cfg.configFile
    else
      pkgs.writeText "dashboard-config.js" "const SOLAR_CONFIG = ${builtins.toJSON cfg.settings};";

  execArgs = lib.concatStringsSep " " (
    [
      "--listen ${cfg.listenHost}:${toString cfg.listenPort}"
      "--upstream ${cfg.prometheusUrl}"
      "--prom-prefix ${cfg.promPrefix}"
      "--config-js ${configFile}"
      "--max-clients ${toString cfg.maxClients}"
      "--client-timeout ${toString cfg.clientTimeout}"
      "--max-conn-per-ip ${toString cfg.maxConnPerIp}"
    ]
    ++ lib.optional (cfg.staticDir != null) "--static-dir ${cfg.staticDir}"
    ++ lib.optional cfg.logAccess "--log-access"
    ++ lib.optionals cfg.noAuditLog [ "--no-audit-log" ]
    ++ lib.optionals (cfg.auditLog != null) [
      "--audit-log ${cfg.auditLog}"
      "--audit-max-mb ${toString cfg.auditMaxMb}"
      "--audit-files ${toString cfg.auditFiles}"
    ]
    ++ lib.optional cfg.auditDaily "--audit-daily"
    ++ lib.optionals (cfg.auditForward != null) [ "--audit-forward ${cfg.auditForward}" ]
    ++ lib.optionals (cfg.logLevel != null) [ "--log-level ${cfg.logLevel}" ]
    ++ lib.optional cfg.logQueries "--log-queries"
    ++ lib.optional cfg.localTime "--local-time"
    ++ lib.optionals (cfg.controlPort != null) [
      "--control-port ${
        if lib.isInt cfg.controlPort then toString cfg.controlPort else "'${cfg.controlPort}'"
      }"
    ]
    ++ lib.optionals (cfg.controlToken != null) [ "--control-token ${cfg.controlToken}" ]
    ++ lib.optionals (cfg.controlTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      "--control-token file:/run/credentials/dashboard/control-token"
    ]
    ++ lib.optionals (cfg.controlOpsToken != null) [ "--control-ops-token ${cfg.controlOpsToken}" ]
    ++ lib.optionals (cfg.controlOpsTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      "--control-ops-token file:/run/credentials/dashboard/control-ops-token"
    ]
    ++ lib.optionals (cfg.controlOpsVerbs != null) [ "--control-ops-verbs ${cfg.controlOpsVerbs}" ]
    ++ lib.optionals (cfg.controlTrustUids != null) [ "--control-trust-uids ${cfg.controlTrustUids}" ]
    ++ lib.optional cfg.controlSocketGroup "--control-socket-group"
    ++ lib.optionals (cfg.metricsServer != null) [ "--metrics-server" ]
    ++ lib.optionals (cfg.metricsServer != null) [
      "--metrics-listen ${cfg.metricsListen}"
      "--metrics-token file:/run/credentials/dashboard/metrics-token"
      "--metrics-max-clients ${toString cfg.metricsMaxClients}"
      "--metrics-client-timeout ${toString cfg.metricsClientTimeout}"
      "--metrics-max-conn-per-ip ${toString cfg.metricsMaxConnPerIp}"
    ]
    ++ lib.optionals (cfg.metricsAcl != null) [ "--metrics-acl ${cfg.metricsAcl}" ]
    ++ lib.optionals (cfg.metricsToken != null) [ "--metrics-token ${cfg.metricsToken}" ]
    ++ lib.optionals (cfg.authTokenFile != null) [ "--auth-token file:/run/credentials/dashboard/auth-token" ]
    ++ lib.optionals (cfg.authToken != null) [ "--auth-token ${cfg.authToken}" ]
    ++ lib.optionals (cfg.dumpPath != null) [ "--dump-path ${cfg.dumpPath}" ]
    ++ lib.optionals (cfg.dumpPath != null && cfg.dumpKey != null) [ "--dump-key ${cfg.dumpKey}" ]
    ++ lib.optionals (cfg.dumpPath != null && cfg.dumpInterval != null) [ "--dump-interval ${toString cfg.dumpInterval}" ]
    ++ lib.optional cfg.restoreOnStart "--restore-on-start"
  );
in
{
  options.services.dashboard = {
    enable = lib.mkEnableOption "the PV dashboard static server with Prometheus proxy";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ./package.nix { }";
      description = "The dashboard package to run.";
    };

    listenHost = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1";
      description = "Address to bind (the serve address's host part).";
    };

    listenPort = lib.mkOption {
      type = lib.types.port;
      default = 8080;
      description = "Listen port (the serve address's port part).";
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

    maxClients = lib.mkOption {
      type = lib.types.int;
      default = 64;
      description = "Maximum concurrent HTTP clients (pages + proxy); extras get an immediate 503 (0 = unlimited).";
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

    logAccess = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Log every HTTP request (page loads, /prom queries) at INFO — audit trail for who polled and when.";
    };

    controlPort = lib.mkOption {
      type = lib.types.nullOr (lib.types.either lib.types.int lib.types.str);
      default = null;
      description = ''
        The JSON-lines control server target: a TCP port (bound to
        127.0.0.1) or a unix socket path. The service has PrivateTmp — a
        socket under /tmp is unreachable from outside; use a path under
        /run/dashboard/ (created for the service). The control surface
        speaks the signed wire (the full sha256 HMAC of every frame, keyed
        by the token) and is talked to with dashboard-ctl / dashboard-cli.
        null = the server default (a /tmp unix socket, private to the
        service).
      '';
    };

    controlToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Require a token on TCP control connections. WARNING: it is rendered
        into the world-readable systemd unit in the nix store — prefer
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
        run the show/clear verbs only (no set/unset, no request
        reload-config, no request reload, no request dump/restore, no
        shutdown) — the ops shift against the admin key. Needs
        controlToken/controlTokenFile. WARNING: it is rendered into the
        world-readable systemd unit in the nix store — prefer
        controlOpsTokenFile.
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

    metricsServer = lib.mkOption {
      type = lib.types.nullOr lib.types.bool;
      default = null;
      description = ''
        Serve the dashboard's own Prometheus /metrics endpoint (the uptime,
        the request counters, the proxied query total, the client gate).
        Off by default; when on, a bearer token is mandatory — mount it
        with metricsTokenFile.
      '';
    };

    metricsToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The /metrics bearer token (a token is mandatory when
        metricsServer is on). WARNING: rendered into the world-readable
        systemd unit in the nix store — prefer metricsTokenFile.
      '';
    };

    metricsMaxClients = lib.mkOption {
      type = lib.types.int;
      default = 16;
      description = "Maximum concurrent /metrics clients; extras get an immediate 503; 0 = unlimited.";
    };

    metricsClientTimeout = lib.mkOption {
      type = lib.types.float;
      default = 5.0;
      description = "Seconds an idle /metrics client is kept before the socket times out; 0 = the built-in 5 s cap.";
    };

    metricsMaxConnPerIp = lib.mkOption {
      type = lib.types.int;
      default = 0;
      description = "Maximum concurrent /metrics connections from one peer IP; 0 = no per-IP limit.";
    };

    metricsListen = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1:9353";
      description = "The /metrics bind address HOST:PORT (metricsServer on).";
    };

    metricsAcl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Clients allowed to connect to the dashboard's /metrics endpoint:
        "any", "none" (refuse every peer), a comma-separated list of IPs
        and CIDR prefixes, or "file:<path>" — the standalone ip-prefix acl
        file. Checked at accept — a client off the ACL is closed without a
        reply. null = the tool's default ("any").
      '';
    };

    metricsTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        The /metrics bearer token from a file (the first line is the
        token), mounted via systemd LoadCredential. Mandatory when
        metricsServer is on.
      '';
    };

    authToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The page's bearer token (F21): mandatory when listenHost is beyond
        the loopback. WARNING: rendered into the world-readable systemd unit
        in the nix store — prefer authTokenFile.
      '';
    };

    authTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        The page's bearer token from a file (the first line is the
        token), mounted via systemd LoadCredential. Mandatory when
        listenHost is beyond the loopback (F21).
      '';
    };

    dumpPath = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The state dump file: the live setting overrides (set through the
        control surface) as one JSON, written 0600 with an integrity hash on
        `request dump`, the graceful shutdown and every dumpInterval
        seconds, and re-applied on start when restoreOnStart is set. null =
        the dumps are off.
      '';
    };

    dumpInterval = lib.mkOption {
      type = lib.types.nullOr lib.types.number;
      default = null;
      description = ''
        Seconds between the automatic state dumps; 0 = on request (the
        request dump command and the shutdown). Needs dumpPath. null = the
        default (0).
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

    controlSocketGroup = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Leave the unix control socket group-accessible (chmod 0660 instead
        of the plain 0600): a local group may speak to the control without
        being the service user.
      '';
    };

    auditLog = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = "-";
      description = ''
        The DSH audit trail (the control commands, the auth attempts,
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

    auditForward = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "syslog" ]);
      default = null;
      description = ''
        Also forward the DSH audit trail to the local syslog socket
        ("syslog"): journald picks every audit line up — the sealed external
        copy beside the file/stdout sink, the per-writer hash chain included.
        null = off.
      '';
    };

    auditDaily = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Also rotate the audit log at UTC midnight.";
    };

    auditFiles = lib.mkOption {
      type = lib.types.int;
      default = 3;
      description = "Rotated audit backups to keep.";
    };

    noAuditLog = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Disable the DSH audit trail entirely.";
    };

    logLevel = lib.mkOption {
      type = lib.types.enum [ "DEBUG" "INFO" "WARNING" "ERROR" ];
      default = "INFO";
      description = "Log level.";
    };

    logQueries = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Log the proxied Prometheus queries at INFO.";
    };

    localTime = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Log timestamps in the system time zone instead of UTC.";
    };
  };

  config = lib.mkIf cfg.enable {
    warnings = lib.optional (cfg.controlToken != null)
      "services.dashboard: controlToken is rendered into the world-readable systemd unit in the nix store — prefer controlTokenFile."
      ++ lib.optional (cfg.controlOpsToken != null)
      "services.dashboard: controlOpsToken is rendered into the world-readable systemd unit in the nix store — prefer controlOpsTokenFile."
      ++ lib.optionals (cfg.controlPort != null
          && lib.isString cfg.controlPort
          && lib.hasPrefix "/tmp/" cfg.controlPort)
      [
        "services.dashboard: the control socket is under /tmp, which the service's PrivateTmp makes private — the CLI outside cannot reach it; use a path under /run/dashboard/ instead."
      ];

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ cfg.listenPort ];

    systemd.services.dashboard = {
      description = "PV dashboard server (static + Prometheus proxy)";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      reloadIfChanged = true;
      restartIfChanged = false;

      serviceConfig = {
        ExecStart = "${lib.getExe cfg.package} ${execArgs}";
        ExecReload = "${pkgs.util-linux}/bin/kill -HUP $MAINPID";
        DynamicUser = true;
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
      } // lib.optionalAttrs (cfg.controlTokenFile != null || cfg.controlOpsTokenFile != null
          || cfg.metricsTokenFile != null || cfg.authTokenFile != null) {
        LoadCredential = lib.optionals (cfg.controlTokenFile != null) [ "control-token:${toString cfg.controlTokenFile}" ]
          ++ lib.optionals (cfg.controlOpsTokenFile != null) [ "control-ops-token:${toString cfg.controlOpsTokenFile}" ]
          ++ lib.optionals (cfg.metricsTokenFile != null) [ "metrics-token:${toString cfg.metricsTokenFile}" ]
          ++ lib.optionals (cfg.authTokenFile != null) [ "auth-token:${toString cfg.authTokenFile}" ];
      } // lib.optionalAttrs (cfg.controlPort != null
          && lib.isString cfg.controlPort
          && lib.hasPrefix "/run/dashboard/" cfg.controlPort) {
        # the control socket's directory, owned by the dynamic user
        RuntimeDirectory = "dashboard";
        RuntimeDirectoryMode = "0755";
      };
    };
  };
}
