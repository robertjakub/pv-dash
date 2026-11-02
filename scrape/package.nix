{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-scraper";
  version = "0.0.6";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 src/scraper.py $out/share/modbus-scraper/scraper.py
    install -dm755 $out/share/modbus-scraper/lib
    install -m644 src/lib/*.py $out/share/modbus-scraper/lib/
    install -Dm644 src/metrics.json $out/share/modbus-scraper/metrics.json
    install -Dm755 src/fake_inverter.py $out/share/modbus-scraper/fake_inverter.py
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper \
      --add-flags "$out/share/modbus-scraper/scraper.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-inverter \
      --add-flags "$out/share/modbus-scraper/fake_inverter.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Prometheus exporter for Huawei SUN2000 inverters (stdlib-only Modbus TCP poller)";
    longDescription = ''
      Polls Huawei SUN2000 PV inverters over Modbus TCP (FC3 holding
      registers) and exposes the huawei_*_watts metrics the pv-dashboard
      expects, plus sun2000_up health gauges, at /metrics in the Prometheus
      text format. Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-scraper";
    platforms = lib.platforms.unix;
  };
})
