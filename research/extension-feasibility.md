# Browser-Extension Feasibility for Site Blocking (MV3)

**Ticket:** task-buddy-backend#50 — Wayfinder research
**Scope:** What a browser extension can actually do for site blocking today, plus the mobile story, ahead of SPECing the Task Buddy site-blocking feature.
**Research date:** 2026-02 (source versions noted inline)

---

## TL;DR

A site-blocking extension is fully feasible on desktop Chrome MV3 and Firefox — two working open-source models exist (LeechBlock NG: observe-and-redirect; Habitica SiteKeeper: in-page paywall overlay). `declarativeNetRequest` (DNR) gives real network-level blocking on Chrome/Firefox/Safari; for a user blocklist of dozens–hundreds of domains, DNR limits are non-issues. Mobile is the hard part: Firefox for Android is the only mainstream browser with a real extension platform (LeechBlock NG ships there today); Chrome for Android supports no extensions; iOS requires either a Safari web extension shipped inside an app or the Screen Time APIs (Family Controls entitlement — Apple approval required). Backend-API sync is the only cross-device story; `storage.sync` is per-vendor, small, and absent on Firefox Android.

---

## 0. Feasibility matrix

| Capability | Chrome MV3 (desktop) | Firefox (desktop) | Android | iOS |
|---|---|---|---|---|
| Network-level site block | ✅ DNR rules (block/redirect) [C1] | ✅ DNR (FF 113+) **and** blocking `webRequest` (retained) [M1][M2] | ✅ Firefox for Android only (MV3 since FF 128; DNR available). ❌ Chrome for Android has no extensions [M3][A1] | ✅ Safari web ext via DNR (iOS 15+, Safari only) [S1][S2]; content-blocker app ext (Safari + SafariViewController) [S3]; Screen Time shields (system-wide) [S4] |
| Custom block/lock page | ✅ DNR `redirect` → `extensionPath`, or `tabs.update` → bundled page w/ URL params (LeechBlock model) [C1][L1] | ✅ Same; blocking `webRequest` can also return the page directly | ✅ Firefox for Android (LeechBlock NG ships this) [L2][A1] | ✅ Safari ext page via DNR redirect; native shield screen via ShieldConfiguration ext [S4] |
| Temporary pass (unblock N min) | ✅ higher-priority `allow` rule or remove session rule; session rules auto-clear on restart [C1] | ✅ Same | ✅ Same (FF Android) | ✅ Safari: same DNR mechanics; native: clear shield / `ShieldAction` button [S4] |
| Scheduled/locked blocks | ✅ alarms + stored timestamps; no precision timers [C3] | ✅ event page + alarms; non-persistent bg | ✅ FF Android alarms; Android may kill bg — DNR rules preferable since they need no background [M2] | ✅ Best-in-class: `DeviceActivitySchedule` + `DeviceActivityMonitor` ext — OS wakes it even if app killed [S4][W1] |
| Countdown UI | ✅ On block page (normal page, real timers) or toolbar badge; **not** in SW [C3] | ✅ Same | ✅ Same | ✅ ShieldConfiguration ext renders custom view [S4] |
| Pay-to-bypass call to backend | ✅ `fetch()` from extension page/SW (remote *data* allowed; remote *code* banned) [C4] | ✅ Same | ✅ Same (FF Android) | ✅ Ext page `fetch()`; native: ShieldAction button → open app → API/IAP [S4] |
| Block-attempt telemetry | ⚠️ `webRequest`/`webNavigation` observers only; `getMatchedRules`/`onRuleMatchedDebug` are **unpacked-only** [C1][C5] | ✅ blocking webRequest or observers | ✅ Same (FF Android) | ⚠️ Content blockers see nothing (privacy by design) [S3]; DNR same as Chrome; native: `DeviceActivityReport` framework [S4][W1] |
| Cross-device sync | ⚠️ `storage.sync` per-vendor (100 KB, 8 KB/item, 512 items, 120 w/min, 1800 w/hr) [C6] | ⚠️ `storage.sync` works via Mozilla account, needs `gecko.id`; ~10-min cadence [M4] | ❌ `storage.sync` does **not** sync on Firefox for Android (bug 1625257) [M4] | ❌ `storage.sync` is a no-op in Safari [S5] → backend API required everywhere |
| Anti-tamper | ❌ uninstall/disable anytime; `ExtensionInstallForcelist` policy = enterprise only [K1]; `webRequestBlocking` only for policy-installed exts [C5] | ❌ Same consumer story | ⚠️ App-level: AccessibilityService + Device Admin (Freedom model) [F1]; extension-level: none | ✅ `application.denyAppRemoval`, shields via OS; **but** user can revoke Screen Time access in Settings (passcode does not protect 3rd-party perms) [S4][X1] |
| Distribution | Chrome Web Store | AMO | AMO (Android section) | App Store (ext inside app) + Family Controls entitlement request for native [S4][X2] |

