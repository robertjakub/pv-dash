{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-cache";
  version = "0.5.0";

  src = lib.cleanSource ../../../apps/cache;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus-cache.py $out/share/modbus-cache.py
    install -Dm755 ${../../../apps/pvsuite-cli.py} $out/share/modbus-cache-cli.py
    install -dm755 $out/share/lib
    install -m644 lib/*.py lib/defaults.json lib/options.json $out/share/lib/
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
    install -m644 examples/modbus-cache.conf $out/share/examples/
    install -m644 ${../../../extras/examples}/modbus-cache-filter.json ${../../../extras/examples}/acl-write-registers.json ${../../../extras/examples}/acl-ip-prefix.json $out/share/examples/
    install -dm755 $out/share/shared/schema
    install -m644 ${../../../shared}/schema/acl-write-registers.schema.json ${../../../shared}/schema/acl-ip-prefix.schema.json ${../../../shared}/schema/modbus-cache-filter.schema.json $out/share/shared/schema/
    install -Dm644 ${../../../extras/alerts}/cache.yml $out/share/alerts.yml
    install -dm755 $out/share/profiles
    install -m644 ${../../../shared/profiles}/*.json $out/share/profiles/
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache \
      --add-flags "$out/share/modbus-cache.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache-cli \
      --add-flags "$out/share/modbus-cache-cli.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Modbus TCP caching proxy for single-client devices (stdlib only, experimental) + console-style control CLIs";
    longDescription = ''
      Owns the one Modbus TCP connection the inverter allows and multiplexes
      it: a background loop polls the configured register ranges at a fixed
      interval while any number of clients connect and are served FC3 reads
      from an in-memory cache. Reads outside the cached ranges and other
      function codes are forwarded to the device (serialized). Includes
      modbus-cache-cli, the CLI client (one-shot, batch, console) for the JSON-lines control
      server. Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-cache";
    platforms = lib.platforms.unix;
  };
})
