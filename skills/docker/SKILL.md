---
name: docker
description: Generate Dockerfiles, docker-compose.yml, optimize containers, and security audit
argument-hint: "generate <project-type> | compose <services> | optimize <dockerfile> | security <dockerfile> | help"
user-invocable: true
context: fork
when_to_use: "When you need to generate Dockerfiles for common project types, create docker-compose configurations, optimize existing Dockerfiles for size/performance, or audit Dockerfiles for security issues"
---

# Docker Automation Skill

When invoked, immediately output: **SKILL_STARTED:** docker

Generate, optimize, and audit Docker configurations for any project type.

## Commands

| Command | Description |
|---------|-------------|
| `/docker generate <type>` | Generate Dockerfile for project type |
| `/docker compose <services>` | Generate docker-compose.yml |
| `/docker optimize <dockerfile>` | Analyze and optimize Dockerfile |
| `/docker security <dockerfile>` | Security audit of Dockerfile |
| `/docker help` | Show usage |

## Argument Reference

| Command | Arguments | Example |
|---------|-----------|---------|
| `generate` | `<type>` (nextjs\|python\|go\|node\|rust\|java) | `/docker generate nextjs` |
| `compose` | `<services>` (postgres\|redis\|mongo\|nginx) | `/docker compose postgres redis` |
| `optimize` | `<dockerfile-path>` | `/docker optimize ./Dockerfile` |
| `security` | `<dockerfile-path>` | `/docker security ./Dockerfile` |

## Detailed Workflow

### Generate Dockerfile

Generate production-ready Dockerfile for common project types:

```bash
/docker generate nextjs      # Next.js with multi-stage build
/docker generate python      # Python with pip/poetry
/docker generate go          # Go with scratch base
/docker generate node        # Node.js with Alpine
/docker generate rust        # Rust with cargo
/docker generate java        # Java Spring Boot
```

**Output:**
- Multi-stage Dockerfile for production
- .dockerignore template
- Build/run instructions

**Features:**
- ✅ Multi-stage builds (build → production)
- ✅ Layer caching optimization
- ✅ Minimal base images (Alpine, distroless, scratch)
- ✅ Non-root user setup
- ✅ Security best practices

**Use when:**
- Starting new project with Docker
- Converting existing project to containers
- Need production-ready Dockerfile template

### Generate Docker Compose

Create docker-compose.yml with common service stacks:

```bash
/docker compose postgres redis       # Database + cache
/docker compose mongo nginx          # NoSQL + web server
/docker compose postgres redis nginx # Full stack
```

**Supported services:**
- `postgres` - PostgreSQL database with persistent volume
- `redis` - Redis cache with password auth
- `mongo` - MongoDB with authentication
- `nginx` - Nginx reverse proxy
- `mysql` - MySQL database
- `rabbitmq` - RabbitMQ message queue
- `elasticsearch` - Elasticsearch search engine

**Output:**
- Complete docker-compose.yml
- Environment variable templates
- Volume configurations
- Network setup

**Use when:**
- Setting up local development environment
- Creating microservices architecture
- Need multi-container application stack

### Optimize Dockerfile

Analyze existing Dockerfile and suggest optimizations:

```bash
/docker optimize ./Dockerfile
```

**Analysis includes:**
- 📊 Layer count and cache efficiency
- 📦 Image size estimate
- ⚡ Build time optimizations
- 🔄 Multi-stage conversion suggestions
- 📝 .dockerignore recommendations

**Optimization strategies:**
1. Multi-stage builds (reduce final image size)
2. Layer ordering (maximize cache hits)
3. Combine RUN commands (reduce layers)
4. Use specific base image versions (reproducibility)
5. .dockerignore patterns (faster builds)

**Example output:**
```
Current Dockerfile Analysis:
├─ Layers: 18 (high - consider combining)
├─ Estimated size: 450MB
├─ Cache efficiency: Medium
└─ Security issues: 2 found

Recommendations:
✅ Use multi-stage build → reduce to 120MB
✅ Combine RUN commands → 18 layers → 8 layers
⚠️  Add .dockerignore for node_modules
⚠️  Pin base image to specific version
```

