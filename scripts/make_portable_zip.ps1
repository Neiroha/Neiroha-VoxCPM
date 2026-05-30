[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$Script = Join-Path $PSScriptRoot "make_portable_7z.ps1"
& $Script @RemainingArgs
exit $LASTEXITCODE
