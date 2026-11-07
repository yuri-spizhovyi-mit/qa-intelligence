# Locked Docker builds

The supported build target is Python 3.12 on Linux amd64, as used by Docker Desktop. The Dockerfile pins the Python image by digest. Lock files pin transitive dependencies and their SHA-256 hashes.

| File | Purpose |
| --- | --- |
| `pyproject.toml` | Direct dependency declarations and package metadata |
| `requirements.txt` | Runtime dependency resolution |
| `requirements-dev.txt` | Runtime plus development dependencies, constrained to runtime versions |
| `requirements-build.txt` | Python package build dependencies |

The runtime build installs wheels with `--require-hashes` and `--only-binary=:all:`. The local application is then built with the locked backend, disabled dependency resolution and disabled network access. Standard builds consume the committed locks.

## Build

```text
docker compose build api
docker compose up -d api
```

Verify health at `http://127.0.0.1:8000/health` and inspect the API at `http://127.0.0.1:8000/docs`. Use an available local port if a live-provider session already occupies port 8000.

## Refresh dependencies

After changing dependency declarations or deliberately updating the resolved versions, run these commands in PowerShell from the repository root:

```powershell
docker build --no-cache --target lock-tools -t qi-lock-tools .
$lockContainer = docker create qi-lock-tools
try {
    docker cp "${lockContainer}:/app/requirements.txt" ./requirements.txt
    docker cp "${lockContainer}:/app/requirements-dev.txt" ./requirements-dev.txt
    docker cp "${lockContainer}:/app/requirements-build.txt" ./requirements-build.txt
} finally {
    docker rm $lockContainer
}
docker compose build --no-cache api
```

The lock-tools target uses pip 25.3 and pip-tools 7.5.2 in the pinned Python image. Lock regeneration intentionally resolves versions against the package index and requires review. Review all three lock diffs together, then rebuild and run the approved platform tests in verified isolation. Test-file edits require renewed human review.

Base-image updates require deliberately replacing the digest and repeating the build and verification process. Other operating systems, architectures and Python versions need separately generated and verified locks.

## Verification scope

Fixed build inputs support repeatable dependency installation. Package-index availability is still required for a clean installation. Image manifests and application wheel bytes can differ because of build metadata and timestamps.
