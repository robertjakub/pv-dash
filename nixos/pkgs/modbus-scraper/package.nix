{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-scraper";
  version = "0.5.1";

  src = lib.cleanSource ../../../apps/scraper;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus-scraper.py $out/share/modbus-scraper.py
    install -Dm755 ${../../../apps/pvsuite-cli.py} $out/share/modbus-scraper-cli.py
    install -dm755 $out/share/lib
    install -m644 lib/*.py lib/defaults.json lib/metrics.json lib/options.json $out/share/lib/
    install -dm755 $out/share/common
    install -m644 ${../../../common}/*.py $out/share/common/
    install -dm755 $out/share/common/render
    install -m644 ${../../../common}/render/*.py $out/share/common/render/
    install -dm755 $out/share/common/runtime
    install -m644 ${../../../common}/runtime/*.py $out/share/common/runtime/
    install -dm755 $out/share/common/settings
    install -m644 ${../../../common}/settings/*.py $out/share/common/settings/
    install -dm755 $out/share/common/serve
    install -m644 ${../../../common}/serve/*.py $out/share/common/serve/
    install -dm755 $out/share/common/wire
    install -m644 ${../../../common}/wire/*.py $out/share/common/wire/
    install -dm755 $out/share/shared/suite
    install -m644 ${../../../shared}/suite/wire.json $out/share/shared/suite/
    install -m644 ${../../../shared}/suite/texts.json $out/share/shared/suite/
    install -m644 ${../../../shared}/suite/tags.json $out/share/shared/suite/
    install -m644 ${../../../shared}/suite/options.json $out/share/shared/suite/
    install -dm755 $out/share/common/modbus
    install -m644 ${../../../common}/modbus/*.py $out/share/common/modbus/
    install -m644 ${../../../shared}/suite/protocol.json $out/share/shared/suite/
    install -dm755 $out/share/examples
    install -m644 examples/metrics.json examples/modbus-scraper.conf $out/share/examples/
    install -m644 ${../../../extras/examples}/acl-ip-prefix.json $out/share/examples/
    install -Dm644 ${../../../extras/alerts}/scraper.yml $out/share/alerts.yml
    install -Dm644 ${../../../shared}/schema/acl-ip-prefix.schema.json $out/share/shared/schema/acl-ip-prefix.schema.json
    install -Dm644 schema/metrics.schema.json $out/share/schema/metrics.schema.json
    install -dm755 $out/share/profiles
    install -m644 ${../../../shared/profiles}/*.json $out/share/profiles/
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper \
      --add-flags "$out/share/modbus-scraper.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper-cli \
      --add-flags "$out/share/modbus-scraper-cli.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Prometheus exporter for Modbus TCP inverters (stdlib-only Modbus TCP poller) + console-style control CLIs";
    longDescription = ''
      Polls Modbus TCP inverters over FC3/FC4 registers and exposes the
      huawei_*_watts metrics the dashboard expects (the metric names follow
      the dashboard contract), plus health gauges, at /metrics in the
      Prometheus text format. Includes modbus-scraper-cli, the CLI client (one-shot, batch, console)
      clients for the JSON-lines control server (inspect, the live
      settings, request poll now, the config reload, shutdown — the token-signed
      wire). Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-scraper";
    platforms = lib.platforms.unix;
  };
})
