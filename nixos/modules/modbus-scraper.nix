{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.modbus-scraper;

  # the service contract: `settings` carries the daemon's env twins verbatim
  # (the bare upper-snake names — the generated
  # docker/env/modbus-scraper.env.example documents the key list); the module
  # inspects three of them for the
  # sandbox's write paths and the control socket, everything else renders
  # untouched
  listen = cfg.settings.LISTEN or "127.0.0.1:9350";
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
    lib.optionals (modbusAuthKeyFile != null) [ { env = "MODBUS_AUTH_KEY"; name = "modbus-auth-key"; path = modbusAuthKeyFile; } ]
    ++ lib.optionals (controlTokenFile != null) [ { env = "CONTROL_TOKEN"; name = "control-token"; path = controlTokenFile; } ]
    ++ lib.optionals (controlOpsTokenFile != null) [ { env = "CONTROL_OPS_TOKEN"; name = "control-ops-token"; path = controlOpsTokenFile; } ]
    ++ lib.optionals (authTokenFile != null) [ { env = "AUTH_TOKEN"; name = "auth-token"; path = authTokenFile; } ]
    ++ lib.optionals (dumpKeyFile != null) [ { env = "DUMP_KEY"; name = "dump-key"; path = dumpKeyFile; } ];

  # the env file: every settings entry verbatim (the daemon's env layer
  # parses them: flag > env > config script > default) + the credential
  # pointers — the daemon's file: reference loader reads those at start
  envFile = pkgs.writeText "modbus-scraper.env" (lib.concatStringsSep "\n"
    (lib.mapAttrsToList (name: value: "${name}=${value}") cfg.settings
      ++ map (c: "${c.env}=file:/run/credentials/modbus-scraper/${c.name}") credentials)
    + "\n");

  # the eval-time gates: no secret in settings, the keys are env names, the
  # values are single lines, no credential source inside the store
  secretInSettings = lib.filter (n: lib.elem n secretEnvNames) (lib.attrNames cfg.settings);
  badKeys = lib.filter (k: builtins.match "[A-Za-z_][A-Za-z0-9_]*" k == null) (lib.attrNames cfg.settings);
  badValues = lib.filter (v: lib.hasInfix "\n" v || lib.hasInfix "\r" v) (lib.attrValues cfg.settings);
  storeCreds = lib.filter (c: lib.hasPrefix "/nix/store/" c.path) credentials;

  removedOpt = name: file: lib.mkRemovedOptionModule [ "services" "modbus-scraper" name ]
    "secrets may not be rendered into the world-readable nix store — use services.modbus-scraper.${file} (an absolute path outside the store, mounted via systemd LoadCredential).";

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
      `file:/run/credentials/modbus-scraper/<name>`.
    '';
  };
in
{
  imports = [
    (removedOpt "authKey" "modbusAuthKeyFile")
    (removedOpt "controlToken" "controlTokenFile")
    (removedOpt "controlOpsToken" "controlOpsTokenFile")
    (removedOpt "authToken" "authTokenFile")
    (removedOpt "dumpKey" "dumpKeyFile")
  ];

  options.services.modbus-scraper = {
    enable = lib.mkEnableOption "the Modbus TCP Prometheus exporter";

    package = lib.mkOption {
      type = lib.types.package;
      defaultText = lib.literalExpression "pkgs.callPackage ../pkgs/modbus-scraper/package.nix { }";
      description = "The modbus-scraper package to run.";
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
        are the bare env twins the daemon resolves (UPSTREAM, LISTEN,
        INTERVAL, DUMP_PATH, ... — the generated
        docker/env/modbus-scraper.env.example documents the key list), the values
        are strings the daemon's own conv parses ("true"/"false", "10.0");
        an absent key leaves the daemon default. Nothing is mapped,
        converted or validated against the knob registry — except the
        secret env names, which are refused here: the env file lives in the
        world-readable store, and the secrets ride the <secret>File
        credential options only.
      '';
    };

    modbusAuthKeyFile = mkFileOption "The shared key the suite handshake proves (min 16 characters). Needs settings.MODBUS_AUTH = \"suite\".";
    controlTokenFile = mkFileOption "The control token from a file (the first line is the token) — the hardened way to pass the secret over TCP control.";
    controlOpsTokenFile = mkFileOption "The read-only ops control token from a file (the first line is the token). Needs controlTokenFile.";
    authTokenFile = mkFileOption "The /metrics bearer token from a file (single line, trimmed).";
    dumpKeyFile = mkFileOption "The key that seals the state dumps and the reload's state file. Needs settings.DUMP_PATH.";

    openFirewall = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Open the listen port in the firewall (needed when Prometheus runs on another host).";
    };
  };

  config = lib.mkIf cfg.enable {
    warnings =
      lib.optionals (ctl != null && lib.hasPrefix "/tmp/" ctl) [
        "services.modbus-scraper: the control socket is under /tmp, which the service's PrivateTmp makes private — the CLI outside cannot reach it; set settings.CTL to a path under /run/modbus-scraper/ instead."
      ]
      ++ lib.optionals (cfg.openFirewall && (listenHost == "127.0.0.1" || listenHost == "localhost")) [
        "services.modbus-scraper: openFirewall is set but the exporter binds to ${listenHost} — the firewall hole is unreachable; set settings.LISTEN to 0.0.0.0:PORT (or the external IP) if Prometheus scrapes from another host."
      ]
      ++ lib.optionals (cfg.user == "root") [
        "services.modbus-scraper: user is root — the sandbox is built for a service account (the dynamic user, or pvsuite); root under the empty CapabilityBoundingSet is still root."
      ];

    assertions = [
      {
        assertion = cfg.group == null || cfg.user != null;
        message = "services.modbus-scraper: group is set without user — a group alone runs the daemon as root; set user (the family's shared identity is \"pvsuite\") or drop group.";
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
    # through modbus-scraper-cli, and the man pages ride the package
    environment.systemPackages = [ cfg.package ];

    networking.firewall.allowedTCPPorts = lib.mkIf cfg.openFirewall [ listenPort ];

    systemd.services.modbus-scraper = {
      description = "Modbus TCP Prometheus exporter";
      after = [ "network.target" ];
      wantedBy = [ "multi-user.target" ];
      restartIfChanged = true;

      serviceConfig = {
        # everything rides the EnvironmentFile: flag > env > config script
        # > default — the env file occupies the env slot
        ExecStart = "${lib.getExe cfg.package}";
        ExecReload = "${pkgs.util-linux}/bin/kill -HUP $MAINPID";
        EnvironmentFile = [ "${envFile}" ];
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
          && lib.hasPrefix "/run/modbus-scraper/" ctl) {
        # the control socket's directory, owned by the service user (the
        # dynamic user, or the named account)
        RuntimeDirectory = "modbus-scraper";
        RuntimeDirectoryMode = "0755";
      };
    };
  };
}
