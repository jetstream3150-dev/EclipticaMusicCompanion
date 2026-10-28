param(
  [Parameter(Mandatory=$true)][string] $ZipFile,
  [Parameter(Mandatory=$true)][string] $PublicKeyFile,
  [Parameter(Mandatory=$true)][string] $OutputFile
)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Security.Cryptography;

public static class PrivatePreviewCrypto {
    public static void Encrypt(string zipFile, string publicKeyFile, string outputFile) {
        byte[] key = RandomNumberGenerator.GetBytes(32);
        try {
            using (RSA rsa = RSA.Create()) {
                rsa.ImportFromPem(File.ReadAllText(publicKeyFile));
                if (rsa.KeySize != 3072) throw new InvalidOperationException("Unexpected public key size.");
                byte[] wrappedKey = rsa.Encrypt(key, RSAEncryptionPadding.OaepSHA256);
                if (wrappedKey.Length != 384) throw new InvalidOperationException("Unexpected wrapped key size.");
                byte[] nonce = RandomNumberGenerator.GetBytes(12);
                byte[] plain = File.ReadAllBytes(zipFile);
                byte[] cipher = new byte[plain.Length];
                byte[] tag = new byte[16];
                using (AesGcm aes = new AesGcm(key, 16)) {
                    aes.Encrypt(nonce, plain, cipher, tag);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(outputFile));
                using (FileStream output = new FileStream(outputFile, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                    byte[] magic = new byte[] { 69, 67, 80, 49 };
                    output.Write(magic, 0, magic.Length);
                    output.Write(wrappedKey, 0, wrappedKey.Length);
                    output.Write(nonce, 0, nonce.Length);
                    output.Write(tag, 0, tag.Length);
                    output.Write(cipher, 0, cipher.Length);
                }
            }
        } finally {
            CryptographicOperations.ZeroMemory(key);
        }
    }
}
'@
[PrivatePreviewCrypto]::Encrypt(
  (Resolve-Path -LiteralPath $ZipFile).Path,
  (Resolve-Path -LiteralPath $PublicKeyFile).Path,
  $OutputFile
)
Write-Host 'Encrypted transfer package created; no plaintext application files are uploaded.'
