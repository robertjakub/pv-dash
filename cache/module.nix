{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.modbus-cache;

  # a name list is rendered into the selection JSON the --selection flag reads
  selectionFile = pkgs.writeText "modbus-cache-selection.json"
    (builtins.toJSON { registers = cfg.selection; });

  # the dirs the service may write: the audit trail and the state dump
  rwPaths = lib.filter (p: p != null) [
    (if cfg.auditLog != null && cfg.auditLog != "-" then dirOf cfg.auditLog else null)
    (if cfg.dumpPath != null then dirOf cfg.dumpPath else null)
  ];

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
    } // lib.optionalAttrs (cfg.profile != null) {
      profile = toString cfg.profile;
    } // lib.optionalAttrs (cfg.selection != null) {
      selection = if lib.isList cfg.selection then toString selectionFile else toString cfg.selection;
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
    } // lib.optionalAttrs (cfg.writeRegisters != null) {
      write_registers = cfg.writeRegisters;
    } // {
      allow_write = lib.boolToString cfg.allowWrite;
      local_time = lib.boolToString cfg.localTime;
      log_access = lib.boolToString cfg.logAccess;
      log_level = cfg.logLevel;
      audit_log = if cfg.auditLog == null then "-" else cfg.auditLog;
      audit_max_mb = toString cfg.auditMaxMb;
      audit_daily = lib.boolToString cfg.auditDaily;
      audit_files = toString cfg.auditFiles;
      requests_audit_s = toString cfg.requestsAudit;
    } // lib.optionalAttrs (cfg.controlPort != null) {
      control_port = toString cfg.controlPort;
    } // lib.optionalAttrs (cfg.controlToken != null) {
      control_token = cfg.controlToken;
    } // lib.optionalAttrs (cfg.controlTokenFile != null) {
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      control_token_file = "/run/credentials/modbus-cache/control-token";
    } // lib.optionalAttrs (cfg.controlTrustUids != null) {
      control_trust_uids = cfg.controlTrustUids;
    } // {
      control_socket_group = lib.boolToString cfg.controlSocketGroup;
    } // lib.optionalAttrs (cfg.dumpPath != null) {
      dump_path = cfg.dumpPath;
      restore_on_start = lib.boolToString cfg.restoreOnStart;
    } // lib.optionalAttrs (cfg.dumpPath != null && cfg.dumpInterval != null) {
      dump_interval = toString cfg.dumpInterval;
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

    profile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        Device-profile JSON naming the registers to cache (the shared
        profiles/ schema: {"registers": [{"name", "register", "type" —
        i16/u16/i32/u32 word widths —, "fc" 3 (holding, the default) or
        4 (input), an optional per-entry "ttl" in seconds, ...]}): every
        listed entry is polled and cached; reads outside the profile are
        forwarded to the inverter. null = the profile bundled with the
        package (the default monitoring set). Which of the entries are
        actually fetched is selection's job.
      '';
    };

    selection = lib.mkOption {
      type = lib.types.nullOr (lib.types.either (lib.types.enum [ "all" "none" ])
        (lib.types.either (lib.types.listOf lib.types.str) lib.types.path));
      default = null;
      description = ''
        Which profile entries are actually fetched: "all" (every profile
        entry — the proxy default), "none" (cache nothing, every read
        forwards), a list of profile names (the module renders it into
        the selection JSON), or a path to such a JSON
        ({"registers": ["pv-power", ...]}). The names must exist in the
        profile. null = all.
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
      default = "127.0.0.1";
      description = "Proxy bind address (loopback by default — set 0.0.0.0 when Modbus clients live on other hosts).";
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

    writeRegisters = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Register ranges a forwarded write may touch: a comma-separated
        START:COUNT list (e.g. "47400:100,47600:100"). Writes outside the
        ranges are refused with a Modbus illegal-function exception.
        null = any register writable (the default).
      '';
    };

    controlPort = lib.mkOption {
      type = lib.types.nullOr (lib.types.either lib.types.int lib.types.str);
      default = null;
      description = ''
        The JSON-lines control server target: a TCP port (bound to
        127.0.0.1) or a unix socket path. The service has PrivateTmp — a
        socket under /tmp is unreachable from outside; use a path under
        /run/modbus-cache/ (created for the service). null = the proxy
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

    dumpPath = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The state dump (write-behind): the cached words + their stamps and
        the live setting overrides, as one JSON — written on shutdown, by
        the request dump command and every dumpInterval seconds, restored
        on start and by the request restore command; a daemon restart
        serves last-known values instead of cold misses. null =
        persistence off.
      '';
    };

    dumpInterval = lib.mkOption {
      type = lib.types.nullOr lib.types.number;
      default = null;
      description = ''
        Seconds between the automatic state dumps; 0 = on request (the
        request dump command and the shutdown). Needs dumpPath. null = the
        proxy default (0).
      '';
    };

    restoreOnStart = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Load the state dump when the daemon starts (needs dumpPath) — a
        restart serves last-known values instead of cold misses. Off by
        default: start cold, load on demand (the request restore command).
      '';
    };

    requestsAudit = lib.mkOption {
      type = lib.types.nullOr lib.types.number;
      default = null;
      description = ''
        Audit one REQUESTS tally per client per this many seconds (who is
        hammering the cache); null = the proxy default (300 s). 0 = off.
      '';
    };

    controlSocketGroup = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Leave the unix control socket group-accessible (chmod 0660 instead
        of the default 0600): a local group may speak to the control
        without being the service user.
      '';
    };

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listen port in the firewall (needed when clients run on another host).";
    };

    auditLog = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The CACHE audit trail (who/when/what for the control commands, the
        auth attempts and the forwarded/refused writes): a file path, or "-"
        for stdout (default — journald captures it; the hardened service
        cannot write the XDG state home). null = stdout.
      '';
    };

    auditMaxMb = lib.mkOption {
      type = lib.types.float;
      default = 10.0;
      description = "Rotate the audit log at this size in MB, keeping auditFiles backups; 0 = off.";
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
  };

  config = lib.mkIf cfg.enable {
    warnings =
      lib.optional (cfg.openFirewall && cfg.listenHost == "127.0.0.1")
        "services.modbus-cache: openFirewall is set but the proxy binds to 127.0.0.1 — the firewall hole is unreachable; set listenHost to 0.0.0.0 (or the external IP) if Modbus clients live on other hosts."
      ++ lib.optional (cfg.controlToken != null)
        "services.modbus-cache: controlToken is rendered into the world-readable ini in the nix store — prefer controlTokenFile."
      ++ lib.optionals (cfg.controlPort != null
          && lib.isString cfg.controlPort
          && lib.hasPrefix "/tmp/" cfg.controlPort)
        [
          "services.modbus-cache: the control socket is under /tmp, which the service's PrivateTmp makes private — the CLI outside cannot reach it; use a path under /run/modbus-cache/ instead."
        ];

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
      } // lib.optionalAttrs (rwPaths != [ ]) {
        ReadWritePaths = rwPaths;
      } // lib.optionalAttrs (cfg.controlTokenFile != null) {
        LoadCredential = [ "control-token:${toString cfg.controlTokenFile}" ];
      } // lib.optionalAttrs (cfg.controlPort != null
          && lib.isString cfg.controlPort
          && lib.hasPrefix "/run/modbus-cache/" cfg.controlPort) {
        # the control socket's directory, owned by the dynamic user
        RuntimeDirectory = "modbus-cache";
        RuntimeDirectoryMode = "0755";
      };
    };
  };
}
