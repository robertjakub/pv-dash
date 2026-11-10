{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "dashboard";
  version = "0.4.2";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/dashboard.py $out/share/dashboard/dashboard.py
    install -Dm755 bin/dashboard-ctl.py $out/share/dashboard/dashboard-ctl.py
    install -Dm755 bin/dashboard-cli.py $out/share/dashboard/dashboard-cli.py
    install -dm755 $out/share/dashboard/lib
    install -m644 lib/*.py lib/defaults.json lib/options.json $out/share/dashboard/lib/
    install -dm755 $out/share/dashboard/common
    install -m644 ${../common}/*.py $out/share/dashboard/common/
    install -dm755 $out/share/dashboard/common/render
    install -m644 ${../common}/render/*.py $out/share/dashboard/common/render/
    install -dm755 $out/share/dashboard/common/runtime
    install -m644 ${../common}/runtime/*.py $out/share/dashboard/common/runtime/
    install -dm755 $out/share/dashboard/common/settings
    install -m644 ${../common}/settings/*.py $out/share/dashboard/common/settings/
    install -dm755 $out/share/dashboard/common/serve
    install -m644 ${../common}/serve/*.py $out/share/dashboard/common/serve/
    install -dm755 $out/share/dashboard/common/wire
    install -m644 ${../common}/wire/*.py $out/share/dashboard/common/wire/
    install -dm755 $out/share/dashboard/shared
    install -m644 ${../shared}/texts.json $out/share/dashboard/shared/
    install -dm755 $out/share/dashboard/common/modbus
    install -m644 ${../common}/modbus/*.py $out/share/dashboard/common/modbus/
    cp -r static $out/share/dashboard/static
    install -Dm644 examples/config.js $out/share/dashboard/config.js
    install -Dm644 examples/server.conf $out/share/dashboard/server.conf
    install -Dm644 ${../examples}/acl-ip-prefix.json $out/share/dashboard/acl-ip-prefix.json
    install -Dm644 ${../shared}/schema/acl-ip-prefix.schema.json $out/share/dashboard/acl-ip-prefix.schema.json
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/

    makeWrapper ${lib.getExe python3} $out/bin/dashboard \
      --add-flags "$out/share/dashboard/dashboard.py"
    makeWrapper ${lib.getExe python3} $out/bin/dashboard-ctl \
      --add-flags "$out/share/dashboard/dashboard-ctl.py"
    makeWrapper ${lib.getExe python3} $out/bin/dashboard-cli \
      --add-flags "$out/share/dashboard/dashboard-cli.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    updateScript = null; # no upstream releases; version bumps are manual
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Single-page home PV monitoring dashboard with a Prometheus proxy + console-style control CLIs";
    longDescription = ''
      Static single-page dashboard (energy flow diagram, energy summary and
      chart) fed by Prometheus through the bundled stdlib-only proxy server
      (/prom is proxied to the upstream). Includes dashboard-ctl and
      dashboard-cli, CLI clients for the JSON-lines control server (inspect,
      the live settings, the config reload, shutdown — the token-signed
      wire). Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "dashboard";
    platforms = lib.platforms.unix;
  };
})
