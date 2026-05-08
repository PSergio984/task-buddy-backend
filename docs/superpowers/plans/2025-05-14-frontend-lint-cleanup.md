# Frontend Lint Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all "unused variable" and "unused import" lint errors in the frontend project to make the build pass.

**Architecture:** Remove unused imports and variables, or prefix them with `_` if they are part of a destructuring that cannot be easily changed without affecting readability or if they might be needed later but are currently unused.

**Tech Stack:** React, TypeScript, Vite, TailwindCSS, Lucide React.

---

### Task 1: Fix `src/components/audit-trail.tsx`

**Files:**
- Modify: `src/components/audit-trail.tsx`

- [ ] **Step 1: Remove unused `History` import**

Remove `History` from the lucide-react import.

- [ ] **Step 2: Commit**

```bash
git add src/components/audit-trail.tsx
git commit -m "chore: remove unused History import in audit-trail"
```

### Task 2: Fix `src/components/auth/RegisterForm.tsx`

**Files:**
- Modify: `src/components/auth/RegisterForm.tsx`

- [ ] **Step 1: Remove unused `UserPlus` import and prefix unused `error` variable**

Remove `UserPlus` from lucide-react. Prefix `error` with `_` in `const { register, loading, error } = useAuth()`.

- [ ] **Step 2: Commit**

```bash
git add src/components/auth/RegisterForm.tsx
git commit -m "chore: remove unused import and prefix unused variable in RegisterForm"
```

### Task 3: Fix `src/components/sidebar.tsx`

**Files:**
- Modify: `src/components/sidebar.tsx`

- [ ] **Step 1: Remove unused imports and variables**

Remove `AnimatePresence` from `framer-motion`.
Remove `Briefcase`, `GraduationCap`, `HeartPulse`, `LogOut`, `Settings`, `ChevronLeft`, `ChevronRight`, `User` from `lucide-react`.
Prefix `user` with `_` in `const { user, logout } = useAuth()`.

- [ ] **Step 2: Commit**

```bash
git add src/components/sidebar.tsx
git commit -m "chore: remove unused imports and variables in sidebar"
```

### Task 4: Fix `src/components/system-overview.tsx`

**Files:**
- Modify: `src/components/system-overview.tsx`

- [ ] **Step 1: Remove unused `LayoutGrid` import and `cn` import**

Remove `LayoutGrid` from `lucide-react`.
Remove the entire `import { cn } from "@/lib/utils"` line.

- [ ] **Step 2: Commit**

```bash
git add src/components/system-overview.tsx
git commit -m "chore: remove unused LayoutGrid and cn imports in system-overview"
```

### Task 5: Fix `src/components/task-card.tsx`

**Files:**
- Modify: `src/components/task-card.tsx`

- [ ] **Step 1: Remove unused `Layers` import**

Remove `Layers` from `lucide-react`.

- [ ] **Step 2: Commit**

```bash
git add src/components/task-card.tsx
git commit -m "chore: remove unused Layers import in task-card"
```

### Task 6: Fix `src/components/topnav.tsx`

**Files:**
- Modify: `src/components/topnav.tsx`

- [ ] **Step 1: Remove unused imports and prefix unused props**

Remove `Sparkles`, `PanelLeftOpen`, `PanelLeftClose`, `Menu`, `ShieldCheck` from `lucide-react`.
Prefix `isCollapsed` and `onToggle` with `_` in the `TopNav` component parameters.

- [ ] **Step 2: Commit**

```bash
git add src/components/topnav.tsx
git commit -m "chore: remove unused imports and prefix unused props in topnav"
```

### Task 7: Fix `src/contexts/ProtectedRoute.tsx`

**Files:**
- Modify: `src/contexts/ProtectedRoute.tsx`

- [ ] **Step 1: Remove unused `CheckCircle2` import**

Remove `CheckCircle2` from `lucide-react`.

- [ ] **Step 2: Commit**

```bash
git add src/contexts/ProtectedRoute.tsx
git commit -m "chore: remove unused CheckCircle2 import in ProtectedRoute"
```

### Task 8: Fix `src/pages/LoginPage.tsx`

**Files:**
- Modify: `src/pages/LoginPage.tsx`

- [ ] **Step 1: Prefix unused `error` variable and remove unused `submitLabel`**

Prefix `error` with `_` in `const { login, loading, error } = useAuth()`.
Remove the `const submitLabel = ...` definition.

- [ ] **Step 2: Commit**

```bash
git add src/pages/LoginPage.tsx
git commit -m "chore: fix unused variables in LoginPage"
```

### Task 9: Fix `src/pages/RegisterPage.tsx`

**Files:**
- Modify: `src/pages/RegisterPage.tsx`

- [ ] **Step 1: Remove unused `navigate` hook usage**

Remove the `const navigate = useNavigate()` line.

- [ ] **Step 2: Commit**

```bash
git add src/pages/RegisterPage.tsx
git commit -m "chore: remove unused navigate in RegisterPage"
```

### Task 10: Final Verification

- [ ] **Step 1: Run build**

Run `npm run build` in `task-buddy-frontend`.

- [ ] **Step 2: Final Commit**

If any minor tweaks were needed, commit them.
