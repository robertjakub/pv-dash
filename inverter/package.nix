{
  lib,
  stdenv,
  python3,
  makeWrapper,
}:

stdenv.mkDerivation (finalAttrs: {
  pname = "modbus-fake-inverter";
  version = "0.2.0";

  src = lib.cleanSource ./.;

  nativeBuildInputs = [ makeWrapper ];

  strictDeps = true;
  dontConfigure = true;
  dontBuild = true;

  installPhase = ''
    runHook preInstall

    install -Dm755 src/fake_inverter.py $out/share/modbus-fake-inverter/fake_inverter.py
    install -Dm755 src/fake_ctl.py $out/share/modbus-fake-inverter/fake_ctl.py
    install -Dm755 src/fake_cli.py $out/share/modbus-fake-inverter/fake_cli.py
    install -dm755 $out/share/modbus-fake-inverter/lib
    install -m644 src/lib/*.py $out/share/modbus-fake-inverter/lib/
    install -dm755 $out/share/modbus-fake-inverter/profiles
    install -m644 ${../profiles}/*.json $out/share/modbus-fake-inverter/profiles/
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-inverter \
      --add-flags "$out/share/modbus-fake-inverter/fake_inverter.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-ctl \
      --add-flags "$out/share/modbus-fake-inverter/fake_ctl.py"
    makeWrapper ${lib.getExe python3} $out/bin/modbus-fake-cli \
      --add-flags "$out/share/modbus-fake-inverter/fake_cli.py"

    runHook postInstall
  '';

  passthru = {
    skipTests = true;
    inherit (finalAttrs) version;
  };

  meta = {
    description = "Fake Huawei SUN2000 inverter + smart meter (stdlib-only Modbus TCP demo server with runtime control) [experimental]";
    longDescription = ''
      EXPERIMENTAL, work in progress: a Modbus TCP server simulating a Huawei SUN2000 inverter with a
      LUNA2000 battery and a smart meter: day curve or static demo values,
      the modbus-cache diagnostics block, an optional line-protocol control
      server (set/show values at runtime) and seeded chaos injection.
      Includes fake_ctl, a CLI client for the control server. Python
      standard library only.
    '';
    license = lib.licenses.bsd3;
    mainProgram = "modbus-fake-inverter";
    platforms = lib.platforms.unix;
  };
})
