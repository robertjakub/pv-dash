{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "dashboard";
  version = "0.3.0";

  src = lib.cleanSource ./src;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/dashboard $out/bin
    cp -r static $out/share/dashboard/static
    cp -r lib $out/share/dashboard/lib
    install -Dm755 server.py $out/share/dashboard/server.py
    install -Dm644 config.js $out/share/dashboard/config.js
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/

    makeWrapper ${lib.getExe python3} $out/bin/dashboard \
      --add-flags "$out/share/dashboard/server.py"

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
      (dashboard launcher runs server.py; /prom is proxied to the upstream).
    '';
    license = lib.licenses.bsd3;
    mainProgram = "dashboard";
    platforms = lib.platforms.unix;
  };
})
