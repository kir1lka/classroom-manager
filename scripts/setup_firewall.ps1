<#
.SYNOPSIS
    Opens LAN ports in Windows Firewall for Classroom Manager (Teacher & Student)
    so automatic UDP discovery works with dynamic DHCP IPs.
.DESCRIPTION
    Run as Administrator once on the Teacher PC (and optionally on Student PCs).
#>
param(
    [int]$TcpPort = 45455,
    [int]$UdpDiscoveryPort = 45454
)

$ErrorActionPreference = "Stop"

Write-Host "Настройка правил Брандмауэра Windows для Classroom Manager..." -ForegroundColor Cyan

# Remove old rules if re-running
Get-NetFirewallRule -DisplayName "ClassroomManager*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule

New-NetFirewallRule `
    -DisplayName "ClassroomManager TLS TCP ($TcpPort)" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $TcpPort `
    -Profile Private,Domain `
    -Action Allow | Out-Null

New-NetFirewallRule `
    -DisplayName "ClassroomManager LAN Discovery UDP ($UdpDiscoveryPort)" `
    -Direction Inbound `
    -Protocol UDP `
    -LocalPort $UdpDiscoveryPort `
    -Profile Private,Domain `
    -Action Allow | Out-Null

Write-Host "Готово! Порты TCP $TcpPort и UDP $UdpDiscoveryPort открыты для локальной (Частной/Доменной) сети." -ForegroundColor Green
