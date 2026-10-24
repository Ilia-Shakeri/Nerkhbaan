import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const verifier = path.resolve(import.meta.dirname, 'verify-windows-signature.ps1');
const quote = value => `'${value.replaceAll("'", "''")}'`;
const thumbprint = 'A'.repeat(40);

// Synthetic signatures exercise policy only; they prove no publisher trust.
function runCase(options = {}) {
  const directory = mkdtempSync(path.join(tmpdir(), 'nerkhbaan-signature-policy-'));
  try {
    const artifact = path.join(directory, 'fixture.exe');
    const receipt = path.join(directory, 'receipt.json');
    writeFileSync(artifact, 'unsigned policy fixture');
    if (options.existing) writeFileSync(receipt, 'prior-result');
    const mock = options.native ? '' : `
${options.productVersion ? `function Get-Item {
  param($LiteralPath)
  $file = Microsoft.PowerShell.Management\\Get-Item -LiteralPath $LiteralPath
  [pscustomobject]@{PSIsContainer=$false; FullName=$file.FullName; Name=$file.Name; Length=$file.Length; VersionInfo=[pscustomobject]@{ProductVersion='${options.productVersion}'}}
}` : ''}
function Get-AuthenticodeSignature {
  param($LiteralPath)
  ${options.changed ? "[IO.File]::AppendAllText($LiteralPath, 'changed')" : ''}
  [pscustomobject]@{
    Status = '${options.status ?? 'Valid'}'; SignatureType = 'Authenticode'
    SignerCertificate = [pscustomobject]@{
      Subject = 'CN=Policy Fixture'; Issuer = '${options.selfSigned ? 'CN=Policy Fixture' : 'CN=Fixture Issuer'}'
      Thumbprint = '${thumbprint}'
      Extensions = @([pscustomobject]@{
        Oid = [pscustomobject]@{Value='2.5.29.37'}
        EnhancedKeyUsages = @([pscustomobject]@{Value='${options.noEku ? '1.2.3' : '1.3.6.1.5.5.7.3.3'}'})
      })
    }
    TimeStamperCertificate = ${options.noTimestamp ? '$null' : "[pscustomobject]@{Subject='CN=Fixture Timestamp'}"}
  }
}`;
    const script = `${mock}
& ${quote(verifier)} -ArtifactPath ${quote(artifact)} -ExpectedPublisher ${quote(options.publisher ?? 'CN=Policy Fixture')} -ExpectedSignerThumbprint '${options.wrongThumbprint ? 'B'.repeat(40) : thumbprint}' ${options.version ? "-ExpectedVersion '2.8.13'" : ''} -ReceiptPath ${quote(receipt)}
exit $LASTEXITCODE`;
    const runner = path.join(directory, 'runner.ps1');
    writeFileSync(runner, `$ErrorActionPreference = 'Stop'
Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1"
Import-Module "$PSHOME/Modules/Microsoft.PowerShell.Security/Microsoft.PowerShell.Security.psd1"
${script}`);
    const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-File', runner], { encoding: 'utf8', timeout: 30_000 });
    assert.ifError(result.error);
    assert.notEqual(result.status, null, result.stderr);
    const content = readFileSync(receipt, 'utf8');
    return { status: result.status, content, stderr: result.stderr, receipt: options.existing ? null : JSON.parse(content) };
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

const windowsOnly = { skip: process.platform !== 'win32' };
test('synthetic policy control accepts all required attributes', windowsOnly, () => {
  const result = runCase();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.receipt.accepted, true);
});
for (const productVersion of ['2.8.13', '2.8.13.0']) {
  test(`synthetic policy accepts product version ${productVersion}`, windowsOnly, () => {
    const result = runCase({ version: true, productVersion });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.receipt.artifacts[0].version_matches, true);
    assert.equal(result.receipt.accepted, true);
  });
}
for (const [name, options] of [
  ['untrusted signature', { status: 'NotTrusted' }],
  ['wrong publisher', { publisher: 'CN=Other Publisher' }],
  ['wrong thumbprint', { wrongThumbprint: true }],
  ['missing signing EKU', { noEku: true }],
  ['missing timestamp', { noTimestamp: true }],
  ['self-signed leaf', { selfSigned: true }],
  ['wrong or absent product version', { version: true }],
  ['nonzero Windows revision', { version: true, productVersion: '2.8.13.1' }],
  ['previous release product version', { version: true, productVersion: '2.8.12.0' }],
  ['artifact changed during inspection', { changed: true }],
  ['actual unsigned file with native trust inspection', { native: true }],
]) {
  test(`rejects ${name}`, windowsOnly, () => {
    const result = runCase(options);
    assert.notEqual(result.status, 0);
    assert.equal(result.receipt.artifacts.length, 1, result.stderr);
    assert.equal(result.receipt.accepted, false);
  });
}
test('existing receipt remains byte-identical', windowsOnly, () => {
  const result = runCase({ existing: true });
  assert.notEqual(result.status, 0);
  assert.equal(result.content, 'prior-result');
});
