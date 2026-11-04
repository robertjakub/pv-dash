{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-scraper";
  version = "0.2.1";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 src/scraper.py $out/share/modbus-scraper/scraper.py
    install -dm755 $out/share/modbus-scraper/lib
    install -m644 src/lib/*.py src/lib/static.json $out/share/modbus-scraper/lib/
    install -Dm644 src/metrics.json $out/share/modbus-scraper/metrics.json
    install -dm755 $out/share/modbus-scraper/profiles
    install -m644 ${../profiles}/*.json $out/share/modbus-scraper/profiles/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper \
      --add-flags "$out/share/modbus-scraper/scraper.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Prometheus exporter for Modbus TCP inverters (stdlib-only Modbus TCP poller)";
    longDescription = ''
      Polls Modbus TCP inverters over FC3 holding registers and exposes the
      huawei_*_watts metrics the dashboard expects (the metric names follow
      the dashboard contract), plus health gauges, at /metrics in the
      Prometheus text format. Python standard library only, no third-party
      dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-scraper";
    platforms = lib.platforms.unix;
  };
})