**Use when:**
- Dockerfile builds are slow
- Images are too large
- Need to improve CI/CD performance

### Security Audit

Scan Dockerfile for security vulnerabilities:

```bash
/docker security ./Dockerfile
```

**Security checks:**
- 🔒 Root user usage (should run as non-root)
- 🔑 Secrets in ENV variables
- 📦 Unverified base images (no SHA digest)
- 🔓 Exposed sensitive ports
- 📝 Missing health checks
- 🔄 Outdated base images

**Example output:**
```
Security Audit Results:

❌ CRITICAL: Running as root user
   Fix: Add 'USER node' before CMD

❌ HIGH: Secrets in ENV variables
   Found: ENV DATABASE_PASSWORD=secret123
   Fix: Use Docker secrets or .env files

⚠️  MEDIUM: Base image not pinned
   Found: FROM node:18
   Fix: Use node:18.19.0-alpine@sha256:abc123...

✅ PASSED: .dockerignore exists
✅ PASSED: Multi-stage build used
```

**Use when:**
- Preparing for production deployment
- Security compliance review
- Reducing attack surface

## Best Practices

**Image Size:**
- Use Alpine Linux base images (5-10MB vs 100MB+)
- Multi-stage builds (build deps ≠ runtime deps)
- Clean package manager cache (`apt-get clean`)

**Security:**
- Run as non-root user (`USER node`)
- Never store secrets in ENV or layers
- Pin base image versions with SHA digests
- Scan images with `docker scan` or Trivy

**Performance:**
- Order layers by change frequency (least → most)
- Combine RUN commands for related operations
- Use .dockerignore to exclude unnecessary files
- Leverage build cache with `--cache-from`

**Reproducibility:**
- Pin all versions (base images, packages)
- Use lock files (package-lock.json, poetry.lock)
- Specify exact versions in package managers

## Implementation

```bash
python ~/.claude/skills/docker/scripts/docker.py <command> [args]
```

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| **Unknown project type** | Unsupported framework | Use supported types: nextjs, python, go, node, rust, java |
| **File not found** | Invalid Dockerfile path | Check file exists and path is correct |
| **Invalid service** | Unknown service name | Use supported services: postgres, redis, mongo, nginx, mysql |
| **Parse error** | Malformed Dockerfile | Fix Dockerfile syntax errors first |

## Examples

**Generate Next.js Dockerfile:**
```bash
/docker generate nextjs
# → Creates production Dockerfile with:
#    - pnpm dependency installation
#    - Standalone output build
#    - Distroless base image
#    - Non-root user
```

**Create full-stack compose:**
```bash
/docker compose postgres redis nginx
# → Generates docker-compose.yml with:
#    - PostgreSQL (port 5432, persistent volume)
#    - Redis (port 6379, password auth)
#    - Nginx (port 80, reverse proxy config)
#    - Shared network for services
```

**Optimize existing Dockerfile:**
```bash
/docker optimize ./Dockerfile
# → Analyzes and suggests:
#    - Convert to multi-stage build
#    - Reorder layers for caching
#    - Add .dockerignore patterns
#    - Reduce final image size
```

**Security audit before deployment:**
```bash
/docker security ./Dockerfile
# → Checks for:
#    - Root user usage
#    - Hardcoded secrets
#    - Unverified base images
#    - Missing security headers
```

## When to Use

Use `/docker` when you need to:
- ✅ Generate Dockerfile for new projects (Next.js, Python, Go, etc.)
- ✅ Create docker-compose.yml for local development
- ✅ Optimize Dockerfile for smaller images or faster builds
- ✅ Audit Dockerfile for security vulnerabilities
- ✅ Convert single-stage to multi-stage builds
- ✅ Set up microservices infrastructure

Do NOT use when:
- ❌ Need Kubernetes manifests (use Helm or Kustomize)
- ❌ Complex orchestration (use docker swarm or k8s)
- ❌ Runtime container management (use docker CLI directly)
