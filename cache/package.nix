{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-cache";
  version = "0.2.1";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus_cache.py $out/share/modbus-cache/modbus_cache.py
    install -Dm755 bin/cache_ctl.py $out/share/modbus-cache/cache_ctl.py
    install -Dm755 bin/cache_cli.py $out/share/modbus-cache/cache_cli.py
    install -dm755 $out/share/modbus-cache/lib
    install -m644 lib/*.py lib/static.json $out/share/modbus-cache/lib/
    install -Dm644 modbus_cache.ini $out/share/modbus-cache/modbus_cache.ini
    install -Dm644 selection.json $out/share/modbus-cache/selection.json
    install -dm755 $out/share/modbus-cache/profiles
    install -m644 ${../profiles}/*.json $out/share/modbus-cache/profiles/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache \
      --add-flags "$out/share/modbus-cache/modbus_cache.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache-ctl \
      --add-flags "$out/share/modbus-cache/cache_ctl.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache-cli \
      --add-flags "$out/share/modbus-cache/cache_cli.py"

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
      cache_ctl and cache_cli, CLI clients for the JSON-lines control
      server. Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-cache";
    platforms = lib.platforms.unix;
  };
})
