<#
.SYNOPSIS
Creates a safe Label OS development branch.

.DESCRIPTION
Builds a branch name from a branch type, optional ticket number, and short
description. The script validates inputs, requires a clean working tree,
updates the source branch with a fast-forward-only pull, refuses local or
remote branch name collisions, creates the branch, and asks before pushing it.

Source branch rules:
- all development branches start from main.

.EXAMPLE
./scripts/new-branch.ps1 -Type feat -Ticket LOS-107 -Description "Artist profile API"

Creates:
feat/los-107-artist-profile-api
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Type,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Description,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$Ticket
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$allowedTypes = @(
    "feat",
    "fix",
    "hotfix",
    "refactor",
    "docs",
    "test",
    "chore",
    "ci",
    "infra",
    "build",
    "perf"
)

function Write-Failure {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Error "new-branch: $Message"
}

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $false)]
        [string]$FailureMessage = "Git command failed: git $($Arguments -join ' ')"
    )

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw $FailureMessage
    }
}

function Test-GitSuccess {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & git @Arguments *> $null
    return $LASTEXITCODE -eq 0
}

function ConvertTo-BranchSegment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value,

        [Parameter(Mandatory = $true)]
        [string]$FieldName
    )

    $trimmed = $Value.Trim()
    if ($trimmed.Length -eq 0) {
        Write-Failure "$FieldName cannot be empty."
    }

    if ($trimmed -notmatch "^[A-Za-z0-9][A-Za-z0-9 _-]*[A-Za-z0-9]$|^[A-Za-z0-9]$") {
        Write-Failure "$FieldName may contain only letters, numbers, spaces, underscores, and hyphens, and must start and end with a letter or number."
    }

    $lower = $trimmed.ToLowerInvariant()
    $segment = $lower -replace "[ _-]+", "-"
    $segment = $segment.Trim("-")

    if ($segment.Length -eq 0) {
        Write-Failure "$FieldName did not produce a usable branch segment."
    }

    return $segment
}

function ConvertTo-TicketSegment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    $trimmed = $Value.Trim()
    if ($trimmed.Length -eq 0) {
        Write-Failure "Ticket cannot be empty."
    }

    if ($trimmed -notmatch "^[A-Za-z0-9][A-Za-z0-9_-]*[A-Za-z0-9]$|^[A-Za-z0-9]$") {
        Write-Failure "Ticket may contain only letters, numbers, underscores, and hyphens, and must start and end with a letter or number."
    }

    return ($trimmed.ToLowerInvariant() -replace "[_-]+", "-").Trim("-")
}

try {
    $normalizedType = $Type.Trim().ToLowerInvariant()
    if ($allowedTypes -notcontains $normalizedType) {
        Write-Failure "Invalid branch type '$Type'. Allowed types: $($allowedTypes -join ', ')."
    }

    $descriptionSegment = ConvertTo-BranchSegment -Value $Description -FieldName "Description"
    $nameParts = @()

    if ($PSBoundParameters.ContainsKey("Ticket")) {
        $ticketSegment = ConvertTo-TicketSegment -Value $Ticket
        $nameParts += $ticketSegment
    }

    $nameParts += $descriptionSegment
    $branchName = "$normalizedType/$($nameParts -join '-')"
    $sourceBranch = "main"

    if (-not (Test-GitSuccess -Arguments @("rev-parse", "--show-toplevel"))) {
        Write-Failure "Run this script from inside a git repository."
    }

    $status = & git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect git working tree status."
    }

    if ($status) {
        Write-Failure "Working tree is not clean. Commit, stash, or discard changes before creating a branch."
    }

    Write-Host "Fetching and pruning origin..."
    Invoke-Git -Arguments @("fetch", "--prune", "origin") -FailureMessage "Failed to fetch and prune origin."

    if (-not (Test-GitSuccess -Arguments @("show-ref", "--verify", "--quiet", "refs/heads/$sourceBranch"))) {
        Write-Failure "Source branch '$sourceBranch' does not exist locally."
    }

    if (-not (Test-GitSuccess -Arguments @("show-ref", "--verify", "--quiet", "refs/remotes/origin/$sourceBranch"))) {
        Write-Failure "Source branch 'origin/$sourceBranch' does not exist."
    }

    if (Test-GitSuccess -Arguments @("show-ref", "--verify", "--quiet", "refs/heads/$branchName")) {
        Write-Failure "Local branch '$branchName' already exists."
    }

    if (Test-GitSuccess -Arguments @("show-ref", "--verify", "--quiet", "refs/remotes/origin/$branchName")) {
        Write-Failure "Remote branch 'origin/$branchName' already exists."
    }

    Write-Host "Updating source branch '$sourceBranch' with fast-forward only..."
    Invoke-Git -Arguments @("switch", $sourceBranch) -FailureMessage "Failed to switch to source branch '$sourceBranch'."
    Invoke-Git -Arguments @("pull", "--ff-only", "origin", $sourceBranch) -FailureMessage "Failed to fast-forward '$sourceBranch' from origin/$sourceBranch."

    Write-Host "Creating branch '$branchName'..."
    Invoke-Git -Arguments @("switch", "-c", $branchName) -FailureMessage "Failed to create branch '$branchName'."

    $pushAnswer = Read-Host "Push '$branchName' to origin and set upstream? [y/N]"
    if ($pushAnswer -match "^(y|yes)$") {
        Invoke-Git -Arguments @("push", "-u", "origin", $branchName) -FailureMessage "Failed to push '$branchName' to origin."
    }
    else {
        Write-Host "Skipped push. To push later, run: git push -u origin $branchName"
    }

    Write-Host "Branch created: $branchName"
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
