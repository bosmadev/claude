#!/usr/bin/env python3
"""
Docker automation skill - generate, optimize, and audit Docker configurations.
Usage: python docker.py <command> [args]
"""

import sys
import re
from pathlib import Path
from typing import List, Dict, Tuple


# Dockerfile Templates
DOCKERFILE_TEMPLATES = {
    "nextjs": """# syntax=docker/dockerfile:1

# Build stage
FROM node:20-alpine AS builder
WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package files
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source
COPY . .

# Build application
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

# Production stage
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy standalone output
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
""",

    "python": """# syntax=docker/dockerfile:1

# Build stage
FROM python:3.12-slim AS builder
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.12-slim
WORKDIR /app

# Create non-root user
RUN useradd -m -u 1001 appuser

# Copy dependencies from builder
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Copy application
COPY --chown=appuser:appuser . .

# Update PATH
ENV PATH=/home/appuser/.local/bin:$PATH

USER appuser

EXPOSE 8000

CMD ["python", "main.py"]
""",

    "go": """# syntax=docker/dockerfile:1

# Build stage
FROM golang:1.22-alpine AS builder
WORKDIR /app

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY . .

# Build binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o main .

# Production stage
FROM scratch
WORKDIR /

# Copy binary from builder
COPY --from=builder /app/main /main

# Copy CA certificates for HTTPS
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

EXPOSE 8080

CMD ["/main"]
""",

    "node": """# syntax=docker/dockerfile:1

# Build stage
FROM node:20-alpine AS builder
WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm ci --only=production

# Production stage
FROM node:20-alpine
WORKDIR /app

ENV NODE_ENV=production

# Create non-root user
RUN addgroup -g 1001 nodejs && adduser -u 1001 -G nodejs -s /bin/sh -D nodejs

# Copy dependencies
COPY --from=builder --chown=nodejs:nodejs /app/node_modules ./node_modules

# Copy application
COPY --chown=nodejs:nodejs . .

USER nodejs

EXPOSE 3000

CMD ["node", "index.js"]
""",

    "rust": """# syntax=docker/dockerfile:1

# Build stage
FROM rust:1.76-alpine AS builder
WORKDIR /app

# Install build dependencies
RUN apk add --no-cache musl-dev

# Copy manifests
COPY Cargo.toml Cargo.lock ./

# Build dependencies (cached layer)
RUN mkdir src && echo "fn main() {}" > src/main.rs
RUN cargo build --release
RUN rm -rf src

# Copy source
COPY src ./src

# Build application
RUN cargo build --release

# Production stage
FROM alpine:latest
WORKDIR /app

# Create non-root user
RUN addgroup -g 1001 appuser && adduser -u 1001 -G appuser -s /bin/sh -D appuser

# Copy binary
COPY --from=builder --chown=appuser:appuser /app/target/release/app /app/app

USER appuser

EXPOSE 8080

CMD ["./app"]
""",

    "java": """# syntax=docker/dockerfile:1

# Build stage
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /app

# Copy pom.xml
COPY pom.xml .

# Download dependencies (cached layer)
RUN mvn dependency:go-offline

# Copy source
COPY src ./src

# Build application
RUN mvn package -DskipTests

# Production stage
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

# Create non-root user
RUN addgroup -g 1001 spring && adduser -u 1001 -G spring -s /bin/sh -D spring

# Copy JAR from builder
COPY --from=builder --chown=spring:spring /app/target/*.jar app.jar

USER spring

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "app.jar"]
"""
}

DOCKERIGNORE_TEMPLATE = """# Dependencies
node_modules/
__pycache__/
*.pyc
.venv/
venv/

# Build outputs
dist/
build/
target/
.next/
out/

# Development
.git/
.github/
.vscode/
.idea/
*.log
.env.local
.env.*.local

# Testing
coverage/
.pytest_cache/
*.test

# OS
.DS_Store
Thumbs.db
"""


