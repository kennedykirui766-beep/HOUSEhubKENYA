# PowerShell installer for git hooks (Windows-friendly)
# Run in repository root: .\install-git-hooks.ps1

Param()

Write-Host "Setting git core.hooksPath to .githooks"
git config core.hooksPath .githooks

if (Test-Path -Path .githooks) {
    Write-Host "Attempting to unblock hook files..."
    Get-ChildItem -Path .githooks -File | ForEach-Object {
        try { Unblock-File -Path $_.FullName } catch {}
    }
    Write-Host "Hooks path set. To enable hooks in other clones run: git config core.hooksPath .githooks"
} else {
    Write-Host ".githooks directory not found. Ensure .githooks exists in the repo." -ForegroundColor Yellow
}
