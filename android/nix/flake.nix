{
  description = "VOX Android companion app: pinned Android SDK, emulator, JDK and Gradle via nixpkgs androidenv";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        config = {
          allowUnfree = true;
          # Android SDK licences are accepted ONLY through androidenv's own mechanism (nixpkgs config).
          # See README.md "Licences".
          android_sdk.accept_license = true;
        };
      };
      sdk = import ./sdk.nix { inherit pkgs; };
    in {
      packages.${system} = {
        androidsdk = sdk.androidsdk;
        default = sdk.androidsdk;
      };
      devShells.${system}.default = import ./shell.nix { inherit pkgs sdk; };
    };
}
