<!-- TEMPLATE:UNFILLED — delete this line once this document is genuinely filled in. -->
# Interface specification

Phase 6, written **before** any frontend code exists.

The purpose of this document is a one-shot build. Every question a designer or an
implementer would otherwise stop and ask is answered here first, in writing. If a
decision is missing from this file, the build will either stall or guess — and a guess
is what produces the round-trip this document exists to prevent.

Fill it in one sitting, with the backend already running, so every screen can be
described against a real API response rather than an imagined one.

## Readiness check

Do not start filling this in until all of these are true. Each one is a question the
interface design depends on, and answering them mid-build is what causes rework.

- [ ] The backend runs and its endpoints return real shapes
- [ ] `docs/01-DESIGN.md`'s API contract is settled — no endpoint still "probably"
- [ ] Every screen below can be pointed at an actual endpoint
- [ ] The slowest realistic response time is measured, not assumed

---

## 1. What this interface is for

<!-- One sentence. The single job. If two jobs are named, one of them is a second app. -->

**Primary user and the moment they arrive**

<!-- What just happened to them, what they need in the next thirty seconds. -->

**The one thing that must be obvious within five seconds of the page loading**

---

## 2. Reference points

<!-- Name two or three real products whose patterns are being borrowed, and say
     precisely WHAT is being borrowed from each — not "looks like X" but
     "the message column width and the way streamed text settles, from X."
     Being specific here is most of what makes a one-shot possible. -->

| Product | What we take | What we deliberately do not take |
|---------|--------------|----------------------------------|
| | | |

**The feeling in three adjectives** <!-- e.g. calm, dense, confident. These adjudicate later arguments. -->

---

## 3. Design tokens

Concrete values, not descriptions. Every value here is chosen deliberately — none are
inherited from a framework default. Both themes are specified; the interface ships with
light and dark from day one, because retrofitting dark mode is far more expensive.

### Colour

<!-- Neutrals carry the interface; the accent is used sparingly and means "act here."
     Pick the neutral ramp first and the accent last — the reverse produces a UI that
     shouts. -->

| Token | Light | Dark | Used for |
|-------|-------|------|----------|
| `bg` | | | page background |
| `surface` | | | cards, panels |
| `surface-raised` | | | menus, popovers, modals |
| `border` | | | hairlines, dividers |
| `text` | | | body copy |
| `text-muted` | | | secondary, timestamps, captions |
| `accent` | | | primary action, active state |
| `accent-fg` | | | text on accent |
| `success` | | | |
| `warning` | | | |
| `danger` | | | destructive, errors |

**Contrast check** — body text against its background must reach at least 4.5:1 in both
themes, and large text 3:1. Record the measured ratios here, not the intention:

| Pair | Light ratio | Dark ratio |
|------|-------------|------------|
| `text` on `bg` | | |
| `text-muted` on `bg` | | |
| `accent-fg` on `accent` | | |

### Type

| Token | Value | Used for |
|-------|-------|----------|
| Font, UI | | |
| Font, monospace | | code, identifiers, numbers in tables |
| `text-xs` … `text-3xl` | | |
| Body line-height | | |
| Long-form measure | | maximum line length for reading text |

<!-- Pick fonts deliberately. A generic system stack reads as unfinished; so does a
     display face used for body copy. Name the fallback chain. -->

### Space, radius, motion

| Token | Value | Notes |
|-------|-------|-------|
| Spacing scale | | one scale, used everywhere |
| Radius | | |
| Shadow | | |
| Motion duration | | |
| Motion easing | | |

**Reduced motion:** every animation has a defined still state under
`prefers-reduced-motion`. Say what each becomes.

---

## 4. Layout

**Page shell** <!-- Sidebar, top bar, or centred column. Sketch it in ASCII if it helps. -->

**Breakpoints and what changes at each**

| Width | Layout |
|-------|--------|
| < 640px | |
| 640–1024px | |
| > 1024px | |

**Maximum content width** <!-- And what fills the space beyond it. -->

---

## 5. Screens

<!-- One block per screen. The states are the important part: default and loading are
     easy to imagine, and empty and error are the ones that get skipped and then look
     broken in the demo. Every screen gets all five. -->

### <screen name>

- **Route:**
- **Job:** <!-- what the user accomplishes here -->
- **Data:** <!-- the exact endpoints it calls -->

| State | What the user sees |
|-------|--------------------|
| First load | |
| Loading | <!-- skeleton, spinner, or optimistic content — pick one and say which --> |
| Empty | <!-- no data yet: what does it say, and what is the next action? --> |
| Error | <!-- what failed, in the user's words, and how do they recover? --> |
| Success | |

---

## 6. Components

<!-- Every reusable piece, with every state named. A component whose focus and disabled
     states are unspecified will ship without them. -->

| Component | States | Notes |
|-----------|--------|-------|
| Button, primary | default / hover / focus-visible / active / loading / disabled | |
| Button, secondary | | |
| Input | default / focus / invalid / disabled | |
| Table | | sort, empty, overflow behaviour |
| Card | | |
| Toast | | how long it stays, whether it can be dismissed |
| Modal | | focus trap, escape to close, what gets focus on open |

---

## 7. Response behaviour

<!-- Fill this in for any interface where the user waits on a slow or streamed response.
     These decisions are what separate an interface that feels considered from one that
     feels like a loading spinner with opinions. -->

| Question | Decision |
|----------|----------|
| Does output stream in, or appear complete? | |
| What is on screen in the first 200ms? | |
| What indicates work is still happening? | |
| Can the user stop it? | |
| What happens to a partial response when it fails? | |
| Is the input disabled while waiting, or can they queue? | |
| How is a long response scrolled — pinned to bottom, or free? | |

---

## 8. Accessibility floor

Not aspirational. These are checked before the phase is done.

- [ ] Every interactive element reachable by keyboard, in a sensible order
- [ ] Focus is always visible, and not only via the browser default
- [ ] Contrast ratios in section 3 measured and recorded
- [ ] Images and icon-only buttons have text alternatives
- [ ] Forms: every input has a label; errors are described in text, not colour alone
- [ ] `prefers-reduced-motion` honoured
- [ ] Page is usable at 200% zoom

---

## 9. Voice

<!-- Microcopy rules. Errors say what happened and what to do next, in plain language,
     without apologising. Empty states say what will appear here and how to make it
     appear. Buttons are verbs. -->

| Situation | Say | Never say |
|-----------|-----|-----------|
| Request failed | | "Oops! Something went wrong" |
| Nothing to show yet | | |
| Destructive confirm | | |

---

## 10. Out of scope

<!-- Named here so it reads as a decision rather than an omission, and so it cannot
     quietly reappear mid-build. -->

-

## 11. Open questions

<!-- Must be empty before the build starts. Anything still open here becomes a guess. -->

-
