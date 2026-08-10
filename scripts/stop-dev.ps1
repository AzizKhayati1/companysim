<#
.SYNOPSIS
    Stop the companysim dev servers.

.DESCRIPTION
    Kills whatever holds ports 8611 and 5173.

    By port, never by process name. `Stop-Process -Name node,python` on a
    dev box takes out unrelated language servers, editors and terminals
    that happen to share a runtime — the port is the only thing that
    identifies *these* servers specifically.

.EXAMPLE
    .\scripts\stop-dev.ps1
    .\scripts\stop-dev.ps1 -ApiOnly
#>
[CmdletBinding()]
param(
    [switch]$ApiOnly,
    [switch]$WebOnly
)

$ports = @()
if (-not $WebOnly) { $ports += 8611 }
if (-not $ApiOnly) { $ports += 5173 }

foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host ("port {0}: nothing listening" -f $port) -ForegroundColor DarkGray
        continue
    }
    # Not $pid — that is a PowerShell automatic variable holding *this*
    # process's id, and assigning to it in the loop is an error.
    foreach ($procId in ($conns.OwningProcess | Select-Object -Unique)) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($proc) { $name = $proc.ProcessName } else { $name = "?" }
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host ("port {0}: killed {1} (pid {2})" -f $port, $name, $procId) -ForegroundColor Green
        } catch {
            Write-Host ("port {0}: could not kill pid {1} - {2}" -f $port, $procId, $_.Exception.Message) -ForegroundColor Red
        }
    }
}
