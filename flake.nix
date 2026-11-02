{
  description = "Single-page home PV monitoring dashboard with a Prometheus proxy";

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
          pv-dashboard = pkgs.callPackage ./package.nix { };
          modbus-scraper = pkgs.callPackage ./scrape/package.nix { };
          modbus-cache = pkgs.callPackage ./cache/package.nix { };
          default = self.packages.${system}.pv-dashboard;
        }
      );

      apps = forAllSystems (system: {
        pv-dashboard = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/pv-dashboard";
        };
        modbus-scraper = {
          type = "app";
          program = "${self.packages.${system}.modbus-scraper}/bin/modbus-scraper";
        };
        modbus-cache = {
          type = "app";
          program = "${self.packages.${system}.modbus-cache}/bin/modbus-cache";
        };
        default = self.apps.${system}.pv-dashboard;
      });

      overlays = {
        pv-dashboard = final: _prev: { pv-dashboard = final.callPackage ./package.nix { }; };
        default = self.overlays.pv-dashboard;
      };

      nixosModules = {
        pv-dashboard = import ./module.nix;
        modbus-scraper = import ./scrape/module.nix;
        modbus-cache = import ./cache/module.nix;
        default = self.nixosModules.pv-dashboard;
      };
    };
}
