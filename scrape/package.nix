{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "sun2000-scraper";
  version = "0.0.3";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 src/scraper.py $out/share/sun2000-scraper/scraper.py
    install -Dm644 src/metrics.json $out/share/sun2000-scraper/metrics.json
    install -Dm755 src/fake_inverter.py $out/share/sun2000-scraper/fake_inverter.py
    makeWrapper ${lib.getExe python3} $out/bin/sun2000-scraper \
      --add-flags "$out/share/sun2000-scraper/scraper.py"
    makeWrapper ${lib.getExe python3} $out/bin/sun2000-fake-inverter \
      --add-flags "$out/share/sun2000-scraper/fake_inverter.py"

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
    mainProgram = "sun2000-scraper";
    platforms = lib.platforms.unix;
  };
})