Legend: ✅ works today · ⚠️ works with caveats · ❌ not available

---

## 1. MV3 capabilities relevant to site blocking

### 1.1 declarativeNetRequest (the enforcement primitive)

Three ruleset types [C1]:

| Type | Lifetime | Managed by | Limits (Chrome) |
|---|---|---|---|
| **Static** | bundled; updated only on extension update | manifest `declarative_net_request.rule_resources` JSON files | ≤100 rulesets, ≤50 enabled; guaranteed min 30,000 rules; global shared pool 300,000 across all installed exts (Chrome 128: disabled ext frees its quota) [C1][C7] |
| **Dynamic** | persists across browser restarts **and** extension updates | `updateDynamicRules()` | 30,000 "safe" rules (`block`/`allow`/`allowAllRequests`/`upgradeScheme`) since Chrome 121; ≤5,000 "unsafe" rules (`redirect`, `modifyHeaders`) within that budget [C1][C7] |
| **Session** | cleared at browser shutdown **and** on extension update | `updateSessionRules()` | 5,000 rules [C1] |

Additional constraints: ≤1,000 regex (`regexFilter`) rules per ruleset type; each compiled rule < 2 KB [C1]. Rule actions: `block`, `redirect`, `upgradeScheme`, `allow`/`allowAllRequests` (negation), `modifyHeaders`. Conditions: `urlFilter`, `regexFilter`, `requestDomains`, `excludedRequestDomains`, `initiatorDomains`, `resourceTypes`, `requestMethods`. Permissions: `declarativeNetRequest` (implicit host coverage, install warning) or `declarativeNetRequestWithHostAccess` + host permissions [C1].

Relevance: a Task Buddy blocklist of even thousands of domains fits trivially inside dynamic-rule limits. `allow` rules let a paid pass negate a `block` rule without deleting it — priority-ordered.

Gotchas worth noting:

- A DNR `redirect` to `extensionPath` targets a bundled page that **must** be listed in `web_accessible_resources` [C1].
- `extensionPath` is a static path — it cannot carry the originally-requested URL as a parameter (`regexSubstitution` only applies to `url` redirects with `regexFilter`) [C1]. LeechBlock avoids DNR partly for this reason and redirects the tab itself with params (§3.1).
- `declarativeNetRequestFeedback` (`getMatchedRules`, `onRuleMatchedDebug`) is for **unpacked extensions only** — no production "which rule fired" telemetry; count attempts by observing navigations to your block page instead [C1].
- Blocking `webRequest` is gone for consumer installs; it survives **only for policy-installed (enterprise) extensions** [C5]. Non-blocking `webRequest` observers still exist.

### 1.2 Content scripts + `scripting`

Content scripts run in the page context (declared in manifest, `document_start` possible, `<all_urls>` with host permissions) and `chrome.scripting.executeScript/insertCSS` injects on demand from the background [L1][H1]. Both are the basis for in-page overlays, timers, and gate UX (§3.2). MV3 keeps these intact — they're unaffected by the webRequest removal.

### 1.3 Service worker lifecycle & alarms (the countdown question)

- The MV3 background is a **service worker that Chrome terminates after ~30 s of inactivity**; extension events/API calls reset the timer; any single request >5 min kills it; globals die on shutdown → all state in `chrome.storage`/IndexedDB; incoming events revive the worker [C2].
- `chrome.alarms` wakes the SW at a scheduled time. Current API docs: alarms fire "at most once every second" but "may delay them an arbitrary amount," missed alarms fire on device wake, and `persistAcrossSessions` (Chrome 150+) controls survival across restarts — the docs still recommend re-asserting alarms on every SW start [C3]. **History flag:** earlier docs/behavior enforced 1-min (pre-Chrome 120) then 30-s (Chrome 120+) minimum periods; the current 1-s figure reflects a newer relaxation — do not design around sub-minute precision.
- Practical pattern: store `blockedUntil`/`passExpiry` timestamps in storage; the **block page itself** (a normal extension page, unrestricted JS) renders the live countdown; an alarm wakes the SW at expiry to swap rules. This is what production blockers do — LeechBlock additionally keeps an **offscreen document** (`offscreen` permission, `Reason.WORKERS`) as a 1-Hz "ticker" and staggers six alarms 10 s apart as a SW keep-alive [L1].

