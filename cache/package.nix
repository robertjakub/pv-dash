{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-cache";
  version = "0.0.6";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 src/modbus_cache.py $out/share/modbus-cache/modbus_cache.py
    install -dm755 $out/share/modbus-cache/lib
    install -m644 src/lib/*.py $out/share/modbus-cache/lib/
    install -Dm644 src/modbus_cache.ini $out/share/modbus-cache/modbus_cache.ini
    install -Dm644 src/registers.json $out/share/modbus-cache/registers.json
    makeWrapper ${lib.getExe python3} $out/bin/modbus-cache \
      --add-flags "$out/share/modbus-cache/modbus_cache.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Modbus TCP caching proxy for single-client devices like Huawei SUN2000 inverters (stdlib only, experimental)";
    longDescription = ''
      Owns the one Modbus TCP connection the inverter allows and multiplexes
      it: a background loop polls the configured register ranges at a fixed
      interval while any number of clients connect and are served FC3 reads
      from an in-memory cache. Reads outside the cached ranges and other
      function codes are forwarded to the device (serialized). Python
      standard library only, no third-party dependencies.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-cache";
    platforms = lib.platforms.unix;
  };
})
