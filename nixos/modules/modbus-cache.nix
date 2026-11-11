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

  # the set-grammar config script (the ini format is gone): every line a
  # `set <name> <value>` — the file pipes through modbus-cache-ctl unchanged
  setLine = name: value: "set ${name} ${value}";
  configScript = pkgs.writeText "modbus_cache.conf" (lib.concatStringsSep "\n" (lib.flatten [
    "# modbus-cache configuration — the control grammar: every line a `set <name> <value>`"
    "# rendered by services.modbus-cache; the flags and the env still win over this file"
    ""
    "# --- the device (upstream inverter) and the register map ---"
    (setLine "modbus upstream" cfg.upstream)
    (setLine "modbus unit" (toString cfg.unitId))
    (setLine "modbus timeout" (toString cfg.timeout))
    (lib.optionals (cfg.modbusAuth != null) [ (setLine "modbus auth" cfg.modbusAuth) ])
    (lib.optionals (cfg.authKey != null) [ (setLine "modbus auth key" cfg.authKey) ])
    (lib.optionals (cfg.authUpstream != null) [ (setLine "modbus auth-upstream" cfg.authUpstream) ])
    (lib.optionals (cfg.authUpstreamKey != null) [ (setLine "modbus auth-upstream-key" cfg.authUpstreamKey) ])
    (setLine "system listen" "${cfg.listenHost}:${toString cfg.listenPort}")
    (setLine "modbus interval" (toString cfg.interval))
    (setLine "modbus read-delay" (toString cfg.readDelay))
    (setLine "modbus merge-gap" (toString cfg.mergeGap))
    (lib.optionals (cfg.profile != null) [ (setLine "modbus profile" (toString cfg.profile)) ])
    (lib.optionals (cfg.selection != null) [
      (setLine "modbus selection" (if lib.isList cfg.selection then toString selectionFile else toString cfg.selection))
    ])
    (lib.optionals (cfg.cacheTtl != null) [ (setLine "cache ttl" (toString cfg.cacheTtl)) ])
    (setLine "write allow" (lib.boolToString cfg.allowWrite))
    (lib.optionals (cfg.writeRegisters != null) [ (setLine "write registers" cfg.writeRegisters) ])
    (lib.optionals (cfg.connectAcl != null) [ (setLine "acl connect" cfg.connectAcl) ])
    (lib.optionals (cfg.writeAcl != null) [ (setLine "acl write" cfg.writeAcl) ])
    ""
    "# --- what the tool serves and where ---"
    (setLine "local-time" (lib.boolToString cfg.localTime))
    ""
    "# --- the connection caps ---"
    (lib.optionals (cfg.maxClients != null) [ (setLine "limits max-clients" (toString cfg.maxClients)) ])
    (lib.optionals (cfg.clientTimeout != null) [ (setLine "limits client-timeout" (toString cfg.clientTimeout)) ])
    (lib.optionals (cfg.maxConnPerIp != null) [ (setLine "limits max-conn-per-ip" (toString cfg.maxConnPerIp)) ])
    ""
    "# --- the control plane ---"
    (lib.optionals (cfg.controlPort != null) [ (setLine "control port" (toString cfg.controlPort)) ])
    (lib.optionals (cfg.controlToken != null) [ (setLine "control token" cfg.controlToken) ])
    (lib.optionals (cfg.controlTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      (setLine "control token" "file:/run/credentials/modbus-cache/control-token")
    ])
    (lib.optionals (cfg.controlOpsToken != null) [ (setLine "control ops token" cfg.controlOpsToken) ])
    (lib.optionals (cfg.controlOpsTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      (setLine "control ops token" "file:/run/credentials/modbus-cache/control-ops-token")
    ])
    (lib.optionals (cfg.controlOpsVerbs != null) [ (setLine "control ops verbs" cfg.controlOpsVerbs) ])
    (lib.optionals (cfg.controlTrustUids != null) [ (setLine "control trust-uids" cfg.controlTrustUids) ])
    (setLine "control socket-group" (lib.boolToString cfg.controlSocketGroup))
    (setLine "system log-replies" (lib.boolToString cfg.controlLogReplies))
    ""
    "# --- the own Prometheus /metrics endpoint ---"
    (lib.optionals (cfg.metricsMaxClients != null) [ (setLine "metrics limits max-clients" (toString cfg.metricsMaxClients)) ])
    (lib.optionals (cfg.metricsClientTimeout != null) [ (setLine "metrics limits timeout" (toString cfg.metricsClientTimeout)) ])
    (lib.optionals (cfg.metricsMaxConnPerIp != null) [ (setLine "metrics limits max-conn-per-ip" (toString cfg.metricsMaxConnPerIp)) ])
    ""
    "# --- the audit trail ---"
    (setLine "audit disable" (lib.boolToString cfg.noAuditLog))
    (setLine "audit log-file" (if cfg.auditLog == null then "-" else cfg.auditLog))
    (setLine "audit forward" (if cfg.auditForward == null then "none" else cfg.auditForward))
    (lib.optionals (cfg.auditForwardFormat != null) [ (setLine "audit forward format" cfg.auditForwardFormat) ])
    (setLine "audit rotate max-size" (toString cfg.auditMaxMb))
    (setLine "audit rotate daily" (lib.boolToString cfg.auditDaily))
    (setLine "audit rotate files" (toString cfg.auditFiles))
    (setLine "audit requests" (toString cfg.requestsAudit))
    ""
    "# --- the log surface ---"
    (setLine "system log-level" cfg.logLevel)
    (setLine "system log-access" (lib.boolToString cfg.logAccess))
    ""
    "# --- the state dump (write-behind) ---"
    (lib.optionals (cfg.dumpPath != null) [
      (setLine "dump path" cfg.dumpPath)
      (setLine "dump with-cache" (lib.boolToString cfg.dumpWithCache))
      (setLine "dump restore-on-start" (lib.boolToString cfg.restoreOnStart))
    ])
    (lib.optionals (cfg.dumpPath != null && cfg.dumpKey != null) [
      (setLine "dump key" cfg.dumpKey)
    ])
    (lib.optionals (cfg.dumpPath != null && cfg.dumpInterval != null) [
      (setLine "dump-interval" (toString cfg.dumpInterval))
    ])
    (lib.optionals (cfg.metricsServer != null) [
      (setLine "metrics enable" (lib.boolToString cfg.metricsServer))
      (setLine "metrics listen" cfg.metricsListen)
    ])
    (lib.optionals (cfg.metricsToken != null) [ (setLine "metrics token" cfg.metricsToken) ])
    (lib.optionals (cfg.metricsTokenFile != null) [
      # systemd LoadCredential mounts the file here (see serviceConfig below)
      (setLine "metrics token" "file:/run/credentials/modbus-cache/metrics-token")
    ])
    (lib.optionals (cfg.metricsAcl != null) [ (setLine "metrics acl" cfg.metricsAcl) ])
  ]));