### 1.4 `storage.sync` and friends

`storage.sync` quotas (Chrome): **102,400 B total, 8,192 B/item, 512 items, 120 writes/min, 1,800 writes/hr** (sustained-writes quota deprecated); `storage.local` = 10 MB (5 MB ≤ Chrome 113; `unlimitedStorage` raises) [C6]. It syncs via the *browser vendor's* account only — Chrome account on Chrome, Mozilla account on Firefox (requires `browser_specific_settings.gecko.id`; merges ~every 10 min, server-wins) [M4], **not on Firefox for Android** [M4], and **implemented but never syncs in Safari** [S5]. Fine for settings backup; unusable as the cross-device source of truth (§5).

---

## 2. Building a lock/block page with pay-to-bypass

Three proven patterns, all shippable under MV3 today:

1. **DNR redirect → bundled page.** `redirect: { extensionPath: "/blocked.html" }`. Cheapest enforcement (browser-side, works even while the SW sleeps — a plus Mozilla explicitly cites for Android [M2]). Constraints: page must be web-accessible [C1]; redirect rules count as "unsafe" (5 k cap) [C7]; `extensionPath` can't embed the original URL — recover it from `webNavigation` state or accept a generic page [C1].
2. **Observe-and-redirect (LeechBlock NG's Chrome model).** `webNavigation.onBeforeNavigate`/`tabs.onUpdated` → match blocklist → `tabs.update(id, { url: "blocked.html?$S&$U" })` [L1]. Full control of the URL → can pass domain, set, keyword as params; same code path drives the **delay page** (configurable `delaySecs` countdown before the site loads) and **password page** [L1][L3]. Slight flash risk: the navigation may start before the redirect lands — mitigate by checking at `onBeforeNavigate`, not `onCompleted` (SiteKeeper checks at `status=="complete"` and pays for it in UX) [H1].
3. **In-page overlay (SiteKeeper's model).** On `tabs.onUpdated`/`onActivated`, inject `pageOverlay.css`+`pageOverlay.js` via `chrome.scripting`, painting a gate over the page itself with "Pay X Gold to access for Y minutes" / "can't afford" states [H1]. No redirect needed, works as pure augmentation; but the underlying page is already loaded → weakest guarantee. Best combined with DNR block as the floor and overlay as the UX layer.

**Pay-to-bypass mechanics.** A `fetch()` from an extension page or SW to your backend is remote **data**, not code — permitted [C4]. On pay success: add a higher-priority `allow` rule (or remove the session `block` rule) for that domain + set an alarm at `passExpiry` to restore the block. Session rules are attractive for passes because they auto-clear at shutdown/update [C1]. SiteKeeper is the direct precedent: stores Habitica `uid`+`apiToken` in extension storage, calls `habitica.com/api/v3` directly, creates/scores a `sitepass` reward task to debit GP, then stamps `passExpiry = now + passDuration` [H1][H2].

**MV3 gotchas checklist:**

- **No persistent background.** SW dies ~30 s idle [C2]. Any per-second countdown must live in a visible page or an offscreen doc (LeechBlock ticker) [L1], never in `setInterval` in the SW. Alarms wake it for transitions [C3].
- **Remote code is banned.** All logic ships in the package; the backend may only send data (blocklists as JSON → `updateDynamicRules` is exactly the AdGuard-style pattern blessed by Chrome's docs) [C4][C7].
- **Can't style `chrome://` network-error pages.** A `block` action shows the generic error page; a custom page requires `redirect` (unsafe-rule budget) or `tabs.update` [C1][L1].
- **Session rules die on update/restart** — re-derive them from storage on SW start; dynamic rules persist updates but add startup cost if you keep thousands [C1].
- **Update latency:** rule changes apply via async API calls and are cheap at this scale; the documented hard boundary is static rules — those only change on extension update (i.e., store review cycle) [C1]. Anything user-editable must be dynamic/session.
- **Bypass surface:** users can still open another browser, incognito without extension permission, or disable the ext — `ExtensionInstallForcelist` is enterprise-policy-only [K1][C5]. Task Buddy should treat extension blocks as *friction*, not enforcement (LeechBlock's `prevExts`/hide-options-during-block options are the extent of consumer-grade tamper-proofing) [L3].

---

## 3. How comparable products work

### 3.1 LeechBlock NG (open source, MPL-2) — the reference implementation

Repos: `proginosko/LeechBlockNG` (Firefox), `-chrome`, `-edge` [L2]. The **Chrome MV3 port declares `alarms, contextMenus, offscreen, storage, tabs, unlimitedStorage, webNavigation` + `<all_urls>` — notably *no* `declarativeNetRequest`** [L1]. Flow: `webNavigation.onBeforeNavigate` → `checkTab()` evaluates per-set regexes/time windows/time-limits → `browser.tabs.update(id, { url: blockURL })` where `blockURL` is `blocked.html?$S&$U` / `delayed.html?...` / `password.html?...` (bundled pages with param placeholders) [L1][L3]. Timekeeping runs on an offscreen ticker doc + staggered alarms [L1]. Bypass/deterrence menu: delay page w/ configurable seconds + auto-load, password page, random access-code image, timed **override** (`overrideMins`, code/password), **lockdown** mode, options to hide its own options/extensions page during blocks (`prevOpts`, `prevExts`), and a 1–30 block-set model with per-set schedules + daily limits + rollover [L3]. Syncs options via `storage.sync` optionally [L1]. **Recommended on Firefox for Android** (AMO Android listing, ~67 k users) — proof this architecture survives mobile [A1][L4].

### 3.2 Habitica SiteKeeper (`ofekmiz/Habitica-Pomodoro-SiteKeeper`, MIT) — the pay-to-bypass precedent

MV3, ~8.x, actively used. `service-worker.js` + `tabs.onUpdated/onActivated` → `checkBlockedUrl()` returns `{block, payToPass, cost, hostname, passTime}` → injects `pageOverlay` via `chrome.scripting` [H1]. Pay = score a per-user `sitepass` Habitica reward task (debits GP); unaffordable → "You shall not pass!" overlay. Per-site `cost` + `passDuration` + `passExpiry`; Pomodoro mode blocks the whole list; free-pass windows, vacation mode, break passes [H1][H2]. Manifest: `storage, unlimitedStorage, notifications, scripting, tabs, offscreen` + `*://*/*` host access [H3]. **This is the closest living analog to the Task Buddy concept** — extension + REST API + gamified currency, no DNR at all.

### 3.3 StayFocusd (Sensor Tower; closed source)

Chrome-only. Model: daily **time budget** per blocked site; after budget → blocked for the day. **Nuclear Option**: scheduled total block that *cannot* be canceled once armed. **Require Challenge**: retype a long passage without errors to change settings [K2]. In-page element blocking (YouTube shorts, etc.) [K2]. Internal mechanism isn't published; feature set confirms time-limit + scheduled-lock patterns map onto the same extension surface (flag: mechanism inferred, not verified).

### 3.4 Cold Turkey Blocker (closed source)

Desktop app (Windows/macOS only — official docs: "Limitations in the operating system prevent apps like Blocker from being hard to delete" → no iOS/Android) + companion browser extensions for each browser [K3][K4]. Enforcement at the app layer: locking a block makes the uninstaller fail, **requires the companion extension to stay enabled** (the ext serves the "you were brought here because the Blocker extension isn't enabled" page when missing), and disables guest/Tor-bypass routes [K3]. Lock types: timer, password, **random text 1–999 chars**, time-range windows [K3]. Takeaway: consumer-grade tamper-proofing needs a native companion process watching the extension — beyond Task Buddy's likely scope.

### 3.5 Freedom (closed source)

Desktop: **local HTTP proxy** (port 7769, compiled-regex pass/block) + browser extension that exists mainly to render the "green screen" quickly and serve as the standalone blocker on ChromeOS/Linux [F2][F3]. iOS: **Screen Time API for apps + a local "Freedom Profile" VPN for system-wide website blocking + optional Safari content blocker** [F4]. Android: **Accessibility Service** ("Block Apps & Websites" permission) + optional Device Admin anti-uninstall + DND integration [F1]. Sync: backend pushes blocklists/schedules to all devices; blocking decisions are on-device [F5]. Takeaway: system-wide mobile blocking needs a native app (VPN or Screen Time), not a browser extension — and their ChromeOS extension proves a standalone ext can own auth + sync + blocking end-to-end [F3].

### 3.6 Forest (closed source)

Blocklist or allowlist mode; planting a tree starts a focus timer; visiting a blocked site shows a block screen with a **"Give Up" button that kills your tree**; coins fund tree species; extension syncs with the mobile app account [G1][G2]. Ships on Chrome, Firefox, and **Firefox for Android** (AMO Android listing) [G3]; iOS/Android apps do app-level blocking. Takeaway: the "consequence" model (bypass allowed, costs progress) needs only pattern (3) overlay mechanics + backend sync — cheap and on-brand for gamification.

---

## 4. Mobile story per platform

### 4.1 Android

- **Chrome for Android: no extension support, period.** No announced roadmap [A2].
- **Firefox for Android: the real story.** Open extension ecosystem since FF 120 (Dec 14, 2023, 450+ extensions at launch) [M3]; **MV3 supported since FF 128** [M5]; DNR available and specifically valuable on Android because rules keep working when the OS kills the extension's background page [M2]. Site blockers demonstrably work: LeechBlock NG and Forest are both AMO-Android-listed [A1][G3]. Caveats: `storage.sync` doesn't sync there [M4]; distribution is AMO-only (no sideloading your ext via your app — installs must come from AMO or self-distribution) [M3]; some desktop APIs missing (e.g., offscreen docs).
- **Samsung Internet:** add-ons are a curated set distributed via Galaxy Store; on non-Samsung devices the pick is essentially ad-blockers only — not a general extension platform [A3].
- **Edge for Android:** extension install-by-ID exists in Canary behind developer options (inherited Kiwi's code) — pre-release/dev surface only [A4].
- **Kiwi:** discontinued Jan 2025, pulled from Play Store, sideload-only with stale Chromium → do not recommend [A4].
- **App-level alternative:** Freedom shows the Android-native path — Accessibility Service for app/site blocking + Device Admin anti-uninstall [F1]. If Task Buddy already ships a native Android app, this is stronger than any extension route.

### 4.2 iOS

Two sanctioned routes; both are app-store apps, not just "extensions":

**Route A — Safari web extension (iOS 15+).** Standard WebExtensions MV3 surface inside an iOS app distributed via App Store/Xcode [S1][S6]. DNR works since Safari 15 [S2]; MV3 supported since Safari 15.4 [S5]. Hard limits: **`webRequestBlocking` is unsupported everywhere in Safari** [S5]; `storage.sync` is a no-op [S5]; iOS background must be non-persistent [S5]; the user must manually enable the ext in Settings → Safari → Extensions, and content-accessing exts are off by default [S2][S6]; blocking applies **inside Safari (and SafariViewController for content blockers) only** — Chrome iOS and other apps untouched [S3][S6].

**Route B — Safari content blocker (iOS 9+).** App extension returning `blockerList.json` (`url-filter` triggers; `block`/`block-cookies`/`css-display-none`/`make-https` actions); Safari compiles rules to bytecode; host app refreshes via `SFContentBlockerManager.reloadContentBlocker` [S3][W2]. Privacy-perfect (ext never sees traffic) but **zero UX** — no custom block page, no telemetry; good as a silent always-on base layer only. Empirical ~50 k rule ceiling per blocker (community-reported; Apple documents no official cap — **flag: unverifiable**).

**Route C — Screen Time API (the system-wide play).** Three frameworks, iOS 15+ (FamilyControls types iOS 16+) [S4][W1]:
- **FamilyControls**: `AuthorizationCenter.requestAuthorization(for: .individual)` (self-restriction) or `.child` (parent-gated, stronger); `FamilyActivityPicker` returns **opaque tokens** for apps/categories/websites (privacy-preserving — the app can't enumerate what was picked) [S4][W1][X2].
- **ManagedSettings**: `ManagedSettingsStore.shield.applications`/`.webDomains` (token sets) and `.webDomainCategories` (`ActivityCategoryPolicy<WebDomain>`); `WebDomain` also has a **literal `init(domain: String)`** so known-list blocking doesn't require the picker [S4]. Plus `webContent.blockedByFilter` (domain filter policy), `safari` settings, and `application.denyAppRemoval` (uninstall lock — used in production by Flint, Ripple) [S4][X1].
- **DeviceActivity**: `DeviceActivitySchedule` intervals + a `DeviceActivityMonitor` **app extension** whose `intervalDidStart/End` callbacks run even when the app is dead — the iOS equivalent of "alarms," but OS-enforced [S4][W1].
- **Custom shield UX**: `ShieldConfiguration`/`ShieldAction` extensions render your own shield screen + handle its buttons (e.g., "Pay 50 coins" → `.defer` → open app → backend → clear shield) [X1][X3].
- **Gatekeeper**: `com.apple.developer.family-controls` — dev works free, but **distribution requires an Apple-approved entitlement request per app** [X2].
- **Anti-tamper ceiling**: user can revoke access at Settings → Screen Time → Apps with Screen Time Access, and the Screen Time passcode does **not** protect third-party grants (long-standing Apple dev complaint) [X1]; deleting the app drops shields unless `denyAppRemoval` is set. Freedom ships exactly this stack (Screen Time for apps; VPN profile for sites) [F4].

---

## 5. Sync story: blocklist & timer state ↔ backend ↔ extension

| Option | What you get | Limits |
|---|---|---|
| `storage.sync` | Vendor-account sync Chrome↔Chrome / FF↔FF desktop | 100 KB/512-item/8 KB-per-item quotas; ~min-to-10-min cadence; server-wins conflicts; **no** FF Android; **no** Safari; not cross-vendor; write quotas throttle churn [C6][M4][S5] |
| `storage.local` / `unlimitedStorage` | Big, fast, per-device cache (10 MB+, expandable) — the working set for rule compilation [C6] | Per-device only |
| **Backend API + auth** | True cross-device truth incl. Android, iOS app, web app; enables economy writes (coin debit → pass) | Needs auth plumbing + offline caching |

**Auth options for the extension:** (a) **paste API token** — SiteKeeper's model (Habitica `uid`+`apiToken` in `storage`) [H1][H2]; (b) **read the web app's session cookie** via `chrome.cookies` (needs `cookies` permission + host access to the API domain) — zero-UX if the user is logged into the Task Buddy web app; (c) **`chrome.identity.launchWebAuthFlow`** for OAuth-style flows. Freedom's ChromeOS extension proves a store-listed ext can own sign-in + sync + enforcement standalone [F3].

**Recommended shape:** backend holds `{blocklist, schedules, economy state}`; extension pulls on SW start/alarm, caches to `storage.local`, compiles to session/dynamic rules; writes back only events (block attempts, pass purchases). `storage.sync` optionally mirrors prefs as a courtesy.

---

## 6. Recommended approach for Task Buddy (what the SPEC ticket should assume)

1. **Ship a single WebExtensions codebase (MV3) targeting Chrome + Edge + Firefox desktop first.** WECG convergence is real: DNR, alarms, storage, scripting, webNavigation all interoperate; keep the Firefox build on event-page background + optionally blocking `webRequest` for richer matching [M1][M2][M6].
2. **Enforce with two layers:** DNR `block`/`redirect` rules as the floor (works while SW sleeps, survives Android process kills [M2]) + LeechBlock-style `webNavigation`/`tabs.update` redirect to a bundled `blocked.html?domain=&remaining=` for the branded lock page — because `extensionPath` can't carry context params [C1][L1].
3. **Pay-to-bypass = SiteKeeper pattern, generalized.** Extension-page gate → `fetch()` to Task Buddy API → debit currency → write high-priority `allow` (or drop session `block`) + stamp `passExpiry`; alarm at expiry restores the block. Remote *data* is legal; bundle all logic [C4][H1].
4. **Never keep time in the service worker.** Store timestamps in `storage.local`; countdown renders in the block page (real DOM timers); alarms only for transitions — they're coarse and arbitrarily delayed [C2][C3]. If per-second tab-level state is ever needed, copy LeechBlock's offscreen ticker [L1].
5. **Backend is the source of truth; `storage.sync` is decoration.** Per-vendor caps and no-ops on Firefox Android/Safari kill it as the sync layer; it's a settings-backup nicety at best [C6][M4][S5]. Plan API auth via web-session cookie reuse (`cookies` perm) or pasted token.
6. **Android = Firefox for Android, period.** It's the only mainstream extension platform there; LeechBlock NG/Forest prove site blockers ship and get recommended [A1][G3][M3]. Chrome-Android users are unreachable by extensions; a future native app could go the AccessibilityService route (Freedom) [F1].
7. **iOS = two-track spec, not extension-only.** Track 1: Safari web extension inside the Task Buddy iOS app (DNR, Safari-only). Track 2 (the strong play): Screen Time API — `ManagedSettings` shields/`webContent` filters + `DeviceActivityMonitor` schedules + `ShieldAction` pay-button → survives app death, system-wide. Costs: Family Controls **entitlement approval** and the known self-revocation ceiling [S4][X1][X2].
8. **Budget for soft enforcement.** Extensions can't prevent their own uninstall/incognito bypass/second browser on consumer installs [C5][K1]; design the economy so bypassing loses progress (Forest's dead-tree model) rather than relying on hard locks [G1][G2].
9. **Telemetry is observer-side.** No production API reports which DNR rule matched (`onRuleMatchedDebug` is unpacked-only) [C1]; count block attempts by instrumenting the block page's load + `webNavigation` events.
10. **Reuse prior art, don't re-derive it.** LeechBlock NG (MPL-2) documents every hard-won edge case — delay pages, overrides, keyword blocking, per-set schedules, Android guards — and SiteKeeper (MIT) shows a working pay-per-visit economy loop end-to-end [L1][L3][H1].

---

## Sources

**Chrome platform**
- [C1] `chrome.declarativeNetRequest` API reference — rulesets, limits, `extensionPath`, unsafe rules, web_accessible_resources, Feedback API: https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest
- [C2] Extension service worker lifecycle (30 s idle kill, persistence): https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- [C3] `chrome.alarms` API (granularity, sleep behavior, `persistAcrossSessions`): https://developer.chrome.com/docs/extensions/reference/api/alarms
- [C4] CWS "Additional Requirements for MV3" / remotely hosted code policy: https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements and https://developer.chrome.com/docs/extensions/develop/migrate/remote-hosted-code
- [C5] "Replace blocking web request listeners" (`webRequestBlocking` → policy-installed only): https://developer.chrome.com/docs/extensions/migrating/blocking-web-requests
- [C6] `chrome.storage` API (sync/local quotas, write limits): https://developer.chrome.com/docs/extensions/reference/api/storage
- [C7] Content filtering concepts (30 k guaranteed, 300 k pool, 30 k safe dynamic): https://developer.chrome.com/docs/extensions/develop/concepts/content-filtering + https://developer.chrome.com/blog/improvements-to-content-filtering-in-manifest-v3

**Firefox**
- [M1] "declarativeNetRequest available in Firefox" (FF 113): https://blog.mozilla.org/addons/2023/05/17/declarativenetrequest-available-in-firefox/
- [M2] Same source — DNR needs no background page; important for Android: https://blog.mozilla.org/addons/2023/05/17/declarativenetrequest-available-in-firefox/
- [M3] "A new world of open extensions on Firefox for Android" (FF 120, Dec 2023, 450+ exts): https://blog.mozilla.org/addons/2023/12/14/a-new-world-of-open-extensions-on-firefox-for-android/
- [M4] MDN `storage.sync` (quotas, gecko.id requirement, 10-min cadence, **no Android sync**): https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/storage/sync
- [M5] "Manifest V3 updates landed in Firefox 127" (MV3 → Android in FF 128; rule-limit parity; no MV2/webRequest deprecation): https://blog.mozilla.org/addons/2024/06/13/manifest-v3-updates-landed-in-firefox-127/
- [M6] Mozilla MV3 stance (blocking webRequest + MV2 retained; event pages, no SW support — pref locked): https://blog.mozilla.org/en/firefox/firefox-manifest-v3-adblockers/ + https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/background + https://github.com/mozilla/web-ext/issues/2532
- [MDN-DNR] MDN DNR constants (Safari combined 30 k dynamic+session; FF 126 split): https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/declarativeNetRequest/MAX_NUMBER_OF_DYNAMIC_AND_SESSION_RULES

**Apple**
- [S1] "Safari web extensions" doc (iOS 15+, app-bundle distribution): https://developer.apple.com/documentation/safariservices/safari-web-extensions/
- [S2] WWDC21 "Explore Safari Web Extension improvements" (DNR in Safari 15): https://developer.apple.com/videos/play/wwdc2021/10027/
- [S3] "Creating a content blocker" + WWDC15 session 511 (JSON rules, compiled, SafariViewController coverage, `SFContentBlockerManager.reloadContentBlocker`): https://developer.apple.com/documentation/safariservices/creating-a-content-blocker/ + https://nonstrict.eu/wwdcindex/wwdc2015/511/
- [S4] ManagedSettings docs — `ManagedSettingsStore` (incl. `safari`, `webContent`, `shield`, `application`), `ShieldSettings` (`webDomains` tokens, `webDomainCategories`), `WebDomain` (`init(domain:)`), `WebContentSettings.blockedByFilter`: https://developer.apple.com/documentation/managedsettings/managedsettingsstore + sibling pages
- [S5] "Assessing your Safari web extension's browser compatibility" (`webRequestBlocking` unsupported; `storage.sync` no-op; MV3 → Safari 15.4): https://developer.apple.com/documentation/safariservices/assessing-your-safari-web-extension-s-browser-compatibility
- [S6] WWDC23 "What's new in Safari extensions" (four extension types; DNR; per-site gating): https://developer.apple.com/videos/play/wwdc2023/10119/
- [W1] WWDC22 "What's new in Screen Time API" (`ManagedSettingsStore` shields, `DeviceActivityMonitor` callbacks): https://developer.apple.com/videos/play/wwdc2022/110336/
- [W2] InfoQ "Safari Content Blockers Under the Hood": https://www.infoq.com/articles/safari-content-blockers/
- [X1] Apple Dev Forums — Screen Time passcode doesn't protect 3rd-party grants; `denyAppRemoval` in the wild (Flint commit): https://developer.apple.com/forums/tags/managed-settings + https://github.com/Prakashmaheshwaran/flint-app/commit/cdc0f008b32487d0dc221f5e98b4acb9da0e184e + https://screenfine.info/guides/ios-apps-that-use-family-controls/
- [X2] "Configuring Family Controls" (entitlement + distribution request): https://developer.apple.com/documentation/xcode/configuring-family-controls.md + TN3134 (content-filter providers; Screen Time path = child devices): https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment
- [X3] Apple Dev Forums — ShieldActionDelegate handling shield buttons: https://developer.apple.com/forums/tags/device-activity

**Comparable products**
- [L1] LeechBlockNG-chrome: `manifest.json`, `background.js`, `common.js` (webNavigation→tabs.update model, offscreen ticker, staggered alarms, option schema): https://github.com/proginosko/LeechBlockNG-chrome
- [L2] LeechBlockNG repo family (Firefox/Chrome/Edge, MPL-2): https://github.com/proginosko/LeechBlockNG
- [L3] LeechBlock documentation (block sets, delay/password pages, lockdown, override, prevention options): https://www.proginosko.com/leechblock/documentation/
- [L4] AMO Android recommended listing incl. LeechBlock NG (~67 k users) + maintainer confirms Android support: https://addons.mozilla.org/en-US/android/search/?promoted=recommended&sort=rating&type=extension + https://github.com/proginosko/LeechBlockNG/discussions/555
- [H1] SiteKeeper `service-worker.js` (checkBlockedUrl → overlay injection; Habitica API): https://github.com/ofekmiz/Habitica-Pomodoro-SiteKeeper
- [H2] SiteKeeper README ("Pay to Pass" model, GP cost, Pomodoro): https://github.com/ofekmiz/Habitica-Pomodoro-SiteKeeper
- [H3] SiteKeeper `app/manifest.json` (MV3 permissions surface): https://github.com/ofekmiz/Habitica-Pomodoro-SiteKeeper/blob/master/app/manifest.json
- [K1] Tech Lockdown — `ExtensionInstallForcelist` enterprise enforcement: https://www.techlockdown.com/articles/how-to-enforce-browser-extensions
- [K2] StayFocusd Chrome Web Store listing (time budget, Nuclear Option, Require Challenge): https://chromewebstore.google.com/detail/laankejkbhbdhmipfmgcngdelahlfoji + https://findfocus.net/stayfocusd/
- [K3] Cold Turkey user guide/support (lock modes, extension-requires, no mobile): https://getcoldturkey.com/support/user-guide/ + https://getcoldturkey.com/support/extensions/chrome/
- [F1] Freedom Android options (Accessibility + Device Admin): https://support.freedom.to/en/articles/6350161-freedom-for-android-app-options-explained
- [F2] Freedom desktop architecture (local proxy :7769): https://support.freedom.to/en/articles/4523574
- [F3] Freedom browser extension role (green screen; standalone on ChromeOS/Linux): https://support.freedom.to/en/articles/1347519-freedom-browser-extension
- [F4] Freedom iOS (Screen Time app blocking + "Freedom Profile" local VPN + content blocker): https://support.freedom.to/en/articles/14596751 + https://support.freedom.to/en/articles/1347477
- [F5] Freedom privacy/sync description: https://support.freedom.to/en/articles/1347493
- [G1] Forest extension guides (blocklist/allowlist, Give Up kills tree): https://learningwithangie.com/how-to-use-forest-chrome-extension/ + https://eduk8.me/forest-really-cool-chrome-extension-help-teachers-students-focus/
- [G2] Forest extension review (modes, sync): https://reviewsapp.org/forest
- [G3] Forest on AMO Android: https://addons.mozilla.org/en-US/android/addon/forest-stay-focused-be-present/

**Android browsers**
- [A1] (see [M3], [L4], [G3])
- [A2] How-To Geek "4 Android Browsers That Support Extensions" (Chrome has none; landscape): https://www.howtogeek.com/android-browsers-that-support-extensions/
- [A3] Same source — Samsung Internet add-on curation: https://www.howtogeek.com/android-browsers-that-support-extensions/
- [A4] Android Authority — Kiwi shutdown & code ported to Edge Canary (dev-options install-by-ID): https://www.androidauthority.com/kiwi-browser-shutting-down-3519510/

**Flagged unverifiable / secondary:** StayFocusd internal mechanism (closed source); Safari content-blocker ~50 k rule ceiling (community-reported, no official doc); Samsung Internet add-on program details (secondary press); current Chrome alarm 1-s granularity reflects newest docs — earlier releases enforced 30 s/1 min.