def cmd_generate(project_type: str):
    """Generate Dockerfile for project type."""
    if project_type not in DOCKERFILE_TEMPLATES:
        print(f"❌ Unknown project type: {project_type}", file=sys.stderr)
        print(f"   Supported: {', '.join(DOCKERFILE_TEMPLATES.keys())}", file=sys.stderr)
        return 1

    dockerfile = DOCKERFILE_TEMPLATES[project_type]

    # Write Dockerfile
    Path("Dockerfile").write_text(dockerfile)
    print("✅ Generated: Dockerfile")

    # Write .dockerignore
    Path(".dockerignore").write_text(DOCKERIGNORE_TEMPLATE)
    print("✅ Generated: .dockerignore")

    # Show build instructions
    print(f"""
Build Instructions:
  docker build -t {project_type}-app .
  docker run -p 3000:3000 {project_type}-app

Multi-platform build:
  docker buildx build --platform linux/amd64,linux/arm64 -t {project_type}-app .
""")

    return 0


def cmd_compose(services: List[str]):
    """Generate docker-compose.yml for services."""
    service_configs = {
        "postgres": {
            "image": "postgres:16-alpine",
            "environment": [
                "POSTGRES_USER=postgres",
                "POSTGRES_PASSWORD=postgres",
                "POSTGRES_DB=myapp"
            ],
            "ports": ["5432:5432"],
            "volumes": ["postgres_data:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres"],
                "interval": "10s",
                "timeout": "5s",
                "retries": 5
            }
        },
        "redis": {
            "image": "redis:7-alpine",
            "command": "redis-server --requirepass redis",
            "ports": ["6379:6379"],
            "volumes": ["redis_data:/data"],
            "healthcheck": {
                "test": ["CMD", "redis-cli", "ping"],
                "interval": "10s",
                "timeout": "3s",
                "retries": 5
            }
        },
        "mongo": {
            "image": "mongo:7",
            "environment": [
                "MONGO_INITDB_ROOT_USERNAME=mongo",
                "MONGO_INITDB_ROOT_PASSWORD=mongo"
            ],
            "ports": ["27017:27017"],
            "volumes": ["mongo_data:/data/db"]
        },
        "nginx": {
            "image": "nginx:alpine",
            "ports": ["80:80", "443:443"],
            "volumes": ["./nginx.conf:/etc/nginx/nginx.conf:ro"],
            "depends_on": ["app"]
        },
        "mysql": {
            "image": "mysql:8",
            "environment": [
                "MYSQL_ROOT_PASSWORD=mysql",
                "MYSQL_DATABASE=myapp"
            ],
            "ports": ["3306:3306"],
            "volumes": ["mysql_data:/var/lib/mysql"]
        }
    }

    # Build compose file
    compose = {
        "version": "3.8",
        "services": {},
        "volumes": {},
        "networks": {
            "app-network": {
                "driver": "bridge"
            }
        }
    }

    for svc in services:
        if svc not in service_configs:
            print(f"⚠️  Unknown service: {svc} (skipping)", file=sys.stderr)
            continue

        config = service_configs[svc].copy()
        config["networks"] = ["app-network"]
        compose["services"][svc] = config

        # Add volumes
        for vol in config.get("volumes", []):
            vol_name = vol.split(":")[0]
            if not vol_name.startswith("."):
                compose["volumes"][vol_name] = {}

    # Write compose file
    import yaml
    try:
        content = yaml.dump(compose, default_flow_style=False, sort_keys=False)
    except ImportError:
        # Fallback to manual YAML generation
        content = generate_yaml_manually(compose)

    Path("docker-compose.yml").write_text(content)
    print("✅ Generated: docker-compose.yml")

    print("\nUsage:")
    print("  docker-compose up -d        # Start services")
    print("  docker-compose ps           # Check status")
    print("  docker-compose logs -f      # View logs")
    print("  docker-compose down         # Stop services")

    return 0


