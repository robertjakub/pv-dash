{
  description = "pv-suite — a family of home-PV tools: dashboard, Modbus scraper, cache proxy, fake inverter";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      forAllSystems = nixpkgs.lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          dashboard = pkgs.callPackage ./nixos/pkgs/dashboard/package.nix { };
          modbus-scraper = pkgs.callPackage ./nixos/pkgs/modbus-scraper/package.nix { };
          modbus-cache = pkgs.callPackage ./nixos/pkgs/modbus-cache/package.nix { };
          modbus-fake-inverter = pkgs.callPackage ./nixos/pkgs/modbus-fake-inverter/package.nix { };
          default = self.packages.${system}.dashboard;
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        nixpkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # the sandbox pass, verified in a VM: both units scored with
          # systemd-analyze security (tests/hardening.nix)
          hardening = pkgs.callPackage ./tests/hardening.nix { };
        }
      );

      apps = forAllSystems (system: {
        dashboard = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/dashboard";
        };
        modbus-scraper = {
          type = "app";
          program = "${self.packages.${system}.modbus-scraper}/bin/modbus-scraper";
        };
        modbus-cache = {
          type = "app";
          program = "${self.packages.${system}.modbus-cache}/bin/modbus-cache";
        };
        modbus-fake-inverter = {
          type = "app";
          program = "${self.packages.${system}.modbus-fake-inverter}/bin/modbus-fake-inverter";
        };
        default = self.apps.${system}.dashboard;
      });

      overlays = {
        pv-suite = final: _prev: {
          dashboard = final.callPackage ./nixos/pkgs/dashboard/package.nix { };
          modbus-scraper = final.callPackage ./nixos/pkgs/modbus-scraper/package.nix { };
          modbus-cache = final.callPackage ./nixos/pkgs/modbus-cache/package.nix { };
          modbus-fake-inverter = final.callPackage ./nixos/pkgs/modbus-fake-inverter/package.nix { };
        };
        default = self.overlays.pv-suite;
      };

      # the modules ship default-free (the nixpkgs shape — the file is
      # contributed verbatim); the flake's wrappers carry the in-repo
      # package defaults, mkDefault keeps a user override winning
      nixosModules = {
        dashboard = {
          pkgs, lib, ...
        }: {
          imports = [ ./nixos/modules/dashboard.nix ];
          services.dashboard.package = lib.mkDefault (pkgs.callPackage ./nixos/pkgs/dashboard/package.nix { });
        };
        modbus-scraper = {
          pkgs, lib, ...
        }: {
          imports = [ ./nixos/modules/modbus-scraper.nix ];
          services.modbus-scraper.package = lib.mkDefault (pkgs.callPackage ./nixos/pkgs/modbus-scraper/package.nix { });
        };
        modbus-cache = {
          pkgs, lib, ...
        }: {
          imports = [ ./nixos/modules/modbus-cache.nix ];
          services.modbus-cache.package = lib.mkDefault (pkgs.callPackage ./nixos/pkgs/modbus-cache/package.nix { });
        };
        default = self.nixosModules.dashboard;
      };
    };
}
