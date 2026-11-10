{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-scraper";
  version = "0.4.2";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus-scraper.py $out/share/modbus-scraper/modbus-scraper.py
    install -Dm755 bin/modbus-scraper-ctl.py $out/share/modbus-scraper/modbus-scraper-ctl.py
    install -Dm755 bin/modbus-scraper-cli.py $out/share/modbus-scraper/modbus-scraper-cli.py
    install -dm755 $out/share/modbus-scraper/lib
    install -m644 lib/*.py lib/defaults.json lib/metrics.json lib/options.json $out/share/modbus-scraper/lib/
    install -dm755 $out/share/modbus-scraper/common
    install -m644 ${../common}/*.py $out/share/modbus-scraper/common/
    install -dm755 $out/share/modbus-scraper/common/render
    install -m644 ${../common}/render/*.py $out/share/modbus-scraper/common/render/
    install -dm755 $out/share/modbus-scraper/common/runtime
    install -m644 ${../common}/runtime/*.py $out/share/modbus-scraper/common/runtime/
    install -dm755 $out/share/modbus-scraper/common/settings
    install -m644 ${../common}/settings/*.py $out/share/modbus-scraper/common/settings/
    install -dm755 $out/share/modbus-scraper/common/serve
    install -m644 ${../common}/serve/*.py $out/share/modbus-scraper/common/serve/
    install -dm755 $out/share/modbus-scraper/common/wire
    install -m644 ${../common}/wire/*.py $out/share/modbus-scraper/common/wire/
    install -dm755 $out/share/modbus-scraper/shared
    install -m644 ${../shared}/texts.json $out/share/modbus-scraper/shared/
    install -dm755 $out/share/modbus-scraper/common/modbus
    install -m644 ${../common}/modbus/*.py $out/share/modbus-scraper/common/modbus/
    install -m644 ${../common}/modbus/protocol.json $out/share/modbus-scraper/common/modbus/
    install -Dm644 examples/metrics.json $out/share/modbus-scraper/metrics.json
    install -Dm644 examples/scraper.conf $out/share/modbus-scraper/scraper.conf
    install -Dm644 ${../alerts}/scraper.yml $out/share/modbus-scraper/alerts.yml
    install -Dm644 ${../examples}/acl-ip-prefix.json $out/share/modbus-scraper/acl-ip-prefix.json
    install -Dm644 ${../shared}/schema/acl-ip-prefix.schema.json $out/share/modbus-scraper/acl-ip-prefix.schema.json
    install -dm755 $out/share/modbus-scraper/profiles
    install -m644 ${../profiles/profiles}/*.json $out/share/modbus-scraper/profiles/
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper \
      --add-flags "$out/share/modbus-scraper/modbus-scraper.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper-ctl \
      --add-flags "$out/share/modbus-scraper/modbus-scraper-ctl.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-scraper-cli \
      --add-flags "$out/share/modbus-scraper/modbus-scraper-cli.py"

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
      Prometheus text format. Includes modbus-scraper-ctl and modbus-scraper-cli, CLI
      clients for the JSON-lines control server (inspect, the live
      settings, poll now, the config reload, shutdown — the token-signed
      wire). Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-scraper";
    platforms = lib.platforms.unix;
  };
})