def generate_yaml_manually(data: dict) -> str:
    """Generate YAML manually (fallback when PyYAML not available)."""
    lines = ["version: '3.8'\n"]

    lines.append("\nservices:")
    for name, svc in data["services"].items():
        lines.append(f"  {name}:")
        for key, val in svc.items():
            if isinstance(val, list):
                lines.append(f"    {key}:")
                for item in val:
                    if isinstance(item, dict):
                        lines.append(f"      - {item}")
                    else:
                        lines.append(f"      - {item}")
            elif isinstance(val, dict):
                lines.append(f"    {key}:")
                for k, v in val.items():
                    if isinstance(v, list):
                        lines.append(f"      {k}:")
                        for item in v:
                            lines.append(f"        - {item}")
                    else:
                        lines.append(f"      {k}: {v}")
            else:
                lines.append(f"    {key}: {val}")

    if data.get("volumes"):
        lines.append("\nvolumes:")
        for vol in data["volumes"]:
            lines.append(f"  {vol}: {{}}")

    if data.get("networks"):
        lines.append("\nnetworks:")
        for net, cfg in data["networks"].items():
            lines.append(f"  {net}:")
            for k, v in cfg.items():
                lines.append(f"    {k}: {v}")

    return "\n".join(lines)


def cmd_optimize(dockerfile_path: str):
    """Analyze and suggest optimizations for Dockerfile."""
    path = Path(dockerfile_path)
    if not path.exists():
        print(f"❌ File not found: {dockerfile_path}", file=sys.stderr)
        return 1

    content = path.read_text()
    lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().startswith("#")]

    print("\n📊 Dockerfile Analysis\n")

    # Count layers
    layer_commands = ["RUN", "COPY", "ADD"]
    layers = sum(1 for line in lines if any(line.startswith(cmd) for cmd in layer_commands))
    print(f"├─ Layers: {layers}", end="")
    if layers > 15:
        print(" (high - consider combining RUN commands)")
    elif layers > 10:
        print(" (medium)")
    else:
        print(" (good)")

    # Check multi-stage
    has_multistage = content.count("FROM") > 1
    print(f"├─ Multi-stage: {'✅ Yes' if has_multistage else '❌ No (consider adding)'}")

    # Check base image
    from_lines = [l for l in lines if l.startswith("FROM")]
    if from_lines:
        base = from_lines[0]
        if "alpine" in base.lower():
            print("├─ Base image: ✅ Alpine (minimal)")
        elif "slim" in base.lower():
            print("├─ Base image: ✅ Slim (good)")
        elif "scratch" in base.lower():
            print("├─ Base image: ✅ Scratch (optimal)")
        else:
            print("├─ Base image: ⚠️  Full (consider Alpine/slim)")

    # Check .dockerignore
    has_dockerignore = Path(".dockerignore").exists()
    print(f"├─ .dockerignore: {'✅ Present' if has_dockerignore else '❌ Missing'}")

    # Check user
    has_user = any("USER" in line for line in lines)
    print(f"└─ Non-root user: {'✅ Yes' if has_user else '❌ No (security risk)'}")

    # Recommendations
    print("\n✨ Recommendations:\n")

    if not has_multistage:
        print("1. Use multi-stage build to reduce final image size")
        print("   Example: FROM node:20 AS builder ... FROM node:20-alpine")

    if layers > 12:
        print("2. Combine related RUN commands to reduce layers")
        print("   Example: RUN apt-get update && apt-get install ... && apt-get clean")

    if not has_dockerignore:
        print("3. Add .dockerignore to exclude unnecessary files")
        print("   Include: node_modules/, .git/, *.log, .env.local")

    if not has_user:
        print("4. Run as non-root user for security")
        print("   Add: USER node (or create custom user)")

    print("\n")
    return 0


