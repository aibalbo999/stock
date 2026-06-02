from __future__ import annotations

import subprocess


LOCAL_DOCKER_DEPENDENCY_IMAGES = {
    "neo4j": "neo4j:5-community",
    "browserless": "ghcr.io/browserless/chromium:latest",
}


def local_docker_image_status(images: dict[str, str] | None = None) -> dict:
    image_map = images or LOCAL_DOCKER_DEPENDENCY_IMAGES
    rows = []
    docker_available = True
    docker_error = None
    for service, image in image_map.items():
        try:
            completed = subprocess.run(
                ["docker", "image", "inspect", image],
                check=False,
                text=True,
                capture_output=True,
                timeout=10,
            )
        except FileNotFoundError:
            docker_available = False
            docker_error = "docker_not_found"
            rows.append({"service": service, "image": image, "present": False, "error": docker_error})
            continue
        except subprocess.TimeoutExpired:
            docker_error = "docker_image_inspect_timeout"
            rows.append({"service": service, "image": image, "present": False, "error": docker_error})
            continue
        present = completed.returncode == 0
        rows.append(
            {
                "service": service,
                "image": image,
                "present": present,
                "error": None if present else (completed.stderr or completed.stdout or "").strip(),
            }
        )
    missing = [row for row in rows if not row.get("present")]
    return {
        "docker_available": docker_available,
        "docker_error": docker_error,
        "images": rows,
        "all_present": not missing,
        "missing_services": [row["service"] for row in missing],
        "remediation": None
        if not missing
        else "docker compose pull " + " ".join(row["service"] for row in missing),
    }
