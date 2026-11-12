# The sandbox verification (docs/TODO.md's "the systemd unit hardening
# review"): both family units run inside a NixOS VM and are scored with
# systemd-analyze security — the hardened sandbox must land in the low
# exposure band (the default for an unprotected service is ~9.6; the suite's
# strict sandbox targets under 2.0). A second node runs the cache under the
# family's shared static account (`user`/`group` = pvsuite — the module
# creates it, the unit renders User=/Group= instead of the DynamicUser).
# Runs on Linux only (a VM); `nix flake check` picks it up there, darwin
# evaluates and skips it.
{ pkgs }:

pkgs.testers.nixosTest (
  let
    # the units must not merely run — they must run sandboxed: every knob of
    # the hardening pass asserted from the live unit config, then the score
    assertHardened = unit: ''
      out = machine.succeed("systemctl show ${unit} -p CapabilityBoundingSet --value")
      assert out.strip() == "", "${unit}: CapabilityBoundingSet is not empty: " + out
      for prop in ("ProtectSystem=strict", "PrivateTmp=yes", "PrivateDevices=yes", "ProtectHome=yes",
                   "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectKernelLogs=yes",
                   "ProtectControlGroups=yes", "ProtectClock=yes", "ProtectHostname=yes",
                   "ProtectProc=invisible", "RestrictNamespaces=yes", "RestrictRealtime=yes",
                   "RestrictSUIDSGID=yes", "LockPersonality=yes", "MemoryDenyWriteExecute=yes",
                   "NoNewPrivileges=yes", "SystemCallArchitectures=native"):
          out = machine.succeed("systemctl show ${unit} -p %s --value" % prop.split("=")[0]).strip()
          want = prop.split("=")[1]
          assert out == want, "${unit}: %s is %r, expected %r" % (prop, out, want)
      fams = machine.succeed("systemctl show ${unit} -p RestrictAddressFamilies --value").split()
      for fam in ("AF_INET", "AF_INET6", "AF_UNIX"):
          assert fam in fams, "${unit}: RestrictAddressFamilies lacks %s" % fam
      filt = machine.succeed("systemctl show ${unit} -p SystemCallFilter --value")
      assert "@system-service" in filt, "${unit}: SystemCallFilter lacks @system-service"
    '';
  in
  {
    name = "pv-suite-hardening";

    nodes.machine =
      { lib, pkgs, ... }:
      {
        imports = [
          ../modules/modbus-cache.nix
          ../modules/modbus-scraper.nix
          ../modules/dashboard.nix
        ];
        # the raw modules (no flake wrapper) — the packages named explicitly
        services.modbus-cache = {
          enable = true;
          package = pkgs.callPackage ../pkgs/modbus-cache/package.nix { };
          settings = {
            LISTEN = "127.0.0.1:15502";
            # the audit trail to the journal: the hardened service has no
            # XDG state home (ProtectHome + DynamicUser)
            AUDIT_LOG = "-";
          };
        };
        services.modbus-scraper = {
          enable = true;
          package = pkgs.callPackage ../pkgs/modbus-scraper/package.nix { };
          settings = {
            LISTEN = "127.0.0.1:9350";
            AUDIT_LOG = "-";
            # the control surface over the unix socket under /run (PrivateTmp
            # makes /tmp private) — the sockets must be reachable for the ctl
            CTL = "/run/modbus-scraper/control.socket";
          };
        };
        services.dashboard = {
          enable = true;
          package = pkgs.callPackage ../pkgs/dashboard/package.nix { };
          settings = {
            LISTEN = "127.0.0.1:8080";
            AUDIT_LOG = "-";
            CTL = "/run/dashboard/control.socket";
          };
        };
        virtualisation.graphics = false;
      };

    # the static-account node: the cache under the family's shared pvsuite
    # identity — the module auto-creates the account and the unit drops the
    # DynamicUser for User=/Group= (the sandbox knobs are the same)
    nodes.static =
      { lib, pkgs, ... }:
      {
        imports = [ ../modules/modbus-cache.nix ];
        services.modbus-cache = {
          enable = true;
          package = pkgs.callPackage ../pkgs/modbus-cache/package.nix { };
          user = "pvsuite";
          group = "pvsuite";
          settings = {
            LISTEN = "127.0.0.1:15502";
            AUDIT_LOG = "-";
            CTL = "/run/modbus-cache/control.socket";
          };
        };
        virtualisation.graphics = false;
      };

    testScript = ''
      machine.start()
      machine.wait_for_unit("modbus-cache.service", timeout=90)
      machine.wait_for_unit("modbus-scraper.service", timeout=90)
      machine.wait_for_unit("dashboard.service", timeout=90)
      machine.wait_until_succeeds("ctl=$(ls /run/modbus-scraper/control.socket /run/dashboard/control.socket 2>/dev/null) && [ -S $ctl ]", timeout=30)

      ${assertHardened "modbus-cache.service"}
      ${assertHardened "modbus-scraper.service"}
      ${assertHardened "dashboard.service"}

      # the exposure scores: a number per unit in the check output, the
      # hardened sandbox must stay in the low band (0.0 = sealed, 10.0 =
      # unprotected; 9.6 is what the stock service config scores)
      for unit in ("modbus-cache.service", "modbus-scraper.service", "dashboard.service"):
          out = machine.succeed("systemd-analyze security %s --no-pager" % unit)
          line = [l for l in out.splitlines() if "Overall exposure level" in l][-1]
          score = float(line.split(":")[1].split()[0])
          print("%s exposure: %.2f" % (unit, score))
          assert score < 2.0, "%s too exposed: %.2f (%s)" % (unit, score, line)

      # the static-account node: the cache runs as pvsuite/pvsuite — the
      # module created the account, the unit renders User=/Group= instead of
      # the DynamicUser, and the RuntimeDirectory is owned by the account
      static.start()
      static.wait_for_unit("modbus-cache.service", timeout=90)
      static.wait_until_succeeds("test -S /run/modbus-cache/control.socket", timeout=30)
      assert static.succeed("systemctl show modbus-cache -p User --value").strip() == "pvsuite"
      assert static.succeed("systemctl show modbus-cache -p Group --value").strip() == "pvsuite"
      assert static.succeed("systemctl show modbus-cache -p DynamicUser --value").strip() == "no"
      assert static.succeed("stat -c %U:%G /run/modbus-cache").strip() == "pvsuite:pvsuite"
      static.succeed("/run/current-system/sw/bin/modbus-cache-cli --control-port /run/modbus-cache/control.socket show version")

      # the services still serve their surfaces sandboxed: the control
      # sockets speak (the ctl inside the VM), the metrics answer, the
      # dashboard page loads
      machine.succeed("/run/current-system/sw/bin/modbus-scraper-cli --control-port /run/modbus-scraper/control.socket show version")
      machine.succeed("/run/current-system/sw/bin/dashboard-cli --control-port /run/dashboard/control.socket show version")
      machine.succeed("curl -fsS http://127.0.0.1:9350/metrics | head -1")
      machine.succeed("curl -fsS http://127.0.0.1:8080/ | head -1")
    '';
  }
)
