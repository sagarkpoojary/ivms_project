# IVMS UI DESIGN SYSTEM
**Enterprise Visual Standards & Design Tokens Guide**
**Date:** May 31, 2026
**Author:** Antigravity (Advanced Agentic UI/UX Division)
**Status:** Completed (Audit & Planning Only)

---

## 1. Design System Tokens & Color Palette

The IVMS Enterprise Design System uses a refined, modern color palette designed to ensure high contrast, professional aesthetics, and optimal readability for night operators (in dark mode) and day operators alike.

```
┌────────────────────────────────────────────────────────┐
│                      CORE BRAND COLORS                 │
├─────────────────┬──────────────────┬───────────────────┤
│ Token           │ Hex/CSS Value    │ Intent / Usage    │
├─────────────────┼──────────────────┼───────────────────┤
│ --primary       │ #2563eb          │ Vivid Blue Brand  │
│ --primary-hover │ #1d4ed8          │ Deep Blue Hover   │
│ --success       │ #10b981          │ Moving / Active   │
│ --warning       │ #f59e0b          │ Idle / Warning    │
│ --danger        │ #ef4444          │ Stop / Critical   │
│ --info          │ #06b6d4          │ Info / Diagnostic │
└─────────────────┴──────────────────┴───────────────────┘
```

### 🎨 Background & Surface Gradients
* **Body Background**: `#f1f5f9` (Light Slate Grey)
* **Surface Background (Cards)**: `#ffffff` (Pure White)
* **Sidebar Background**: `#1e293b` (Deep Navy Slate)
* **Premium Accent Gradient**: `linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)` (Samsara-inspired blue gradient)

---

## 2. Typography Scale

We use **Inter** as our primary typography standard (hosted locally or via secure CDN) to optimize readability on dynamic monitors and telemetry readouts.

* **Main Font Family**: `'Inter', system-ui, -apple-system, sans-serif;`
* **Heading scale**:
  * `h1` (Display Pages): **32px** (Bold, letter-spacing -0.02em)
  * `h2` (Section Titles): **24px** (Semibold, letter-spacing -0.015em)
  * `h3` (Component Headers): **20px** (Semibold, letter-spacing -0.01em)
  * `h4` (Card Titles): **16px** (Medium, color: `--text-main`)
  * `h5` / `h6` (Sub-headers): **14px** (Semibold, color: `--text-muted`)
* **Body Text**:
  * Large Body: **16px** (Regular, line-height 1.6)
  * Base Body: **14px** (Regular, line-height 1.5, default size)
  * Small Text: **12px** (Medium, color: `--text-muted`)

---

## 3. UI Component Standards

### 🏷️ 3.1. Soft-Badges & Status Elements
Standardize all badges using the soft, semi-transparent background format with bold contrast text.

```css
/* Example Soft Badge Token */
.badge-soft-success {
    background-color: rgba(16, 185, 129, 0.1) !important;
    color: #10b981 !important;
    border: 1px solid rgba(16, 185, 129, 0.2);
    font-weight: 600;
}
```

### 🔲 3.2. Form Inputs (Outlined Material Style)
Outlined form input groups are styled with absolute label borders to prevent layout shifts.

```css
.outlined-group {
    position: relative;
    margin-bottom: 1rem;
}
.outlined-group > label {
    position: absolute;
    top: -10px;
    left: 12px;
    background: #fff;
    padding: 0 6px;
    font-size: 0.75rem;
    font-weight: 600;
    color: var(--secondary);
}
```

### 📊 3.3. Premium Tables
All dynamic tables use subtle hover animations and soft bottom separation borders.

```css
.table-premium {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
}
.table-premium th {
    background: #f8fafc;
    color: var(--secondary);
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding: 1rem;
}
.table-premium tr:hover {
    background-color: rgba(37, 99, 235, 0.02);
    transition: background-color 0.2s ease;
}
```

---

## 4. Layout & Spacing Standards

* **Grid Breakpoints**: Standard Bootstrap 5.3 spacing breakpoints (`xs: 0, sm: 576px, md: 768px, lg: 992px, xl: 1200px, xxl: 1400px`).
* **Container Padding**: Default main content uses `.p-4` spacing (**24px**) on desktop and `.p-3` (**16px**) on mobile devices.
* **Component Margins**: Margins between sections and tables are standardized using `mb-4` (**24px**) to ensure vertical rhythm.
