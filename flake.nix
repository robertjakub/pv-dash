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
          dashboard = pkgs.callPackage ./dashboard/package.nix { };
          modbus-scraper = pkgs.callPackage ./scraper/package.nix { };
          modbus-cache = pkgs.callPackage ./cache/package.nix { };
          modbus-fake-inverter = pkgs.callPackage ./inverter/package.nix { };
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
        dashboard = final: _prev: { dashboard = final.callPackage ./dashboard/package.nix { }; };
        default = self.overlays.dashboard;
      };

      nixosModules = {
        dashboard = import ./dashboard/module.nix;
        modbus-scraper = import ./scraper/module.nix;
        modbus-cache = import ./cache/module.nix;
        default = self.nixosModules.dashboard;
      };
    };
}