def cmd_security(dockerfile_path: str):
    """Security audit of Dockerfile."""
    path = Path(dockerfile_path)
    if not path.exists():
        print(f"❌ File not found: {dockerfile_path}", file=sys.stderr)
        return 1

    content = path.read_text()
    lines = content.split("\n")

    issues = []
    passed = []

    # Check 1: Root user
    has_user = any("USER" in line and "root" not in line.lower() for line in lines)
    if not has_user:
        issues.append(("CRITICAL", "Running as root user", "Add 'USER <non-root-user>' before CMD"))
    else:
        passed.append("Non-root user configured")

    # Check 2: Secrets in ENV
    env_secrets = []
    for line in lines:
        if line.strip().startswith("ENV"):
            if any(keyword in line.upper() for keyword in ["PASSWORD", "SECRET", "TOKEN", "API_KEY"]):
                env_secrets.append(line.strip())
    if env_secrets:
        issues.append(("HIGH", "Secrets in ENV variables", f"Found: {env_secrets[0][:60]}..."))
    else:
        passed.append("No secrets in ENV")

    # Check 3: Base image pinning
    from_lines = [l.strip() for l in lines if l.strip().startswith("FROM")]
    unpinned = [f for f in from_lines if "@sha256:" not in f and "scratch" not in f]
    if unpinned and len(unpinned) == len(from_lines):
        issues.append(("MEDIUM", "Base image not pinned with SHA", f"Use: {unpinned[0]}@sha256:..."))
    else:
        passed.append("Base image pinned")

    # Check 4: Latest tag
    if any("latest" in line for line in from_lines):
        issues.append(("MEDIUM", "Using 'latest' tag", "Pin to specific version"))

    # Check 5: Multi-stage build
    if content.count("FROM") > 1:
        passed.append("Multi-stage build used")

    # Check 6: .dockerignore
    if Path(".dockerignore").exists():
        passed.append(".dockerignore exists")

    # Print results
    print("\n🔒 Security Audit Results\n")

    if issues:
        for severity, issue, fix in issues:
            if severity == "CRITICAL":
                print(f"❌ CRITICAL: {issue}")
            elif severity == "HIGH":
                print(f"❌ HIGH: {issue}")
            else:
                print(f"⚠️  MEDIUM: {issue}")
            print(f"   Fix: {fix}\n")

    for check in passed:
        print(f"✅ PASSED: {check}")

    print(f"\nTotal: {len(issues)} issues, {len(passed)} passed\n")

    return 0 if len(issues) == 0 else 1


def cmd_help():
    """Show usage information."""
    print("""
Docker Automation Skill

Usage:
  python docker.py generate <type>        # Generate Dockerfile
  python docker.py compose <services>     # Generate docker-compose.yml
  python docker.py optimize <dockerfile>  # Analyze and optimize
  python docker.py security <dockerfile>  # Security audit

Examples:
  python docker.py generate nextjs
  python docker.py compose postgres redis
  python docker.py optimize ./Dockerfile
  python docker.py security ./Dockerfile

Supported project types:
  nextjs, python, go, node, rust, java

Supported services:
  postgres, redis, mongo, nginx, mysql
""")
    return 0


def main():
    if len(sys.argv) < 2:
        cmd_help()
        return 1

    command = sys.argv[1]

    if command == "help":
        return cmd_help()

    elif command == "generate":
        if len(sys.argv) < 3:
            print("❌ Usage: docker.py generate <type>", file=sys.stderr)
            return 1
        return cmd_generate(sys.argv[2])

    elif command == "compose":
        if len(sys.argv) < 3:
            print("❌ Usage: docker.py compose <service1> [service2 ...]", file=sys.stderr)
            return 1
        return cmd_compose(sys.argv[2:])

    elif command == "optimize":
        if len(sys.argv) < 3:
            print("❌ Usage: docker.py optimize <dockerfile>", file=sys.stderr)
            return 1
        return cmd_optimize(sys.argv[2])

    elif command == "security":
        if len(sys.argv) < 3:
            print("❌ Usage: docker.py security <dockerfile>", file=sys.stderr)
            return 1
        return cmd_security(sys.argv[2])

    else:
        print(f"❌ Unknown command: {command}", file=sys.stderr)
        cmd_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
