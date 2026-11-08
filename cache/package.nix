{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-cache";
  version = "0.4.2";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 bin/modbus-cache.py $out/share/modbus-cache/modbus-cache.py
    install -Dm755 bin/modbus-cache-ctl.py $out/share/modbus-cache/modbus-cache-ctl.py
    install -Dm755 bin/modbus-cache-cli.py $out/share/modbus-cache/modbus-cache-cli.py
    install -dm755 $out/share/modbus-cache/lib
    install -m644 lib/*.py lib/static.json lib/options.json $out/share/modbus-cache/lib/
    install -dm755 $out/share/modbus-cache/common
    install -m644 ${../common}/*.py $out/share/modbus-cache/common/
    install -dm755 $out/share/modbus-cache/common/modbus
    install -m644 ${../common}/modbus/*.py $out/share/modbus-cache/common/modbus/
    install -Dm644 examples/modbus_cache.conf $out/share/modbus-cache/modbus_cache.conf
    install -Dm644 examples/selection.json $out/share/modbus-cache/selection.json
    install -Dm644 examples/acl-write-registers.json $out/share/modbus-cache/acl-write-registers.json
    install -Dm644 examples/acl-ip-prefix.json $out/share/modbus-cache/acl-ip-prefix.json
    install -dm755 $out/share/modbus-cache/profiles
    install -m644 ${../profiles/profiles}/*.json $out/share/modbus-cache/profiles/
    install -dm755 $out/share/man/man1
    install -m644 man/*.1 $out/share/man/man1/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache \
      --add-flags "$out/share/modbus-cache/modbus-cache.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache-ctl \
      --add-flags "$out/share/modbus-cache/modbus-cache-ctl.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache-cli \
      --add-flags "$out/share/modbus-cache/modbus-cache-cli.py"

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
      modbus-cache-ctl and modbus-cache-cli, CLI clients for the JSON-lines control
      server. Python standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-cache";
    platforms = lib.platforms.unix;
  };
})
