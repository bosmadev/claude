# PR Review Base Criteria

**Purpose:** Unified review criteria for VERIFY+FIX, /review, and @claude review GitHub Actions.

**Usage:**
- VERIFY+FIX agents: Auto-fix simple issues, escalate complex ones
- /review agents: Leave TODO-P1/P2/P3 comments
- @claude review: Add PR comments

---

## Security Checklist (OWASP Top 10)

### A01 - Broken Access Control
- [ ] Authorization checks on all protected routes/endpoints
- [ ] User permissions verified before data access
- [ ] No client-side access control logic only
- [ ] CORS policies properly configured
- [ ] Direct object references protected (no guessable IDs exposed)

### A02 - Cryptographic Failures
- [ ] Sensitive data encrypted at rest and in transit
- [ ] HTTPS enforced for all communications
- [ ] Strong encryption algorithms used (AES-256, RSA-2048+)
- [ ] No hardcoded secrets, API keys, or passwords
- [ ] Secrets stored in environment variables or secret managers
- [ ] PII/PHI properly protected per compliance requirements

### A03 - Injection
- [ ] SQL queries use parameterized statements/ORMs
- [ ] User input sanitized before use in commands/queries
- [ ] No `eval()` or dynamic code execution with user input
- [ ] XSS prevention: output encoding, CSP headers
- [ ] Command injection prevented in shell executions
- [ ] NoSQL injection prevented (MongoDB, etc.)

### A04 - Insecure Design
- [ ] Threat modeling performed for new features
- [ ] Security requirements defined upfront
- [ ] Fail-secure defaults (deny by default)
- [ ] Rate limiting on sensitive operations
- [ ] Input validation at boundaries
- [ ] Separation of duties enforced

### A05 - Security Misconfiguration
- [ ] Default credentials changed
- [ ] Unnecessary features/services disabled
- [ ] Error messages don't leak sensitive info
- [ ] Security headers configured (CSP, HSTS, X-Frame-Options)
- [ ] Dependencies up to date
- [ ] Cloud storage buckets properly secured

### A06 - Vulnerable and Outdated Components
- [ ] All dependencies current (check `npm audit`, `pnpm audit`)
- [ ] No known CVEs in dependencies
- [ ] Unused dependencies removed
- [ ] Lock files committed (package-lock.json, pnpm-lock.yaml)
- [ ] Automated dependency updates configured

### A07 - Identification and Authentication Failures
- [ ] Multi-factor authentication available for sensitive accounts
- [ ] Password requirements enforce strong passwords
- [ ] Session tokens securely generated (crypto-random)
- [ ] Session invalidation on logout
- [ ] Brute force protection (rate limiting, account lockout)
- [ ] No credentials in URLs or logs

### A08 - Software and Data Integrity Failures
- [ ] Code signing/verification for CI/CD pipelines
- [ ] Integrity checks for critical data
- [ ] Auto-update mechanisms secured
- [ ] Deserialization of untrusted data avoided
- [ ] Dependency integrity verified (SRI, checksums)

### A09 - Security Logging and Monitoring Failures
- [ ] Security events logged (auth failures, access violations)
- [ ] Logs don't contain sensitive data
- [ ] Log tampering prevented
- [ ] Alerting configured for suspicious activity
- [ ] Audit trail for sensitive operations

