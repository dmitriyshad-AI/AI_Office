#!/usr/bin/env bash
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/ai-office}"
REPO_URL="${REPO_URL:-https://github.com/dmitriyshad-AI/AI_Office.git}"
BRANCH="${BRANCH:-main}"

echo "==> Deploy path: ${DEPLOY_PATH}"
echo "==> Repo: ${REPO_URL}"
echo "==> Branch: ${BRANCH}"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required on the server." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required on the server." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is required on the server." >&2
  exit 1
fi

mkdir -p "$(dirname "${DEPLOY_PATH}")"

if [ ! -d "${DEPLOY_PATH}/.git" ]; then
  echo "==> Cloning repository"
  git clone --branch "${BRANCH}" --single-branch "${REPO_URL}" "${DEPLOY_PATH}"
else
  echo "==> Updating existing checkout"
  cd "${DEPLOY_PATH}"
  git fetch origin "${BRANCH}"
  git checkout "${BRANCH}"
  git pull --ff-only origin "${BRANCH}"
fi

cd "${DEPLOY_PATH}"

if [ ! -f ".env" ]; then
  echo "Missing ${DEPLOY_PATH}/.env. Create it on the server before deploying." >&2
  exit 1
fi

echo "==> Building and starting containers"
docker compose up -d --build

echo "==> Running containers"
docker compose ps

echo "==> Health check"
curl -fsS http://localhost:8000/api/health || true
