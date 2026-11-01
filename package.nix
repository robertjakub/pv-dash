{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "pv-dashboard";
  version = "0.0.1";

  src = lib.cleanSource ./src;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/pv-dashboard $out/bin
    cp -r static $out/share/pv-dashboard/static
    install -Dm755 server.py $out/share/pv-dashboard/server.py
    install -Dm644 config.js $out/share/pv-dashboard/config.js

    makeWrapper ${lib.getExe python3} $out/bin/pv-dashboard \
      --add-flags "$out/share/pv-dashboard/server.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    updateScript = null; # no upstream releases; version bumps are manual
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Single-page home PV monitoring dashboard with a Prometheus proxy";
    longDescription = ''
      Static single-page dashboard (energy flow diagram, energy summary and
      chart) fed by Prometheus through the bundled stdlib-only proxy server
      (pv-dashboard launcher runs server.py; /prom is proxied to the upstream).
    '';
    license = lib.licenses.bsd3;
    mainProgram = "pv-dashboard";
    platforms = lib.platforms.unix;
  };
})
