"""Read locally encrypted credentials into process memory; never log the values."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_local_credentials(version):
    if version not in (2, 3):
        raise ValueError("Unsupported API version")
    configured=os.environ.get('ENVERUS_CREDENTIAL_PATH')
    path = Path(configured) if configured else ROOT / "Xml" / "LocalCredentials" / f"EnverusV{version}.xml"
    if not path.exists():
        return None
    if os.name != "nt":
        raise RuntimeError("Local credentials require the original Windows account.")
    # Only a file path goes into the child environment. Decrypted output is captured,
    # not sent to the terminal, and is never included in an exception message.
    script = r"""
$ErrorActionPreference = 'Stop'
try {
    $saved = Import-Clixml -LiteralPath $env:ENVERUS_CREDENTIAL_PATH
    $fields = if ($saved.ApiVersion -eq '3') { @('SecretKey') } else { @('ApiKey','ClientId','ClientSecret') }
    $result = @{}
    foreach ($name in $fields) {
        if ($saved.$name -isnot [System.Security.SecureString]) { exit 2 }
        $result[$name] = ([System.Net.NetworkCredential]::new('', $saved.$name)).Password
    }
    $result | ConvertTo-Json -Compress
} catch { exit 1 }
"""
    environment = os.environ.copy()
    environment["ENVERUS_CREDENTIAL_PATH"] = str(path)
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    completed = subprocess.run(
        [str(shell), "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, env=environment, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if completed.returncode:
        raise RuntimeError("Could not decrypt local credentials under this Windows account.")
    try:
        values = json.loads(completed.stdout)
    except ValueError:
        raise RuntimeError("Local credential reader returned an invalid response.") from None
    expected = ("SecretKey",) if version == 3 else ("ApiKey", "ClientId", "ClientSecret")
    if any(not isinstance(values.get(name), str) or not values[name] for name in expected):
        raise RuntimeError("Local credential fields are missing or empty.")
    return values
