<#
.SYNOPSIS
  Get an access token for a demo user, for testing the service or running `aurai-knowledge eval --url`.

.DESCRIPTION
  The workspace client (open-webui) deliberately has direct access grants off, so it cannot be used here.
  Create a separate test client in a NON-PRODUCTION realm: confidential, direct access grants on, the same
  groups and audience mappers as open-webui. Pass its id and secret. The password is read from the prompt and
  never written to disk.
#>
param(
  [Parameter(Mandatory)][string]$Username,
  [Parameter(Mandatory)][string]$ClientId,
  [string]$ClientSecret = $env:TEST_CLIENT_SECRET,
  [string]$KeycloakUrl = "http://localhost:8080",
  [string]$Realm = "aurai"
)
$ErrorActionPreference = "Stop"
$password = Read-Host -Prompt "Password for $Username" -AsSecureString
$plain = [System.Net.NetworkCredential]::new("", $password).Password
$body = @{ grant_type = "password"; client_id = $ClientId; client_secret = $ClientSecret; username = $Username; password = $plain }
$response = Invoke-RestMethod -Method Post -Uri "$KeycloakUrl/realms/$Realm/protocol/openid-connect/token" -Body $body
$response.access_token