in
{
  options.services.modbus-cache = {
    enable = lib.mkEnableOption "the Modbus TCP caching proxy for single-client devices";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../pkgs/modbus-cache/package.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/modbus-cache/package.nix { }";
      description = "The modbus-cache package to run.";
    };

    upstream = lib.mkOption {
      type = lib.types.str;
      default = "127.0.0.1:5502";
      description = "The inverter Modbus TCP endpoint HOST:PORT (`:PORT` = 127.0.0.1:PORT) — set HOST to the inverter/dongle's LAN IP.";
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

    modbusAuth = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "suite" ]);
      default = null;
      description = ''
        The auth scheme the cache's own Modbus clients must speak: "suite"
        demands the crypt handshake (magic + nonce + HMAC proof of the
        shared key, min 16 characters) right after every connect and drops
        the client on ERR/anything else. null = no auth at all.
      '';
    };

    authKey = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The shared key the cache's clients prove with the suite handshake
        (min 16 characters). Needs auth = "suite".
      '';
    };

    authUpstream = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "suite" "waveshare" ]);
      default = null;
      description = ''
        The auth scheme toward the upstream inverter: "suite" proves the
        shared authUpstreamKey with the crypt handshake right after every
        connect (the peer answers OK, or ERR and the connection fails —
        the poller keeps retrying); "waveshare" sends the shared
        authUpstreamKey as the Waveshare TCP connection password right
        after every connect (the gateway answers OK, or anything else or
        nothing and the connection fails). null = no auth at all.
      '';
    };

    authUpstreamKey = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The key the cache presents to the upstream inverter: the suite
        handshake's shared key (min 16 characters) or the Waveshare TCP
        connection password (non-empty ASCII). Needs authUpstream.
      '';
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

    maxConnPerIp = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = ''
        Refuse further connections from one peer IP past this many
        simultaneous connections (proxy default: 0 = no per-IP limit).
        The NAT'd-household shape: one gateway IP, many clients — set it
        above the client count you expect from a single site.
      '';
    };

    metricsMaxClients = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = ''
        Maximum concurrent HTTP clients on the /metrics endpoint; extras
        get an immediate 503 (default: 64; 0 = unlimited).
      '';
    };

    metricsServer = lib.mkOption {
      type = lib.types.nullOr lib.types.bool;
      default = null;
      description = ''
        Serve the cache's own Prometheus /metrics endpoint (default:
        false). A token is mandatory when it is on — metricsServerToken /
        metricsServerTokenFile. Live-settable on the control server.
      '';
    };

    metricsListen = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The metrics bind address HOST:PORT (default: 127.0.0.1:9351).
        0.0.0.0:PORT serves every interface — a token is mandatory
        regardless.
      '';
    };

    metricsClientTimeout = lib.mkOption {
      type = lib.types.nullOr lib.types.float;
      default = null;
      description = ''
        Seconds an idle /metrics client is kept before the socket times
        out (default: 5; 0 = the same built-in 5 s cap).
      '';
    };

    metricsMaxConnPerIp = lib.mkOption {
      type = lib.types.nullOr lib.types.int;
      default = null;
      description = ''
        Maximum concurrent /metrics connections from one peer IP
        (default: 0 = no per-IP limit).
      '';
    };

    connectAcl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Clients allowed to connect: "any", "none" (refuse every peer), a
        comma-separated list of IPs and CIDR prefixes (e.g.
        "10.0.0.7,10.48.0.0/16", IPv4 or IPv6), or "file:<path>" — the
        standalone ip-prefix acl file (the chain's last matching rule
        decides, a client no rule decides refuses). null = the tool's
        default ("any").
      '';
    };

    writeAcl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Clients allowed to write (also needs allowWrite): "any", "none"
        (refuse every peer), a comma-separated list of IPs and CIDR
        prefixes, or "file:<path>" — the standalone ip-prefix acl file
        (the same gate acl/connect reads). null = the tool's default
        ("none" — no client writes).
      '';
    };

    writeRegisters = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Register ranges a forwarded write may touch: a comma-separated
        START:COUNT list (e.g. "47400:100,47600:100"), "any", "none",
        "profile" (the device profile's acl/write gate) or "file:<path>"
        (the standalone acl file). Writes outside the ranges are refused
        with a Modbus illegal-function exception. null = the tool's
        default ("none" — no register writable).
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
        secret. Passed to the daemon as a file: reference (the value form
        the token knob speaks). Mutually exclusive with controlToken.
      '';
    };

    controlOpsToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        A second, read-only control token: sessions authenticating with it
        run its policy's verbs only (the default policy: show,flush) (no set/clear, no request
        dump/restore, no restart, no shutdown) — the ops shift against the
        admin key. Needs controlToken/controlTokenFile. WARNING: it is
        rendered into the world-readable config script in the nix store — prefer
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

    metricsToken = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The /metrics bearer token (a token is mandatory when
        metricsServer is on). WARNING: rendered into the world-readable
        config script in the nix store — prefer metricsTokenFile.
      '';
    };

    metricsTokenFile = lib.mkOption {
      type = lib.types.nullOr lib.types.path;
      default = null;
      description = ''
        The /metrics bearer token from a file (the first line is the
        token), mounted via systemd LoadCredential. Mutually exclusive
        with metricsToken; mandatory when metricsServer is on.
      '';
    };

    metricsAcl = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        Clients allowed to connect to the cache's /metrics endpoint: "any",
        "none" (refuse every peer), a comma-separated list of IPs and CIDR
        prefixes, or "file:<path>" — the standalone ip-prefix acl file (the
        same gate acl/connect reads). Checked at accept — a client off the
        ACL is closed without a reply. Re-read at startup and on every
        SIGHUP reload. null = the tool's default ("any").
      '';
    };

    controlOpsVerbs = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = ''
        The read-only ops role's RBAC policy: the verbs its sessions may
        run, comma-separated (default: show,flush).
        control grammar at start; needs controlOpsToken/controlOpsTokenFile.
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
        The state dump (write-behind): the live setting overrides and —
        when dumpWithCache — the cached words + their stamps, as one JSON —
        written on shutdown, by the request dump command and every
        dumpInterval seconds, restored on start and by the request restore
        command; created 0600, integrity-hashed, restored only after the
        checks pass. null = persistence off.
      '';
    };

    dumpWithCache = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Dump the cached words too: the request dump command and the
        dumpInterval loop write the words + the settings (the default off =
        settings only; request dump with-cache always includes them; the
        restore takes either shape).
      '';
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

    controlLogReplies = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        DEBUG-log the full output of every control command (plainly: the
        command and its status log; the live `set system log-replies` toggle).
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

    auditForward = lib.mkOption {
      type = lib.types.nullOr (lib.types.addCheck lib.types.str
        (v: v == "none" || v == "syslog" || lib.hasPrefix "syslog:/" v
            || lib.hasPrefix "udp://" v || lib.hasPrefix "tcp://" v));
      default = null;
      description = ''
        Also forward the CACHE audit trail: "syslog" (the local socket
        auto-scan), "syslog:/path" (an explicit socket), "udp://host[:514]"
        (RFC5426, best-effort) or "tcp://host[:514]" (RFC6587 framing) — the
        off-box copy carries the per-writer hash chain, so a scheduled search
        at the collector can alert on a chain break. null = off.
      '';
    };

    auditForwardFormat = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "rfc5424" "cef" ]);
      default = null;
      description = ''
        The remote forward's envelope: RFC5424 (the tool's default) or CEF —
        the local syslog forms keep the verbatim send (remote targets only).
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
      description = "Disable the CACHE audit trail entirely.";
    };
  };

  config = lib.mkIf cfg.enable {
    warnings =
      lib.optional (cfg.openFirewall && cfg.listenHost == "127.0.0.1")
        "services.modbus-cache: openFirewall is set but the proxy binds to 127.0.0.1 — the firewall hole is unreachable; set listenHost to 0.0.0.0 (or the external IP) if Modbus clients live on other hosts."
      ++ lib.optional (cfg.controlToken != null)
        "services.modbus-cache: controlToken is rendered into the world-readable config script in the nix store — prefer controlTokenFile."
      ++ lib.optional (cfg.controlOpsToken != null)
        "services.modbus-cache: controlOpsToken is rendered into the world-readable config script in the nix store — prefer controlOpsTokenFile."
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
      } // lib.optionalAttrs (rwPaths != [ ]) {
        ReadWritePaths = rwPaths;
      } // lib.optionalAttrs (cfg.controlTokenFile != null || cfg.controlOpsTokenFile != null
          || cfg.metricsTokenFile != null) {
        LoadCredential = lib.optionals (cfg.controlTokenFile != null) [ "control-token:${toString cfg.controlTokenFile}" ]
          ++ lib.optionals (cfg.controlOpsTokenFile != null) [ "control-ops-token:${toString cfg.controlOpsTokenFile}" ]
          ++ lib.optionals (cfg.metricsTokenFile != null) [ "metrics-token:${toString cfg.metricsTokenFile}" ];
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