### A10 - Server-Side Request Forgery (SSRF)
- [ ] URL validation before making requests
- [ ] Allowlist for external services
- [ ] No user-controlled URLs in server requests
- [ ] Network segmentation for internal services
- [ ] Disable unused URL schemas (file://, gopher://)

---

## Code Quality Criteria

### Formatting & Style
- [ ] Consistent indentation (tabs/spaces per project config)
- [ ] Line length within limits (120 chars default)
- [ ] No trailing whitespace
- [ ] Files end with newline
- [ ] Biome/Prettier rules followed
- [ ] Import ordering consistent
- [ ] No commented-out code blocks

### Naming Conventions
- [ ] Variables: camelCase for local, UPPER_SNAKE for constants
- [ ] Functions: camelCase, descriptive verb+noun (e.g., `getUserById`)
- [ ] Classes: PascalCase
- [ ] Files: kebab-case for components, camelCase for utilities
- [ ] Boolean variables prefixed with `is`, `has`, `should`
- [ ] Event handlers prefixed with `handle` or `on`
- [ ] No single-letter variables except loop counters

### Code Complexity
- [ ] Functions under 50 lines (prefer 20-30)
- [ ] Cyclomatic complexity < 10
- [ ] Nesting depth < 4 levels
- [ ] No duplicate code blocks (DRY principle)
- [ ] Single Responsibility Principle followed
- [ ] Early returns used to reduce nesting

### Error Handling
- [ ] All async operations have error handling
- [ ] Errors logged with context
- [ ] User-facing errors are friendly
- [ ] Network errors handled gracefully
- [ ] No swallowed errors (`catch {}` without logging)
- [ ] Proper error types used (don't catch generic `Error`)

### TypeScript Specific
- [ ] No `any` types (use `unknown` if needed)
- [ ] Interfaces preferred over types for objects
- [ ] Strict null checks enabled and respected
- [ ] Generic types used where appropriate
- [ ] Return types explicit for public functions
- [ ] No `@ts-ignore` without justification comment
- [ ] Type assertions minimized

### React Specific
- [ ] Hooks rules followed (only at top level)
- [ ] Dependencies arrays complete and correct
- [ ] No inline function definitions in JSX (performance)
- [ ] Keys used correctly in lists (stable, unique)
- [ ] Props destructured for clarity
- [ ] Memoization used for expensive computations
- [ ] State updates use functional form when depending on previous state
- [ ] No direct DOM manipulation (use refs sparingly)

---

## Design Checklist

### Typography
- [ ] Font sizes use design system scale (12, 14, 16, 18, 20, 24, 32, 48px)
- [ ] Line height 1.5-1.6 for body text, 1.2-1.3 for headings
- [ ] Letter spacing adjusted for all-caps text
- [ ] Contrast ratio >= 4.5:1 for body, >= 3:1 for large text (WCAG AA)
- [ ] No more than 3 font weights per page
- [ ] Hierarchy clear (size, weight, spacing)

### Color
- [ ] Colors from design system palette only
- [ ] Sufficient contrast (WCAG AA minimum)
- [ ] Color not the only indicator (icons, labels, patterns)
- [ ] Dark mode colors distinct from light mode
- [ ] Focus indicators visible (3px outline, high contrast)

### Motion & Animation
- [ ] Animations under 300ms for UI feedback
- [ ] Respects `prefers-reduced-motion` media query
- [ ] No auto-playing videos/carousels without controls
- [ ] Loading states for async operations
- [ ] Skeleton screens preferred over spinners
- [ ] Transitions smooth (ease-in-out or custom bezier)

### Accessibility
- [ ] Semantic HTML (header, nav, main, article, aside, footer)
- [ ] ARIA labels on custom controls
- [ ] Form labels associated with inputs
- [ ] Keyboard navigation works (tab order logical)
- [ ] Focus indicators visible and high contrast
- [ ] Alt text on all images (empty string for decorative)
- [ ] Heading hierarchy correct (no skipped levels)
- [ ] Touch targets >= 44x44px (mobile)
- [ ] Error messages associated with fields (aria-describedby)

### Layout & Spacing
- [ ] Spacing follows 8px grid (8, 16, 24, 32, 48, 64px)
- [ ] Responsive breakpoints used (sm, md, lg, xl)
- [ ] No horizontal scrolling on mobile
- [ ] Content max-width for readability (65-75 characters)
- [ ] Consistent padding/margin within component types
- [ ] Alignment consistent (left, center, right used purposefully)

---

## Performance Considerations

### Frontend Performance
- [ ] Images optimized (WebP/AVIF, lazy loading)
- [ ] Bundle size reasonable (< 200KB gzipped for initial load)
- [ ] Code splitting used for routes
- [ ] Third-party scripts loaded async/defer
- [ ] No layout shift (CLS < 0.1)
- [ ] First Contentful Paint < 1.8s
- [ ] Time to Interactive < 3.8s

### Backend Performance
- [ ] Database queries optimized (indexes, no N+1)
- [ ] API responses < 200ms for simple queries
- [ ] Pagination used for large datasets
- [ ] Caching implemented where appropriate
- [ ] Connection pooling configured
- [ ] Rate limiting on public endpoints

### Network
- [ ] Compression enabled (gzip/brotli)
- [ ] HTTP/2 or HTTP/3 used
- [ ] CDN for static assets
- [ ] Minimal redirects
- [ ] Keep-alive connections

---

## Test Coverage Expectations

### Unit Tests
- [ ] Critical business logic covered (>80%)
- [ ] Edge cases tested (null, empty, boundary values)
- [ ] Error paths tested
- [ ] Mocks/stubs used for external dependencies
- [ ] Tests isolated (no shared state between tests)
- [ ] Test names descriptive (should/when/then pattern)

### Integration Tests
- [ ] API endpoints tested (happy path + errors)
- [ ] Database interactions tested
- [ ] Authentication/authorization flows tested
- [ ] File uploads/downloads tested

### E2E Tests (where applicable)
- [ ] Critical user journeys covered
- [ ] Login/logout flows
- [ ] Form submissions
- [ ] Error handling visible to users

### Test Quality
- [ ] No flaky tests (run reliably)
- [ ] Fast execution (unit < 100ms, integration < 1s)
- [ ] No console errors/warnings in test output
- [ ] Fixtures/factories for test data
- [ ] Test coverage reported

---

## Documentation

### Code Comments
- [ ] Complex algorithms explained
- [ ] Non-obvious business logic documented
- [ ] TODOs have context and priority (TODO-P1, TODO-P2, TODO-P3)
- [ ] No obsolete comments (dead code references)
- [ ] JSDoc comments on public APIs

### README/Docs
- [ ] Setup instructions accurate
- [ ] API changes documented
- [ ] Breaking changes highlighted
- [ ] Examples provided for new features
- [ ] Environment variables documented

---

## Git Hygiene

### Commits
- [ ] Commit messages follow conventional commits (scope: description)
- [ ] Commits atomic (single logical change)
- [ ] No merge commits in feature branches (rebase preferred)
- [ ] No WIP commits in PR (squashed before merge)

### Branch
- [ ] Branch name follows pattern: `type/bID-description`
- [ ] Build ID present in branch name
- [ ] No stale branches (clean up after merge)

### PR
- [ ] Description explains "why" not just "what"
- [ ] Screenshots for UI changes
- [ ] Breaking changes highlighted
- [ ] Linked to issue/ticket
- [ ] Self-review completed before requesting review

---

## Framework-Specific Rules

### Next.js
- [ ] Server Components used by default
- [ ] Client Components (`'use client'`) only when needed
- [ ] Metadata API used for SEO
- [ ] Dynamic routes follow conventions
- [ ] API routes secure (rate limiting, validation)
- [ ] Environment variables prefixed correctly (`NEXT_PUBLIC_` for client)

### React Server Components
- [ ] No hooks in Server Components
- [ ] Props serializable (no functions, Dates, etc.)
- [ ] Async components used correctly
- [ ] Suspense boundaries placed strategically
- [ ] Loading states handled with `loading.tsx`

### Tailwind CSS
- [ ] Custom colors in `tailwind.config.ts`
- [ ] No arbitrary values in production (`[#ff0000]`)
- [ ] Responsive classes used correctly (`sm:`, `md:`, `lg:`)
- [ ] Dark mode classes prefixed (`dark:`)
- [ ] Component styles extracted to CSS files if repeated

### Zod/Validation
- [ ] Schema validation on all API inputs
- [ ] Type inference used (`z.infer<typeof schema>`)
- [ ] Error messages user-friendly
- [ ] Nested objects validated

---

## Dependency Management

### Package.json
- [ ] All dependencies used
- [ ] No duplicate packages (check with `pnpm why`)
- [ ] Peer dependencies satisfied
- [ ] Versions pinned or locked
- [ ] Scripts documented

### License Compliance
- [ ] Dependencies have compatible licenses
- [ ] GPL dependencies not in proprietary code
- [ ] License file updated if needed

---

## Environment & Configuration

### Environment Variables
- [ ] All required variables documented
- [ ] `.env.example` up to date
- [ ] No secrets in source code
- [ ] Validation on startup (missing vars fail fast)
- [ ] Prefixes used correctly (NEXT_PUBLIC_, VITE_, etc.)

### Configuration Files
- [ ] TypeScript config strict mode enabled
- [ ] ESLint/Biome rules enforced
- [ ] Git ignores correct (.env, node_modules, build artifacts)
- [ ] Editor config consistent (.editorconfig)

---

## Checklist Usage

**VERIFY+FIX agents:**
- Auto-fix: formatting, imports, simple type errors
- Escalate: security issues, design problems, missing tests

**/review agents:**
- Leave TODO-P1: security, breaking changes, critical bugs
- Leave TODO-P2: performance issues, complex refactors
- Leave TODO-P3: minor improvements, style nitpicks

**@claude review GitHub Actions:**
- Add PR comments with line numbers
- Group related issues
- Suggest fixes where possible
